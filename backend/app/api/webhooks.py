"""Public webhook endpoints for the messaging bot connectors.

These routes are intentionally PUBLIC: they are called by Telegram / Twilio,
not by staff, so they must never require the staff JWT. Each provider
authenticates its own way:

- Telegram: ``X-Telegram-Bot-Api-Secret-Token`` must equal
  ``TELEGRAM_WEBHOOK_SECRET`` (403 otherwise).
- WhatsApp (Twilio): ``X-Twilio-Signature`` must validate against
  ``TWILIO_AUTH_TOKEN`` for the request URL + form params (403 otherwise).

Both handlers:

- resolve the sender to a :class:`~app.models.guest.Guest` by
  ``(hotel_id, telegram_chat_id)`` / ``(hotel_id, whatsapp_number)``,
  creating the guest only when absent (never duplicates);
- run one :func:`~app.agent.runner.run_chat` turn with
  ``channel="telegram"`` / ``channel="whatsapp"``;
- echo the agent reply back over the same channel;
- never return 500: provider failures are logged and answered with 200 so
  the provider does not retry-loop a doomed update.
"""

from __future__ import annotations

import hmac
import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.config import AgentConfig
from app.agent.runner import run_chat
from app.bots import telegram as telegram_bot
from app.bots import whatsapp as whatsapp_bot
from app.core.config import get_settings
from app.core.rate_limit import (
    rate_limit_telegram_webhook,
    rate_limit_whatsapp_webhook,
)
from app.db.session import get_db
from app.models.guest import Guest
from app.models.hotel import Hotel

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


def _get_hotel_or_404(db: Session, hotel_id: int) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return hotel


def _agent_config() -> AgentConfig:
    return AgentConfig.from_settings(settings)


def _get_or_create_channel_guest(
    db: Session,
    *,
    hotel_id: int,
    channel_attr: str,
    channel_value: str,
    display_name: str,
) -> Guest:
    """Find the guest for a channel identity, creating it only when absent."""
    stmt = select(Guest).where(
        Guest.hotel_id == hotel_id,
        getattr(Guest, channel_attr) == channel_value,
    )
    guest = db.scalar(stmt)
    if guest is not None:
        return guest
    guest = Guest(hotel_id=hotel_id, name=f"{display_name} {channel_value}")
    setattr(guest, channel_attr, channel_value)
    db.add(guest)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent webhook for the same sender:
        # roll back and return the row that won.
        db.rollback()
        guest = db.scalar(stmt)
        if guest is None:  # pragma: no cover - defensive
            raise
    return guest


def _run_agent_reply(
    db: Session,
    *,
    hotel_id: int,
    message: str,
    guest_id: int,
    channel: str,
) -> str | None:
    """Run one agent turn; return the reply, or None on failure (never 500)."""
    try:
        result = run_chat(
            db,
            hotel_id=hotel_id,
            message=message,
            guest_id=guest_id,
            channel=channel,
            config=_agent_config(),
        )
    except Exception:  # noqa: BLE001 - webhooks must not 500 on agent failure
        logger.exception("Agent failed for %s webhook (hotel %s)", channel, hotel_id)
        return None
    return result.reply


@router.post(
    "/webhooks/telegram/{hotel_id}",
    tags=["webhooks"],
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
async def telegram_webhook(
    hotel_id: int,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_telegram_webhook),
) -> dict[str, bool]:
    """Handle an inbound Telegram update for a hotel."""
    secret = request.headers.get("x-telegram-bot-api-secret-token")
    expected = settings.telegram_webhook_secret
    if not expected or not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON is a no-op, not a 500
        logger.warning("Telegram webhook got non-JSON body for hotel %s", hotel_id)
        return {"ok": True}

    chat_id, text = telegram_bot.parse_update(payload)
    if chat_id is None or text is None:
        return {"ok": True}  # non-message update: acknowledge, do nothing

    _get_hotel_or_404(db, hotel_id)
    guest = _get_or_create_channel_guest(
        db,
        hotel_id=hotel_id,
        channel_attr="telegram_chat_id",
        channel_value=str(chat_id),
        display_name="Telegram guest",
    )
    db.commit()

    reply = _run_agent_reply(
        db, hotel_id=hotel_id, message=text, guest_id=guest.id, channel="telegram"
    )
    if reply:
        telegram_bot.send_message(settings.telegram_bot_token, chat_id, reply)
    return {"ok": True}


@router.post(
    "/webhooks/whatsapp/{hotel_id}",
    tags=["webhooks"],
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
async def whatsapp_webhook(
    hotel_id: int,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_whatsapp_webhook),
) -> dict[str, bool]:
    """Handle an inbound Twilio WhatsApp message for a hotel."""
    raw_body = await request.body()
    params = dict(
        urllib.parse.parse_qsl(raw_body.decode("utf-8", "replace"), keep_blank_values=True)
    )

    signature = request.headers.get("x-twilio-signature")
    # Twilio signs the exact public URL it called. Deployments behind a
    # reverse proxy must make request.url reflect that public URL
    # (e.g. via X-Forwarded-Proto/Host handling) for validation to pass.
    url = str(request.url)
    if not whatsapp_bot.verify_twilio_signature(settings.twilio_auth_token, signature, url, params):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    number, text = whatsapp_bot.parse_message(params)
    if number is None or text is None:
        return {"ok": True}  # status callback etc.: acknowledge, do nothing

    _get_hotel_or_404(db, hotel_id)
    guest = _get_or_create_channel_guest(
        db,
        hotel_id=hotel_id,
        channel_attr="whatsapp_number",
        channel_value=number,
        display_name="WhatsApp guest",
    )
    db.commit()

    reply = _run_agent_reply(
        db, hotel_id=hotel_id, message=text, guest_id=guest.id, channel="whatsapp"
    )
    if reply:
        whatsapp_bot.send_message(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            settings.twilio_whatsapp_number,
            number,
            reply,
        )
    return {"ok": True}
