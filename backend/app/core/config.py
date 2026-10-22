from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-in-production"


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy-ready database URL.

    Managed Postgres providers (Neon, Supabase, Heroku-style add-ons) hand
    out bare ``postgres://`` / ``postgresql://`` URLs, but this project
    ships psycopg v3 only (no psycopg2), so SQLAlchemy needs the explicit
    ``postgresql+psycopg://`` driver. Already-qualified URLs
    (``postgresql+psycopg://``, ``postgresql+asyncpg://``, ``sqlite:///``
    …) pass through untouched, query parameters included
    (``?sslmode=require`` survives).
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


# Secrets that must be explicitly configured (non-empty) in production.
# Maps the Settings field name to a short fix hint shown in the error message.
_PROD_REQUIRED_SECRETS: dict[str, str] = {
    "telegram_bot_token": "set TELEGRAM_BOT_TOKEN to the bot token from @BotFather",
    "telegram_webhook_secret": "generate one with `openssl rand -hex 32` and "
    "configure the same value as the Telegram webhook secret token",
    "twilio_account_sid": "set TWILIO_ACCOUNT_SID from the Twilio console",
    "twilio_auth_token": "set TWILIO_AUTH_TOKEN from the Twilio console",
}


class Settings(BaseSettings):
    app_name: str = "StayFlow AI"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    api_prefix: str = "/api/v1"

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    log_level: str = "INFO"
    database_url: str

    # --- Hotel staff JWT auth (Prompt-1 section 3) ------------------------------
    # JWT_SECRET_KEY signs staff session tokens. The default below is for
    # local development only; production deployments MUST set JWT_SECRET_KEY
    # in the environment (enforced by the validator below).
    jwt_secret_key: str = _DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # --- AI agent layer -------------------------------------------------
    # Production default provider. The mock provider is an explicit opt-in
    # (LLM_PROVIDER=mock / AGENT_PROVIDER=mock) for tests and demos only —
    # the app must never silently serve mock responses in production.
    # llm_provider is set it takes precedence.
    agent_provider: str = "inception"  # "inception" | "ollama" | "mock"
    agent_model: str = "qwen3:8b"
    agent_ollama_base_url: str = "http://localhost:11434"
    agent_timeout_seconds: int = 120
    agent_temperature: float = 0.2
    agent_max_iterations: int = 8
    agent_history_limit: int = 20

    # --- LLM provider selection (Prompt-2 section 5) ---------------------------
    # Takes precedence over the legacy agent_provider above; when unset (None),
    # the agent falls back to agent_provider so existing deployments with an
    # explicit AGENT_PROVIDER keep working unchanged. Defaults to inception
    # in production; set LLM_PROVIDER=mock explicitly for tests/demos.
    llm_provider: str | None = None  # "inception" | "ollama" | "mock"
    # Inception Labs Mercury via its OpenAI-compatible chat-completions API.
    # The key is never logged; it is only sent as a Bearer token to the
    # configured base URL. Fail-fast: when the inception provider is selected
    # but this is unset, the app refuses to start (see _validate_agent_provider
    # in app/main.py) instead of silently falling back to the mock provider.
    inception_api_key: str | None = None
    inception_model: str = "mercury-2.5"
    inception_base_url: str = "https://api.inceptionlabs.ai/v1"
    inception_timeout_seconds: int = 120
    inception_max_retries: int = 2

    # --- Messaging bot connectors (Prompt-1 sections 4-5) ------------------

    # --- Knowledge RAG embeddings (Prompt-1 section 2) ---------------------------
    # Which embedding backend the hotel knowledge base uses:
    #   "sentence-transformer" — real semantic embeddings from a local
    #       sentence-transformer model (default; downloads ~90 MB once on
    #       first use, then runs fully offline).
    #   "hashed" — deterministic hashed bag-of-words, stdlib-only, no model
    #       download (fast; used by the unit-test suite and fully-offline
    #       runs).
    embedding_provider: str = "sentence-transformer"
    # Local sentence-transformer model id (Hugging Face). Only used when
    # embedding_provider == "sentence-transformer".
    embedding_model: str = "all-MiniLM-L6-v2"

    # --- Background job queue (Prompt-1 §6) ------------------------------------
    # Redis backs the arq job queue used for slow operations (RAG document
    # ingestion: chunking + embedding). The API enqueues a job and answers
    # 202 immediately; the `worker` service (docker-compose.yml) runs the
    # jobs. Format: redis://[:password@]host[:port][/db]
    redis_url: str = "redis://localhost:6379/0"
    # Synchronous fallback: run document ingestion inline in the API process
    # instead of enqueueing it (single-process setups with no Redis, and
    # tests that assert the sync path). Default False: the API goes through
    # the queue.
    ingest_jobs_sync: bool = False
    # Public base URL of this deployment (scheme + host, no trailing
    # slash), e.g. https://stayflow-ai-demo.onrender.com. Used at startup
    # to register the Telegram webhook against the public address —
    # behind a host/proxy the app cannot derive it from requests. Unset
    # in local development: webhook auto-registration is skipped there.
    app_public_base_url: str | None = None
    # Telegram bot (Bot HTTP API). Webhooks stay public; Telegram
    # authenticates via X-Telegram-Bot-Api-Secret-Token.
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    # Twilio WhatsApp (REST API). Webhooks stay public; Twilio
    # authenticates via X-Twilio-Signature.
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_number: str | None = None

    # --- Rate limiting for public endpoints (Prompt-1 section 4) -----------------
    # In-memory sliding-window limiter (app/core/rate_limit.py). Redis is in
    # this stack now, but only for the arq background job queue — rate
    # limiting stays in-memory and per-process by design.
    # Limits are per <namespace>:<identity> bucket:
    #   agent/chat keyed by guest_id from the request body (client IP fallback);
    #   Telegram/WhatsApp webhooks keyed by sender identity (chat_id / From
    #   number) with client IP fallback;
    #   /auth/login keyed by client IP + email (slows credential stuffing).
    # An exhausted budget answers HTTP 429 with a Retry-After header (seconds
    # until the window resets) and a JSON body that leaks no internals.
    rate_limit_enabled: bool = True
    rate_limit_chat_per_minute: int = 20
    rate_limit_chat_window_seconds: int = 60
    rate_limit_webhook_per_minute: int = 30
    rate_limit_webhook_window_seconds: int = 60
    rate_limit_login_per_minute: int = 5
    rate_limit_login_window_seconds: int = 60

    # --- Embeddable widget + integration API (Master Prompt §11/§12) --------
    # Base URL where the widget assets are served (used to build the embed
    # snippet shown in the staff dashboard). Empty means "same origin as the
    # API", which is how the FastAPI app serves /widget.js itself.
    widget_base_url: str = ""
    # Public widget chat budget: per hotel public_id + client IP.
    rate_limit_public_chat_per_minute: int = 20
    rate_limit_public_chat_window_seconds: int = 60
    # Integration API budget: per hotel public_id + client IP.
    rate_limit_integration_per_minute: int = 60
    rate_limit_integration_window_seconds: int = 60
    # HMAC timestamp replay window for integration requests (seconds).
    integration_timestamp_window_seconds: int = 300
    # Optional global fallback signing secret for hotels that have not
    # generated their own per-hotel secret yet. Per-hotel secrets take
    # precedence; leave unset to require per-hotel secrets.
    integration_fallback_secret: str | None = None
    # Outbound webhook delivery (async integration responses).
    integration_http_timeout_seconds: float = 5.0
    integration_max_retries: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # The single normalization point: the app engine (app/database.py),
        # the Alembic env (alembic/env.py) and the demo bootstrap
        # (app/demo_bootstrap.py) all read settings.database_url, so they
        # all see the same driver-qualified URL.
        return normalize_database_url(value)

    @field_validator("embedding_provider")
    @classmethod
    def _validate_embedding_provider(cls, value: str) -> str:
        allowed = {"sentence-transformer", "hashed"}
        if value.lower() not in allowed:
            raise ValueError(f"embedding_provider must be one of {sorted(allowed)}, got {value!r}")
        return value.lower()

    @model_validator(mode="after")
    def _require_prod_secrets(self) -> "Settings":
        """Fail fast in production when secrets are missing or insecure.

        When ENVIRONMENT=production the app refuses to start if any required
        secret is missing/blank or still set to its insecure development
        default. Error messages name the offending variable and how to fix it;
        secret values are never echoed back.
        """
        if self.environment.lower() != "production":
            return self

        problems: list[str] = []

        if self.jwt_secret_key == _DEV_JWT_SECRET:
            problems.append(
                "JWT_SECRET_KEY is still the insecure development default — "
                "set it to a strong random value, e.g. `openssl rand -hex 32`"
            )

        for field_name, fix_hint in _PROD_REQUIRED_SECRETS.items():
            value = getattr(self, field_name)
            if not value or not str(value).strip():
                problems.append(f"{field_name.upper()} is not set — {fix_hint}")

        # DATABASE_URL has no dev default in code (it is a required field),
        # but refuse obvious local/dev database URLs in production.
        if self.database_url.strip().lower().startswith("sqlite"):
            problems.append(
                "DATABASE_URL points at a local sqlite database — "
                "set it to the production PostgreSQL URL"
            )

        # INCEPTION_API_KEY is only required when Inception is the active
        # provider (llm_provider takes precedence over agent_provider).
        provider = (self.llm_provider or self.agent_provider or "mock").lower()
        if provider == "inception" and not self.inception_api_key:
            problems.append(
                "INCEPTION_API_KEY is not set — "
                "set it to the Inception Labs API key or switch to another provider"
            )

        if problems:
            raise ValueError(
                "Refusing to start in production with missing/insecure secrets: "
                + "; ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
