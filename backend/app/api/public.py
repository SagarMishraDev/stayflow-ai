"""Public widget API (Master Prompt §11).

These routes power the embeddable website chat widget. They are
intentionally PUBLIC (guests have no staff JWT) and follow strict rules:

- Hotels are resolved ONLY by their non-sequential ``public_id``. The
  internal integer id is never accepted and never returned.
- No staff tokens, secrets, or internal fields are exposed — responses
  use dedicated public schemas.
- Chat runs through the same agent runner as every other channel
  (``channel="widget"``); booking/order mutations keep the deterministic
  confirmation gate inside the agent tools.
- Every chat request is rate-limited per hotel + client IP.
- Data stays hotel-isolated: a conversation id minted for one hotel is
  rejected when presented under another hotel's public_id (the runner
  raises, mapped to 422).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.config import AgentConfig
from app.agent.runner import run_chat
from app.core.config import get_settings
from app.core.rate_limit import rate_limit_public_chat, rate_limit_public_read
from app.db.session import get_db
from app.models.faq import FAQ
from app.models.hotel import Hotel
from app.models.menu_item import MenuItem
from app.models.offer import Offer
from app.models.policy import Policy
from app.models.rate import Rate
from app.models.room import Room
from app.models.service import Service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["public-widget"])


class PublicHotelInfo(BaseModel):
    """The only hotel fields a guest/widget may ever see."""

    hotel_id: str  # the public_id — never the internal integer id
    name: str
    city: str
    description: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    currency: str


class WidgetConfig(PublicHotelInfo):
    welcome_message: str
    widget_title: str


class PublicChatRequest(BaseModel):
    hotel_public_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    # Session continuity: the conversation_id returned by the previous
    # response, as a string. Omit (or send an unknown value) to start a
    # fresh conversation.
    session_id: str | None = None


class PublicChatResponse(BaseModel):
    reply: str
    conversation_id: int
    session_id: str
    hotel_id: str  # the public_id
    status: str = "ok"
    degraded: bool = False


def get_hotel_by_public_id(db: Session, public_id: str) -> Hotel:
    """Resolve a hotel by public_id only; 404 for unknown/inactive ids.

    A purely numeric value that happens to equal an internal integer id
    does NOT resolve a hotel unless it is literally the hotel's public_id
    (public ids are 32-char hex tokens), so internal ids cannot be used
    to enumerate or address hotels through the public API.
    """
    hotel = db.scalars(select(Hotel).where(Hotel.public_id == public_id)).first()
    if hotel is None or not hotel.is_active:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return hotel


def _hotel_info(hotel: Hotel) -> PublicHotelInfo:
    return PublicHotelInfo(
        hotel_id=hotel.public_id,
        name=hotel.name,
        city=hotel.city,
        description=hotel.description,
        check_in_time=hotel.check_in_time,
        check_out_time=hotel.check_out_time,
        currency=hotel.currency,
    )


@router.get("/public/hotels/{public_id}", response_model=PublicHotelInfo)
def public_hotel_info(
    public_id: str,
    db: Session = Depends(get_db, scope="function"),
) -> PublicHotelInfo:
    return _hotel_info(get_hotel_by_public_id(db, public_id))


@router.get("/public/hotels/{public_id}/widget-config", response_model=WidgetConfig)
def public_widget_config(
    public_id: str,
    db: Session = Depends(get_db, scope="function"),
) -> WidgetConfig:
    hotel = get_hotel_by_public_id(db, public_id)
    info = _hotel_info(hotel)
    welcome = f"Welcome to {hotel.name}! Ask me about rooms, rates, the menu, or services."
    return WidgetConfig(
        **info.model_dump(),
        welcome_message=welcome,
        widget_title=hotel.name,
    )


@router.post(
    "/public/chat",
    response_model=PublicChatResponse,
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
def public_chat(
    payload: PublicChatRequest,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_public_chat),
) -> PublicChatResponse:
    hotel = get_hotel_by_public_id(db, payload.hotel_public_id)

    conversation_id: int | None = None
    if payload.session_id:
        try:
            conversation_id = int(payload.session_id)
        except ValueError:
            # Unknown/opaque session token: start fresh rather than error.
            conversation_id = None

    try:
        result = run_chat(
            db,
            hotel_id=hotel.id,
            message=payload.message,
            conversation_id=conversation_id,
            channel="widget",
            config=AgentConfig.from_settings(settings),
        )
    except ValueError as exc:
        # Includes "Conversation not found for this hotel" — a session id
        # minted for another hotel is rejected here, enforcing isolation.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Metadata only: never log the guest's message or the reply (PII).
    logger.info(
        "public.chat hotel=%s conversation=%s iterations=%s degraded=%s",
        hotel.id,
        result.conversation_id,
        result.iterations,
        result.degraded,
    )
    return PublicChatResponse(
        reply=result.reply,
        conversation_id=result.conversation_id,
        session_id=str(result.conversation_id),
        hotel_id=hotel.public_id,
        degraded=result.degraded,
    )


# --------------------------------------------------------------------- #
# Public landing page payload                                            #
# --------------------------------------------------------------------- #
class LandingHotel(BaseModel):
    """Public-safe hotel fields for the landing page.

    Deliberately has NO ``id`` field: the internal integer id is never
    exposed; hotels are addressed only by ``public_id``.
    """

    public_id: str
    name: str
    description: str | None = None
    city: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    currency: str
    check_in_time: str | None = None
    check_out_time: str | None = None


class LandingRoom(BaseModel):
    name: str  # the room type, e.g. "Deluxe King"
    room_type: str
    capacity: int
    description: str | None = None
    features: str | None = None  # the room's amenities text, as stored
    nightly_rate: Decimal | None = None  # earliest upcoming real DB rate
    currency: str


class LandingOffer(BaseModel):
    name: str
    description: str | None = None
    discount_type: str
    discount_value: Decimal
    valid_from: date
    valid_until: date


class LandingService(BaseModel):
    name: str
    description: str | None = None
    price: Decimal | None = None
    category: str | None = None


class LandingFaq(BaseModel):
    question: str
    answer: str
    category: str | None = None


class LandingPolicy(BaseModel):
    policy_type: str
    title: str
    description: str


class LandingMenuItem(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    price: Decimal


class LandingPayload(BaseModel):
    hotel: LandingHotel
    rooms: list[LandingRoom]
    offers: list[LandingOffer]
    services: list[LandingService]
    faqs: list[LandingFaq]
    policies: list[LandingPolicy]
    menu_highlights: list[LandingMenuItem]


def _build_landing_payload(db: Session, hotel: Hotel) -> LandingPayload:
    """Aggregate one hotel's public content. Every query is hotel-scoped;
    prices come only from stored Rate rows (earliest upcoming rate per
    room) — nothing is invented or defaulted."""
    today = date.today()

    rooms: list[LandingRoom] = []
    room_rows = db.scalars(
        select(Room).where(Room.hotel_id == hotel.id, Room.is_active.is_(True)).order_by(Room.id)
    ).all()
    for room in room_rows:
        rate = db.scalars(
            select(Rate)
            .where(
                Rate.room_id == room.id,
                Rate.is_active.is_(True),
                Rate.date >= today,
            )
            .order_by(Rate.date)
        ).first()
        rooms.append(
            LandingRoom(
                name=room.room_type,
                room_type=room.room_type,
                capacity=room.capacity,
                description=room.description,
                features=room.amenities,
                nightly_rate=rate.price if rate else None,
                currency=rate.currency if rate else hotel.currency,
            )
        )

    offers = db.scalars(
        select(Offer)
        .where(
            Offer.hotel_id == hotel.id,
            Offer.is_active.is_(True),
            Offer.valid_from <= today,
            Offer.valid_until >= today,
        )
        .order_by(Offer.id)
    ).all()
    services = db.scalars(
        select(Service)
        .where(Service.hotel_id == hotel.id, Service.is_active.is_(True))
        .order_by(Service.id)
    ).all()
    faqs = db.scalars(
        select(FAQ).where(FAQ.hotel_id == hotel.id, FAQ.is_active.is_(True)).order_by(FAQ.id)
    ).all()
    policies = db.scalars(
        select(Policy)
        .where(Policy.hotel_id == hotel.id, Policy.is_active.is_(True))
        .order_by(Policy.id)
    ).all()
    menu_items = db.scalars(
        select(MenuItem)
        .where(
            MenuItem.hotel_id == hotel.id,
            MenuItem.is_active.is_(True),
            MenuItem.is_available.is_(True),
        )
        .order_by(MenuItem.id)
    ).all()

    return LandingPayload(
        hotel=LandingHotel(
            public_id=hotel.public_id,
            name=hotel.name,
            description=hotel.description,
            city=hotel.city,
            address=hotel.address,
            phone=hotel.phone,
            email=hotel.email,
            currency=hotel.currency,
            check_in_time=hotel.check_in_time,
            check_out_time=hotel.check_out_time,
        ),
        rooms=rooms,
        offers=[
            LandingOffer(
                name=o.name,
                description=o.description,
                discount_type=o.discount_type,
                discount_value=o.discount_value,
                valid_from=o.valid_from,
                valid_until=o.valid_until,
            )
            for o in offers
        ],
        services=[
            LandingService(
                name=s.name,
                description=s.description,
                price=s.price,
                category=s.category,
            )
            for s in services
        ],
        faqs=[LandingFaq(question=f.question, answer=f.answer, category=f.category) for f in faqs],
        policies=[
            LandingPolicy(policy_type=p.policy_type, title=p.title, description=p.description)
            for p in policies
        ],
        menu_highlights=[
            LandingMenuItem(
                name=m.name, description=m.description, category=m.category, price=m.price
            )
            for m in menu_items
        ],
    )


@router.get(
    "/public/hotels/{public_id}/landing",
    response_model=LandingPayload,
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
def public_landing(
    public_id: str,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_public_read),
) -> LandingPayload:
    return _build_landing_payload(db, get_hotel_by_public_id(db, public_id))


@router.get(
    "/public/featured-hotel/landing",
    response_model=LandingPayload,
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
def public_featured_landing(
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_public_read),
) -> LandingPayload:
    """Landing payload for the first active hotel.

    Single-property / demo convenience: a deployment hosting exactly one
    hotel can point its domain root at ``/`` without a ``?hotel=`` param.
    Multi-hotel deployments should use
    ``/public/hotels/{public_id}/landing`` (or ``/?hotel=<public_id>``).
    """
    hotel = db.scalars(select(Hotel).where(Hotel.is_active.is_(True)).order_by(Hotel.id)).first()
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return _build_landing_payload(db, hotel)
