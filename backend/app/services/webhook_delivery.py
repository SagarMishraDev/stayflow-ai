"""Outbound webhook delivery for the integration API (Master Prompt §12).

When a hotel configures an ``integration_webhook_url``, the integration
endpoint delivers the chat response there as a signed JSON POST. This is
the asynchronous path: the synchronous API response is authoritative;
webhook delivery is best-effort with bounded retries and never blocks or
fails the chat request.

Signing: the same scheme as inbound requests — an
``X-StayFlow-Signature: sha256=<hex>`` header holding
HMAC-SHA256(webhook_secret, ``f"{timestamp}." + raw_body``), plus an
``X-StayFlow-Timestamp`` header with the signing time (Unix seconds), so
receivers can apply the same replay-window check.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.services.integration_security import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
)

logger = logging.getLogger(__name__)

# Backoff between attempts (seconds). Delivery is bounded: at most
# ``max_retries`` total attempts (default from settings, 3).
_BACKOFF_SECONDS = (0.5, 1.0, 2.0)


def sign_payload(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Compute the delivery signature for a webhook payload."""
    return compute_signature(secret, timestamp, raw_body)


def build_delivery(
    url: str, payload: dict, secret: str, *, timestamp: str | None = None
) -> tuple[bytes, dict[str, str]]:
    """Serialize the payload and build the signed headers for a delivery."""
    ts = timestamp or str(int(time.time()))
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: ts,
        SIGNATURE_HEADER: sign_payload(secret, ts, raw_body),
    }
    return raw_body, headers


def deliver_webhook(
    url: str,
    payload: dict,
    secret: str,
    *,
    timeout_seconds: float = 5.0,
    max_retries: int = 3,
    sleep=time.sleep,
) -> bool:
    """POST ``payload`` to ``url`` with signed headers; bounded retries.

    Retries on network errors and 5xx responses; 4xx responses are treated
    as permanent failures (retrying a malformed/rejected payload cannot
    help). Returns True on the first 2xx response, False after the retry
    budget is exhausted. Never raises for delivery failures.
    """
    attempts = max(1, max_retries)
    raw_body, headers = build_delivery(url, payload, secret)
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(url, content=raw_body, headers=headers, timeout=timeout_seconds)
        except httpx.HTTPError as exc:
            # Log the error type only — never the URL query or the payload.
            logger.warning(
                "webhook delivery attempt %s/%s failed: %s",
                attempt,
                attempts,
                type(exc).__name__,
            )
            response = None
        if response is not None:
            if 200 <= response.status_code < 300:
                logger.info("webhook delivered on attempt %s", attempt)
                return True
            if 400 <= response.status_code < 500:
                logger.warning(
                    "webhook delivery rejected with %s (permanent, not retrying)",
                    response.status_code,
                )
                return False
            logger.warning(
                "webhook delivery attempt %s/%s got %s",
                attempt,
                attempts,
                response.status_code,
            )
        if attempt < attempts:
            sleep(_BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
    logger.warning("webhook delivery failed after %s attempts", attempts)
    return False
