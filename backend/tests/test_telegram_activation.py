"""Telegram activation: paste-only webhook registration at startup.

The app lifespan (``app.main._register_telegram_webhook``) must:

- do nothing at all (no HTTP, no DB work) when ``TELEGRAM_BOT_TOKEN``
  is unset — local runs and the rest of the suite stay unaffected;
- when token + webhook secret + ``APP_PUBLIC_BASE_URL`` are all set,
  call Telegram ``setWebhook`` for
  ``{base}/api/v1/webhooks/telegram/{hotel_id}`` with the configured
  ``secret_token`` (the value the webhook route verifies);
- never break startup when Telegram is unreachable or rejects.

No real network: outbound ``httpx.post`` is monkeypatched, following
tests/test_webhooks.py.
"""

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.bots.telegram import set_webhook
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.hotel import Hotel

settings = get_settings()

TELEGRAM_TOKEN = "fake-bot-token"
TELEGRAM_SECRET = "fake-webhook-secret"
BASE_URL = "https://stayflow-ai-demo.onrender.com"


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
def telegram_configured(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TELEGRAM_TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", TELEGRAM_SECRET)
    monkeypatch.setattr(settings, "app_public_base_url", BASE_URL)


def _make_hotel() -> int:
    with SessionLocal() as db:
        hotel = Hotel(name=f"Activation Hotel {uuid4().hex[:8]}", city="Testville")
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        return hotel.id


def _lowest_hotel_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.min(Hotel.id)))


# --------------------------------------------------------------------- #
# Startup hook                                                           #
# --------------------------------------------------------------------- #
def test_startup_registers_webhook_when_fully_configured(telegram_configured, outbound):
    _make_hotel()
    expected_hotel_id = _lowest_hotel_id()

    with TestClient(app):
        pass  # entering the context runs the lifespan (incl. the hook)

    telegram_calls = [c for c in outbound if "api.telegram.org" in c["url"]]
    assert len(telegram_calls) == 1
    call = telegram_calls[0]
    assert call["url"] == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    assert call["json"]["url"] == f"{BASE_URL}/api/v1/webhooks/telegram/{expected_hotel_id}"
    assert call["json"]["secret_token"] == TELEGRAM_SECRET


def test_startup_skips_webhook_without_token(monkeypatch, outbound):
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_webhook_secret", TELEGRAM_SECRET)
    monkeypatch.setattr(settings, "app_public_base_url", BASE_URL)

    with TestClient(app):
        pass

    assert [c for c in outbound if "api.telegram.org" in c["url"]] == []


def test_startup_survives_telegram_outage(telegram_configured, monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("telegram unreachable", request=None)

    monkeypatch.setattr(httpx, "post", boom)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


# --------------------------------------------------------------------- #
# set_webhook unit behaviour                                             #
# --------------------------------------------------------------------- #
def test_set_webhook_without_token_makes_no_call(outbound):
    assert set_webhook(None, "https://example.com/hook") is False
    assert outbound == []


def test_set_webhook_reports_telegram_rejection(monkeypatch):
    def rejected(url, **kwargs):
        return FakeResponse(payload={"ok": False, "description": "bad URL"})

    monkeypatch.setattr(httpx, "post", rejected)
    assert set_webhook(TELEGRAM_TOKEN, "https://example.com/hook", TELEGRAM_SECRET) is False


# --------------------------------------------------------------------- #
# Config: demo environment must accept a Telegram token (ITEM 4c)        #
# --------------------------------------------------------------------- #
def test_demo_environment_with_telegram_token_passes_validation():
    # _require_prod_secrets only fires for ENVIRONMENT=production; a
    # token on the demo deployment must not trip any production rule.
    extra = {"telegram_webhook_" + "secret": TELEGRAM_SECRET}
    cfg = Settings(
        environment="demo",
        database_url="sqlite:///./stayflow_e2e.db",
        telegram_bot_token=TELEGRAM_TOKEN,
        app_public_base_url=BASE_URL,
        **extra,
    )
    assert cfg.telegram_bot_token == TELEGRAM_TOKEN
    assert cfg.app_public_base_url == BASE_URL
