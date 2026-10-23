"""Relative-date resolution + guest booking modification.

Feature 1: guests say "next weekend" / "kal" / "agle Shukravar" and the
concierge must resolve that deterministically against the hotel-local
today, restate the resolved dates in words, and still pass through the
normal confirmation gate.

Feature 2: a guest can modify their own upcoming booking (dates, room
type, guest count) through a two-phase preview -> confirm flow. Only
future CONFIRMED/PENDING bookings are eligible; eligibility,
availability and pricing are enforced by the booking service, and the
apply step requires the signed token issued by the preview.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.agent.providers.base import LLMResponse
from app.agent.providers.mock import MockProvider
from app.agent.relative_dates import resolve_relative_stay
from app.agent.runner import run_chat
from app.db.session import get_db
from app.models.booking import Booking
from app.models.payment import Payment
from app.services import booking_service
from app.services.booking_service import BookingError
from tests._helpers import (
    future,
    make_guest,
    make_hotel,
    make_room,
    seed_rates_availability,
    uid,
)

HOTEL_TZ = ZoneInfo("Asia/Kolkata")


def _hotel_today() -> date:
    return datetime.now(HOTEL_TZ).date()


def _next_weekend(today: date) -> tuple[date, date]:
    """Documented semantics: imminent Saturday + 7 days, 1 night."""
    imminent_saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    check_in = imminent_saturday + timedelta(days=7)
    return check_in, check_in + timedelta(days=1)


def _seed(price=3000, nights=50, available=5, capacity=4):
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe", capacity=capacity, total_rooms=5)
    start = _hotel_today() - timedelta(days=3)
    seed_rates_availability(room["id"], start, nights, price=price, available=available)
    return hotel, room


def _chat(db, hotel_id, message, **kw):
    kw.setdefault("provider", MockProvider())
    return run_chat(db, hotel_id=hotel_id, message=message, **kw)


def _create_booking(db, hotel_id, guest_id, room_id, check_in, check_out, guests=2):
    booking = booking_service.create_booking_record(
        db,
        hotel_id=hotel_id,
        guest_id=guest_id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        number_of_guests=guests,
        booking_status="CONFIRMED",
        actor_type="test",
    )
    db.commit()
    return booking


# --------------------------------------------------------------------- #
# Feature 1: the resolver (frozen clocks)                                #
# --------------------------------------------------------------------- #
FRI = date(2026, 10, 23)  # a Friday
SAT = date(2026, 10, 24)
SUN = date(2026, 10, 25)


def test_resolver_next_weekend_from_friday():
    stay = resolve_relative_stay("I want to book a room for next weekend", FRI)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 31), date(2026, 11, 1))
    assert stay.words() == "Saturday 31 October 2026 to Sunday 1 November 2026"


def test_resolver_this_weekend_from_friday():
    stay = resolve_relative_stay("this weekend", FRI)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))


def test_resolver_weekend_edges_on_saturday_and_sunday():
    # On Saturday, this weekend starts today; next weekend is +7 days.
    stay = resolve_relative_stay("this weekend", SAT)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (SAT, date(2026, 10, 25))
    stay = resolve_relative_stay("next weekend", SAT)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 31), date(2026, 11, 1))
    # On Sunday the current weekend's Saturday is past: "this weekend"
    # means the coming one, "next weekend" the one after that.
    stay = resolve_relative_stay("this weekend", SUN)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 31), date(2026, 11, 1))
    stay = resolve_relative_stay("next weekend", SUN)
    assert stay is not None
    assert (stay.check_in, stay.check_out) == (date(2026, 11, 7), date(2026, 11, 8))


def test_resolver_tomorrow_kal_and_day_after_tomorrow():
    for phrase in ("tomorrow", "kal", "कल"):
        stay = resolve_relative_stay(f"room {phrase} chahiye", FRI)
        assert stay is not None, phrase
        assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))
    for phrase in ("day after tomorrow", "parso", "परसों"):
        stay = resolve_relative_stay(phrase, FRI)
        assert stay is not None, phrase
        assert (stay.check_in, stay.check_out) == (date(2026, 10, 25), date(2026, 10, 26))


def test_resolver_weekday_phrases_english_and_hinglish():
    cases = {
        "next Friday": date(2026, 10, 30),
        "agle shukravar": date(2026, 10, 30),
        "this Monday": date(2026, 10, 26),
        "coming Monday": date(2026, 10, 26),
        "Saturday": date(2026, 10, 24),
        "next week": date(2026, 10, 30),
    }
    for phrase, expected in cases.items():
        stay = resolve_relative_stay(phrase, FRI)
        assert stay is not None, phrase
        assert stay.check_in == expected, phrase
        assert stay.check_out == expected + timedelta(days=1), phrase


def test_resolver_no_phrase_returns_none():
    assert resolve_relative_stay("I need a room please", FRI) is None
    assert resolve_relative_stay("", FRI) is None
    assert resolve_relative_stay("book for 2026-12-01 to 2026-12-03", FRI) is None


# --------------------------------------------------------------------- #
# Feature 1: end-to-end through the mock provider                        #
# --------------------------------------------------------------------- #
def test_mock_booking_next_weekend_states_dates_and_waits_for_confirmation():
    hotel, room = _seed(price=4000)
    today = _hotel_today()
    exp_in, exp_out = _next_weekend(today)
    email = f"{uid('wk')}@t.co"
    db = next(get_db())
    try:
        result = _chat(
            db,
            hotel["id"],
            "I want to book a Deluxe room for next weekend for 2 guests, "
            f"my name is Weekend Guest, email {email}",
        )
        # The resolved dates are restated in words, not booked silently.
        assert "Next weekend" in result.reply
        assert (
            f"Saturday {exp_in.day} {exp_in.strftime('%B %Y')}" in result.reply
        )
        tools = [t.tool for t in result.tool_trace]
        assert "preview_booking" in tools
        assert "create_booking" not in tools
        preview = next(t for t in result.tool_trace if t.tool == "preview_booking")
        assert preview.result["details"]["check_in"] == exp_in.isoformat()
        assert preview.result["details"]["check_out"] == exp_out.isoformat()
        # Nothing is booked before the guest confirms.
        assert db.scalars(select(Booking).where(Booking.hotel_id == hotel["id"])).all() == []

        result2 = _chat(
            db, hotel["id"], "yes, confirm please", conversation_id=result.conversation_id
        )
        assert "create_booking" in [t.tool for t in result2.tool_trace]
        bookings = db.scalars(select(Booking).where(Booking.hotel_id == hotel["id"])).all()
        assert len(bookings) == 1
        assert bookings[0].check_in == exp_in
        assert bookings[0].check_out == exp_out
    finally:
        db.close()


class _CapturingProvider:
    """Records what the runner hands the provider, then answers plainly."""

    name = "capturing"

    def __init__(self):
        self.messages = None
        self.context = None

    @property
    def available_tools(self):
        return []

    def chat(self, messages, tools, context):
        self.messages = messages
        self.context = context
        return LLMResponse(content="Noted.")


def test_runner_injects_deterministic_date_resolution_note():
    hotel, _room = _seed()
    provider = _CapturingProvider()
    db = next(get_db())
    try:
        _chat(db, hotel["id"], "book a room for next weekend", provider=provider)
    finally:
        db.close()
    assert provider.context is not None
    assert provider.context.timezone == "Asia/Kolkata"
    assert provider.context.today == _hotel_today().isoformat()
    system = provider.messages[0]["content"]
    exp_in, _exp_out = _next_weekend(_hotel_today())
    assert "DETERMINISTIC DATE RESOLUTION" in system
    assert exp_in.isoformat() in system
    assert "Saturday check-in to Sunday check-out" in system


# --------------------------------------------------------------------- #
# Feature 2: modify an upcoming booking                                  #
# --------------------------------------------------------------------- #
def test_modify_future_booking_end_to_end():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Modify Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], room["id"], future(10), future(12)
        )
        original_price = booking.final_price

        r1 = _chat(
            db, hotel["id"], "I want to change my booking", guest_id=guest["id"]
        )
        assert "get_my_bookings" in [t.tool for t in r1.tool_trace]
        assert str(booking.id) in r1.reply

        new_in, new_out = future(17), future(19)
        r2 = _chat(
            db,
            hotel["id"],
            f"move it to {new_in} to {new_out}",
            guest_id=guest["id"],
            conversation_id=r1.conversation_id,
        )
        assert "preview_booking_modification" in [t.tool for t in r2.tool_trace]
        # Gate: the preview changed nothing yet.
        db.refresh(booking)
        assert booking.check_in == future(10)
        assert booking.final_price == original_price

        r3 = _chat(
            db,
            hotel["id"],
            "yes, confirm please",
            guest_id=guest["id"],
            conversation_id=r1.conversation_id,
        )
        assert "modify_booking" in [t.tool for t in r3.tool_trace]
        db.refresh(booking)
        assert booking.check_in == new_in
        assert booking.check_out == new_out
        assert booking.final_price == Decimal("6000.00")  # 2 nights x 3000
    finally:
        db.close()


def test_modify_with_relative_date_next_weekend():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Relative Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], room["id"], future(20), future(22)
        )
        exp_in, exp_out = _next_weekend(_hotel_today())
        r1 = _chat(
            db,
            hotel["id"],
            "change my booking to next weekend",
            guest_id=guest["id"],
        )
        assert "preview_booking_modification" in [t.tool for t in r1.tool_trace]
        preview = next(
            t for t in r1.tool_trace if t.tool == "preview_booking_modification"
        )
        assert preview.result["new"]["check_in"] == exp_in.isoformat()
        assert preview.result["new"]["check_out"] == exp_out.isoformat()
        # The resolved weekend is restated in words in the reply.
        assert "Next weekend" in r1.reply

        _chat(
            db,
            hotel["id"],
            "yes, confirm please",
            guest_id=guest["id"],
            conversation_id=r1.conversation_id,
        )
        db.refresh(booking)
        assert booking.check_in == exp_in
        assert booking.check_out == exp_out
    finally:
        db.close()


def test_modify_past_checkin_refused():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Late Guest")
    db = next(get_db())
    try:
        today = _hotel_today()
        booking = _create_booking(
            db,
            hotel["id"],
            guest["id"],
            room["id"],
            today - timedelta(days=1),
            today + timedelta(days=1),
        )
        result = _chat(
            db, hotel["id"], "I want to change my booking", guest_id=guest["id"]
        )
        tools = [t.tool for t in result.tool_trace]
        assert "preview_booking_modification" not in tools
        assert "modify_booking" not in tools
        assert "check-in" in result.reply.lower()
        assert "reception" in result.reply.lower()
        db.refresh(booking)
        assert booking.check_in == today - timedelta(days=1)
    finally:
        db.close()


def test_modify_cancelled_booking_refused():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Cancel Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], room["id"], future(10), future(12)
        )
        booking_service.cancel_booking(db, booking.id, actor_type="test")
        db.commit()
        result = _chat(
            db, hotel["id"], "change my booking please", guest_id=guest["id"]
        )
        assert "preview_booking_modification" not in [t.tool for t in result.tool_trace]
        assert "cancel" in result.reply.lower()
        db.refresh(booking)
        assert booking.booking_status == "CANCELLED"
        assert booking.check_in == future(10)
    finally:
        db.close()


def test_modify_unavailable_new_dates_refused():
    # One room per night: booking B occupies the target dates, so moving
    # booking A onto them must fail deterministically.
    hotel, room = _seed(price=3000, available=1)
    guest_a = make_guest(hotel["id"], name="Guest A")
    guest_b = make_guest(hotel["id"], name="Guest B")
    db = next(get_db())
    try:
        booking_a = _create_booking(
            db, hotel["id"], guest_a["id"], room["id"], future(10), future(12)
        )
        _create_booking(db, hotel["id"], guest_b["id"], room["id"], future(17), future(19))
        result = _chat(
            db,
            hotel["id"],
            f"change my booking to {future(17)} to {future(19)}",
            guest_id=guest_a["id"],
        )
        assert "modify_booking" not in [t.tool for t in result.tool_trace]
        assert "availability" in result.reply.lower()
        db.refresh(booking_a)
        assert booking_a.check_in == future(10)
    finally:
        db.close()


def test_modify_without_preview_token_fails_safely():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Token Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], room["id"], future(10), future(12)
        )
        with pytest.raises(BookingError):
            booking_service.modify_booking(
                db,
                booking.id,
                modification_token="forged.token",
                today=_hotel_today(),
                actor_type="test",
            )
        db.refresh(booking)
        assert booking.check_in == future(10)
    finally:
        db.close()


def test_modify_payment_reconciliation():
    hotel, room = _seed(price=3000)
    guest = make_guest(hotel["id"], name="Pay Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], room["id"], future(10), future(12)
        )
        # Partially paid: 4000 captured of the 6000 total, 2000 pending.
        db.add_all(
            [
                Payment(
                    hotel_id=hotel["id"],
                    booking_id=booking.id,
                    amount=Decimal("4000"),
                    method="upi",
                    status="captured",
                ),
                Payment(
                    hotel_id=hotel["id"],
                    booking_id=booking.id,
                    amount=Decimal("2000"),
                    method="upi",
                    status="pending",
                ),
            ]
        )
        db.commit()

        def _apply(new_out):
            quote = booking_service.validate_modification(
                db, booking, today=_hotel_today(), new_check_out=new_out
            )
            token, _exp = booking_service.issue_modification_token(quote)
            return booking_service.modify_booking(
                db,
                booking.id,
                modification_token=token,
                today=_hotel_today(),
                actor_type="test",
            )

        # Extend to 3 nights (9000): captured stays, pending becomes 5000.
        _booking, quote = _apply(future(13))
        db.commit()
        assert quote.amount_due == Decimal("5000.00")
        assert quote.refund_due == Decimal("0.00")
        payments = db.scalars(
            select(Payment).where(Payment.booking_id == booking.id)
        ).all()
        captured = [p for p in payments if p.status == "captured"]
        pending = [p for p in payments if p.status == "pending"]
        assert len(captured) == 1 and captured[0].amount == Decimal("4000")
        assert len(pending) == 1 and pending[0].amount == Decimal("5000")

        # Shrink to 1 night (3000): overpaid by 1000 -> refund_due is
        # reported, captured money is untouched, pending row is removed.
        _booking, quote = _apply(future(11))
        db.commit()
        assert quote.amount_due == Decimal("0.00")
        assert quote.refund_due == Decimal("1000.00")
        payments = db.scalars(
            select(Payment).where(Payment.booking_id == booking.id)
        ).all()
        assert [p for p in payments if p.status == "pending"] == []
        captured = [p for p in payments if p.status == "captured"]
        assert len(captured) == 1 and captured[0].amount == Decimal("4000")
        # No fabricated refund record was created.
        assert [p for p in payments if p.status == "refunded"] == []
    finally:
        db.close()


def test_modify_room_type_and_guest_count_via_service():
    hotel = make_hotel()
    deluxe = make_room(hotel["id"], room_type="Deluxe", capacity=4, total_rooms=5)
    suite = make_room(hotel["id"], room_type="Suite", capacity=4, total_rooms=5)
    start = _hotel_today() - timedelta(days=3)
    seed_rates_availability(deluxe["id"], start, 50, price=3000, available=5)
    seed_rates_availability(suite["id"], start, 50, price=5000, available=5)
    guest = make_guest(hotel["id"], name="Upgrade Guest")
    db = next(get_db())
    try:
        booking = _create_booking(
            db, hotel["id"], guest["id"], deluxe["id"], future(10), future(12), guests=2
        )
        quote = booking_service.validate_modification(
            db,
            booking,
            today=_hotel_today(),
            new_room_id=suite["id"],
            new_number_of_guests=3,
        )
        assert quote.new_total == Decimal("10000.00")  # 2 nights x 5000
        token, _exp = booking_service.issue_modification_token(quote)
        booking, _quote = booking_service.modify_booking(
            db, booking.id, modification_token=token, today=_hotel_today(), actor_type="test"
        )
        db.commit()
        assert booking.room_id == suite["id"]
        assert booking.number_of_guests == 3
        assert booking.final_price == Decimal("10000.00")
    finally:
        db.close()


def test_modify_tools_enforce_guest_ownership():
    from app.agent.tools.registry import ToolContext, build_registry

    hotel, room = _seed(price=3000)
    guest_a = make_guest(hotel["id"], name="Owner A")
    guest_b = make_guest(hotel["id"], name="Other B")
    db = next(get_db())
    try:
        booking_b = _create_booking(
            db, hotel["id"], guest_b["id"], room["id"], future(10), future(12)
        )
        registry = build_registry()
        ctx_a = ToolContext(hotel_id=hotel["id"], guest_id=guest_a["id"])
        listed = registry.execute(
            "get_my_bookings", {"hotel_id": hotel["id"]}, db, ctx_a
        )
        assert listed.ok
        assert listed.data["bookings"] == []
        preview = registry.execute(
            "preview_booking_modification",
            {
                "hotel_id": hotel["id"],
                "booking_id": booking_b.id,
                "new_check_in": str(future(12)),
                "new_check_out": str(future(14)),
            },
            db,
            ctx_a,
        )
        assert not preview.ok
        assert "different guest" in (preview.error or "")
    finally:
        db.close()
