"""Rate-limit tests (Prompt-1 section 4): in-memory sliding-window limiter.

Short windows (2 requests per 2 seconds) via settings overrides keep the
suite fast. The limiter reads settings at request time, so monkeypatching
attributes on the shared settings object is enough; an autouse fixture
resets the in-memory buckets so tests never leak state into each other or
into the rest of the suite.
"""

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bots import telegram as telegram_bot
from app.bots import whatsapp as whatsapp_bot
from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limit_state
from app.db.session import SessionLocal
from app.main import app
from app.models.guest import Guest
from app.models.hotel import Hotel

settings = get_settings()
client = TestClient(app)

CHAT_URL = "/api/v1/agent/chat"
LOGIN_URL = "/api/v1/auth/login"

TELEGRAM_SECRET = "rl-test-telegram-webhook-secret"
TWILIO_AUTH_TOKEN = "rl-test-twilio-auth-token"
TWILIO_ACCOUNT_SID = "ACtestsid00000000000000000000000000"
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"


@pytest.fixture(autouse=True)
def _fresh_rate_limit_buckets():
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


def _make_hotel() -> int:
    with SessionLocal() as db:
        hotel = Hotel(name=f"RL Hotel {uuid4().hex[:8]}", city="Testville")
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        return hotel.id


def _make_guest(hotel_id: int) -> int:
    """Seed a real guest (POST /api/v1/agent/chat 422s on unknown guest_id)."""
    with SessionLocal() as db:
        guest = Guest(hotel_id=hotel_id, name=f"RL Guest {uuid4().hex[:8]}")
        db.add(guest)
        db.commit()
        db.refresh(guest)
        return guest.id


def _assert_rate_limited(response) -> None:
    assert response.status_code == 429
    retry_after = response.headers.get("retry-after")
    assert retry_after is not None, "429 must carry a Retry-After header"
    assert int(retry_after) >= 1, "Retry-After must be a positive number of seconds"
    body = response.json()
    assert "detail" in body
    # The body must not leak internals (keys, identities, bucket state).
    lowered = response.text.lower()
    assert "bucket" not in lowered
    assert "namespace" not in lowered


# --------------------------------------------------------------------- #
# POST /api/v1/agent/chat — 20/min by guest_id (IP fallback)             #
# --------------------------------------------------------------------- #
def test_agent_chat_rate_limited_per_guest_id(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_chat_window_seconds", 2)
    hotel_id = _make_hotel()
    guest_id = _make_guest(hotel_id)
    body = {"hotel_id": hotel_id, "message": "Do you have rooms?", "guest_id": guest_id}

    assert client.post(CHAT_URL, json=body).status_code == 200
    assert client.post(CHAT_URL, json=body).status_code == 200
    _assert_rate_limited(client.post(CHAT_URL, json=body))
    assert str(guest_id) not in client.post(CHAT_URL, json=body).text

    # A different guest gets its own bucket and is unaffected.
    other_guest = {**body, "guest_id": _make_guest(hotel_id)}
    assert client.post(CHAT_URL, json=other_guest).status_code == 200

    # The window resets: after 2s the same guest is allowed again.
    time.sleep(2.3)
    assert client.post(CHAT_URL, json=body).status_code == 200


def test_agent_chat_rate_limit_falls_back_to_ip(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_chat_window_seconds", 2)
    hotel_id = _make_hotel()
    body = {"hotel_id": hotel_id, "message": "Do you have rooms?"}  # no guest_id

    assert client.post(CHAT_URL, json=body).status_code == 200
    assert client.post(CHAT_URL, json=body).status_code == 200
    _assert_rate_limited(client.post(CHAT_URL, json=body))


# --------------------------------------------------------------------- #
# POST /api/v1/auth/login — 5/min by client IP + email                   #
# --------------------------------------------------------------------- #
def test_auth_login_rate_limited_per_ip_and_email(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 2)
    email = f"{uuid4().hex}@example.com"
    payload = {"email": email, "password": "wrong-password"}

    # Under the limit, wrong passwords still answer 401 (behavior preserved).
    assert client.post(LOGIN_URL, json=payload).status_code == 401
    assert client.post(LOGIN_URL, json=payload).status_code == 401

    r = client.post(LOGIN_URL, json=payload)
    _assert_rate_limited(r)
    # The 429 body must not leak the attempted email address.
    assert email.split("@")[0] not in r.text

    # A different email is a different bucket: still 401, not 429.
    other = {"email": f"{uuid4().hex}@example.com", "password": "wrong-password"}
    assert client.post(LOGIN_URL, json=other).status_code == 401

    # The window resets: attempts are counted again (401, not 429).
    time.sleep(2.3)
    assert client.post(LOGIN_URL, json=payload).status_code == 401


# --------------------------------------------------------------------- #
# Telegram + WhatsApp webhooks — 30/min by sender identity (IP fallback) #
# --------------------------------------------------------------------- #
def test_telegram_webhook_rate_limited_per_chat_id(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_webhook_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_webhook_window_seconds", 2)
    monkeypatch.setattr(settings, "telegram_webhook_secret", TELEGRAM_SECRET)
    monkeypatch.setattr(telegram_bot, "send_message", lambda *a, **k: True)

    hotel_id = _make_hotel()
    url = f"/api/v1/webhooks/telegram/{hotel_id}"
    headers = {"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET}

    def post(chat_id):
        return client.post(
            url,
            json={
                "update_id": 1,
                "message": {"message_id": 7, "chat": {"id": chat_id}, "text": "hi"},
            },
            headers=headers,
        )

    assert post(424242).status_code == 200
    assert post(424242).status_code == 200
    _assert_rate_limited(post(424242))

    # A different sender gets its own bucket and is unaffected.
    assert post(777000).status_code == 200

    # The window resets: the same sender is allowed again.
    time.sleep(2.3)
    assert post(424242).status_code == 200


def test_whatsapp_webhook_rate_limited_per_sender(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_webhook_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_webhook_window_seconds", 2)
    monkeypatch.setattr(settings, "twilio_auth_token", TWILIO_AUTH_TOKEN)
    monkeypatch.setattr(settings, "twilio_account_sid", TWILIO_ACCOUNT_SID)
    monkeypatch.setattr(settings, "twilio_whatsapp_number", TWILIO_WHATSAPP_NUMBER)
    monkeypatch.setattr(whatsapp_bot, "send_message", lambda *a, **k: True)

    hotel_id = _make_hotel()
    url = f"/api/v1/webhooks/whatsapp/{hotel_id}"

    def post(sender):
        params = {"From": f"whatsapp:{sender}", "Body": "Do you have rooms?"}
        signature = whatsapp_bot.compute_twilio_signature(
            TWILIO_AUTH_TOKEN, f"http://testserver{url}", params
        )
        return client.post(url, data=params, headers={"X-Twilio-Signature": signature})

    assert post("+15550001111").status_code == 200
    assert post("+15550001111").status_code == 200
    _assert_rate_limited(post("+15550001111"))

    # A different sender gets its own bucket and is unaffected.
    assert post("+15550002222").status_code == 200

    # The window resets: the same sender is allowed again.
    time.sleep(2.3)
    assert post("+15550001111").status_code == 200
