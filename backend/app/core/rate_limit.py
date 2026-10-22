"""In-memory sliding-window rate limiting for public-facing endpoints.

A small dependency-based limiter — no Redis in this stack yet, and adding
a third-party dependency (e.g. slowapi) for this is not warranted when the
keys must be derived from request *bodies* (``guest_id``, Telegram
``chat_id``, WhatsApp ``From``, login ``email``), which dependencies read
cleanly from the cached request body.

Budgets are configured via ``app.core.config.Settings`` (env vars, see
``RATE_LIMIT_*`` in ``backend/.env.example``) and read at request time so
tests can retune them without a restart. When a budget is exhausted the
dependency raises HTTP 429 with a ``Retry-After`` header (seconds until the
oldest request in the window expires) and a JSON body that reveals nothing
about buckets, keys, or configuration.

Buckets live in process memory (a plain dict guarded by a lock). That is
correct for a single-process deployment; a multi-worker deployment should
move this to a shared store (Redis) — until then each worker enforces its
own budget.

Test hook: :func:`reset_rate_limit_state` clears every bucket so tests can
isolate runs.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import urllib.parse

from fastapi import HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# bucket key ("<namespace>:<identity>") -> sorted (oldest first) timestamps of
# allowed requests, as time.monotonic() floats.
_buckets: dict[str, list[float]] = {}
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


def _check_budget(
    namespace: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> int | None:
    """Record one request against a bucket.

    Returns ``None`` when the request is within budget (it is counted), or
    the retry-after delay in seconds when the budget is exhausted.
    """
    bucket_key = f"{namespace}:{key}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        timestamps = _buckets.setdefault(bucket_key, [])
        # Prune expired entries in place (the list stays oldest-first).
        if timestamps and timestamps[0] <= cutoff:
            fresh = [t for t in timestamps if t > cutoff]
            timestamps[:] = fresh
        if len(timestamps) >= limit:
            oldest = timestamps[0]
            retry_after = max(1, math.ceil(oldest + window_seconds - now))
            return retry_after
        timestamps.append(now)
        return None


def reset_rate_limit_state() -> None:
    """Drop every in-memory bucket. Test hook for isolation between tests."""
    with _lock:
        _buckets.clear()


def _too_many_requests(namespace: str, retry_after: int) -> HTTPException:
    # The identity is never logged or echoed: it may be a phone number or an
    # email address. The response body likewise carries no internals.
    logger.warning("Rate limit exceeded on %s; retry after %s seconds", namespace, retry_after)
    return HTTPException(
        status_code=429,
        detail=f"Too many requests. Please try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


async def _json_body(request: Request) -> dict:
    """Best-effort parsed JSON body; {} when the body is missing or invalid.

    Reading via ``request.body()`` caches the payload in Starlette, so the
    endpoint's Pydantic model can still parse it afterwards. Malformed bodies
    are left for FastAPI to answer with 422 — the limiter just falls back to
    the client IP for those.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed body: fall back to IP keying
        return {}
    return body if isinstance(body, dict) else {}


async def rate_limit_chat(request: Request) -> None:
    """Limit ``POST /api/v1/agent/chat``: 20/min per ``guest_id`` (body),
    falling back to the client IP when ``guest_id`` is absent."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    guest_id = (await _json_body(request)).get("guest_id")
    key = f"guest:{guest_id}" if guest_id is not None else f"ip:{_client_ip(request)}"
    retry_after = _check_budget(
        "agent_chat",
        key,
        settings.rate_limit_chat_per_minute,
        settings.rate_limit_chat_window_seconds,
    )
    if retry_after is not None:
        raise _too_many_requests("agent_chat", retry_after)


async def rate_limit_telegram_webhook(request: Request) -> None:
    """Limit ``POST /api/v1/webhooks/telegram/{hotel_id}``: 30/min per sender
    (Telegram ``chat_id`` from the update payload), falling back to IP."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    body = await _json_body(request)
    chat_id = None
    message = body.get("message")
    if isinstance(message, dict):
        chat = message.get("chat")
        if isinstance(chat, dict):
            chat_id = chat.get("id")
    key = f"sender:{chat_id}" if chat_id is not None else f"ip:{_client_ip(request)}"
    retry_after = _check_budget(
        "telegram_webhook",
        key,
        settings.rate_limit_webhook_per_minute,
        settings.rate_limit_webhook_window_seconds,
    )
    if retry_after is not None:
        raise _too_many_requests("telegram_webhook", retry_after)


async def rate_limit_whatsapp_webhook(request: Request) -> None:
    """Limit ``POST /api/v1/webhooks/whatsapp/{hotel_id}``: 30/min per sender
    (WhatsApp number from the Twilio ``From`` form field), falling back to IP."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    try:
        raw = await request.body()
        params = dict(
            urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True)
        )
        number = (params.get("From") or "").strip()
    except Exception:  # noqa: BLE001 - malformed body: fall back to IP keying
        number = ""
    key = f"sender:{number}" if number else f"ip:{_client_ip(request)}"
    retry_after = _check_budget(
        "whatsapp_webhook",
        key,
        settings.rate_limit_webhook_per_minute,
        settings.rate_limit_webhook_window_seconds,
    )
    if retry_after is not None:
        raise _too_many_requests("whatsapp_webhook", retry_after)


def check_rate_limit(namespace: str, key: str, limit: int, window_seconds: int) -> int | None:
    """Public wrapper over the bucket check (returns retry-after or None).

    Used by the factory-generated limiters below and available to any new
    public endpoint that keys its budget on path/query data rather than
    the request body.
    """
    return _check_budget(namespace, key, limit, window_seconds)


def too_many_requests(namespace: str, retry_after: int) -> HTTPException:
    """Public wrapper building the standard 429 response."""
    return _too_many_requests(namespace, retry_after)


def client_ip(request: Request) -> str:
    return _client_ip(request)


def rate_limit_factory(
    namespace: str,
    limit_attr: str,
    window_attr: str,
    key_extractor,
):
    """Build a rate-limit dependency keyed by ``key_extractor(request, body)``.

    ``limit_attr`` / ``window_attr`` name the Settings attributes read at
    request time, so tests can retune budgets by monkeypatching settings.
    """

    async def _dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        body = await _json_body(request)
        key = key_extractor(request, body) or f"ip:{_client_ip(request)}"
        retry_after = _check_budget(
            namespace,
            key,
            getattr(settings, limit_attr),
            getattr(settings, window_attr),
        )
        if retry_after is not None:
            raise _too_many_requests(namespace, retry_after)

    return _dependency


# Public widget chat: keyed by hotel public_id (body) + client IP, so one
# hotel's guests cannot exhaust another hotel's budget and vice versa.
rate_limit_public_chat = rate_limit_factory(
    "public_chat",
    "rate_limit_public_chat_per_minute",
    "rate_limit_public_chat_window_seconds",
    lambda request, body: (
        f"hotel:{body.get('hotel_public_id')}:ip:{_client_ip(request)}"
        if body.get("hotel_public_id")
        else None
    ),
)

# Public read endpoints (hotel info, landing payload): GET requests carry
# the public_id in the path, so key the budget by path + client IP. Shares
# the public-chat budget settings — public reads get the same per-minute cap.
rate_limit_public_read = rate_limit_factory(
    "public_read",
    "rate_limit_public_chat_per_minute",
    "rate_limit_public_chat_window_seconds",
    lambda request, body: f"path:{request.url.path}:ip:{_client_ip(request)}",
)

# Server-to-server integration API: keyed the same way (body carries the
# hotel public_id).
rate_limit_integration = rate_limit_factory(
    "integration_chat",
    "rate_limit_integration_per_minute",
    "rate_limit_integration_window_seconds",
    lambda request, body: (
        f"hotel:{body.get('hotel_public_id')}:ip:{_client_ip(request)}"
        if body.get("hotel_public_id")
        else None
    ),
)


async def rate_limit_login(request: Request) -> None:
    """Limit ``POST /api/v1/auth/login``: 5/min per client IP + email pair,
    slowing credential-stuffing attempts without punishing unrelated users."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    email = str((await _json_body(request)).get("email") or "").strip().lower()
    key = f"{_client_ip(request)}:{email or 'no-email'}"
    retry_after = _check_budget(
        "auth_login",
        key,
        settings.rate_limit_login_per_minute,
        settings.rate_limit_login_window_seconds,
    )
    if retry_after is not None:
        raise _too_many_requests("auth_login", retry_after)
