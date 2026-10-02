"""Webhook tests for the Telegram + WhatsApp connectors (Prompt-1 sections 4-5).

No real network: outbound ``httpx.post`` calls are monkeypatched and the
agent runs on the deterministic mock provider (see tests/conftest.py).

Hotels/guests are seeded and asserted directly through SQLAlchemy so these
tests do not depend on the staff JWT auth protecting the CRUD endpoints —
the webhooks themselves must stay public.
"""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.bots import whatsapp as whatsapp_bot
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.guest import Guest
from app.models.hotel import Hotel
from tests._helpers import client, ok

settings = get_settings()

TELEGRAM_SECRET = "test-telegram-secret"
TELEGRAM_TOKEN = "test-bot-token"
TWILIO_AUTH_TOKEN = "test-twilio-auth-token"
TWILIO_ACCOUNT_SID = "ACtestsid00000000000000000000000000"
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
GUEST_WHATSAPP = "+15551234567"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


@pytest.fixture
def outbound(monkeypatch):
    """Capture outbound httpx.post calls instead of hitting the network."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": str(url), **kwargs})
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


@pytest.fixture
def telegram_settings(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", TELEGRAM_SECRET)
    monkeypatch.setattr(settings, "telegram_bot_token", TELEGRAM_TOKEN)


@pytest.fixture
def twilio_settings(monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", TWILIO_AUTH_TOKEN)
    monkeypatch.setattr(settings, "twilio_account_sid", TWILIO_ACCOUNT_SID)
    monkeypatch.setattr(settings, "twilio_whatsapp_number", TWILIO_WHATSAPP_NUMBER)


def _make_hotel():
    """Seed a hotel straight in the DB (POST /hotels is staff-protected)."""
    with SessionLocal() as db:
        hotel = Hotel(name=f"Webhook Hotel {uuid4().hex[:8]}", city="Testville")
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        return hotel.id


def _guests_for_hotel(hotel_id):
    """Read guests straight from the DB (GET /guests is staff-protected)."""
    with SessionLocal() as db:
        return db.scalars(select(Guest).where(Guest.hotel_id == hotel_id)).all()


def _telegram_headers(secret=TELEGRAM_SECRET):
    return {"X-Telegram-Bot-Api-Secret-Token": secret}


def _telegram_update(chat_id=424242, text="Hello, do you have rooms?"):
    return {"update_id": 1, "message": {"message_id": 7, "chat": {"id": chat_id}, "text": text}}


# --------------------------------------------------------------------- #
# Telegram                                                               #
# --------------------------------------------------------------------- #
def test_telegram_webhook_happy_path(telegram_settings, outbound):
    hotel_id = _make_hotel()
    r = client.post(
        f"/api/v1/webhooks/telegram/{hotel_id}",
        json=_telegram_update(),
        headers=_telegram_headers(),
    )
    ok(r, 200)
    assert r.json() == {"ok": True}

    assert len(outbound) == 1
    call = outbound[0]
    assert call["url"] == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    assert call["json"]["chat_id"] == 424242
    assert isinstance(call["json"]["text"], str) and call["json"]["text"].strip()

    guests = _guests_for_hotel(hotel_id)
    assert len(guests) == 1
    assert guests[0].telegram_chat_id == "424242"


def test_telegram_webhook_wrong_secret(telegram_settings, outbound):
    hotel_id = _make_hotel()
    r = client.post(
        f"/api/v1/webhooks/telegram/{hotel_id}",
        json=_telegram_update(),
        headers=_telegram_headers("wrong-secret"),
    )
    assert r.status_code == 403
    assert outbound == []


def test_telegram_webhook_missing_secret(telegram_settings, outbound):
    hotel_id = _make_hotel()
    r = client.post(
        f"/api/v1/webhooks/telegram/{hotel_id}",
        json=_telegram_update(),
    )
    assert r.status_code == 403
    assert outbound == []


def test_telegram_webhook_unconfigured_secret_is_403(outbound, monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", None)
    hotel_id = _make_hotel()
    r = client.post(
        f"/api/v1/webhooks/telegram/{hotel_id}",
        json=_telegram_update(),
        headers=_telegram_headers(),
    )
    assert r.status_code == 403
    assert outbound == []


def test_telegram_webhook_non_message_update_is_noop(telegram_settings, outbound):
    hotel_id = _make_hotel()
    for payload in (
        {"update_id": 2, "message": {"message_id": 8, "chat": {"id": 99}}},  # no text
        {"update_id": 3, "edited_message": {"chat": {"id": 99}, "text": "hi"}},  # not message
        {"update_id": 4},  # empty
    ):
        r = client.post(
            f"/api/v1/webhooks/telegram/{hotel_id}",
            json=payload,
            headers=_telegram_headers(),
        )
        ok(r, 200)
        assert r.json() == {"ok": True}
    assert outbound == []
    assert _guests_for_hotel(hotel_id) == []


def test_telegram_webhook_reuses_guest(telegram_settings, outbound):
    hotel_id = _make_hotel()
    for text in ("Hello", "Do you have a pool?"):
        r = client.post(
            f"/api/v1/webhooks/telegram/{hotel_id}",
            json=_telegram_update(text=text),
            headers=_telegram_headers(),
        )
        ok(r, 200)
    guests = _guests_for_hotel(hotel_id)
    assert len(guests) == 1
    assert guests[0].telegram_chat_id == "424242"
    assert len(outbound) == 2  # one reply per message


def test_telegram_webhook_unknown_hotel(telegram_settings, outbound):
    r = client.post(
        "/api/v1/webhooks/telegram/999999",
        json=_telegram_update(),
        headers=_telegram_headers(),
    )
    assert r.status_code == 404
    assert outbound == []


# --------------------------------------------------------------------- #
# WhatsApp (Twilio)                                                      #
# --------------------------------------------------------------------- #
def _twilio_params(body="Hello, do you have rooms?", sender=GUEST_WHATSAPP):
    return {"From": f"whatsapp:{sender}", "Body": body}


def _twilio_headers(hotel_id, params, token=TWILIO_AUTH_TOKEN):
    url = f"http://testserver/api/v1/webhooks/whatsapp/{hotel_id}"
    signature = whatsapp_bot.compute_twilio_signature(token, url, params)
    return {"X-Twilio-Signature": signature}


def test_whatsapp_webhook_happy_path(twilio_settings, outbound):
    hotel_id = _make_hotel()
    params = _twilio_params()
    r = client.post(
        f"/api/v1/webhooks/whatsapp/{hotel_id}",
        data=params,
        headers=_twilio_headers(hotel_id, params),
    )
    ok(r, 200)
    assert r.json() == {"ok": True}

    assert len(outbound) == 1
    call = outbound[0]
    assert (
        call["url"]
        == f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    )
    assert call["auth"] == (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    assert call["data"]["From"] == TWILIO_WHATSAPP_NUMBER
    assert call["data"]["To"] == f"whatsapp:{GUEST_WHATSAPP}"
    assert isinstance(call["data"]["Body"], str) and call["data"]["Body"].strip()

    guests = _guests_for_hotel(hotel_id)
    assert len(guests) == 1
    assert guests[0].whatsapp_number == GUEST_WHATSAPP


def test_whatsapp_webhook_bad_signature(twilio_settings, outbound):
    hotel_id = _make_hotel()
    params = _twilio_params()
    r = client.post(
        f"/api/v1/webhooks/whatsapp/{hotel_id}",
        data=params,
        headers=_twilio_headers(hotel_id, params, token="wrong-token"),
    )
    assert r.status_code == 403
    assert outbound == []


def test_whatsapp_webhook_missing_signature(twilio_settings, outbound):
    hotel_id = _make_hotel()
    r = client.post(
        f"/api/v1/webhooks/whatsapp/{hotel_id}",
        data=_twilio_params(),
    )
    assert r.status_code == 403
    assert outbound == []


def test_whatsapp_webhook_status_callback_is_noop(twilio_settings, outbound):
    hotel_id = _make_hotel()
    params = {"MessageSid": "SM123", "MessageStatus": "delivered"}
    r = client.post(
        f"/api/v1/webhooks/whatsapp/{hotel_id}",
        data=params,
        headers=_twilio_headers(hotel_id, params),
    )
    ok(r, 200)
    assert r.json() == {"ok": True}
    assert outbound == []
    assert _guests_for_hotel(hotel_id) == []


def test_whatsapp_webhook_reuses_guest(twilio_settings, outbound):
    hotel_id = _make_hotel()
    for body in ("Hello", "What time is check-in?"):
        params = _twilio_params(body=body)
        r = client.post(
            f"/api/v1/webhooks/whatsapp/{hotel_id}",
            data=params,
            headers=_twilio_headers(hotel_id, params),
        )
        ok(r, 200)
    guests = _guests_for_hotel(hotel_id)
    assert len(guests) == 1
    assert guests[0].whatsapp_number == GUEST_WHATSAPP
    assert len(outbound) == 2
