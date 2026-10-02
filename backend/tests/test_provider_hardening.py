"""Provider/registry hardening regression tests (Prompt-1 section 3).

Covers the hardening added around the Inception/Mercury provider and the
tool registry:

- hallucinated tool arguments (invented price/total/discount fields) are
  rejected before reaching any handler;
- unknown tools and malformed arguments fail safely as tool errors;
- provider 429s are retried and then surfaced when the budget is exhausted;
- a provider failure degrades the chat to a graceful guest-facing reply.

All HTTP is mocked (no API key exists in this sandbox); live calls against
api.inceptionlabs.ai remain unverified.
"""

import time

import httpx
import pytest

from app.agent.config import AgentConfig, build_provider
from app.agent.providers.base import ProviderError
from app.agent.providers.inception import InceptionProvider
from app.agent.providers.mock import ScriptedProvider
from app.agent.runner import run_chat
from app.agent.tools.registry import ToolContext, build_registry
from app.db.session import get_db
from tests._helpers import make_hotel


def _db():
    return next(get_db())


def _install(monkeypatch, responses):
    """Replace httpx.post with a fake serving the given responses."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# ----------------------------------------------------------------------
# Registry: hallucinated tool arguments are rejected
# ----------------------------------------------------------------------


def test_hallucinated_price_fields_rejected_on_preview_booking():
    """An LLM must not smuggle prices into tool arguments."""
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute(
            "preview_booking",
            {
                "hotel_id": 1,
                "room_id": 2,
                "check_in": "2026-11-01",
                "check_out": "2026-11-03",
                "number_of_guests": 2,
                "total_price": 5000,  # hallucinated: prices come from tools
            },
            db,
            ctx,
        )
        assert res.ok is False
        assert "invalid argument" in res.error.lower()
        assert "total_price" in res.error
    finally:
        db.close()


def test_hallucinated_discount_rejected_on_create_booking():
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute(
            "create_booking",
            {"hotel_id": 1, "draft_id": 7, "discount": 10},  # hallucinated
            db,
            ctx,
        )
        assert res.ok is False
        assert "invalid argument" in res.error.lower()
        assert "discount" in res.error
    finally:
        db.close()


def test_valid_arguments_still_pass():
    """The strict unknown-field check must not break legitimate calls."""
    from tests._helpers import make_hotel

    hotel = make_hotel()
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"])
        res = registry.execute(
            "list_rooms",
            {"hotel_id": hotel["id"]},
            db,
            ctx,
        )
        assert res.ok is True
        assert "invalid argument" not in (res.error or "").lower()
    finally:
        db.close()


# ----------------------------------------------------------------------
# Registry: unknown tool and malformed arguments fail safely
# ----------------------------------------------------------------------


def test_unknown_tool_fails_safely():
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute("invent_room_price", {"hotel_id": 1}, db, ctx)
        assert res.ok is False
        assert "unknown tool" in res.error.lower()
        # The error names real tools so the LLM can self-correct.
        assert "preview_booking" in res.error
    finally:
        db.close()


def test_malformed_non_dict_arguments_fail_safely():
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute("list_rooms", ["hotel_id", 1], db, ctx)
        assert res.ok is False
        assert "object" in res.error.lower()
    finally:
        db.close()


def test_wrong_typed_arguments_fail_safely():
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute(
            "preview_booking",
            {
                "hotel_id": 1,
                "room_id": "not-a-room",
                "check_in": "yesterday",
                "check_out": "tomorrow",
                "number_of_guests": -2,
            },
            db,
            ctx,
        )
        assert res.ok is False
        assert "invalid arguments" in res.error.lower()
    finally:
        db.close()


# ----------------------------------------------------------------------
# Provider: 429 retried, then surfaced
# ----------------------------------------------------------------------


def _ctx():
    from app.agent.providers.base import ProviderContext

    return ProviderContext(hotel_id=1, hotel_name="Test Hotel", currency="INR", today="2026-09-29")


def test_429_exhausted_then_surfaced(monkeypatch):
    """Persistent 429s are retried (max_retries+1 attempts) then surfaced."""
    monkeypatch.setattr(time, "sleep", lambda s: None)  # keep the suite fast
    calls = _install(
        monkeypatch,
        [httpx.Response(429, json={"error": "rate limited"})] * 4,
    )
    with pytest.raises(ProviderError, match="after 3 attempts"):
        InceptionProvider(api_key="k", max_retries=2).chat([], [], _ctx())
    assert len(calls) == 3  # initial + 2 retries, then give up


# ----------------------------------------------------------------------
# Provider: retry backoff
# ----------------------------------------------------------------------
def test_429_retries_use_backoff(monkeypatch):
    """Retries wait with exponential backoff instead of hammering the API."""
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    _install(
        monkeypatch,
        [
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ),
        ],
    )
    resp = InceptionProvider(api_key="k", max_retries=2).chat([], [], _ctx())
    assert resp.content == "ok"
    assert sleeps == [1.0, 2.0]


# ----------------------------------------------------------------------
# Runner: provider failure -> graceful degraded response
# ----------------------------------------------------------------------


def test_provider_failure_degrades_to_guest_facing_reply():
    hotel = make_hotel()

    def boom():
        raise ProviderError("connection refused")

    provider = ScriptedProvider([boom])
    db = _db()
    try:
        result = run_chat(
            db,
            hotel_id=hotel["id"],
            message="hello",
            config=AgentConfig(provider_name="mock"),
            provider=provider,
        )
        assert result.degraded is True
        assert result.reply  # a guest-facing message, not a crash/traceback
        assert result.tool_trace == []
    finally:
        db.close()


def test_401_maps_to_auth_error_not_retry(monkeypatch):
    """Auth failures surface immediately with a clear message (no retry)."""
    calls = _install(monkeypatch, [httpx.Response(401, json={"error": "bad key"})])
    with pytest.raises(ProviderError, match="authentication failed"):
        InceptionProvider(api_key="bad").chat([], [], _ctx())
    assert len(calls) == 1


# ----------------------------------------------------------------------
# Config: inception default + fail-fast on missing key
# ----------------------------------------------------------------------


def test_default_provider_is_inception_not_silent_mock(monkeypatch):
    """The production default must not be the mock provider."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    config = AgentConfig()
    assert config.provider_name == "inception"


def test_inception_without_key_fails_fast():
    """LLM_PROVIDER=inception without INCEPTION_API_KEY is a loud error."""
    config = AgentConfig(provider_name="inception", inception_api_key=None)
    with pytest.raises(ValueError, match="INCEPTION_API_KEY"):
        build_provider(config)
