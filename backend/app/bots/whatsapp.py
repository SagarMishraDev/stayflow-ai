"""Minimal Twilio WhatsApp connector (Prompt-1 section 5).

Validates Twilio's ``X-Twilio-Signature`` and sends replies through the Twilio
Messages REST API with plain ``httpx`` calls — no twilio SDK.

Signature algorithm (per spec): ``HMAC-SHA1`` keyed with ``TWILIO_AUTH_TOKEN``
over ``full_url + sorted POST params concatenated as key+value``. The hex
digest is compared with :func:`hmac.compare_digest`.

.. note::
    Real Twilio signs with base64, not hex. This module implements the hex
    variant named by the project spec; if you point this at production Twilio
    webhooks, switch :func:`compute_twilio_signature` to base64.

Sandbox quirk: unset proxy env vars (``NO_PROXY`` containing ``"[::1]"``
breaks httpx in some bot libraries), so every outbound call runs with proxy
variables stripped.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.twilio.com/2010-04-01"

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


@contextmanager
def _no_proxy_env() -> Iterator[None]:
    """Temporarily strip proxy env vars (both cases) for one outbound call."""
    saved: dict[str, str] = {}
    for name in _PROXY_ENV_VARS:
        for key in (name, name.lower()):
            if key in os.environ:
                saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        os.environ.update(saved)


def compute_twilio_signature(
    auth_token: str,
    url: str,
    params: Mapping[str, str],
) -> str:
    """Compute the expected ``X-Twilio-Signature`` hex digest for a request."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    return hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()


def verify_twilio_signature(
    auth_token: str | None,
    signature: str | None,
    url: str,
    params: Mapping[str, str],
) -> bool:
    """Return True when ``signature`` matches the expected Twilio signature."""
    if not auth_token or not signature:
        return False
    expected = compute_twilio_signature(auth_token, url, params)
    return hmac.compare_digest(expected, signature)


def parse_message(params: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Extract ``(whatsapp_number, body)`` from Twilio form params.

    Strips the ``whatsapp:`` prefix from ``From``. Returns ``(None, None)``
    for non-message callbacks (e.g. status callbacks) so the webhook can
    acknowledge them with 200 and do nothing.
    """
    raw_from = (params.get("From") or "").strip()
    body = (params.get("Body") or "").strip()
    if not raw_from or not body:
        return None, None
    number = raw_from
    if raw_from.lower().startswith("whatsapp:"):
        number = raw_from[len("whatsapp:") :]
    return number.strip(), body


def send_message(
    account_sid: str | None,
    auth_token: str | None,
    from_number: str | None,
    to_number: str,
    body: str,
    timeout: float = 10.0,
) -> bool:
    """Send a WhatsApp message via the Twilio Messages REST API.

    Never raises: missing config, network errors, and Twilio API errors are
    logged and return ``False`` so webhook handlers can still answer 200.
    """
    if not (account_sid and auth_token and from_number):
        logger.warning(
            "Twilio WhatsApp is not configured (TWILIO_ACCOUNT_SID / "
            "TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_NUMBER); dropping reply"
        )
        return False
    url = f"{_API_BASE}/Accounts/{account_sid}/Messages.json"
    try:
        with _no_proxy_env():
            response = httpx.post(
                url,
                data={
                    "From": from_number,
                    "To": f"whatsapp:{to_number}",
                    "Body": body,
                },
                auth=(account_sid, auth_token),
                timeout=timeout,
            )
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - webhook must never 500 on send failure
        logger.exception("Failed to send WhatsApp message to %s", to_number)
        return False
    return True
