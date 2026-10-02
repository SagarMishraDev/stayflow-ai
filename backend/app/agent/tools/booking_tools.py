"""Booking and guest tools (Phase 4 of the agent layer).

Write operations are deterministic and validated here:

- ``preview_booking`` validates everything via the booking service, computes
  the backend total, and persists a ``BookingDraft`` with an expiry. It books
  nothing; it returns a ``draft_id`` plus a human-readable summary.
- ``create_booking`` performs the actual mutation and REQUIRES a valid,
  unexpired ``draft_id`` from ``preview_booking``. Availability and pricing
  are re-validated at confirm time, because both can change between preview
  and confirmation. Calling it without a draft fails safely.
- ``create_booking`` never trusts a price from the LLM: the price is computed
  from configured rates by the booking service.
- ``evaluate_price_offer`` enforces the hotel's negotiation rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.tools.registry import ToolContext, ToolSpec
from app.models.booking import Booking
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.room import Room
from app.services import booking_service
from app.services.audit import log_action


def _require_hotel(db: Session, hotel_id: int) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise ValueError(f"Hotel {hotel_id} not found")
    return hotel


# --------------------------------------------------------------------- #
# find_or_create_guest                                                   #
# --------------------------------------------------------------------- #
class FindOrCreateGuestArgs(BaseModel):
    hotel_id: int
    name: str = Field(min_length=1)
    phone: str | None = None
    email: str | None = None


def find_or_create_guest(
    db: Session, ctx: ToolContext, args: FindOrCreateGuestArgs
) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    existing: Guest | None = None
    if args.phone:
        existing = db.scalar(
            select(Guest).where(Guest.hotel_id == args.hotel_id, Guest.phone == args.phone)
        )
    if existing is None and args.email:
        existing = db.scalar(
            select(Guest).where(
                Guest.hotel_id == args.hotel_id,
                func.lower(Guest.email) == args.email.lower(),
            )
        )
    if existing is not None:
        return {
            "guest_id": existing.id,
            "name": existing.name,
            "created": False,
        }
    guest = Guest(
        hotel_id=args.hotel_id,
        name=args.name.strip(),
        phone=args.phone,
        email=args.email,
    )
    db.add(guest)
    db.flush()
    log_action(
        db,
        hotel_id=args.hotel_id,
        actor_type=ctx.actor_type,
        actor_id=ctx.guest_id,
        action="guest.created",
        entity_type="guest",
        entity_id=guest.id,
        details={"name": guest.name},
    )
    return {"guest_id": guest.id, "name": guest.name, "created": True}


# --------------------------------------------------------------------- #
# preview_booking                                                        #
# --------------------------------------------------------------------- #
class PreviewBookingArgs(BaseModel):
    hotel_id: int
    room_id: int
    check_in: date
    check_out: date
    number_of_guests: int = Field(gt=0)
    guest_id: int | None = Field(
        default=None, description="Known guest id; falls back to the conversation guest"
    )


def preview_booking(db: Session, ctx: ToolContext, args: PreviewBookingArgs) -> dict[str, Any]:
    """Phase one: validate, price, and persist a booking draft (books nothing)."""
    _require_hotel(db, args.hotel_id)
    guest_id = args.guest_id or ctx.guest_id
    if guest_id is None:
        raise ValueError(
            "No guest identified. Use find_or_create_guest first, or ask the "
            "guest for their name and phone number."
        )
    room = db.get(Room, args.room_id)
    if room is None or room.hotel_id != args.hotel_id:
        raise ValueError("Room not found for this hotel")

    draft = booking_service.create_booking_draft(
        db,
        hotel_id=args.hotel_id,
        guest_id=guest_id,
        room_id=args.room_id,
        check_in=args.check_in,
        check_out=args.check_out,
        number_of_guests=args.number_of_guests,
        actor_type=ctx.actor_type,
        actor_id=guest_id,
    )
    db.commit()
    return {
        "draft_id": draft.id,
        "expires_at": draft.expires_at.isoformat(),
        "message": (
            "Booking draft created. Present these details to the guest and ask "
            "'Would you like me to confirm this booking?'. Only call "
            "create_booking with this draft_id after the guest explicitly confirms."
        ),
        "details": {
            "room_type": room.room_type,
            "check_in": args.check_in.isoformat(),
            "check_out": args.check_out.isoformat(),
            "number_of_guests": args.number_of_guests,
            "total_price": str(draft.total_price),
            "currency": draft.currency,
        },
    }


# --------------------------------------------------------------------- #
# create_booking (phase two: consumes a draft)                           #
# --------------------------------------------------------------------- #
class CreateBookingArgs(BaseModel):
    hotel_id: int
    draft_id: int = Field(
        description=(
            "Draft id returned by preview_booking. The guest must have explicitly "
            "confirmed the previewed details before you pass it here."
        )
    )


def create_booking(db: Session, ctx: ToolContext, args: CreateBookingArgs) -> dict[str, Any]:
    """Phase two: confirm a booking draft. Requires a valid, unexpired draft.

    Calling this without a draft_id from preview_booking fails safely: no
    booking is created. Availability and pricing are re-validated at confirm
    time by the booking service.
    """
    _require_hotel(db, args.hotel_id)

    booking = booking_service.confirm_booking_draft(
        db,
        draft_id=args.draft_id,
        hotel_id=args.hotel_id,
        actor_type=ctx.actor_type,
        actor_id=ctx.guest_id,
    )
    room = db.get(Room, booking.room_id)
    db.commit()
    return {
        "booking_id": booking.id,
        "booking_status": booking.booking_status,
        "room_type": room.room_type if room else None,
        "check_in": booking.check_in.isoformat(),
        "check_out": booking.check_out.isoformat(),
        "number_of_guests": booking.number_of_guests,
        "final_price": str(booking.final_price),
        "draft_id": args.draft_id,
    }


# --------------------------------------------------------------------- #
# get_booking / cancel_booking                                           #
# --------------------------------------------------------------------- #
class BookingIdArgs(BaseModel):
    hotel_id: int
    booking_id: int


def get_booking(db: Session, ctx: ToolContext, args: BookingIdArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    booking = db.get(Booking, args.booking_id)
    if booking is None or booking.hotel_id != args.hotel_id:
        raise ValueError("Booking not found for this hotel")
    guest = db.get(Guest, booking.guest_id)
    room = db.get(Room, booking.room_id)
    return {
        "booking_id": booking.id,
        "booking_status": booking.booking_status,
        "guest_name": guest.name if guest else None,
        "room_type": room.room_type if room else None,
        "check_in": booking.check_in.isoformat(),
        "check_out": booking.check_out.isoformat(),
        "number_of_guests": booking.number_of_guests,
        "final_price": str(booking.final_price),
    }


class CancelBookingArgs(BaseModel):
    hotel_id: int
    booking_id: int
    reason: str | None = None


def cancel_booking(db: Session, ctx: ToolContext, args: CancelBookingArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    booking = db.get(Booking, args.booking_id)
    if booking is None or booking.hotel_id != args.hotel_id:
        raise ValueError("Booking not found for this hotel")
    booking_service.cancel_booking(
        db,
        booking.id,
        actor_type=ctx.actor_type,
        actor_id=ctx.guest_id,
        reason=args.reason,
    )
    db.commit()
    return {"booking_id": booking.id, "booking_status": booking.booking_status}


# --------------------------------------------------------------------- #
# evaluate_price_offer                                                   #
# --------------------------------------------------------------------- #
class EvaluateOfferArgs(BaseModel):
    hotel_id: int
    room_id: int
    check_in: date
    check_out: date
    offered_price: Decimal = Field(gt=0)


def evaluate_price_offer(db: Session, ctx: ToolContext, args: EvaluateOfferArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    room = db.get(Room, args.room_id)
    if room is None or room.hotel_id != args.hotel_id:
        raise ValueError("Room not found for this hotel")
    result = booking_service.evaluate_price_offer(
        db,
        hotel_id=args.hotel_id,
        room_id=args.room_id,
        check_in=args.check_in,
        check_out=args.check_out,
        offered_price=args.offered_price,
    )
    return {
        "accepted": result.accepted,
        "requires_approval": result.requires_approval,
        "base_price": str(result.base_price),
        "offered_price": str(result.offered_price),
        "minimum_acceptable_price": str(result.minimum_acceptable_price),
        "maximum_discount_percent": str(result.maximum_discount_percent),
        "reason": result.reason,
    }


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="find_or_create_guest",
        description=(
            "Find an existing guest by phone/email or create a new guest profile. "
            "Use before booking when the guest is not identified."
        ),
        args_model=FindOrCreateGuestArgs,
        handler=find_or_create_guest,
        read_only=False,
    ),
    ToolSpec(
        name="preview_booking",
        description=(
            "Phase one of booking: validate the stay, compute the total price "
            "from configured rates, and persist a booking draft with an expiry. "
            "Books nothing. Present the returned summary to the guest and ask "
            "'Would you like me to confirm this booking?' before phase two."
        ),
        args_model=PreviewBookingArgs,
        handler=preview_booking,
        read_only=False,
    ),
    ToolSpec(
        name="create_booking",
        description=(
            "Phase two of booking: confirm a booking draft created by "
            "preview_booking. REQUIRES a valid, unexpired draft_id; the guest "
            "must have explicitly confirmed the previewed details. Availability "
            "and pricing are re-validated at confirm time. The price is always "
            "computed from configured rates — never pass a price."
        ),
        args_model=CreateBookingArgs,
        handler=create_booking,
        read_only=False,
    ),
    ToolSpec(
        name="get_booking",
        description="Look up a booking by id (status, dates, price, guest).",
        args_model=BookingIdArgs,
        handler=get_booking,
        read_only=True,
    ),
    ToolSpec(
        name="cancel_booking",
        description="Cancel a booking, releasing its inventory.",
        args_model=CancelBookingArgs,
        handler=cancel_booking,
        read_only=False,
    ),
    ToolSpec(
        name="evaluate_price_offer",
        description=(
            "Evaluate a guest's price offer against the hotel's negotiation rules. "
            "The hotel's minimum price and max discount are authoritative."
        ),
        args_model=EvaluateOfferArgs,
        handler=evaluate_price_offer,
        read_only=True,
    ),
]

__all__ = ["SPECS"]
