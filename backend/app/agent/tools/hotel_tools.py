"""Read-only hotel information tools (Phase 2/3 of the agent layer)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agent.query_terms import expand_query
from app.agent.tools.registry import ToolContext, ToolSpec
from app.models.faq import FAQ
from app.models.hotel import Hotel
from app.models.offer import Offer
from app.models.policy import Policy
from app.models.room import Room
from app.models.service import Service
from app.services.booking_service import check_availability, quote_booking_price


def _require_hotel(db: Session, hotel_id: int) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise ValueError(f"Hotel {hotel_id} not found")
    return hotel


# --------------------------------------------------------------------- #
# list_rooms                                                             #
# --------------------------------------------------------------------- #
class ListRoomsArgs(BaseModel):
    hotel_id: int = Field(description="Hotel to list room types for")


def list_rooms(db: Session, ctx: ToolContext, args: ListRoomsArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    rooms = db.scalars(
        select(Room)
        .where(Room.hotel_id == args.hotel_id, Room.is_active.is_(True))
        .order_by(Room.id)
    ).all()
    return {
        "rooms": [
            {
                "room_id": r.id,
                "room_type": r.room_type,
                "description": r.description,
                "capacity": r.capacity,
                "total_rooms": r.total_rooms,
                "amenities": r.amenities,
            }
            for r in rooms
        ]
    }


# --------------------------------------------------------------------- #
# check_room_availability                                                #
# --------------------------------------------------------------------- #
class CheckAvailabilityArgs(BaseModel):
    hotel_id: int
    check_in: date
    check_out: date
    room_id: int | None = Field(default=None, description="Specific room type id")
    room_type: str | None = Field(default=None, description="Room type name, e.g. 'Deluxe'")


def _resolve_room(db: Session, hotel_id: int, room_id: int | None, room_type: str | None) -> Room:
    if room_id is not None:
        room = db.get(Room, room_id)
        if room is None or room.hotel_id != hotel_id:
            raise ValueError("Room not found for this hotel")
        return room
    if room_type:
        room = db.scalar(
            select(Room).where(
                Room.hotel_id == hotel_id,
                func.lower(Room.room_type) == room_type.lower(),
                Room.is_active.is_(True),
            )
        )
        if room is None:
            raise ValueError(f"No room type '{room_type}' at this hotel")
        return room
    raise ValueError("Provide room_id or room_type")


def check_room_availability(
    db: Session, ctx: ToolContext, args: CheckAvailabilityArgs
) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    room = _resolve_room(db, args.hotel_id, args.room_id, args.room_type)
    nights = check_availability(db, room.id, args.check_in, args.check_out)
    return {
        "room_id": room.id,
        "room_type": room.room_type,
        "check_in": args.check_in,
        "check_out": args.check_out,
        "nights": [
            {
                "date": n.date,
                "capacity": n.capacity,
                "booked": n.booked,
                "available": n.available,
            }
            for n in nights
        ],
        "fully_available": all(n.available > 0 for n in nights),
    }


# --------------------------------------------------------------------- #
# get_room_details                                                       #
# --------------------------------------------------------------------- #
class RoomDetailsArgs(BaseModel):
    hotel_id: int
    room_id: int


def get_room_details(db: Session, ctx: ToolContext, args: RoomDetailsArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    room = db.get(Room, args.room_id)
    if room is None or room.hotel_id != args.hotel_id:
        raise ValueError("Room not found for this hotel")
    return {
        "room_id": room.id,
        "room_type": room.room_type,
        "description": room.description,
        "capacity": room.capacity,
        "total_rooms": room.total_rooms,
        "amenities": room.amenities,
        "is_active": room.is_active,
    }


# --------------------------------------------------------------------- #
# get_room_rate                                                          #
# --------------------------------------------------------------------- #
class RoomRateArgs(BaseModel):
    hotel_id: int
    check_in: date
    check_out: date
    room_id: int | None = None
    room_type: str | None = None


def get_room_rate(db: Session, ctx: ToolContext, args: RoomRateArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    room = _resolve_room(db, args.hotel_id, args.room_id, args.room_type)
    quote = quote_booking_price(db, room.id, args.check_in, args.check_out)
    return {
        "room_id": room.id,
        "room_type": room.room_type,
        "check_in": args.check_in,
        "check_out": args.check_out,
        "currency": quote.currency,
        "nights": [{"date": n.date, "price": n.price} for n in quote.nights],
        "total": quote.total,
        "missing_dates": quote.missing_dates,
        "fully_priced": quote.fully_priced,
    }


# --------------------------------------------------------------------- #
# get_hotel_policy                                                       #
# --------------------------------------------------------------------- #
class HotelPolicyArgs(BaseModel):
    hotel_id: int
    policy_type: str = Field(
        description="Policy type, e.g. check_in, check_out, cancellation, general"
    )


def get_hotel_policy(db: Session, ctx: ToolContext, args: HotelPolicyArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    policies = db.scalars(
        select(Policy).where(
            Policy.hotel_id == args.hotel_id,
            func.lower(Policy.policy_type) == args.policy_type.lower(),
            Policy.is_active.is_(True),
        )
    ).all()
    if not policies:
        # Fall back to any active policy whose type contains the query.
        policies = db.scalars(
            select(Policy).where(
                Policy.hotel_id == args.hotel_id,
                func.lower(Policy.policy_type).contains(args.policy_type.lower()),
                Policy.is_active.is_(True),
            )
        ).all()
    return {
        "policy_type": args.policy_type,
        "policies": [{"title": p.title, "description": p.description} for p in policies],
    }


# --------------------------------------------------------------------- #
# search_faq                                                             #
# --------------------------------------------------------------------- #
class SearchFaqArgs(BaseModel):
    hotel_id: int
    query: str = Field(description="Guest question / keywords")
    limit: int = Field(default=3, ge=1, le=10)


def search_faq(db: Session, ctx: ToolContext, args: SearchFaqArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    # FAQ text is English; expand Hindi/Hinglish facility terms to their
    # canonical English keywords first (Sweep fix D) so a Hindi question
    # retrieves the same entries its English translation would.
    expanded = expand_query(args.query)
    words = list(
        dict.fromkeys(w for w in expanded.lower().split() if len(w) > 2)
    )[:10]
    stmt = select(FAQ).where(FAQ.hotel_id == args.hotel_id, FAQ.is_active.is_(True))
    if words:
        conditions = [
            or_(
                func.lower(FAQ.question).contains(w),
                func.lower(FAQ.answer).contains(w),
            )
            for w in words
        ]
        stmt = stmt.where(or_(*conditions))
    faqs = db.scalars(stmt.limit(args.limit)).all()
    return {
        "query": args.query,
        "results": [
            {"question": f.question, "answer": f.answer, "category": f.category} for f in faqs
        ],
    }


# --------------------------------------------------------------------- #
# get_services / get_offers                                              #
# --------------------------------------------------------------------- #
class HotelOnlyArgs(BaseModel):
    hotel_id: int


def get_services(db: Session, ctx: ToolContext, args: HotelOnlyArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    services = db.scalars(
        select(Service).where(Service.hotel_id == args.hotel_id, Service.is_active.is_(True))
    ).all()
    return {
        "services": [
            {
                "service_id": s.id,
                "name": s.name,
                "description": s.description,
                "price": s.price,
                "category": s.category,
            }
            for s in services
        ]
    }


class GetOffersArgs(BaseModel):
    hotel_id: int
    on_date: date | None = Field(
        default=None, description="Only offers valid on this date (default today)"
    )


def get_offers(db: Session, ctx: ToolContext, args: GetOffersArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    from datetime import date as _date

    on_date = args.on_date or _date.today()
    offers = db.scalars(
        select(Offer).where(
            Offer.hotel_id == args.hotel_id,
            Offer.is_active.is_(True),
            Offer.valid_from <= on_date,
            Offer.valid_until >= on_date,
        )
    ).all()
    return {
        "on_date": on_date,
        "offers": [
            {
                "offer_id": o.id,
                "name": o.name,
                "description": o.description,
                "discount_type": o.discount_type,
                "discount_value": o.discount_value,
                "valid_from": o.valid_from,
                "valid_until": o.valid_until,
            }
            for o in offers
        ],
    }


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_rooms",
        description="List the hotel's room types with capacity and amenities.",
        args_model=ListRoomsArgs,
        handler=list_rooms,
        read_only=True,
    ),
    ToolSpec(
        name="check_room_availability",
        description=(
            "Check per-night room availability for a room type over a date range. "
            "Use before quoting or booking."
        ),
        args_model=CheckAvailabilityArgs,
        handler=check_room_availability,
        read_only=True,
    ),
    ToolSpec(
        name="get_room_details",
        description="Get details of a specific room type.",
        args_model=RoomDetailsArgs,
        handler=get_room_details,
        read_only=True,
    ),
    ToolSpec(
        name="get_room_rate",
        description=(
            "Get the deterministic price quote for a room type over a date range. "
            "Prices come from configured rates — never invent them."
        ),
        args_model=RoomRateArgs,
        handler=get_room_rate,
        read_only=True,
    ),
    ToolSpec(
        name="get_hotel_policy",
        description="Look up hotel policies (check_in, check_out, cancellation, ...).",
        args_model=HotelPolicyArgs,
        handler=get_hotel_policy,
        read_only=True,
    ),
    ToolSpec(
        name="search_faq",
        description="Search the hotel's FAQs for a guest question.",
        args_model=SearchFaqArgs,
        handler=search_faq,
        read_only=True,
    ),
    ToolSpec(
        name="get_services",
        description="List hotel services (housekeeping, transport, ...).",
        args_model=HotelOnlyArgs,
        handler=get_services,
        read_only=True,
    ),
    ToolSpec(
        name="get_offers",
        description="List currently valid hotel offers and discounts.",
        args_model=GetOffersArgs,
        handler=get_offers,
        read_only=True,
    ),
]

__all__ = ["SPECS"]
