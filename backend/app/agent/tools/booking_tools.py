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

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def _hotel_today(db: Session, hotel_id: int) -> date:
    """Current date in the hotel's configured timezone."""
    hotel = _require_hotel(db, hotel_id)
    tz_name = hotel.timezone or "Asia/Kolkata"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).date()


def _require_own_booking(db: Session, ctx: ToolContext, booking_id: int) -> Booking:
    """Load a booking, enforcing hotel scope and guest ownership."""
    booking = db.get(Booking, booking_id)
    if booking is None or booking.hotel_id != ctx.hotel_id:
        raise ValueError("Booking not found for this hotel")
    if ctx.guest_id is not None and booking.guest_id != ctx.guest_id:
        raise ValueError("This booking belongs to a different guest.")
    return booking


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
# get_my_bookings                                                        #
# --------------------------------------------------------------------- #
class GetMyBookingsArgs(BaseModel):
    hotel_id: int
    guest_id: int | None = Field(
        default=None, description="Known guest id; falls back to the conversation guest"
    )


def get_my_bookings(db: Session, ctx: ToolContext, args: GetMyBookingsArgs) -> dict[str, Any]:
    """List the guest's current/upcoming bookings with modification eligibility."""
    _require_hotel(db, args.hotel_id)
    guest_id = args.guest_id or ctx.guest_id
    if guest_id is None:
        raise ValueError(
            "No guest identified. Use find_or_create_guest first, or ask the "
            "guest for their name and phone number."
        )
    guest = db.get(Guest, guest_id)
    if guest is None or guest.hotel_id != args.hotel_id:
        raise ValueError("Guest not found for this hotel")
    today = _hotel_today(db, args.hotel_id)
    bookings = db.scalars(
        select(Booking)
        .where(
            Booking.hotel_id == args.hotel_id,
            Booking.guest_id == guest_id,
            Booking.check_out >= today,
        )
        .order_by(Booking.check_in, Booking.id)
    ).all()
    result = []
    for booking in bookings:
        room = db.get(Room, booking.room_id)
        reason = booking_service.modification_ineligibility_reason(booking, today)
        result.append(
            {
                "booking_id": booking.id,
                "room_type": room.room_type if room else None,
                "check_in": booking.check_in.isoformat(),
                "check_out": booking.check_out.isoformat(),
                "number_of_guests": booking.number_of_guests,
                "booking_status": booking.booking_status,
                "final_price": str(booking.final_price),
                "modifiable": reason is None,
                "ineligible_reason": reason,
            }
        )
    return {"guest_id": guest_id, "today": today.isoformat(), "bookings": result}


# --------------------------------------------------------------------- #
# preview_booking_modification / modify_booking (two-phase)              #
# --------------------------------------------------------------------- #
class PreviewModificationArgs(BaseModel):
    hotel_id: int
    booking_id: int
    new_room_id: int | None = None
    new_check_in: date | None = None
    new_check_out: date | None = None
    new_number_of_guests: int | None = Field(default=None, gt=0)


def _modification_summary(
    db: Session, quote: booking_service.ModificationQuote
) -> dict[str, Any]:
    old_room = db.get(Room, quote.old_room_id)
    new_room = db.get(Room, quote.new_room_id)
    return {
        "booking_id": quote.booking_id,
        "old": {
            "room_type": old_room.room_type if old_room else None,
            "check_in": quote.old_check_in.isoformat(),
            "check_out": quote.old_check_out.isoformat(),
            "number_of_guests": quote.old_number_of_guests,
            "total_price": str(quote.old_total),
        },
        "new": {
            "room_type": new_room.room_type if new_room else None,
            "check_in": quote.new_check_in.isoformat(),
            "check_out": quote.new_check_out.isoformat(),
            "number_of_guests": quote.new_number_of_guests,
            "total_price": str(quote.new_total),
        },
        "difference": str(quote.difference),
        "amount_due": str(quote.amount_due),
        "refund_due": str(quote.refund_due),
        "currency": quote.currency,
    }


def preview_booking_modification(
    db: Session, ctx: ToolContext, args: PreviewModificationArgs
) -> dict[str, Any]:
    """Phase one of modifying a booking: validate + price + issue a token.

    Changes nothing. Eligibility (future check-in, CONFIRMED/PENDING),
    availability and the new total are all enforced by the booking
    service; the returned modification_token is required by phase two.
    """
    _require_hotel(db, args.hotel_id)
    booking = _require_own_booking(db, ctx, args.booking_id)
    today = _hotel_today(db, args.hotel_id)
    quote = booking_service.validate_modification(
        db,
        booking,
        today=today,
        new_room_id=args.new_room_id,
        new_check_in=args.new_check_in,
        new_check_out=args.new_check_out,
        new_number_of_guests=args.new_number_of_guests,
    )
    token, expires_at = booking_service.issue_modification_token(quote)
    summary = _modification_summary(db, quote)
    summary.update(
        {
            "modification_token": token,
            "expires_at": expires_at.isoformat(),
            "message": (
                "Modification preview only — nothing has been changed yet. "
                "Present the old vs new summary to the guest and ask 'Would "
                "you like me to apply this change?'. Only call modify_booking "
                "with this modification_token after the guest explicitly "
                "confirms."
            ),
        }
    )
    return summary


class ModifyBookingArgs(BaseModel):
    hotel_id: int
    booking_id: int
    modification_token: str = Field(
        description=(
            "Token returned by preview_booking_modification. The guest must have "
            "explicitly confirmed the previewed change before you pass it here."
        )
    )


def modify_booking(db: Session, ctx: ToolContext, args: ModifyBookingArgs) -> dict[str, Any]:
    """Phase two: apply a previewed modification. Requires a valid token.

    Availability, eligibility and pricing are re-validated at apply time
    by the booking service; calling this without a token from
    preview_booking_modification fails safely and changes nothing.
    """
    _require_hotel(db, args.hotel_id)
    booking = _require_own_booking(db, ctx, args.booking_id)
    today = _hotel_today(db, args.hotel_id)
    booking, quote = booking_service.modify_booking(
        db,
        booking.id,
        modification_token=args.modification_token,
        today=today,
        actor_type=ctx.actor_type,
        actor_id=ctx.guest_id,
    )
    db.commit()
    summary = _modification_summary(db, quote)
    summary["booking_status"] = booking.booking_status
    return summary


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
        name="get_my_bookings",
        description=(
            "List the identified guest's current and upcoming bookings for "
            "this hotel, each flagged with whether it can still be modified "
            "(modifiable) and why not (ineligible_reason). Use this first "
            "when a guest wants to change or review their booking."
        ),
        args_model=GetMyBookingsArgs,
        handler=get_my_bookings,
        read_only=True,
    ),
    ToolSpec(
        name="preview_booking_modification",
        description=(
            "Phase one of modifying a booking: validate the requested "
            "change (new room type and/or new check-in/check-out dates "
            "and/or guest count) against eligibility, availability and "
            "configured rates, and return an old-vs-new summary plus a "
            "modification_token. Changes nothing. Only future CONFIRMED or "
            "PENDING bookings can be modified. Present the summary and ask "
            "'Would you like me to apply this change?' before phase two."
        ),
        args_model=PreviewModificationArgs,
        handler=preview_booking_modification,
        read_only=True,
    ),
    ToolSpec(
        name="modify_booking",
        description=(
            "Phase two of modifying a booking: apply a change previewed by "
            "preview_booking_modification. REQUIRES the modification_token "
            "from that preview; the guest must have explicitly confirmed "
            "the previewed old-vs-new summary. Eligibility, availability "
            "and pricing are re-validated at apply time."
        ),
        args_model=ModifyBookingArgs,
        handler=modify_booking,
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
