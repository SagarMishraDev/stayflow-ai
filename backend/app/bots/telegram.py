"""Minimal Telegram Bot API connector (Prompt-1 section 4).

Parses inbound Telegram update JSON directly and sends replies with plain
``httpx`` POSTs to the Bot HTTP API. No aiogram / python-telegram-bot.

Sandbox quirk: unset proxy env vars (``NO_PROXY`` containing ``"[::1]"``
breaks httpx in some bot libraries), so every outbound call runs with proxy
variables stripped.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"

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


def parse_update(payload: Any) -> tuple[int | str | None, str | None]:
    """Extract ``(chat_id, text)`` from a Telegram update dict.

    Returns ``(None, None)`` for updates without a usable text message
    (edits, callbacks, channel posts, malformed payloads) so the webhook can
    acknowledge them with 200 and do nothing.
    """
    if not isinstance(payload, dict):
        return None, None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None, None
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    text = message.get("text")
    if chat_id is None or not isinstance(text, str) or not text.strip():
        return None, None
    return chat_id, text.strip()


def send_message(
    bot_token: str | None,
    chat_id: int | str,
    text: str,
    timeout: float = 10.0,
) -> bool:
    """Send ``text`` to ``chat_id`` via the Bot HTTP API.

    Never raises: missing token, network errors, and Telegram API errors are
    logged and return ``False`` so webhook handlers can still answer 200.
    """
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured; dropping Telegram reply")
        return False
    url = f"{_API_BASE}/bot{bot_token}/sendMessage"
    try:
        with _no_proxy_env():
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=timeout,
            )
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - webhook must never 500 on send failure
        logger.exception("Failed to send Telegram message to chat %s", chat_id)
        return False
    return True


def set_webhook(
    bot_token: str | None,
    webhook_url: str,
    secret_token: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """Register ``webhook_url`` as the bot's webhook via ``setWebhook``.

    ``secret_token`` is passed through when configured: Telegram then
    sends it as ``X-Telegram-Bot-Api-Secret-Token`` on every update,
    which the webhook route verifies against ``TELEGRAM_WEBHOOK_SECRET``.

    Never raises (same contract as :func:`send_message`): missing token,
    network errors, and Telegram API errors are logged and return
    ``False``, so callers — the app startup hook — can log and boot on.
    Re-registering the same URL is a Telegram no-op, so this is safe to
    call on every startup.
    """
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured; skipping webhook registration")
        return False
    payload: dict[str, Any] = {"url": webhook_url}
    if secret_token:
        payload["secret_token"] = secret_token
    try:
        with _no_proxy_env():
            response = httpx.post(
                f"{_API_BASE}/bot{bot_token}/setWebhook",
                json=payload,
                timeout=timeout,
            )
        response.raise_for_status()
        data = response.json()
    except Exception:  # noqa: BLE001 - registration must never crash startup
        logger.exception("Failed to register Telegram webhook %s", webhook_url)
        return False
    if not data.get("ok"):
        logger.warning(
            "Telegram setWebhook rejected for %s: %s", webhook_url, data.get("description")
        )
        return False
    return True
