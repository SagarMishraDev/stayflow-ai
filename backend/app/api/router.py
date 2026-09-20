from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.faq import FAQ
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.menu_item import MenuItem
from app.models.negotiation_rule import NegotiationRule
from app.models.offer import Offer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.policy import Policy
from app.models.rate import Rate
from app.models.room import Room
from app.models.service import Service
from app.schemas.availability import (
    AvailabilityCreate,
    AvailabilityResponse,
    AvailabilityUpdate,
)
from app.schemas.booking import BookingCreate, BookingResponse, BookingUpdate
from app.schemas.faq import FAQCreate, FAQResponse, FAQUpdate
from app.schemas.guest import GuestCreate, GuestResponse, GuestUpdate
from app.schemas.health import HealthResponse
from app.schemas.hotel import HotelCreate, HotelResponse, HotelUpdate
from app.schemas.menu_item import MenuItemCreate, MenuItemResponse, MenuItemUpdate
from app.schemas.negotiation_rule import (
    NegotiationRuleCreate,
    NegotiationRuleResponse,
    NegotiationRuleUpdate,
)
from app.schemas.offer import OfferCreate, OfferResponse, OfferUpdate
from app.schemas.order import OrderCreate, OrderResponse, OrderUpdate
from app.schemas.order_item import OrderItemCreate, OrderItemResponse, OrderItemUpdate
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.schemas.rate import RateCreate, RateResponse, RateUpdate
from app.schemas.room import RoomCreate, RoomResponse, RoomUpdate
from app.schemas.service import ServiceCreate, ServiceResponse, ServiceUpdate

router = APIRouter()
settings = get_settings()


def _get_or_404(db: Session, model, object_id: int, detail: str):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def _apply_update(obj, data: dict) -> None:
    for field, value in data.items():
        setattr(obj, field, value)


def _validate_date_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise HTTPException(
            status_code=422,
            detail="check_out must be after check_in",
        )


def _recalculate_order_total(db: Session, order: Order) -> None:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    order.total_amount = sum((item.subtotal for item in items), Decimal("0.00"))


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/db-check", tags=["system"])
def database_check(
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/hotels", response_model=list[HotelResponse], tags=["hotels"])
def get_hotels(
    db: Session = Depends(get_db, scope="function"),
) -> list[HotelResponse]:
    return db.scalars(select(Hotel)).all()


@router.post("/hotels", response_model=HotelResponse, status_code=201, tags=["hotels"])
def create_hotel(
    hotel: HotelCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Hotel:
    new_hotel = Hotel(**hotel.model_dump())
    db.add(new_hotel)
    db.commit()
    db.refresh(new_hotel)
    return new_hotel


@router.get("/hotels/{hotel_id}", response_model=HotelResponse, tags=["hotels"])
def get_hotel(
    hotel_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Hotel:
    return _get_or_404(db, Hotel, hotel_id, "Hotel not found")


@router.patch("/hotels/{hotel_id}", response_model=HotelResponse, tags=["hotels"])
def update_hotel(
    hotel_id: int,
    hotel: HotelUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Hotel:
    existing_hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    _apply_update(existing_hotel, hotel.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing_hotel)
    return existing_hotel


@router.delete("/hotels/{hotel_id}", status_code=204, tags=["hotels"])
def delete_hotel(
    hotel_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    db.delete(hotel)
    db.commit()


@router.post("/rooms", response_model=RoomResponse, status_code=201, tags=["rooms"])
def create_room(
    room: RoomCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Room:
    _get_or_404(db, Hotel, room.hotel_id, "Hotel not found")
    new_room = Room(**room.model_dump())
    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    return new_room


@router.get("/rooms", response_model=list[RoomResponse], tags=["rooms"])
def get_rooms(
    db: Session = Depends(get_db, scope="function"),
) -> list[RoomResponse]:
    return db.scalars(select(Room)).all()


@router.get("/rooms/{room_id}", response_model=RoomResponse, tags=["rooms"])
def get_room(
    room_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Room:
    return _get_or_404(db, Room, room_id, "Room not found")


@router.patch("/rooms/{room_id}", response_model=RoomResponse, tags=["rooms"])
def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Room:
    existing_room = _get_or_404(db, Room, room_id, "Room not found")
    _apply_update(existing_room, room.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing_room)
    return existing_room


@router.delete("/rooms/{room_id}", status_code=204, tags=["rooms"])
def delete_room(
    room_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    room = _get_or_404(db, Room, room_id, "Room not found")
    db.delete(room)
    db.commit()


@router.post("/rates", response_model=RateResponse, status_code=201, tags=["rates"])
def create_rate(
    rate: RateCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Rate:
    _get_or_404(db, Room, rate.room_id, "Room not found")
    new_rate = Rate(**rate.model_dump())
    db.add(new_rate)
    db.commit()
    db.refresh(new_rate)
    return new_rate


@router.get("/rates", response_model=list[RateResponse], tags=["rates"])
def get_rates(
    room_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[RateResponse]:
    stmt = select(Rate)
    if room_id is not None:
        stmt = stmt.where(Rate.room_id == room_id)
    return db.scalars(stmt).all()


@router.get("/rates/{rate_id}", response_model=RateResponse, tags=["rates"])
def get_rate(
    rate_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Rate:
    return _get_or_404(db, Rate, rate_id, "Rate not found")


@router.patch("/rates/{rate_id}", response_model=RateResponse, tags=["rates"])
def update_rate(
    rate_id: int,
    rate: RateUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Rate:
    existing = _get_or_404(db, Rate, rate_id, "Rate not found")
    _apply_update(existing, rate.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/rates/{rate_id}", status_code=204, tags=["rates"])
def delete_rate(
    rate_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    rate = _get_or_404(db, Rate, rate_id, "Rate not found")
    db.delete(rate)
    db.commit()


@router.post(
    "/availability",
    response_model=AvailabilityResponse,
    status_code=201,
    tags=["availability"],
)
def create_availability(
    availability: AvailabilityCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Availability:
    _get_or_404(db, Room, availability.room_id, "Room not found")
    new_availability = Availability(**availability.model_dump())
    db.add(new_availability)
    db.commit()
    db.refresh(new_availability)
    return new_availability


@router.get(
    "/availability",
    response_model=list[AvailabilityResponse],
    tags=["availability"],
)
def get_availability(
    room_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[AvailabilityResponse]:
    stmt = select(Availability)
    if room_id is not None:
        stmt = stmt.where(Availability.room_id == room_id)
    return db.scalars(stmt).all()


@router.get(
    "/availability/{availability_id}",
    response_model=AvailabilityResponse,
    tags=["availability"],
)
def get_availability_item(
    availability_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Availability:
    return _get_or_404(db, Availability, availability_id, "Availability not found")


@router.patch(
    "/availability/{availability_id}",
    response_model=AvailabilityResponse,
    tags=["availability"],
)
def update_availability(
    availability_id: int,
    availability: AvailabilityUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Availability:
    existing = _get_or_404(db, Availability, availability_id, "Availability not found")
    _apply_update(existing, availability.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete(
    "/availability/{availability_id}",
    status_code=204,
    tags=["availability"],
)
def delete_availability(
    availability_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    availability = _get_or_404(db, Availability, availability_id, "Availability not found")
    db.delete(availability)
    db.commit()


def _hotel_exists(db: Session, hotel_id: int) -> None:
    _get_or_404(db, Hotel, hotel_id, "Hotel not found")


@router.post(
    "/policies",
    response_model=PolicyResponse,
    status_code=201,
    tags=["policies"],
)
def create_policy(
    policy: PolicyCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Policy:
    _hotel_exists(db, policy.hotel_id)
    new_policy = Policy(**policy.model_dump())
    db.add(new_policy)
    db.commit()
    db.refresh(new_policy)
    return new_policy


@router.get("/policies", response_model=list[PolicyResponse], tags=["policies"])
def get_policies(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[PolicyResponse]:
    stmt = select(Policy)
    if hotel_id is not None:
        stmt = stmt.where(Policy.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    tags=["policies"],
)
def get_policy(
    policy_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Policy:
    return _get_or_404(db, Policy, policy_id, "Policy not found")


@router.patch(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    tags=["policies"],
)
def update_policy(
    policy_id: int,
    policy: PolicyUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Policy:
    existing = _get_or_404(db, Policy, policy_id, "Policy not found")
    _apply_update(existing, policy.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/policies/{policy_id}", status_code=204, tags=["policies"])
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    policy = _get_or_404(db, Policy, policy_id, "Policy not found")
    db.delete(policy)
    db.commit()


@router.post("/faqs", response_model=FAQResponse, status_code=201, tags=["faqs"])
def create_faq(
    faq: FAQCreate,
    db: Session = Depends(get_db, scope="function"),
) -> FAQ:
    _hotel_exists(db, faq.hotel_id)
    new_faq = FAQ(**faq.model_dump())
    db.add(new_faq)
    db.commit()
    db.refresh(new_faq)
    return new_faq


@router.get("/faqs", response_model=list[FAQResponse], tags=["faqs"])
def get_faqs(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[FAQResponse]:
    stmt = select(FAQ)
    if hotel_id is not None:
        stmt = stmt.where(FAQ.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get("/faqs/{faq_id}", response_model=FAQResponse, tags=["faqs"])
def get_faq(
    faq_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> FAQ:
    return _get_or_404(db, FAQ, faq_id, "FAQ not found")


@router.patch("/faqs/{faq_id}", response_model=FAQResponse, tags=["faqs"])
def update_faq(
    faq_id: int,
    faq: FAQUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> FAQ:
    existing = _get_or_404(db, FAQ, faq_id, "FAQ not found")
    _apply_update(existing, faq.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/faqs/{faq_id}", status_code=204, tags=["faqs"])
def delete_faq(
    faq_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    faq = _get_or_404(db, FAQ, faq_id, "FAQ not found")
    db.delete(faq)
    db.commit()


@router.post(
    "/services",
    response_model=ServiceResponse,
    status_code=201,
    tags=["services"],
)
def create_service(
    service: ServiceCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Service:
    _hotel_exists(db, service.hotel_id)
    new_service = Service(**service.model_dump())
    db.add(new_service)
    db.commit()
    db.refresh(new_service)
    return new_service


@router.get("/services", response_model=list[ServiceResponse], tags=["services"])
def get_services(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[ServiceResponse]:
    stmt = select(Service)
    if hotel_id is not None:
        stmt = stmt.where(Service.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/services/{service_id}",
    response_model=ServiceResponse,
    tags=["services"],
)
def get_service(
    service_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Service:
    return _get_or_404(db, Service, service_id, "Service not found")


@router.patch(
    "/services/{service_id}",
    response_model=ServiceResponse,
    tags=["services"],
)
def update_service(
    service_id: int,
    service: ServiceUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Service:
    existing = _get_or_404(db, Service, service_id, "Service not found")
    _apply_update(existing, service.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/services/{service_id}", status_code=204, tags=["services"])
def delete_service(
    service_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    service = _get_or_404(db, Service, service_id, "Service not found")
    db.delete(service)
    db.commit()


@router.post(
    "/offers",
    response_model=OfferResponse,
    status_code=201,
    tags=["offers"],
)
def create_offer(
    offer: OfferCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Offer:
    _hotel_exists(db, offer.hotel_id)
    if offer.valid_until < offer.valid_from:
        raise HTTPException(
            status_code=422,
            detail="valid_until must be on or after valid_from",
        )
    new_offer = Offer(**offer.model_dump())
    db.add(new_offer)
    db.commit()
    db.refresh(new_offer)
    return new_offer


@router.get("/offers", response_model=list[OfferResponse], tags=["offers"])
def get_offers(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[OfferResponse]:
    stmt = select(Offer)
    if hotel_id is not None:
        stmt = stmt.where(Offer.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/offers/{offer_id}",
    response_model=OfferResponse,
    tags=["offers"],
)
def get_offer(
    offer_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Offer:
    return _get_or_404(db, Offer, offer_id, "Offer not found")


@router.patch(
    "/offers/{offer_id}",
    response_model=OfferResponse,
    tags=["offers"],
)
def update_offer(
    offer_id: int,
    offer: OfferUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Offer:
    existing = _get_or_404(db, Offer, offer_id, "Offer not found")
    update_data = offer.model_dump(exclude_unset=True)
    start = update_data.get("valid_from", existing.valid_from)
    end = update_data.get("valid_until", existing.valid_until)
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="valid_until must be on or after valid_from",
        )
    _apply_update(existing, update_data)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/offers/{offer_id}", status_code=204, tags=["offers"])
def delete_offer(
    offer_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    offer = _get_or_404(db, Offer, offer_id, "Offer not found")
    db.delete(offer)
    db.commit()


@router.post(
    "/negotiation-rules",
    response_model=NegotiationRuleResponse,
    status_code=201,
    tags=["negotiation-rules"],
)
def create_negotiation_rule(
    rule: NegotiationRuleCreate,
    db: Session = Depends(get_db, scope="function"),
) -> NegotiationRule:
    _hotel_exists(db, rule.hotel_id)
    if rule.room_id is not None:
        _get_or_404(db, Room, rule.room_id, "Room not found")
    new_rule = NegotiationRule(**rule.model_dump())
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule


@router.get(
    "/negotiation-rules",
    response_model=list[NegotiationRuleResponse],
    tags=["negotiation-rules"],
)
def get_negotiation_rules(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[NegotiationRuleResponse]:
    stmt = select(NegotiationRule)
    if hotel_id is not None:
        stmt = stmt.where(NegotiationRule.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/negotiation-rules/{rule_id}",
    response_model=NegotiationRuleResponse,
    tags=["negotiation-rules"],
)
def get_negotiation_rule(
    rule_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> NegotiationRule:
    return _get_or_404(db, NegotiationRule, rule_id, "Negotiation rule not found")


@router.patch(
    "/negotiation-rules/{rule_id}",
    response_model=NegotiationRuleResponse,
    tags=["negotiation-rules"],
)
def update_negotiation_rule(
    rule_id: int,
    rule: NegotiationRuleUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> NegotiationRule:
    existing = _get_or_404(db, NegotiationRule, rule_id, "Negotiation rule not found")
    update_data = rule.model_dump(exclude_unset=True)
    if update_data.get("room_id") is not None:
        _get_or_404(db, Room, update_data["room_id"], "Room not found")
    _apply_update(existing, update_data)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete(
    "/negotiation-rules/{rule_id}",
    status_code=204,
    tags=["negotiation-rules"],
)
def delete_negotiation_rule(
    rule_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    rule = _get_or_404(db, NegotiationRule, rule_id, "Negotiation rule not found")
    db.delete(rule)
    db.commit()


@router.post("/guests", response_model=GuestResponse, status_code=201, tags=["guests"])
def create_guest(
    guest: GuestCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Guest:
    _hotel_exists(db, guest.hotel_id)
    new_guest = Guest(**guest.model_dump())
    db.add(new_guest)
    db.commit()
    db.refresh(new_guest)
    return new_guest


@router.get("/guests", response_model=list[GuestResponse], tags=["guests"])
def get_guests(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[GuestResponse]:
    stmt = select(Guest)
    if hotel_id is not None:
        stmt = stmt.where(Guest.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get("/guests/{guest_id}", response_model=GuestResponse, tags=["guests"])
def get_guest(
    guest_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Guest:
    return _get_or_404(db, Guest, guest_id, "Guest not found")


@router.patch("/guests/{guest_id}", response_model=GuestResponse, tags=["guests"])
def update_guest(
    guest_id: int,
    guest: GuestUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Guest:
    existing = _get_or_404(db, Guest, guest_id, "Guest not found")
    _apply_update(existing, guest.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/guests/{guest_id}", status_code=204, tags=["guests"])
def delete_guest(
    guest_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    guest = _get_or_404(db, Guest, guest_id, "Guest not found")
    db.delete(guest)
    db.commit()


@router.post(
    "/bookings",
    response_model=BookingResponse,
    status_code=201,
    tags=["bookings"],
)
def create_booking(
    booking: BookingCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Booking:
    _hotel_exists(db, booking.hotel_id)
    guest = _get_or_404(db, Guest, booking.guest_id, "Guest not found")
    room = _get_or_404(db, Room, booking.room_id, "Room not found")
    _validate_date_range(booking.check_in, booking.check_out)

    if guest.hotel_id != booking.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Guest does not belong to this hotel",
        )
    if room.hotel_id != booking.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Room does not belong to this hotel",
        )
    if booking.number_of_guests > room.capacity:
        raise HTTPException(
            status_code=422,
            detail="Number of guests exceeds room capacity",
        )

    new_booking = Booking(**booking.model_dump())
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    return new_booking


@router.get(
    "/bookings",
    response_model=list[BookingResponse],
    tags=["bookings"],
)
def get_bookings(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[BookingResponse]:
    stmt = select(Booking)
    if hotel_id is not None:
        stmt = stmt.where(Booking.hotel_id == hotel_id)
    if guest_id is not None:
        stmt = stmt.where(Booking.guest_id == guest_id)
    return db.scalars(stmt).all()


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    tags=["bookings"],
)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Booking:
    return _get_or_404(db, Booking, booking_id, "Booking not found")


@router.patch(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    tags=["bookings"],
)
def update_booking(
    booking_id: int,
    booking: BookingUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Booking:
    existing = _get_or_404(db, Booking, booking_id, "Booking not found")
    update_data = booking.model_dump(exclude_unset=True)
    start = update_data.get("check_in", existing.check_in)
    end = update_data.get("check_out", existing.check_out)
    _validate_date_range(start, end)

    room = _get_or_404(db, Room, existing.room_id, "Room not found")
    guests = update_data.get("number_of_guests", existing.number_of_guests)
    if guests > room.capacity:
        raise HTTPException(
            status_code=422,
            detail="Number of guests exceeds room capacity",
        )

    _apply_update(existing, update_data)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/bookings/{booking_id}", status_code=204, tags=["bookings"])
def delete_booking(
    booking_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    booking = _get_or_404(db, Booking, booking_id, "Booking not found")
    db.delete(booking)
    db.commit()


@router.post(
    "/menu-items",
    response_model=MenuItemResponse,
    status_code=201,
    tags=["menu-items"],
)
def create_menu_item(
    menu_item: MenuItemCreate,
    db: Session = Depends(get_db, scope="function"),
) -> MenuItem:
    _hotel_exists(db, menu_item.hotel_id)
    new_item = MenuItem(**menu_item.model_dump())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.get(
    "/menu-items",
    response_model=list[MenuItemResponse],
    tags=["menu-items"],
)
def get_menu_items(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[MenuItemResponse]:
    stmt = select(MenuItem)
    if hotel_id is not None:
        stmt = stmt.where(MenuItem.hotel_id == hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
    tags=["menu-items"],
)
def get_menu_item(
    menu_item_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> MenuItem:
    return _get_or_404(db, MenuItem, menu_item_id, "Menu item not found")


@router.patch(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
    tags=["menu-items"],
)
def update_menu_item(
    menu_item_id: int,
    menu_item: MenuItemUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> MenuItem:
    existing = _get_or_404(db, MenuItem, menu_item_id, "Menu item not found")
    _apply_update(existing, menu_item.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete(
    "/menu-items/{menu_item_id}",
    status_code=204,
    tags=["menu-items"],
)
def delete_menu_item(
    menu_item_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    item = _get_or_404(db, MenuItem, menu_item_id, "Menu item not found")
    db.delete(item)
    db.commit()


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=201,
    tags=["orders"],
)
def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db, scope="function"),
) -> Order:
    _hotel_exists(db, order.hotel_id)
    guest = _get_or_404(db, Guest, order.guest_id, "Guest not found")

    if guest.hotel_id != order.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Guest does not belong to this hotel",
        )

    new_order = Order(**order.model_dump())
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return new_order


@router.get("/orders", response_model=list[OrderResponse], tags=["orders"])
def get_orders(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[OrderResponse]:
    stmt = select(Order)
    if hotel_id is not None:
        stmt = stmt.where(Order.hotel_id == hotel_id)
    if guest_id is not None:
        stmt = stmt.where(Order.guest_id == guest_id)
    return db.scalars(stmt).all()


@router.get("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def get_order(
    order_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> Order:
    return _get_or_404(db, Order, order_id, "Order not found")


@router.patch("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def update_order(
    order_id: int,
    order: OrderUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> Order:
    existing = _get_or_404(db, Order, order_id, "Order not found")
    _apply_update(existing, order.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/orders/{order_id}", status_code=204, tags=["orders"])
def delete_order(
    order_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    order = _get_or_404(db, Order, order_id, "Order not found")
    db.delete(order)
    db.commit()


@router.post(
    "/order-items",
    response_model=OrderItemResponse,
    status_code=201,
    tags=["order-items"],
)
def create_order_item(
    item: OrderItemCreate,
    db: Session = Depends(get_db, scope="function"),
) -> OrderItem:
    order = _get_or_404(db, Order, item.order_id, "Order not found")
    menu_item = _get_or_404(db, MenuItem, item.menu_item_id, "Menu item not found")

    if not menu_item.is_active or not menu_item.is_available:
        raise HTTPException(
            status_code=422,
            detail="Menu item is not currently available",
        )
    if menu_item.hotel_id != order.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Menu item does not belong to this hotel",
        )

    subtotal = menu_item.price * item.quantity
    new_item = OrderItem(
        order_id=item.order_id,
        menu_item_id=item.menu_item_id,
        quantity=item.quantity,
        unit_price=menu_item.price,
        customization=item.customization,
        subtotal=subtotal,
    )
    db.add(new_item)
    db.flush()
    _recalculate_order_total(db, order)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.get(
    "/order-items",
    response_model=list[OrderItemResponse],
    tags=["order-items"],
)
def get_order_items(
    order_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
) -> list[OrderItemResponse]:
    stmt = select(OrderItem)
    if order_id is not None:
        stmt = stmt.where(OrderItem.order_id == order_id)
    return db.scalars(stmt).all()


@router.get(
    "/order-items/{order_item_id}",
    response_model=OrderItemResponse,
    tags=["order-items"],
)
def get_order_item(
    order_item_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> OrderItem:
    return _get_or_404(db, OrderItem, order_item_id, "Order item not found")


@router.patch(
    "/order-items/{order_item_id}",
    response_model=OrderItemResponse,
    tags=["order-items"],
)
def update_order_item(
    order_item_id: int,
    item: OrderItemUpdate,
    db: Session = Depends(get_db, scope="function"),
) -> OrderItem:
    existing = _get_or_404(db, OrderItem, order_item_id, "Order item not found")
    order = _get_or_404(db, Order, existing.order_id, "Order not found")

    update_data = item.model_dump(exclude_unset=True)
    menu_item_id = update_data.get("menu_item_id", existing.menu_item_id)
    menu_item = _get_or_404(db, MenuItem, menu_item_id, "Menu item not found")

    if not menu_item.is_active or not menu_item.is_available:
        raise HTTPException(
            status_code=422,
            detail="Menu item is not currently available",
        )
    if menu_item.hotel_id != order.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Menu item does not belong to this hotel",
        )

    quantity = update_data.get("quantity", existing.quantity)
    existing.menu_item_id = menu_item.id
    existing.quantity = quantity
    existing.unit_price = menu_item.price
    if "customization" in update_data:
        existing.customization = update_data["customization"]
    existing.subtotal = menu_item.price * quantity

    db.flush()
    _recalculate_order_total(db, order)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete(
    "/order-items/{order_item_id}",
    status_code=204,
    tags=["order-items"],
)
def delete_order_item(
    order_item_id: int,
    db: Session = Depends(get_db, scope="function"),
) -> None:
    item = _get_or_404(db, OrderItem, order_item_id, "Order item not found")
    order = _get_or_404(db, Order, item.order_id, "Order not found")
    db.delete(item)
    db.flush()
    _recalculate_order_total(db, order)
    db.commit()
