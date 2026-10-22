"""Widget (§11) + integration API (§12) tests.

Covers: hotel public_id / check-in-out fields, public widget API hotel
isolation (public_id only — internal ids never accepted or exposed),
HMAC signature verification (valid / invalid / expired / replay),
idempotency-key duplicate handling, secret rotation, staff settings
auth, outbound webhook signing + bounded retries, and widget asset
serving. The agent runs on the deterministic mock provider (conftest).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limit_state
from app.db.session import SessionLocal
from app.main import app
from app.models.conversation import Conversation
from app.models.hotel import Hotel
from app.models.message import Message
from app.services import webhook_delivery
from app.services.integration_security import verify_signature
from tests._helpers import client as authed_client
from tests._helpers import make_hotel, ok

settings = get_settings()
client = TestClient(app)

SECRET = "test-integration-secret-0123456789abcdef"
WEBHOOK_SECRET = "test-webhook-secret-0123456789abcdef"
CHAT_URL = "/api/v1/integrations/chat/message"


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


def _make_hotel(*, secret: str | None = None, webhook: bool = False) -> Hotel:
    with SessionLocal() as db:
        hotel = Hotel(name=f"Widget Hotel {uuid4().hex[:8]}", city="Testville")
        if secret is not None:
            hotel.integration_secret = secret
            hotel.integration_secret_fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:12]
        if webhook:
            hotel.integration_webhook_url = "https://partner.example/stayflow/webhook"
            hotel.integration_webhook_secret = WEBHOOK_SECRET
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        db.expunge(hotel)
        return hotel


def _sign(secret: str, timestamp: int | str, raw_body: bytes) -> str:
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def _integration_call(
    hotel: Hotel,
    payload: dict,
    *,
    secret: str = SECRET,
    timestamp: int | None = None,
    signature: str | None = None,
    headers: dict | None = None,
):
    raw = json.dumps(payload).encode()
    ts = int(time.time()) if timestamp is None else timestamp
    hdrs = {
        "Content-Type": "application/json",
        "X-StayFlow-Timestamp": str(ts),
        "X-StayFlow-Signature": signature or _sign(secret, ts, raw),
    }
    if headers:
        hdrs.update(headers)
    return client.post(CHAT_URL, content=raw, headers=hdrs)


def _payload(hotel: Hotel, message: str = "Hello, do you have rooms?") -> dict:
    return {"hotel_public_id": hotel.public_id, "message": message}


def _message_count(conversation_id: int) -> int:
    with SessionLocal() as db:
        return (
            db.scalars(select(Message).where(Message.conversation_id == conversation_id))
            .all()
            .__len__()
        )


# --------------------------------------------------------------------- #
# Hotel model fields (§5/§11)                                            #
# --------------------------------------------------------------------- #
def test_hotel_public_id_generated_unique_and_check_times_default():
    a = _make_hotel()
    b = _make_hotel()
    assert a.public_id and len(a.public_id) == 32
    assert b.public_id and a.public_id != b.public_id
    assert a.check_in_time is None and a.check_out_time is None


def test_hotel_check_in_out_times_via_staff_api():
    hotel = make_hotel()
    assert hotel["public_id"]
    r = authed_client.patch(
        f"/api/v1/hotels/{hotel['id']}",
        json={"check_in_time": "14:00", "check_out_time": "11:00"},
    )
    ok(r, 200)
    assert r.json()["check_in_time"] == "14:00"
    assert r.json()["check_out_time"] == "11:00"
    assert r.json()["public_id"] == hotel["public_id"]

    bad = authed_client.patch(f"/api/v1/hotels/{hotel['id']}", json={"check_in_time": "25:00"})
    assert bad.status_code == 422


# --------------------------------------------------------------------- #
# Public widget API (§11)                                                #
# --------------------------------------------------------------------- #
def test_public_hotel_info_by_public_id_only():
    hotel = _make_hotel()
    r = client.get(f"/api/v1/public/hotels/{hotel.public_id}")
    ok(r, 200)
    body = r.json()
    assert body["hotel_id"] == hotel.public_id
    assert body["name"] == hotel.name
    # The internal integer id is never exposed under any key.
    assert "id" not in body
    assert hotel.id not in body.values()

    cfg = client.get(f"/api/v1/public/hotels/{hotel.public_id}/widget-config")
    ok(cfg, 200)
    assert cfg.json()["hotel_id"] == hotel.public_id
    assert hotel.name in cfg.json()["welcome_message"]


def test_public_hotel_info_rejects_internal_id_and_unknown():
    hotel = _make_hotel()
    # The internal integer id must not resolve a hotel.
    assert client.get(f"/api/v1/public/hotels/{hotel.id}").status_code == 404
    assert client.get("/api/v1/public/hotels/does-not-exist").status_code == 404
    assert (
        client.post(
            "/api/v1/public/chat",
            json={"hotel_public_id": str(hotel.id), "message": "hi"},
        ).status_code
        == 404
    )


def test_public_chat_isolated_per_hotel():
    a = _make_hotel()
    b = _make_hotel()
    r = client.post(
        "/api/v1/public/chat",
        json={"hotel_public_id": a.public_id, "message": "Hello!"},
    )
    ok(r, 200)
    body = r.json()
    assert body["hotel_id"] == a.public_id
    assert body["reply"]
    session_a = body["session_id"]

    with SessionLocal() as db:
        conv = db.get(Conversation, body["conversation_id"])
        assert conv is not None and conv.hotel_id == a.id and conv.channel == "widget"

    # Hotel B cannot continue hotel A's session.
    hijack = client.post(
        "/api/v1/public/chat",
        json={
            "hotel_public_id": b.public_id,
            "message": "continue",
            "session_id": session_a,
        },
    )
    assert hijack.status_code == 422

    # Hotel B's own chat works and gets its own conversation.
    rb = client.post(
        "/api/v1/public/chat",
        json={"hotel_public_id": b.public_id, "message": "Hello!"},
    )
    ok(rb, 200)
    assert rb.json()["conversation_id"] != body["conversation_id"]


def test_public_chat_rate_limited(monkeypatch):
    hotel = _make_hotel()
    monkeypatch.setattr(settings, "rate_limit_public_chat_per_minute", 2)
    payload = {"hotel_public_id": hotel.public_id, "message": "Hello!"}
    assert client.post("/api/v1/public/chat", json=payload).status_code == 200
    assert client.post("/api/v1/public/chat", json=payload).status_code == 200
    third = client.post("/api/v1/public/chat", json=payload)
    assert third.status_code == 429
    assert third.headers.get("retry-after")


def test_widget_assets_served():
    loader = client.get("/widget.js")
    ok(loader, 200)
    assert "data-hotel-id" in loader.text

    chat_page = client.get("/widget/chat.html")
    ok(chat_page, 200)
    assert "/api/v1/public/chat" in chat_page.text

    demo = client.get("/widget/")
    ok(demo, 200)
    assert "StayFlow widget" in demo.text

    # The pre-existing guest chat is untouched.
    legacy = client.get("/chat")
    ok(legacy, 200)
    assert "StayFlow" in legacy.text


# --------------------------------------------------------------------- #
# Integration API (§12) — signature auth                                 #
# --------------------------------------------------------------------- #
def test_integration_chat_valid_signature():
    hotel = _make_hotel(secret=SECRET)
    r = _integration_call(hotel, _payload(hotel))
    ok(r, 200)
    body = r.json()
    assert body["hotel_id"] == hotel.public_id
    assert body["status"] == "ok"
    assert body["reply"]
    assert hotel.id not in (body["hotel_id"],)
    with SessionLocal() as db:
        conv = db.get(Conversation, body["conversation_id"])
        assert conv is not None and conv.hotel_id == hotel.id
        assert conv.channel == "integration"


def test_integration_chat_invalid_signature():
    hotel = _make_hotel(secret=SECRET)
    r = _integration_call(hotel, _payload(hotel), signature="sha256=" + "0" * 64)
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "invalid_signature"


def test_integration_chat_missing_headers():
    hotel = _make_hotel(secret=SECRET)
    r = client.post(CHAT_URL, json=_payload(hotel))
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "missing_signature_headers"


def test_integration_chat_expired_timestamp():
    hotel = _make_hotel(secret=SECRET)
    old_ts = int(time.time()) - 10_000
    r = _integration_call(hotel, _payload(hotel), timestamp=old_ts)
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "timestamp_expired"


def test_integration_chat_replay_rejected():
    hotel = _make_hotel(secret=SECRET)
    payload = _payload(hotel)
    raw = json.dumps(payload).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-StayFlow-Timestamp": str(ts),
        "X-StayFlow-Signature": _sign(SECRET, ts, raw),
    }
    first = client.post(CHAT_URL, content=raw, headers=headers)
    ok(first, 200)
    second = client.post(CHAT_URL, content=raw, headers=headers)
    assert second.status_code == 401
    assert second.json()["detail"]["error"]["code"] == "replay_detected"


def test_integration_chat_unknown_hotel_and_unconfigured():
    hotel = _make_hotel()  # no secret configured
    r = _integration_call(hotel, _payload(hotel))
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "integration_not_configured"

    ghost = _payload(hotel)
    ghost["hotel_public_id"] = "f" * 32
    r2 = _integration_call(hotel, ghost)
    assert r2.status_code == 404
    assert r2.json()["detail"]["error"]["code"] == "hotel_not_found"


def test_integration_fallback_secret(monkeypatch):
    hotel = _make_hotel()  # no per-hotel secret
    monkeypatch.setattr(settings, "integration_fallback_secret", "fallback-secret")
    r = _integration_call(hotel, _payload(hotel), secret="fallback-secret")
    ok(r, 200)


# --------------------------------------------------------------------- #
# Integration API (§12) — idempotency                                    #
# --------------------------------------------------------------------- #
def test_integration_idempotency_duplicate_returns_original():
    hotel = _make_hotel(secret=SECRET)
    payload = _payload(hotel, "I would like a room please")
    first = _integration_call(hotel, payload, headers={"Idempotency-Key": "evt-123"})
    ok(first, 200)
    body = first.json()
    count_after_first = _message_count(body["conversation_id"])
    assert count_after_first >= 2

    # A legitimate retry re-signs (fresh timestamp) but reuses the key.
    second = _integration_call(hotel, payload, headers={"Idempotency-Key": "evt-123"})
    ok(second, 200)
    assert second.json() == body
    assert _message_count(body["conversation_id"]) == count_after_first


def test_integration_idempotency_key_scoped_per_hotel():
    a = _make_hotel(secret=SECRET)
    b = _make_hotel(secret=SECRET)
    ra = _integration_call(a, _payload(a), headers={"Idempotency-Key": "shared-key"})
    rb = _integration_call(b, _payload(b), headers={"Idempotency-Key": "shared-key"})
    ok(ra, 200)
    ok(rb, 200)
    assert ra.json()["conversation_id"] != rb.json()["conversation_id"]
    assert ra.json()["hotel_id"] == a.public_id
    assert rb.json()["hotel_id"] == b.public_id


# --------------------------------------------------------------------- #
# Integration settings (staff) + rotation                                #
# --------------------------------------------------------------------- #
def test_integration_settings_require_staff_auth():
    assert client.get("/api/v1/integrations/settings").status_code == 401


def test_integration_secret_rotation_flow():
    hotel = make_hotel()
    settings_r = authed_client.get("/api/v1/integrations/settings")
    ok(settings_r, 200)
    assert settings_r.json()["public_id"] == hotel["public_id"]
    assert settings_r.json()["has_integration_secret"] is False

    rotated = authed_client.post("/api/v1/integrations/secret/rotate")
    ok(rotated, 200)
    secret1 = rotated.json()["integration_secret"]
    assert len(secret1) > 20
    fingerprint = hashlib.sha256(secret1.encode()).hexdigest()[:12]
    assert rotated.json()["integration_secret_fingerprint"] == fingerprint

    after = authed_client.get("/api/v1/integrations/settings")
    assert after.json()["has_integration_secret"] is True
    # The secret itself is never returned again.
    assert secret1 not in after.text

    with SessionLocal() as db:
        row = db.get(Hotel, hotel["id"])
        public_id = row.public_id
    fake = Hotel(id=hotel["id"], name="x", city="y")
    fake.public_id = public_id

    first = _integration_call(fake, _payload(fake), secret=secret1)
    ok(first, 200)

    rotated2 = authed_client.post("/api/v1/integrations/secret/rotate")
    secret2 = rotated2.json()["integration_secret"]
    assert secret2 != secret1
    stale = _integration_call(fake, _payload(fake), secret=secret1)
    assert stale.status_code == 401
    fresh = _integration_call(fake, _payload(fake), secret=secret2)
    ok(fresh, 200)


# --------------------------------------------------------------------- #
# Outbound webhook (§12) — signing + bounded retries                     #
# --------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_webhook_signer_matches_documented_algorithm():
    payload = {"conversation_id": 7, "reply": "Hello", "hotel_id": "abc", "status": "ok"}
    raw, headers = webhook_delivery.build_delivery(
        "https://partner.example/hook", payload, WEBHOOK_SECRET, timestamp="1700000000"
    )
    expected = hmac.new(WEBHOOK_SECRET.encode(), b"1700000000." + raw, hashlib.sha256).hexdigest()
    assert headers["X-StayFlow-Signature"] == f"sha256={expected}"
    assert headers["X-StayFlow-Timestamp"] == "1700000000"
    assert verify_signature(WEBHOOK_SECRET, "1700000000", raw, headers["X-StayFlow-Signature"])
    assert not verify_signature(
        WEBHOOK_SECRET, "1700000000", raw + b"x", headers["X-StayFlow-Signature"]
    )


def test_webhook_delivery_retries_then_succeeds(monkeypatch):
    calls: list = []
    outcomes = iter([500, 502, 200])

    def fake_post(url, **kwargs):
        calls.append(url)
        return _FakeResponse(next(outcomes))

    monkeypatch.setattr(httpx, "post", fake_post)
    delivered = webhook_delivery.deliver_webhook(
        "https://partner.example/hook",
        {"a": 1},
        WEBHOOK_SECRET,
        timeout_seconds=1,
        max_retries=3,
        sleep=lambda _s: None,
    )
    assert delivered is True
    assert len(calls) == 3


def test_webhook_delivery_bounded_retries_and_permanent_4xx(monkeypatch):
    calls: list = []

    def always_500(url, **kwargs):
        calls.append(url)
        return _FakeResponse(500)

    monkeypatch.setattr(httpx, "post", always_500)
    delivered = webhook_delivery.deliver_webhook(
        "https://partner.example/hook",
        {"a": 1},
        WEBHOOK_SECRET,
        timeout_seconds=1,
        max_retries=3,
        sleep=lambda _s: None,
    )
    assert delivered is False
    assert len(calls) == 3

    calls.clear()

    def always_400(url, **kwargs):
        calls.append(url)
        return _FakeResponse(400)

    monkeypatch.setattr(httpx, "post", always_400)
    delivered = webhook_delivery.deliver_webhook(
        "https://partner.example/hook",
        {"a": 1},
        WEBHOOK_SECRET,
        timeout_seconds=1,
        max_retries=3,
        sleep=lambda _s: None,
    )
    assert delivered is False
    assert len(calls) == 1  # 4xx is permanent — no retries


def test_integration_chat_delivers_signed_webhook(monkeypatch):
    hotel = _make_hotel(secret=SECRET, webhook=True)
    calls: list = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    r = _integration_call(hotel, _payload(hotel))
    ok(r, 200)

    deliveries = [c for c in calls if c["url"] == "https://partner.example/stayflow/webhook"]
    assert len(deliveries) == 1
    delivery = deliveries[0]
    body = delivery["content"]
    signature = delivery["headers"]["X-StayFlow-Signature"]
    timestamp = delivery["headers"]["X-StayFlow-Timestamp"]
    assert verify_signature(WEBHOOK_SECRET, timestamp, body, signature)
    delivered_payload = json.loads(body)
    assert delivered_payload["conversation_id"] == r.json()["conversation_id"]
    assert delivered_payload["hotel_id"] == hotel.public_id
