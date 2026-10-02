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
move this to a shared store (Redis) — until then each worker enforces
its own budget.

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

# Bucket key ("<namespace>:<identity>") -> sorted (oldest first) timestamps
# of allowed requests, as time.monotonic() floats.
_buckets: dict[str, list[float]] = {}
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """Return the direct client IP.

    We intentionally do not trust X-Forwarded-For here. If the application
    is deployed behind a trusted reverse proxy, proxy-aware middleware can
    normalize the client address before this function is used.
    """
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

        # Prune expired entries in place.
        if timestamps and timestamps[0] <= cutoff:
            fresh = [t for t in timestamps if t > cutoff]
            timestamps[:] = fresh

        if len(timestamps) >= limit:
            oldest = timestamps[0]
            retry_after = max(
                1,
                math.ceil(oldest + window_seconds - now),
            )
            return retry_after

        timestamps.append(now)
        return None


def reset_rate_limit_state() -> None:
    """Drop every in-memory bucket.

    Test hook used to isolate rate-limit tests from each other.
    """
    with _lock:
        _buckets.clear()


def _too_many_requests(
    namespace: str,
    retry_after: int,
) -> HTTPException:
    """Create the public HTTP 429 response.

    The identity is never logged or echoed because it may contain a phone
    number or email address. The response body carries no bucket/key data.
    """
    logger.warning(
        "Rate limit exceeded on %s; retry after %s seconds",
        namespace,
        retry_after,
    )

    return HTTPException(
        status_code=429,
        detail=(f"Too many requests. Please try again in {retry_after} seconds."),
        headers={"Retry-After": str(retry_after)},
    )


async def _json_body(request: Request) -> dict:
    """Best-effort parsed JSON body.

    Returns ``{}`` when the body is missing or invalid.

    Reading via ``request.body()`` / ``request.json()`` caches the payload in
    Starlette, so the endpoint's Pydantic model can still parse it afterwards.

    Malformed bodies are left for FastAPI to answer with 422 — the limiter
    simply falls back to the client IP.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}

    return body if isinstance(body, dict) else {}


async def rate_limit_chat(request: Request) -> None:
    """Limit ``POST /api/v1/agent/chat``.

    Known guest requests use an isolated ``guest_id`` bucket. Anonymous
    requests fall back to the client IP.

    This matches the application's public-chat rate-limit contract:
    ``guest_id`` is used when supplied, otherwise the IP is used.
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        return

    body = await _json_body(request)
    guest_id = body.get("guest_id")

    if guest_id is not None:
        key = f"guest:{guest_id}"
    else:
        key = f"ip:{_client_ip(request)}"

    retry_after = _check_budget(
        "agent_chat",
        key,
        settings.rate_limit_chat_per_minute,
        settings.rate_limit_chat_window_seconds,
    )

    if retry_after is not None:
        raise _too_many_requests(
            "agent_chat",
            retry_after,
        )


async def rate_limit_telegram_webhook(request: Request) -> None:
    """Limit Telegram webhook requests.

    Default: 30/min per sender using Telegram ``chat_id``.

    Falls back to client IP when a usable ``chat_id`` cannot be extracted.
    """
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
        raise _too_many_requests(
            "telegram_webhook",
            retry_after,
        )


async def rate_limit_whatsapp_webhook(request: Request) -> None:
    """Limit WhatsApp webhook requests.

    Default: 30/min per sender using the Twilio ``From`` form field.

    Falls back to client IP when the sender number cannot be extracted.
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        return

    try:
        raw = await request.body()

        params = dict(
            urllib.parse.parse_qsl(
                raw.decode("utf-8", "replace"),
                keep_blank_values=True,
            )
        )

        number = (params.get("From") or "").strip()

    except Exception:  # noqa: BLE001
        number = ""

    key = f"sender:{number}" if number else f"ip:{_client_ip(request)}"

    retry_after = _check_budget(
        "whatsapp_webhook",
        key,
        settings.rate_limit_webhook_per_minute,
        settings.rate_limit_webhook_window_seconds,
    )

    if retry_after is not None:
        raise _too_many_requests(
            "whatsapp_webhook",
            retry_after,
        )


async def rate_limit_login(request: Request) -> None:
    """Limit ``POST /api/v1/auth/login``.

    Default: 5/min per client IP + email pair.

    This slows credential-stuffing attempts without unnecessarily punishing
    unrelated users sharing the same network.
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        return

    body = await _json_body(request)

    email = str(body.get("email") or "").strip().lower()

    key = f"{_client_ip(request)}:{email or 'no-email'}"

    retry_after = _check_budget(
        "auth_login",
        key,
        settings.rate_limit_login_per_minute,
        settings.rate_limit_login_window_seconds,
    )

    if retry_after is not None:
        raise _too_many_requests(
            "auth_login",
            retry_after,
        )
