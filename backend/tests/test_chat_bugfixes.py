"""Bugfixes (2026-10-22, from the live demo):

1. The staff transcript endpoint must not leak the agent's internal
   TOOL_CALL / TOOL_RESULT rows (raw tool JSON) — while the agent's own
   history keeps seeing them.
2. The mock provider must understand non-ISO dates and carry booking
   slots across turns, instead of dropping a bare date reply into the
   FAQ no-answer fallback.
"""

from datetime import date, timedelta

from app.agent import conversation as conversation_store
from app.agent.providers.mock import _extract_dates
from app.db.session import get_db
from tests._helpers import (
    client,
    future,
    make_guest,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
)


def _chat(hotel_id, message, **kw):
    r = client.post("/api/v1/agent/chat", json={"hotel_id": hotel_id, "message": message, **kw})
    ok(r, 200)
    return r.json()


# --------------------------------------------------------------------- #
# Bug 2a — date formats                                                  #
# --------------------------------------------------------------------- #
def test_extract_dates_formats():
    target = date(2026, 11, 23)
    assert _extract_dates("23/11/2026") == [target]
    assert _extract_dates("23-11-2026") == [target]
    assert _extract_dates("23.11.2026") == [target]
    assert _extract_dates("23 Nov 2026") == [target]
    assert _extract_dates("23rd November 2026") == [target]
    assert _extract_dates("Nov 23, 2026") == [target]
    assert _extract_dates("2026-11-23") == [target]
    # Ranges keep mention order (check-in first).
    assert _extract_dates("from 23/11/2026 to 25/11/2026") == [target, date(2026, 11, 25)]
    # Invalid calendar dates are ignored; day-first means 11/23/2026 has
    # month=23 and is not silently reinterpreted US-style.
    assert _extract_dates("31/02/2026") == []
    assert _extract_dates("11/23/2026") == []
    assert _extract_dates("no dates here") == []


# --------------------------------------------------------------------- #
# Bug 1 — staff transcript hides tool traces                             #
# --------------------------------------------------------------------- #
def test_staff_messages_exclude_tool_traces_but_agent_history_keeps_them():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    r = client.post(
        "/api/v1/conversations",
        json={"hotel_id": hotel["id"], "guest_id": guest["id"]},
    )
    ok(r, 201)
    cid = r.json()["id"]

    # Persist rows exactly like the agent runner does: guest/agent TEXT
    # plus internal TOOL_CALL / TOOL_RESULT traces.
    db = next(get_db())
    try:
        conversation_store.add_message(db, cid, sender_type="guest", message="hii")
        conversation_store.add_message(
            db,
            cid,
            sender_type="agent",
            message='{"tool": "search_faq", "arguments": {"hotel_id": 1, "query": "hii"}}',
            message_type="TOOL_CALL",
        )
        conversation_store.add_message(
            db,
            cid,
            sender_type="agent",
            message='{"tool": "search_faq", "content": "{\\"results\\": []}"}',
            message_type="TOOL_RESULT",
        )
        conversation_store.add_message(
            db, cid, sender_type="agent", message="Hello! How can I help you today?"
        )
        db.commit()

        # The agent's own history (what the runner rebuilds context from)
        # still contains the tool rows — filtering must not touch this.
        history = conversation_store.get_history(db, cid)
        history_types = [row.message_type for row in history]
        assert "TOOL_CALL" in history_types
        assert "TOOL_RESULT" in history_types
    finally:
        db.close()

    # A staff reply posted through the API is TEXT and must show up.
    r = client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"sender_type": "staff", "message": "Staff note: checking on this."},
    )
    ok(r, 201)

    msgs = client.get(f"/api/v1/conversations/{cid}/messages")
    ok(msgs, 200)
    rows = msgs.json()
    assert rows, "expected the TEXT rows to be returned"
    assert all(m["message_type"] == "TEXT" for m in rows)
    assert not any(m["message_type"] in ("TOOL_CALL", "TOOL_RESULT") for m in rows)
    assert not any('"tool"' in m["message"] for m in rows)
    texts = [m["message"] for m in rows]
    assert "hii" in texts
    assert "Hello! How can I help you today?" in texts
    assert "Staff note: checking on this." in texts


# --------------------------------------------------------------------- #
# Bug 2b — mock booking flow with slot carryover                         #
# --------------------------------------------------------------------- #
def _seed_booking_hotel():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe King Room", capacity=2, total_rooms=5)
    check_in = future(30)
    check_out = check_in + timedelta(days=2)
    seed_rates_availability(room["id"], check_in, 2, price=4500, available=5)
    return hotel, room, check_in, check_out


def test_mock_booking_carryover_reaches_preview():
    hotel, room, check_in, check_out = _seed_booking_hotel()

    body = _chat(hotel["id"], "i want a room")
    assert "Deluxe King Room" in body["reply"]
    cid = body["conversation_id"]

    # Room + a day-first date range in one follow-up: slots complete, so
    # the agent asks for guest identity — never the FAQ fallback.
    body = _chat(
        hotel["id"],
        f"Deluxe King Room, {check_in:%d/%m/%Y} to {check_out:%d/%m/%Y}",
        conversation_id=cid,
    )
    assert "I don't have an answer" not in body["reply"]
    assert "name" in body["reply"].lower() or "email" in body["reply"].lower()

    # Identity completes the flow: preview with the deterministic gate.
    body = _chat(
        hotel["id"],
        "my name is Carry Guest, email carry@t.co",
        conversation_id=cid,
    )
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "find_or_create_guest" in tools
    assert "preview_booking" in tools
    assert "create_booking" not in tools
    assert "booking summary" in body["reply"].lower()
    assert "confirm" in body["reply"].lower()
    preview = body["tool_trace"][-1]["result"]
    assert preview["details"]["total_price"] == "9000.00"

    # The confirmation gate still applies after the fix.
    body = _chat(hotel["id"], "yes, confirm please", conversation_id=cid)
    assert "create_booking" in [t["tool"] for t in body["tool_trace"]]
    assert "confirmed" in body["reply"].lower()


def test_mock_booking_pending_guard_asks_only_missing():
    hotel, room, check_in, check_out = _seed_booking_hotel()

    body = _chat(hotel["id"], "i want a room")
    cid = body["conversation_id"]

    # The exact live-demo failure: a bare day-first date as the reply.
    body = _chat(hotel["id"], f"{check_in:%d/%m/%Y}", conversation_id=cid)
    reply = body["reply"]
    assert "I don't have an answer" not in reply
    assert "front desk" not in reply.lower()
    # It asks ONLY for what is missing: room type + check-out date.
    assert "room type" in reply.lower()
    assert "check-out" in reply.lower()
    assert str(check_in) in reply  # the noted check-in, ISO format

    # Slots can be completed piecemeal across turns.
    body = _chat(
        hotel["id"],
        f"Deluxe King Room, check-out {check_out:%d/%m/%Y}",
        conversation_id=cid,
    )
    assert "I don't have an answer" not in body["reply"]
    assert "name" in body["reply"].lower() or "email" in body["reply"].lower()
