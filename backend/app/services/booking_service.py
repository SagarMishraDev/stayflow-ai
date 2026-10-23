"""Deterministic booking business logic.

This module is the single place where booking rules live. Both the REST API
and the AI agent's tools call into it, so the LLM can never bypass hotel
business rules (availability, pricing, capacity, negotiation limits).

Core principle: the tool/service layer validates everything; the LLM only
decides *which* action to take.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.availability import Availability
from app.models.booking import Booking
from app.models.booking_draft import (
    DRAFT_STATUS_CONFIRMED,
    DRAFT_STATUS_EXPIRED,
    DRAFT_STATUS_PENDING,
    BookingDraft,
)
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.negotiation_rule import NegotiationRule
from app.models.rate import Rate
from app.models.room import Room
from app.services.audit import log_action

# Booking statuses that occupy inventory on a given night.
ACTIVE_BOOKING_STATUSES = ("PENDING", "CONFIRMED", "CHECKED_IN")

# How long a booking draft stays confirmable after preview.
DRAFT_TTL_MINUTES = 15

# Statuses a booking may be cancelled from.
CANCELABLE_STATUSES = ("PENDING", "CONFIRMED")

# Allowed status transitions for PATCH /bookings/{id}.
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("CHECKED_IN", "CANCELLED"),
    "CHECKED_IN": ("CHECKED_OUT",),
    "CHECKED_OUT": (),
    "CANCELLED": (),
}


class BookingError(Exception):
    """Deterministic booking failure with an HTTP status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def iter_nights(check_in: date, check_out: date) -> Iterable[date]:
    """Yield each night in [check_in, check_out)."""
    day = check_in
    while day < check_out:
        yield day
        day += timedelta(days=1)


def validate_status_transition(current: str, new: str) -> None:
    allowed = STATUS_TRANSITIONS.get(current, ())
    if new == current:
        return
    if new not in allowed:
        raise BookingError(
            422,
            f"Cannot transition booking from {current} to {new}. "
            f"Allowed: {', '.join(allowed) or 'none'}",
        )


@dataclass
class NightQuote:
    date: date
    price: Decimal | None  # None when no active rate is configured


@dataclass
class BookingQuote:
    room_id: int
    check_in: date
    check_out: date
    nights: list[NightQuote] = field(default_factory=list)
    currency: str = "INR"

    @property
    def total(self) -> Decimal:
        return sum((n.price for n in self.nights if n.price is not None), Decimal("0.00"))

    @property
    def missing_dates(self) -> list[date]:
        return [n.date for n in self.nights if n.price is None]

    @property
    def fully_priced(self) -> bool:
        return len(self.nights) > 0 and not self.missing_dates


def quote_booking_price(db: Session, room_id: int, check_in: date, check_out: date) -> BookingQuote:
    """Compute the deterministic price for a stay from configured rates."""
    room = db.get(Room, room_id)
    if room is None:
        raise BookingError(404, "Room not found")
    if check_out <= check_in:
        raise BookingError(422, "check_out must be after check_in")

    nights = list(iter_nights(check_in, check_out))
    rates = {
        r.date: r
        for r in db.scalars(
            select(Rate).where(
                Rate.room_id == room_id,
                Rate.date >= check_in,
                Rate.date < check_out,
                Rate.is_active.is_(True),
            )
        ).all()
    }
    hotel = db.get(Hotel, room.hotel_id)
    quote = BookingQuote(
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        currency=hotel.currency if hotel else "INR",
    )
    for night in nights:
        rate = rates.get(night)
        quote.nights.append(NightQuote(date=night, price=rate.price if rate else None))
    return quote


@dataclass
class NightAvailability:
    date: date
    capacity: int  # effective inventory for the night
    booked: int  # rooms already occupied by active bookings
    available: int  # capacity - booked


def check_availability(
    db: Session,
    room_id: int,
    check_in: date,
    check_out: date,
    *,
    exclude_booking_id: int | None = None,
    for_update: bool = False,
) -> list[NightAvailability]:
    """Return per-night availability for a room over [check_in, check_out).

    Effective capacity comes from the date-specific availability row when one
    exists, otherwise from the room's total inventory. Already-booked rooms
    are subtracted. Set ``for_update=True`` inside a booking transaction to
    lock the availability rows against concurrent bookings.
    """
    room = db.get(Room, room_id)
    if room is None:
        raise BookingError(404, "Room not found")
    if check_out <= check_in:
        raise BookingError(422, "check_out must be after check_in")

    nights = list(iter_nights(check_in, check_out))

    avail_stmt = select(Availability).where(
        Availability.room_id == room_id,
        Availability.date >= check_in,
        Availability.date < check_out,
        Availability.is_active.is_(True),
    )
    if for_update:
        avail_stmt = avail_stmt.with_for_update()
    availability_rows = {a.date: a for a in db.scalars(avail_stmt).all()}
    if for_update:
        # Nights without a date-specific row fall back to the room's total
        # inventory, so lock the room row itself to serialize concurrent
        # bookings for those nights.
        db.execute(select(Room.id).where(Room.id == room_id).with_for_update())

    booked_stmt = (
        select(Booking.check_in, Booking.check_out, func.count(Booking.id))
        .where(
            Booking.room_id == room_id,
            Booking.booking_status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.check_in < check_out,
            Booking.check_out > check_in,
        )
        .group_by(Booking.check_in, Booking.check_out)
    )
    if exclude_booking_id is not None:
        booked_stmt = booked_stmt.where(Booking.id != exclude_booking_id)
    booked_per_night: dict[date, int] = {}
    for b_in, b_out, count in db.execute(booked_stmt).all():
        for night in iter_nights(max(b_in, check_in), min(b_out, check_out)):
            booked_per_night[night] = booked_per_night.get(night, 0) + count

    result: list[NightAvailability] = []
    for night in nights:
        row = availability_rows.get(night)
        capacity = row.available_rooms if row is not None else room.total_rooms
        booked = booked_per_night.get(night, 0)
        result.append(
            NightAvailability(
                date=night,
                capacity=capacity,
                booked=booked,
                available=max(capacity - booked, 0),
            )
        )
    return result


def _resolve_price(
    db: Session,
    room_id: int,
    check_in: date,
    check_out: date,
    final_price: Decimal | None,
) -> Decimal:
    """Server-side price resolution.

    - When rates cover every night, the price is deterministic: a
      client/agent-supplied price that disagrees is rejected (this blocks
      price-manipulation attempts).
    - When rates are missing for some nights, a supplied price is accepted
      (backwards compatible with PMS clients that price externally).
    - When no price can be determined at all, the booking is rejected.
    """
    quote = quote_booking_price(db, room_id, check_in, check_out)
    if quote.fully_priced:
        if final_price is not None and final_price != quote.total:
            raise BookingError(
                422,
                f"final_price {final_price} does not match the computed stay price "
                f"{quote.total} for {len(quote.nights)} night(s). Prices are "
                "computed from configured rates and cannot be overridden.",
            )
        return quote.total
    if final_price is None:
        missing = ", ".join(d.isoformat() for d in quote.missing_dates)
        raise BookingError(
            422,
            f"No rate configured for date(s): {missing}. Provide final_price or "
            "configure rates for these dates.",
        )
    return final_price


def _validate_booking_parties(
    db: Session, hotel_id: int, guest_id: int, room_id: int
) -> tuple[Guest, Room]:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise BookingError(404, "Hotel not found")
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise BookingError(404, "Guest not found")
    room = db.get(Room, room_id)
    if room is None:
        raise BookingError(404, "Room not found")
    if guest.hotel_id != hotel_id:
        raise BookingError(422, "Guest does not belong to this hotel")
    if room.hotel_id != hotel_id:
        raise BookingError(422, "Room does not belong to this hotel")
    return guest, room


def create_booking_record(
    db: Session,
    *,
    hotel_id: int,
    guest_id: int,
    room_id: int,
    check_in: date,
    check_out: date,
    number_of_guests: int,
    final_price: Decimal | None = None,
    booking_status: str = "PENDING",
    actor_type: str = "api",
    actor_id: int | None = None,
    source: str | None = None,
) -> Booking:
    """Create a booking after enforcing every business rule.

    Raises BookingError on any validation failure. Availability rows are
    locked (SELECT ... FOR UPDATE) so concurrent bookings cannot oversell
    the same night.
    """
    if check_out <= check_in:
        raise BookingError(422, "check_out must be after check_in")
    if number_of_guests <= 0:
        raise BookingError(422, "number_of_guests must be positive")
    if booking_status not in STATUS_TRANSITIONS:
        raise BookingError(422, f"Unknown booking_status: {booking_status}")
    if booking_status not in ("PENDING", "CONFIRMED"):
        raise BookingError(
            422,
            f"Bookings can only be created with status PENDING or CONFIRMED, got {booking_status}",
        )

    _guest, room = _validate_booking_parties(db, hotel_id, guest_id, room_id)

    if number_of_guests > room.capacity:
        raise BookingError(422, "Number of guests exceeds room capacity")

    availability = check_availability(db, room_id, check_in, check_out, for_update=True)
    sold_out = [n.date.isoformat() for n in availability if n.available < 1]
    if sold_out:
        raise BookingError(
            422,
            f"No availability for room {room_id} on: {', '.join(sold_out)}",
        )

    price = _resolve_price(db, room_id, check_in, check_out, final_price)

    booking = Booking(
        hotel_id=hotel_id,
        guest_id=guest_id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        number_of_guests=number_of_guests,
        final_price=price,
        booking_status=booking_status,
        source=source,
    )
    db.add(booking)
    db.flush()  # assign id for the audit entry
    log_action(
        db,
        hotel_id=hotel_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="booking.created",
        entity_type="booking",
        entity_id=booking.id,
        details={
            "room_id": room_id,
            "guest_id": guest_id,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "final_price": str(price),
            "status": booking_status,
        },
    )
    return booking


def create_booking_draft(
    db: Session,
    *,
    hotel_id: int,
    guest_id: int,
    room_id: int,
    check_in: date,
    check_out: date,
    number_of_guests: int,
    actor_type: str = "api",
    actor_id: int | None = None,
) -> BookingDraft:
    """Validate a prospective booking, price it, and persist a draft.

    This is phase one of the two-phase booking flow. Every business rule is
    enforced here (hotel/guest/room ownership, capacity, availability,
    deterministic pricing), and the resulting draft pins the exact parameters
    plus the backend-computed total and an expiry. Nothing is booked yet;
    :func:`confirm_booking_draft` performs the actual mutation after
    re-validating availability and pricing. Raises BookingError on any
    validation failure.
    """
    if check_out <= check_in:
        raise BookingError(422, "check_out must be after check_in")
    if number_of_guests <= 0:
        raise BookingError(422, "number_of_guests must be positive")

    _guest, room = _validate_booking_parties(db, hotel_id, guest_id, room_id)

    if number_of_guests > room.capacity:
        raise BookingError(422, "Number of guests exceeds room capacity")

    availability = check_availability(db, room_id, check_in, check_out)
    sold_out = [n.date.isoformat() for n in availability if n.available < 1]
    if sold_out:
        raise BookingError(
            422,
            f"No availability for room {room_id} on: {', '.join(sold_out)}",
        )

    quote = quote_booking_price(db, room_id, check_in, check_out)
    if not quote.fully_priced:
        missing = ", ".join(d.isoformat() for d in quote.missing_dates)
        raise BookingError(
            422,
            f"No rate configured for date(s): {missing}. Cannot hold a priced draft.",
        )

    now = datetime.now(UTC)
    draft = BookingDraft(
        hotel_id=hotel_id,
        guest_id=guest_id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        number_of_guests=number_of_guests,
        total_price=quote.total,
        currency=quote.currency,
        status=DRAFT_STATUS_PENDING,
        expires_at=now + timedelta(minutes=DRAFT_TTL_MINUTES),
    )
    db.add(draft)
    db.flush()  # assign id for the audit entry
    log_action(
        db,
        hotel_id=hotel_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="booking.draft_created",
        entity_type="booking_draft",
        entity_id=draft.id,
        details={
            "room_id": room_id,
            "guest_id": guest_id,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "number_of_guests": number_of_guests,
            "total_price": str(quote.total),
            "expires_at": draft.expires_at.isoformat(),
        },
    )
    return draft


def confirm_booking_draft(
    db: Session,
    *,
    draft_id: int,
    hotel_id: int,
    actor_type: str = "api",
    actor_id: int | None = None,
) -> Booking:
    """Consume a booking draft: re-validate, then create the booking.

    This is phase two of the two-phase booking flow and the ONLY path that
    mutates inventory for the agent. Raises BookingError when the draft is
    missing, belongs to another hotel, already used, or expired. Availability
    and pricing are re-checked at confirm time because both can change
    between preview and confirmation; a price change fails the confirmation
    instead of silently charging a different amount.
    """
    draft = db.get(BookingDraft, draft_id)
    if draft is None or draft.hotel_id != hotel_id:
        raise BookingError(404, "Booking draft not found")
    if draft.status != DRAFT_STATUS_PENDING:
        raise BookingError(
            422,
            f"Booking draft is {draft.status.lower()}; it cannot be confirmed",
        )
    if draft.is_expired:
        draft.status = DRAFT_STATUS_EXPIRED
        db.flush()
        raise BookingError(
            422,
            "Booking draft has expired; please preview the booking again",
        )

    # Re-validate pricing: rates may have changed since the preview.
    quote = quote_booking_price(db, draft.room_id, draft.check_in, draft.check_out)
    if not quote.fully_priced or quote.total != draft.total_price:
        raise BookingError(
            422,
            "The price changed since the preview; please preview the booking again",
        )

    booking = create_booking_record(
        db,
        hotel_id=hotel_id,
        guest_id=draft.guest_id,
        room_id=draft.room_id,
        check_in=draft.check_in,
        check_out=draft.check_out,
        number_of_guests=draft.number_of_guests,
        final_price=draft.total_price,
        booking_status="CONFIRMED",
        actor_type=actor_type,
        actor_id=actor_id,
        source="agent_chat",
    )
    draft.status = DRAFT_STATUS_CONFIRMED
    db.flush()
    return booking


def cancel_booking(
    db: Session,
    booking_id: int,
    *,
    actor_type: str = "api",
    actor_id: int | None = None,
    reason: str | None = None,
) -> Booking:
    """Cancel a booking. Cancelled bookings release their inventory."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise BookingError(404, "Booking not found")
    if booking.booking_status not in CANCELABLE_STATUSES:
        raise BookingError(
            422,
            f"Booking cannot be cancelled from status {booking.booking_status}",
        )
    booking.booking_status = "CANCELLED"
    db.flush()
    log_action(
        db,
        hotel_id=booking.hotel_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="booking.cancelled",
        entity_type="booking",
        entity_id=booking.id,
        details={"reason": reason} if reason else None,
    )
    return booking


def update_booking_dates_guests(
    db: Session,
    booking: Booking,
    *,
    check_in: date | None = None,
    check_out: date | None = None,
    number_of_guests: int | None = None,
    actor_type: str = "api",
    actor_id: int | None = None,
) -> None:
    """Validate and apply date/guest-count changes, re-checking availability."""
    new_in = check_in if check_in is not None else booking.check_in
    new_out = check_out if check_out is not None else booking.check_out
    new_guests = number_of_guests if number_of_guests is not None else booking.number_of_guests
    if new_out <= new_in:
        raise BookingError(422, "check_out must be after check_in")
    room = db.get(Room, booking.room_id)
    if room is None:
        raise BookingError(404, "Room not found")
    if new_guests > room.capacity:
        raise BookingError(422, "Number of guests exceeds room capacity")

    if booking.booking_status in ACTIVE_BOOKING_STATUSES and (
        new_in != booking.check_in or new_out != booking.check_out
    ):
        availability = check_availability(
            db,
            booking.room_id,
            new_in,
            new_out,
            exclude_booking_id=booking.id,
            for_update=True,
        )
        sold_out = [n.date.isoformat() for n in availability if n.available < 1]
        if sold_out:
            raise BookingError(422, f"No availability for the new dates: {', '.join(sold_out)}")

    changes: dict[str, str] = {}
    if new_in != booking.check_in:
        changes["check_in"] = f"{booking.check_in.isoformat()} -> {new_in.isoformat()}"
    if new_out != booking.check_out:
        changes["check_out"] = f"{booking.check_out.isoformat()} -> {new_out.isoformat()}"
    if new_guests != booking.number_of_guests:
        changes["number_of_guests"] = f"{booking.number_of_guests} -> {new_guests}"

    booking.check_in = new_in
    booking.check_out = new_out
    booking.number_of_guests = new_guests

    if changes:
        log_action(
            db,
            hotel_id=booking.hotel_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="booking.modified",
            entity_type="booking",
            entity_id=booking.id,
            details=changes,
        )


@dataclass
class NegotiationResult:
    accepted: bool
    requires_approval: bool
    base_price: Decimal
    offered_price: Decimal
    minimum_acceptable_price: Decimal
    maximum_discount_percent: Decimal
    reason: str


def evaluate_price_offer(
    db: Session,
    *,
    hotel_id: int,
    room_id: int,
    check_in: date,
    check_out: date,
    offered_price: Decimal,
) -> NegotiationResult:
    """Evaluate a guest's price offer against hotel negotiation rules.

    The hotel's configured rules are authoritative; the agent must never
    invent discounts or go below the hotel's minimum price.
    """
    quote = quote_booking_price(db, room_id, check_in, check_out)
    base_price = quote.total
    if not quote.fully_priced:
        return NegotiationResult(
            accepted=False,
            requires_approval=True,
            base_price=base_price,
            offered_price=offered_price,
            minimum_acceptable_price=base_price,
            maximum_discount_percent=Decimal("0"),
            reason="No complete rate card for these dates; offer needs manual approval.",
        )

    rule = db.scalar(
        select(NegotiationRule).where(
            NegotiationRule.hotel_id == hotel_id,
            NegotiationRule.room_id == room_id,
            NegotiationRule.is_active.is_(True),
        )
    )
    if rule is None:
        rule = db.scalar(
            select(NegotiationRule).where(
                NegotiationRule.hotel_id == hotel_id,
                NegotiationRule.room_id.is_(None),
                NegotiationRule.is_active.is_(True),
            )
        )

    if rule is None or not rule.is_enabled:
        accepted = offered_price >= base_price
        return NegotiationResult(
            accepted=accepted,
            requires_approval=False,
            base_price=base_price,
            offered_price=offered_price,
            minimum_acceptable_price=base_price,
            maximum_discount_percent=Decimal("0"),
            reason=(
                "No negotiation rule configured; full price required."
                if not accepted
                else "Offer meets the full price."
            ),
        )

    minimum_price = Decimal(str(rule.minimum_price))
    max_discount = Decimal(str(rule.maximum_discount_percent))
    discount_floor = base_price * (Decimal("1") - max_discount / Decimal("100"))
    minimum_acceptable = max(minimum_price, discount_floor)

    if offered_price < minimum_acceptable:
        return NegotiationResult(
            accepted=False,
            requires_approval=bool(rule.requires_approval),
            base_price=base_price,
            offered_price=offered_price,
            minimum_acceptable_price=minimum_acceptable,
            maximum_discount_percent=max_discount,
            reason=(
                f"Offer {offered_price} is below the minimum acceptable price "
                f"{minimum_acceptable} (hotel minimum {minimum_price}, max discount "
                f"{max_discount}%)."
            ),
        )
    if rule.requires_approval and offered_price < base_price:
        return NegotiationResult(
            accepted=False,
            requires_approval=True,
            base_price=base_price,
            offered_price=offered_price,
            minimum_acceptable_price=minimum_acceptable,
            maximum_discount_percent=max_discount,
            reason="Offer is within limits but requires staff approval.",
        )
    return NegotiationResult(
        accepted=True,
        requires_approval=False,
        base_price=base_price,
        offered_price=offered_price,
        minimum_acceptable_price=minimum_acceptable,
        maximum_discount_percent=max_discount,
        reason="Offer accepted within hotel negotiation rules.",
    )
