"""AI agent layer: tools, runner, conversation persistence, safety rails."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update

from app.agent.config import AgentConfig
from app.agent.providers.base import LLMResponse, ToolCallRequest
from app.agent.providers.mock import MockProvider, ScriptedProvider
from app.agent.runner import MAX_TOOL_ROUNDS, run_chat
from app.agent.tools.registry import ToolContext, build_registry
from app.db.session import get_db
from app.models.booking import Booking
from app.models.rate import Rate
from app.services import booking_service
from tests._helpers import (
    client,
    future,
    make_guest,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
    uid,
)


def _seed(price=3000, available=5):
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe", capacity=2, total_rooms=5)
    start = future(60)
    seed_rates_availability(room["id"], start, 2, price=price, available=available)
    client.post(
        "/api/v1/policies",
        json={
            "hotel_id": hotel["id"],
            "policy_type": "check_in",
            "title": "Check-in",
            "description": "Check-in after 2 PM",
        },
    )
    client.post(
        "/api/v1/faqs",
        json={
            "hotel_id": hotel["id"],
            "question": "Do you have parking?",
            "answer": "Yes, free parking on site.",
        },
    )
    return hotel, room, start


def _chat(hotel_id, message, **kw):
    r = client.post("/api/v1/agent/chat", json={"hotel_id": hotel_id, "message": message, **kw})
    ok(r, 200)
    return r.json()


def test_availability_question():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"Is Deluxe available from {start} to {end}?")
    assert "available" in body["reply"].lower()
    assert body["degraded"] is False
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "check_room_availability" in tools


def test_price_question():
    hotel, room, start = _seed(price=2500)
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"What is the price for Deluxe from {start} to {end}?")
    assert "5000" in body["reply"]
    assert "get_room_rate" in [t["tool"] for t in body["tool_trace"]]


def test_policy_question():
    hotel, room, start = _seed()
    body = _chat(hotel["id"], "What is your check-in policy?")
    assert "2 PM" in body["reply"]


def test_faq_question():
    hotel, room, start = _seed()
    body = _chat(hotel["id"], "Do you have parking?")
    assert "free parking" in body["reply"].lower()


def test_unknown_hotel_404():
    r = client.post("/api/v1/agent/chat", json={"hotel_id": 999999, "message": "hello"})
    assert r.status_code == 404


def test_booking_flow_with_confirmation_gate():
    hotel, room, start = _seed(price=4000)
    end = start + timedelta(days=2)
    email = f"{uuid4().hex[:8]}@t.co"
    body = _chat(
        hotel["id"],
        f"Book Deluxe for 2 guests from {start} to {end}, my name is Agent Guest, email {email}",
    )
    # Phase one only: the agent previews the booking and asks for confirmation.
    assert "confirm" in body["reply"].lower()
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "find_or_create_guest" in tools
    assert "preview_booking" in tools
    assert "create_booking" not in tools
    preview = body["tool_trace"][-1]["result"]
    assert preview["draft_id"]
    assert preview["details"]["total_price"] == "8000.00"
    # Nothing is booked yet: the draft is not a booking.
    db = next(get_db())
    try:
        guest_id = body["tool_trace"][0]["result"]["guest_id"]
        assert db.scalars(select(Booking).where(Booking.guest_id == guest_id)).all() == []
    finally:
        db.close()

    body2 = _chat(
        hotel["id"],
        "yes, confirm please",
        conversation_id=body["conversation_id"],
        conversation_token=body["conversation_token"],
    )
    assert "confirmed" in body2["reply"].lower()
    assert "create_booking" in [t["tool"] for t in body2["tool_trace"]]
    booking_id = body2["tool_trace"][-1]["result"]["booking_id"]
    r = client.get(f"/api/v1/bookings/{booking_id}")
    ok(r, 200)
    booking = r.json()
    assert booking["booking_status"] == "CONFIRMED"
    # Server-side price wins: 2 nights x 4000.
    assert float(booking["final_price"]) == 8000.0


def _preview(hotel_id, room_id, guest_id, start, end, db, ctx):
    registry = build_registry()
    return registry.execute(
        "preview_booking",
        {
            "hotel_id": hotel_id,
            "room_id": room_id,
            "check_in": str(start),
            "check_out": str(end),
            "number_of_guests": 2,
            "guest_id": guest_id,
        },
        db,
        ctx,
    )


def test_preview_then_confirm_tool_flow():
    hotel, room, start = _seed(price=4000)
    end = start + timedelta(days=2)
    guest = make_guest(hotel["id"])
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], guest_id=guest["id"])
        preview = _preview(hotel["id"], room["id"], guest["id"], start, end, db, ctx)
        assert preview.ok is True, preview.error
        draft_id = preview.data["draft_id"]
        assert preview.data["details"]["total_price"] == "8000.00"

        confirm = registry.execute(
            "create_booking", {"hotel_id": hotel["id"], "draft_id": draft_id}, db, ctx
        )
        assert confirm.ok is True, confirm.error
        assert confirm.data["booking_status"] == "CONFIRMED"
        assert float(confirm.data["final_price"]) == 8000.0

        # A draft is consumed exactly once.
        again = registry.execute(
            "create_booking", {"hotel_id": hotel["id"], "draft_id": draft_id}, db, ctx
        )
        assert again.ok is False
        assert "confirmed" in again.error.lower()
    finally:
        db.close()


def test_create_booking_without_draft_fails_safely():
    """The LLM cannot bypass the preview: no draft_id, no booking."""
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], guest_id=guest["id"])
        # Missing draft_id entirely: argument validation rejects it.
        res = registry.execute("create_booking", {"hotel_id": hotel["id"]}, db, ctx)
        assert res.ok is False
        # Bogus draft_id: the draft lookup rejects it.
        res = registry.execute(
            "create_booking", {"hotel_id": hotel["id"], "draft_id": 999999}, db, ctx
        )
        assert res.ok is False
        assert "not found" in res.error.lower()
        assert db.scalars(select(Booking).where(Booking.guest_id == guest["id"])).all() == []
    finally:
        db.close()


def test_confirm_expired_draft_fails():
    hotel, room, start = _seed(price=4000)
    end = start + timedelta(days=2)
    guest = make_guest(hotel["id"])
    db = next(get_db())
    try:
        draft = booking_service.create_booking_draft(
            db,
            hotel_id=hotel["id"],
            guest_id=guest["id"],
            room_id=room["id"],
            check_in=start,
            check_out=end,
            number_of_guests=2,
        )
        draft.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], guest_id=guest["id"])
        res = registry.execute(
            "create_booking", {"hotel_id": hotel["id"], "draft_id": draft.id}, db, ctx
        )
        assert res.ok is False
        assert "expired" in res.error.lower()
        assert db.scalars(select(Booking).where(Booking.guest_id == guest["id"])).all() == []
    finally:
        db.close()


def test_confirm_revalidates_price_after_rate_change():
    """A rate change between preview and confirm fails instead of mischarging."""
    hotel, room, start = _seed(price=4000)
    end = start + timedelta(days=2)
    guest = make_guest(hotel["id"])
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], guest_id=guest["id"])
        preview = _preview(hotel["id"], room["id"], guest["id"], start, end, db, ctx)
        assert preview.ok is True
        # Rates change after the preview was priced.
        db.execute(update(Rate).where(Rate.room_id == room["id"]).values(price=5000))
        db.commit()
        res = registry.execute(
            "create_booking",
            {"hotel_id": hotel["id"], "draft_id": preview.data["draft_id"]},
            db,
            ctx,
        )
        assert res.ok is False
        assert "price changed" in res.error.lower()
        assert db.scalars(select(Booking).where(Booking.guest_id == guest["id"])).all() == []
    finally:
        db.close()


def test_confirm_rejects_other_hotels_draft():
    hotel_a, room_a, start = _seed()
    hotel_b = make_hotel()
    guest_b = make_guest(hotel_b["id"])
    end = start + timedelta(days=2)
    db = next(get_db())
    try:
        guest_a = make_guest(hotel_a["id"])
        draft = booking_service.create_booking_draft(
            db,
            hotel_id=hotel_a["id"],
            guest_id=guest_a["id"],
            room_id=room_a["id"],
            check_in=start,
            check_out=end,
            number_of_guests=2,
        )
        db.commit()
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel_b["id"], guest_id=guest_b["id"])
        res = registry.execute(
            "create_booking", {"hotel_id": hotel_b["id"], "draft_id": draft.id}, db, ctx
        )
        assert res.ok is False
    finally:
        db.close()


def test_booking_requires_guest_identity():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"Book Deluxe from {start} to {end}")
    assert "email" in body["reply"].lower() or "name" in body["reply"].lower()
    assert body["tool_trace"] == []


def test_sold_out_reported_gracefully():
    hotel, room, start = _seed(available=0)
    end = start + timedelta(days=2)
    email = f"{uuid4().hex[:8]}@t.co"
    body = _chat(
        hotel["id"],
        f"Book Deluxe for 2 guests from {start} to {end}, email {email}",
    )
    assert "issue" in body["reply"].lower() or "available" in body["reply"].lower()


def test_cancel_booking_via_agent():
    hotel, room, start = _seed()
    guest = make_guest(hotel["id"])
    end = start + timedelta(days=2)
    r = client.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "guest_id": guest["id"],
            "check_in": str(start),
            "check_out": str(end),
            "number_of_guests": 2,
            "booking_status": "CONFIRMED",
        },
    )
    ok(r, 201)
    bid = r.json()["id"]
    body = _chat(hotel["id"], f"Cancel booking {bid}")
    assert "cancel" in body["reply"].lower()
    assert "cancel_booking" in [t["tool"] for t in body["tool_trace"]]
    r = client.get(f"/api/v1/bookings/{bid}")
    ok(r, 200)
    assert r.json()["booking_status"] == "CANCELLED"


def test_conversation_persisted_across_turns():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"Is Deluxe available from {start} to {end}?")
    cid = body["conversation_id"]
    _chat(hotel["id"], "What about the price?", conversation_id=cid)
    msgs = client.get(f"/api/v1/conversations/{cid}/messages")
    ok(msgs, 200)
    texts = [m["message"] for m in msgs.json() if m["sender_type"] in ("guest", "agent")]
    assert any("Deluxe available" in t for t in texts)
    assert any("price" in t.lower() for t in texts)


def test_unknown_tool_and_bad_args_are_tool_errors():
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=1)
        res = registry.execute("does_not_exist", {}, db, ctx)
        assert res.ok is False
        assert "unknown tool" in res.error.lower()
        res = registry.execute("create_booking", {"hotel_id": 1}, db, ctx)
        assert res.ok is False
    finally:
        db.close()


def test_tool_rejects_cross_hotel_hotel_id():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    room_b = make_room(hotel_b["id"], room_type=uid("SuiteB"))
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel_a["id"])
        res = registry.execute(
            "check_room_availability",
            {
                "hotel_id": hotel_b["id"],
                "room_id": room_b["id"],
                "check_in": str(future(70)),
                "check_out": str(future(72)),
            },
            db,
            ctx,
        )
        assert res.ok is False
        assert "hotel" in res.error.lower()
    finally:
        db.close()


def test_food_order_uses_menu_price_not_llm_price():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    menu = client.post(
        "/api/v1/menu-items",
        json={"hotel_id": hotel["id"], "name": uid("Pizza"), "price": 450},
    )
    ok(menu, 201)
    db = next(get_db())
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], guest_id=guest["id"])
        res = registry.execute(
            "create_food_order",
            {
                "hotel_id": hotel["id"],
                "guest_id": guest["id"],
                "order_type": "ROOM_SERVICE",
                "items": [{"menu_item_id": menu.json()["id"], "quantity": 2}],
            },
            db,
            ctx,
        )
        assert res.ok is True
        assert float(res.data["total_amount"]) == 900.0
    finally:
        db.close()


def test_scripted_max_iterations_degrades_gracefully():
    hotel, room, start = _seed()
    provider = ScriptedProvider(
        [
            ToolCallRequest(
                name="list_rooms",
                arguments={"hotel_id": hotel["id"]},
            )
        ]
        * 10
    )
    config = AgentConfig(provider_name="scripted", max_iterations=3)
    db = next(get_db())
    try:
        result = run_chat(
            db,
            hotel_id=hotel["id"],
            message="hello",
            config=config,
            provider=provider,
        )
        assert result.degraded is True
        assert "simpler" in result.reply.lower() or "steps" in result.reply.lower()
    finally:
        db.close()


def test_max_tool_rounds_hard_cap():
    """MAX_TOOL_ROUNDS is a hard ceiling even when config asks for more."""
    hotel, room, start = _seed()
    provider = ScriptedProvider(
        [
            ToolCallRequest(
                name="list_rooms",
                arguments={"hotel_id": hotel["id"]},
            )
        ]
        * 30
    )
    config = AgentConfig(provider_name="scripted", max_iterations=100)
    db = next(get_db())
    try:
        result = run_chat(
            db,
            hotel_id=hotel["id"],
            message="hello",
            config=config,
            provider=provider,
        )
        assert result.iterations <= MAX_TOOL_ROUNDS
        assert result.degraded is True
    finally:
        db.close()


def test_history_limit_truncates_context():
    """run_chat loads at most history_limit past messages before each turn."""
    hotel, room, start = _seed()
    seen: dict[str, int] = {}

    class CapProvider:
        name = "cap"

        def chat(self, messages, tools, context):
            seen["count"] = len(messages)
            return LLMResponse(content="done")

    db = next(get_db())
    try:
        run_chat(
            db,
            hotel_id=hotel["id"],
            message="hello",
            config=AgentConfig(provider_name="mock", history_limit=2),
            provider=CapProvider(),
        )
        # System prompt + at most history_limit history messages (the
        # just-persisted guest message counts toward the limit).
        assert seen["count"] <= 1 + 2
    finally:
        db.close()


def test_provider_error_degrades_gracefully():
    from app.agent.providers.base import ProviderError

    hotel = make_hotel()

    def boom():
        raise ProviderError("connection refused")

    provider = ScriptedProvider([boom])
    db = next(get_db())
    try:
        result = run_chat(
            db,
            hotel_id=hotel["id"],
            message="hello",
            config=AgentConfig(provider_name="mock"),
            provider=provider,
        )
        assert result.degraded is True
        assert result.reply
    finally:
        db.close()


def test_mock_provider_lists_registered_tools():
    provider = MockProvider()
    assert "check_room_availability" in provider.available_tools
    assert "preview_booking" in provider.available_tools
    assert "create_booking" in provider.available_tools
