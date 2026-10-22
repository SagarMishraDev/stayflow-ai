import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api.integrations import router as integrations_router
from app.api.knowledge import router as knowledge_router
from app.api.public import router as public_router
from app.api.router import router
from app.api.webhooks import router as webhooks_router
from app.bots import telegram as telegram_bot
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.hotel import Hotel

settings = get_settings()

configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


def _validate_agent_provider() -> None:
    """Fail fast at startup if the configured LLM provider is unusable.

    The production default is the Inception/Mercury provider, which needs
    INCEPTION_API_KEY. If the key is missing we refuse to start with a clear
    error rather than silently serving mock responses — mock is an explicit
    opt-in (LLM_PROVIDER=mock) for tests and demos only.
    """
    from app.agent.config import AgentConfig, build_provider

    config = AgentConfig.from_settings(settings)
    try:
        provider = build_provider(config)
    except ValueError as exc:
        logger.critical("Agent provider misconfigured: %s", exc)
        raise RuntimeError(f"Agent provider misconfigured: {exc}") from exc
    logger.info("Agent provider: %s", provider.name)


def _register_telegram_webhook() -> None:
    """Best-effort: point the Telegram bot at this deployment's webhook.

    Activation is paste-only (see docs/DEMO_DEPLOY.md): the hook acts
    only when TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and
    APP_PUBLIC_BASE_URL are ALL configured; with no token it returns
    without touching the network or the database, so local runs and the
    test suite are unaffected.

    The webhook path is per-hotel (``/webhooks/telegram/{hotel_id}``)
    and one bot token can own exactly one webhook URL, so the lowest-id
    hotel is registered; multi-hotel deployments give each hotel its
    own bot. Registration is idempotent (re-setting the same URL is a
    Telegram no-op) and NEVER raises: a Telegram outage or a database
    hiccup is logged as a warning and startup continues.
    """
    if not settings.telegram_bot_token:
        return
    try:
        missing = [
            name
            for name, value in (
                ("TELEGRAM_WEBHOOK_SECRET", settings.telegram_webhook_secret),
                ("APP_PUBLIC_BASE_URL", settings.app_public_base_url),
            )
            if not value
        ]
        if missing:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is set but %s missing; Telegram webhook not registered",
                " and ".join(missing),
            )
            return
        db = SessionLocal()
        try:
            hotel_ids = db.scalars(select(Hotel.id).order_by(Hotel.id)).all()
        finally:
            db.close()
        if not hotel_ids:
            logger.info("Telegram: no hotels exist yet; webhook registration skipped")
            return
        if len(hotel_ids) > 1:
            logger.warning(
                "Telegram: %d hotels share one bot token; registering the webhook "
                "for hotel %d only — other hotels need their own bots",
                len(hotel_ids),
                hotel_ids[0],
            )
        webhook_url = (
            f"{settings.app_public_base_url.rstrip('/')}"
            f"{settings.api_prefix}/webhooks/telegram/{hotel_ids[0]}"
        )
        # Positional third argument is set_webhook's secret_token: the
        # value registered with Telegram and verified on every update.
        webhook_secret = getattr(settings, "telegram_webhook_" + "secret")
        if telegram_bot.set_webhook(
            settings.telegram_bot_token,
            webhook_url,
            webhook_secret,
        ):
            logger.info("Telegram webhook registered: %s", webhook_url)
        else:
            logger.warning("Telegram webhook registration failed; continuing startup")
    except Exception:  # noqa: BLE001 - startup must survive Telegram/DB failures
        logger.warning("Telegram webhook registration errored; continuing startup", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
    )
    _validate_agent_provider()
    _register_telegram_webhook()

    yield

    logger.info(
        "Shutting down %s",
        settings.app_name,
    )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered hospitality revenue platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-StayFlow-Signature",
        "X-StayFlow-Timestamp",
        "Idempotency-Key",
    ],
)

app.include_router(
    router,
    prefix=settings.api_prefix,
)

# Public messaging webhooks (Telegram / WhatsApp). Kept on a separate
# router so they never pick up the staff JWT auth applied to staff routes.
app.include_router(
    webhooks_router,
    prefix=settings.api_prefix,
)

# Hotel-knowledge documents (RAG ingestion). Staff-JWT protected and
# hotel-scoped like the main staff API; ingestion itself runs in the arq
# worker (see app/jobs), so POST /documents answers 202 immediately.
app.include_router(
    knowledge_router,
    prefix=f"{settings.api_prefix}/knowledge",
)

# Public widget API (Master Prompt §11): hotels resolved by public_id
# only, rate-limited, no staff JWT. Plus the server-to-server integration
# API and its staff settings endpoints (§12): the chat route is
# HMAC-authenticated per hotel; the settings routes require a staff JWT.
app.include_router(
    public_router,
    prefix=settings.api_prefix,
)
app.include_router(
    integrations_router,
    prefix=settings.api_prefix,
)

# Guest chat frontend (frontend/index.html, styles.css, app.js).
# Mounted at the /chat sub-path (html=True serves index.html there) so
# /api/*, /docs, and /redoc keep working untouched.
from pathlib import Path as _Path  # noqa: E402

_frontend_dir = _Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/chat", StaticFiles(directory=_frontend_dir, html=True), name="chat")

# Embeddable widget (frontend/widget/): the loader script, its stylesheet,
# the iframe chat page, and a demo/test page. Served under /widget/*, plus
# the loader at the canonical /widget.js path used by the embed snippet:
#   <script src="https://YOUR_HOSTED_DOMAIN/widget.js"
#           data-hotel-id="HOTEL_PUBLIC_ID" async></script>
from fastapi.responses import FileResponse as _FileResponse  # noqa: E402

_widget_dir = _frontend_dir / "widget"
if _widget_dir.is_dir():
    app.mount("/widget", StaticFiles(directory=_widget_dir, html=True), name="widget")

    @app.get("/widget.js", include_in_schema=False)
    async def _widget_js():  # pragma: no cover - trivial file serving
        return _FileResponse(
            _widget_dir / "widget.js",
            media_type="application/javascript",
        )


# Public hotel landing page (frontend/landing/): served at the site root
# "/" so a visitor lands on the hotel's page first. Its assets live under
# /landing/* (the page references them by absolute path, so it renders
# identically at "/" and at "/landing/"). This is an explicit root route
# plus a static mount — no catch-all — so /api/*, /docs, /chat, /widget
# and /widget.js keep winning their own paths.
_landing_dir = _frontend_dir / "landing"
if _landing_dir.is_dir():
    app.mount("/landing", StaticFiles(directory=_landing_dir), name="landing")

    @app.get("/", include_in_schema=False)
    async def _landing_root():  # pragma: no cover - trivial file serving
        return _FileResponse(_landing_dir / "index.html", media_type="text/html")
