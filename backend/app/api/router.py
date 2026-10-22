import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.runner import run_chat
from app.agent.schemas import ChatRequest, ChatResponse, ToolTraceResponse
from app.core.config import get_settings
from app.core.rate_limit import rate_limit_chat, rate_limit_login
from app.core.roles import HOTEL_ADMIN, SUPER_ADMIN, is_super_admin, normalize_role
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.conversation import Conversation
from app.models.faq import FAQ
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.hotel_room import HotelRoom
from app.models.hotel_user import HotelUser
from app.models.menu_item import MenuItem
from app.models.message import Message
from app.models.negotiation_rule import NegotiationRule
from app.models.notification import Notification
from app.models.offer import Offer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.policy import Policy
from app.models.rate import Rate
from app.models.room import Room
from app.models.service import Service
from app.models.service_request import ServiceRequest
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.availability import (
    AvailabilityCreate,
    AvailabilityResponse,
    AvailabilityUpdate,
)
from app.schemas.booking import (
    BookingCreate,
    BookingQuoteRequest,
    BookingQuoteResponse,
    BookingResponse,
    BookingUpdate,
    NightQuoteResponse,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from app.schemas.faq import FAQCreate, FAQResponse, FAQUpdate
from app.schemas.guest import GuestCreate, GuestResponse, GuestUpdate
from app.schemas.health import HealthResponse
from app.schemas.hotel import HotelCreate, HotelResponse, HotelUpdate
from app.schemas.hotel_room import HotelRoomCreate, HotelRoomResponse, HotelRoomUpdate
from app.schemas.hotel_user import (
    HotelUserCreate,
    HotelUserResponse,
    HotelUserUpdate,
)
from app.schemas.menu_item import MenuItemCreate, MenuItemResponse, MenuItemUpdate
from app.schemas.negotiation import (
    NegotiationEvaluateRequest,
    NegotiationEvaluateResponse,
)
from app.schemas.negotiation_rule import (
    NegotiationRuleCreate,
    NegotiationRuleResponse,
    NegotiationRuleUpdate,
)
from app.schemas.offer import OfferCreate, OfferResponse, OfferUpdate
from app.schemas.ops import AuditLogResponse, NotificationResponse
from app.schemas.order import OrderCreate, OrderResponse, OrderUpdate
from app.schemas.order_item import OrderItemCreate, OrderItemResponse, OrderItemUpdate
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.schemas.rate import RateCreate, RateResponse, RateUpdate
from app.schemas.room import RoomCreate, RoomResponse, RoomUpdate
from app.schemas.service import ServiceCreate, ServiceResponse, ServiceUpdate
from app.schemas.service_request import (
    ServiceRequestCreate,
    ServiceRequestResponse,
    ServiceRequestUpdate,
)
from app.services.audit import log_action, log_super_admin_cross_hotel_access
from app.services.booking_service import (
    BookingError,
    create_booking_record,
    evaluate_price_offer,
    quote_booking_price,
    update_booking_dates_guests,
    validate_status_transition,
)
from app.services.booking_service import (
    cancel_booking as cancel_booking_record,
)
from app.services.booking_service import (
    check_availability as service_check_availability,
)

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)

_CONFLICT_DETAIL = "Database conflict: related records exist or a constraint was violated"


def _get_or_404(db: Session, model, object_id: int, detail: str):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def _apply_update(obj, data: dict) -> None:
    for field, value in data.items():
        setattr(obj, field, value)


def _booking_error_to_http(exc: BookingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _commit_or_409(db: Session, detail: str) -> None:
    """Commit, translating FK violations into 409 Conflict."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from None


def _validate_date_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise HTTPException(
            status_code=422,
            detail="check_out must be after check_in",
        )


def _recalculate_order_total(db: Session, order: Order) -> None:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    order.total_amount = sum((item.subtotal for item in items), Decimal("0.00"))


def _require_tenant(hotel_id: int, current_user: HotelUser) -> None:
    """Raise 403 unless the resource belongs to the caller's hotel.

    Missing objects are reported as 404 by the caller first; this only
    fires when the object exists under a *different* hotel.

    ``SUPER_ADMIN`` bypasses tenant isolation so platform operators can
    inspect any hotel. Every cross-hotel bypass is recorded prominently:
    a ``super_admin.cross_hotel_access`` audit row plus a WARNING log line.
    """
    if is_super_admin(current_user.role):
        if hotel_id != current_user.hotel_id:
            log_super_admin_cross_hotel_access(
                actor_id=current_user.id,
                actor_hotel_id=current_user.hotel_id,
                accessed_hotel_id=hotel_id,
                resource="api",
            )
        return
    if hotel_id != current_user.hotel_id:
        # Denied cross-hotel access: visible in server logs for security
        # monitoring (no audit row — the attempt made no mutation).
        logger.warning(
            "cross-hotel access denied: staff user %s (hotel %s, role %s) "
            "attempted to access hotel %s",
            current_user.id,
            current_user.hotel_id,
            current_user.role,
            hotel_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied: resource belongs to a different hotel",
        )


def _scoped_hotel_id(requested_hotel_id: int | None, current_user: HotelUser) -> int:
    """Resolve the hotel a collection read is scoped to.

    A super admin may pass ``hotel_id`` for any hotel (audited via
    :func:`_require_tenant`); everyone else stays on their own hotel.
    """
    if requested_hotel_id is not None:
        _require_tenant(requested_hotel_id, current_user)
        return requested_hotel_id
    return current_user.hotel_id


def _get_owned(
    db: Session,
    model,
    object_id: int,
    detail: str,
    current_user: HotelUser,
):
    """Load an object by id: 404 when missing, 403 when owned by another hotel."""
    obj = _get_or_404(db, model, object_id, detail)
    _require_tenant(obj.hotel_id, current_user)
    return obj


def _room_hotel_id(db: Session, room_id: int) -> int:
    """Hotel that owns a room (404 when the room does not exist)."""
    room = _get_or_404(db, Room, room_id, "Room not found")
    return room.hotel_id


def _hotel_room_hotel_id(db: Session, hotel_room_id: int) -> int:
    """Hotel that owns a physical hotel room (404 when it does not exist)."""
    hotel_room = _get_or_404(db, HotelRoom, hotel_room_id, "Hotel room not found")
    return hotel_room.hotel_id


def _require_filter_tenant(db: Session, model, object_id: int, current_user: HotelUser) -> None:
    """403 when a collection filter names an object owned by another hotel.

    Missing objects are ignored (the filter then simply matches nothing),
    preserving the previous filter semantics.
    """
    obj = db.get(model, object_id)
    if obj is not None:
        _require_tenant(obj.hotel_id, current_user)


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
    current_user: HotelUser = Depends(get_current_user),
) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


# --------------------------------------------------------------------- #
# Staff authentication (public: issues the JWT used by staff endpoints)  #
# --------------------------------------------------------------------- #
@router.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["auth"],
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
def login(
    credentials: LoginRequest,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_login),
) -> TokenResponse:
    """Authenticate a hotel staff user and return a JWT bearer token."""
    user = db.scalars(
        select(HotelUser).where(HotelUser.email == credentials.email).order_by(HotelUser.id)
    ).first()
    if user is None or not user.is_active:
        # Email only: failed logins are security-relevant, the password is never logged.
        logger.warning("Failed staff login attempt for %s", credentials.email)
        if user is not None:
            log_action(
                db,
                hotel_id=user.hotel_id,
                actor_type="staff",
                actor_id=user.id,
                action="auth.login_failed",
                entity_type="hotel_user",
                entity_id=user.id,
                details={"email": credentials.email},
            )
            _commit_or_409(db, _CONFLICT_DETAIL)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(credentials.password, user.password_hash):
        logger.warning("Failed staff login attempt for %s", credentials.email)
        log_action(
            db,
            hotel_id=user.hotel_id,
            actor_type="staff",
            actor_id=user.id,
            action="auth.login_failed",
            entity_type="hotel_user",
            entity_id=user.id,
            details={"email": credentials.email},
        )
        _commit_or_409(db, _CONFLICT_DETAIL)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    logger.info(
        "Staff login: user %s (hotel %s, role %s)",
        user.id,
        user.hotel_id,
        user.role,
    )
    log_action(
        db,
        hotel_id=user.hotel_id,
        actor_type="staff",
        actor_id=user.id,
        action="auth.login",
        entity_type="hotel_user",
        entity_id=user.id,
        details={"email": user.email, "role": user.role},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    return TokenResponse(
        access_token=create_access_token(
            hotel_user_id=user.id,
            hotel_id=user.hotel_id,
            role=user.role,
        )
    )


@router.get("/hotels", response_model=list[HotelResponse], tags=["hotels"])
def get_hotels(
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[HotelResponse]:
    if is_super_admin(current_user.role):
        return db.scalars(select(Hotel).order_by(Hotel.id)).all()
    return db.scalars(select(Hotel).where(Hotel.id == current_user.hotel_id)).all()


@router.post("/hotels", response_model=HotelResponse, status_code=201, tags=["hotels"])
def create_hotel(
    hotel: HotelCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Hotel:
    new_hotel = Hotel(**hotel.model_dump())
    db.add(new_hotel)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_hotel)
    return new_hotel


@router.get("/hotels/{hotel_id}", response_model=HotelResponse, tags=["hotels"])
def get_hotel(
    hotel_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Hotel:
    hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    _require_tenant(hotel.id, current_user)
    return hotel


@router.patch("/hotels/{hotel_id}", response_model=HotelResponse, tags=["hotels"])
def update_hotel(
    hotel_id: int,
    hotel: HotelUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Hotel:
    existing_hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    _require_tenant(existing_hotel.id, current_user)
    _apply_update(existing_hotel, hotel.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing_hotel)
    return existing_hotel


@router.delete("/hotels/{hotel_id}", status_code=204, tags=["hotels"])
def delete_hotel(
    hotel_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    _require_tenant(hotel.id, current_user)
    db.delete(hotel)
    _commit_or_409(db, _CONFLICT_DETAIL)


# --------------------------------------------------------------------- #
# Hotel staff users (RBAC: management requires HOTEL_ADMIN/SUPER_ADMIN)   #
# --------------------------------------------------------------------- #
_MANAGE_USERS = require_roles(HOTEL_ADMIN, SUPER_ADMIN)


def _validate_role_assignment(role: str | None, current_user: HotelUser) -> str:
    """Validate a staff role string being assigned by ``current_user``.

    Only a super admin may grant the super-admin role; unknown role strings
    are rejected. Returns the role value as provided.
    """
    if role is None:
        raise HTTPException(status_code=422, detail="Role is required")
    if normalize_role(role) is None:
        raise HTTPException(status_code=422, detail=f"Unknown role: {role!r}")
    if normalize_role(role) is SUPER_ADMIN and not is_super_admin(current_user.role):
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can grant the super_admin role",
        )
    return role


@router.post(
    "/hotel-users",
    response_model=HotelUserResponse,
    status_code=201,
    tags=["hotel-users"],
)
def create_hotel_user(
    payload: HotelUserCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_MANAGE_USERS),
) -> HotelUser:
    """Create a staff user. Password is hashed; role assignment is guarded.

    Hotel admins create users for their own hotel. Super admins may pass
    ``hotel_id`` to create a user in another hotel (audited).
    """
    target_hotel_id = current_user.hotel_id
    if payload.hotel_id is not None and payload.hotel_id != current_user.hotel_id:
        if not is_super_admin(current_user.role):
            raise HTTPException(
                status_code=403,
                detail="Only a super admin can create users in another hotel",
            )
        _hotel_exists(db, payload.hotel_id)
        log_super_admin_cross_hotel_access(
            actor_id=current_user.id,
            actor_hotel_id=current_user.hotel_id,
            accessed_hotel_id=payload.hotel_id,
            resource="hotel-users:create",
        )
        target_hotel_id = payload.hotel_id

    role = _validate_role_assignment(payload.role, current_user)
    existing = db.scalars(
        select(HotelUser).where(
            HotelUser.hotel_id == target_hotel_id,
            HotelUser.email == payload.email,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A user with this email already exists for this hotel",
        )
    new_user = HotelUser(
        hotel_id=target_hotel_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        role=role,
        password_hash=hash_password(payload.password),
    )
    db.add(new_user)
    db.flush()
    log_action(
        db,
        hotel_id=target_hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="hotel_user.created",
        entity_type="hotel_user",
        entity_id=new_user.id,
        details={"email": new_user.email, "role": new_user.role},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_user)
    logger.info(
        "hotel_user.created: user %s (hotel %s, role %s) by staff user %s",
        new_user.id,
        new_user.hotel_id,
        new_user.role,
        current_user.id,
    )
    return new_user


@router.get(
    "/hotel-users",
    response_model=list[HotelUserResponse],
    tags=["hotel-users"],
)
def get_hotel_users(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[HotelUserResponse]:
    scoped = _scoped_hotel_id(hotel_id, current_user)
    return db.scalars(select(HotelUser).where(HotelUser.hotel_id == scoped)).all()


@router.get(
    "/hotel-users/{user_id}",
    response_model=HotelUserResponse,
    tags=["hotel-users"],
)
def get_hotel_user(
    user_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelUser:
    return _get_owned(db, HotelUser, user_id, "Hotel user not found", current_user)


@router.patch(
    "/hotel-users/{user_id}",
    response_model=HotelUserResponse,
    tags=["hotel-users"],
)
def update_hotel_user(
    user_id: int,
    payload: HotelUserUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_MANAGE_USERS),
) -> HotelUser:
    existing = _get_owned(db, HotelUser, user_id, "Hotel user not found", current_user)
    update_data = payload.model_dump(exclude_unset=True)
    new_password = update_data.pop("password", None)
    if new_password is not None:
        existing.password_hash = hash_password(new_password)
    if "role" in update_data:
        update_data["role"] = _validate_role_assignment(update_data["role"], current_user)
    deactivated = update_data.get("is_active") is False and existing.is_active
    _apply_update(existing, update_data)
    db.flush()
    log_action(
        db,
        hotel_id=existing.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="hotel_user.deactivated" if deactivated else "hotel_user.updated",
        entity_type="hotel_user",
        entity_id=existing.id,
        details={"changed": sorted(update_data)},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    logger.info(
        "hotel_user.%s: user %s (hotel %s) by staff user %s",
        "deactivated" if deactivated else "updated",
        existing.id,
        existing.hotel_id,
        current_user.id,
    )
    return existing


@router.delete("/hotel-users/{user_id}", status_code=204, tags=["hotel-users"])
def delete_hotel_user(
    user_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_MANAGE_USERS),
) -> None:
    user = _get_owned(db, HotelUser, user_id, "Hotel user not found", current_user)
    log_action(
        db,
        hotel_id=user.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="hotel_user.deleted",
        entity_type="hotel_user",
        entity_id=user.id,
        details={"email": user.email, "role": user.role},
    )
    db.delete(user)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post("/rooms", response_model=RoomResponse, status_code=201, tags=["rooms"])
def create_room(
    room: RoomCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Room:
    _get_or_404(db, Hotel, room.hotel_id, "Hotel not found")
    _require_tenant(room.hotel_id, current_user)
    new_room = Room(**room.model_dump())
    db.add(new_room)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_room)
    return new_room


@router.get("/rooms", response_model=list[RoomResponse], tags=["rooms"])
def get_rooms(
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[RoomResponse]:
    return db.scalars(select(Room).where(Room.hotel_id == current_user.hotel_id)).all()


@router.get("/rooms/{room_id}", response_model=RoomResponse, tags=["rooms"])
def get_room(
    room_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Room:
    return _get_owned(db, Room, room_id, "Room not found", current_user)


@router.patch("/rooms/{room_id}", response_model=RoomResponse, tags=["rooms"])
def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Room:
    existing_room = _get_owned(db, Room, room_id, "Room not found", current_user)
    _apply_update(existing_room, room.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing_room)
    return existing_room


@router.delete("/rooms/{room_id}", status_code=204, tags=["rooms"])
def delete_room(
    room_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    room = _get_owned(db, Room, room_id, "Room not found", current_user)
    db.delete(room)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post("/rates", response_model=RateResponse, status_code=201, tags=["rates"])
def create_rate(
    rate: RateCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Rate:
    room = _get_or_404(db, Room, rate.room_id, "Room not found")
    _require_tenant(room.hotel_id, current_user)
    new_rate = Rate(**rate.model_dump())
    db.add(new_rate)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_rate)
    return new_rate


@router.get("/rates", response_model=list[RateResponse], tags=["rates"])
def get_rates(
    room_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[RateResponse]:
    if room_id is not None:
        _require_tenant(_room_hotel_id(db, room_id), current_user)
        stmt = select(Rate).where(Rate.room_id == room_id)
    else:
        stmt = (
            select(Rate)
            .join(Room, Rate.room_id == Room.id)
            .where(Room.hotel_id == current_user.hotel_id)
        )
    return db.scalars(stmt).all()


@router.get("/rates/{rate_id}", response_model=RateResponse, tags=["rates"])
def get_rate(
    rate_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Rate:
    rate = _get_or_404(db, Rate, rate_id, "Rate not found")
    _require_tenant(_room_hotel_id(db, rate.room_id), current_user)
    return rate


@router.patch("/rates/{rate_id}", response_model=RateResponse, tags=["rates"])
def update_rate(
    rate_id: int,
    rate: RateUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Rate:
    existing = _get_or_404(db, Rate, rate_id, "Rate not found")
    _require_tenant(_room_hotel_id(db, existing.room_id), current_user)
    _apply_update(existing, rate.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/rates/{rate_id}", status_code=204, tags=["rates"])
def delete_rate(
    rate_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    rate = _get_or_404(db, Rate, rate_id, "Rate not found")
    _require_tenant(_room_hotel_id(db, rate.room_id), current_user)
    db.delete(rate)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/availability",
    response_model=AvailabilityResponse,
    status_code=201,
    tags=["availability"],
)
def create_availability(
    availability: AvailabilityCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Availability:
    room = _get_or_404(db, Room, availability.room_id, "Room not found")
    _require_tenant(room.hotel_id, current_user)
    if availability.available_rooms > room.total_rooms:
        raise HTTPException(
            status_code=422,
            detail=(
                f"available_rooms ({availability.available_rooms}) cannot exceed "
                f"the room's total inventory ({room.total_rooms})"
            ),
        )
    new_availability = Availability(**availability.model_dump())
    db.add(new_availability)
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> list[AvailabilityResponse]:
    if room_id is not None:
        _require_tenant(_room_hotel_id(db, room_id), current_user)
        stmt = select(Availability).where(Availability.room_id == room_id)
    else:
        stmt = (
            select(Availability)
            .join(Room, Availability.room_id == Room.id)
            .where(Room.hotel_id == current_user.hotel_id)
        )
    return db.scalars(stmt).all()


@router.get(
    "/availability/{availability_id}",
    response_model=AvailabilityResponse,
    tags=["availability"],
)
def get_availability_item(
    availability_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Availability:
    availability = _get_or_404(db, Availability, availability_id, "Availability not found")
    _require_tenant(_room_hotel_id(db, availability.room_id), current_user)
    return availability


@router.patch(
    "/availability/{availability_id}",
    response_model=AvailabilityResponse,
    tags=["availability"],
)
def update_availability(
    availability_id: int,
    availability: AvailabilityUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Availability:
    existing = _get_or_404(db, Availability, availability_id, "Availability not found")
    _require_tenant(_room_hotel_id(db, existing.room_id), current_user)
    data = availability.model_dump(exclude_unset=True)
    if "available_rooms" in data:
        room = _get_or_404(db, Room, existing.room_id, "Room not found")
        if data["available_rooms"] > room.total_rooms:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"available_rooms ({data['available_rooms']}) cannot exceed "
                    f"the room's total inventory ({room.total_rooms})"
                ),
            )
    _apply_update(existing, data)
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    availability = _get_or_404(db, Availability, availability_id, "Availability not found")
    _require_tenant(_room_hotel_id(db, availability.room_id), current_user)
    db.delete(availability)
    _commit_or_409(db, _CONFLICT_DETAIL)


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
    current_user: HotelUser = Depends(get_current_user),
) -> Policy:
    _hotel_exists(db, policy.hotel_id)
    _require_tenant(policy.hotel_id, current_user)
    new_policy = Policy(**policy.model_dump())
    db.add(new_policy)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_policy)
    return new_policy


@router.get("/policies", response_model=list[PolicyResponse], tags=["policies"])
def get_policies(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[PolicyResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Policy).where(Policy.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    tags=["policies"],
)
def get_policy(
    policy_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Policy:
    return _get_owned(db, Policy, policy_id, "Policy not found", current_user)


@router.patch(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    tags=["policies"],
)
def update_policy(
    policy_id: int,
    policy: PolicyUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Policy:
    existing = _get_owned(db, Policy, policy_id, "Policy not found", current_user)
    _apply_update(existing, policy.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/policies/{policy_id}", status_code=204, tags=["policies"])
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    policy = _get_owned(db, Policy, policy_id, "Policy not found", current_user)
    db.delete(policy)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post("/faqs", response_model=FAQResponse, status_code=201, tags=["faqs"])
def create_faq(
    faq: FAQCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> FAQ:
    _hotel_exists(db, faq.hotel_id)
    _require_tenant(faq.hotel_id, current_user)
    new_faq = FAQ(**faq.model_dump())
    db.add(new_faq)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_faq)
    return new_faq


@router.get("/faqs", response_model=list[FAQResponse], tags=["faqs"])
def get_faqs(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[FAQResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(FAQ).where(FAQ.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get("/faqs/{faq_id}", response_model=FAQResponse, tags=["faqs"])
def get_faq(
    faq_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> FAQ:
    return _get_owned(db, FAQ, faq_id, "FAQ not found", current_user)


@router.patch("/faqs/{faq_id}", response_model=FAQResponse, tags=["faqs"])
def update_faq(
    faq_id: int,
    faq: FAQUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> FAQ:
    existing = _get_owned(db, FAQ, faq_id, "FAQ not found", current_user)
    _apply_update(existing, faq.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/faqs/{faq_id}", status_code=204, tags=["faqs"])
def delete_faq(
    faq_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    faq = _get_owned(db, FAQ, faq_id, "FAQ not found", current_user)
    db.delete(faq)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/services",
    response_model=ServiceResponse,
    status_code=201,
    tags=["services"],
)
def create_service(
    service: ServiceCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Service:
    _hotel_exists(db, service.hotel_id)
    _require_tenant(service.hotel_id, current_user)
    new_service = Service(**service.model_dump())
    db.add(new_service)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_service)
    return new_service


@router.get("/services", response_model=list[ServiceResponse], tags=["services"])
def get_services(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[ServiceResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Service).where(Service.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/services/{service_id}",
    response_model=ServiceResponse,
    tags=["services"],
)
def get_service(
    service_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Service:
    return _get_owned(db, Service, service_id, "Service not found", current_user)


@router.patch(
    "/services/{service_id}",
    response_model=ServiceResponse,
    tags=["services"],
)
def update_service(
    service_id: int,
    service: ServiceUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Service:
    existing = _get_owned(db, Service, service_id, "Service not found", current_user)
    _apply_update(existing, service.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/services/{service_id}", status_code=204, tags=["services"])
def delete_service(
    service_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    service = _get_owned(db, Service, service_id, "Service not found", current_user)
    db.delete(service)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/offers",
    response_model=OfferResponse,
    status_code=201,
    tags=["offers"],
)
def create_offer(
    offer: OfferCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Offer:
    _hotel_exists(db, offer.hotel_id)
    _require_tenant(offer.hotel_id, current_user)
    if offer.valid_until < offer.valid_from:
        raise HTTPException(
            status_code=422,
            detail="valid_until must be on or after valid_from",
        )
    new_offer = Offer(**offer.model_dump())
    db.add(new_offer)
    db.flush()  # assign id for the audit entry
    log_action(
        db,
        hotel_id=new_offer.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="offer.created",
        entity_type="offer",
        entity_id=new_offer.id,
        details={"name": new_offer.name},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_offer)
    return new_offer


@router.get("/offers", response_model=list[OfferResponse], tags=["offers"])
def get_offers(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[OfferResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Offer).where(Offer.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/offers/{offer_id}",
    response_model=OfferResponse,
    tags=["offers"],
)
def get_offer(
    offer_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Offer:
    return _get_owned(db, Offer, offer_id, "Offer not found", current_user)


@router.patch(
    "/offers/{offer_id}",
    response_model=OfferResponse,
    tags=["offers"],
)
def update_offer(
    offer_id: int,
    offer: OfferUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Offer:
    existing = _get_owned(db, Offer, offer_id, "Offer not found", current_user)
    update_data = offer.model_dump(exclude_unset=True)
    start = update_data.get("valid_from", existing.valid_from)
    end = update_data.get("valid_until", existing.valid_until)
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="valid_until must be on or after valid_from",
        )
    _apply_update(existing, update_data)
    log_action(
        db,
        hotel_id=existing.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="offer.modified",
        entity_type="offer",
        entity_id=existing.id,
        details={"changed": sorted(update_data)},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/offers/{offer_id}", status_code=204, tags=["offers"])
def delete_offer(
    offer_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    offer = _get_owned(db, Offer, offer_id, "Offer not found", current_user)
    offer_hotel_id, deleted_offer_id = offer.hotel_id, offer.id
    db.delete(offer)
    log_action(
        db,
        hotel_id=offer_hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="offer.deleted",
        entity_type="offer",
        entity_id=deleted_offer_id,
    )
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/negotiation-rules",
    response_model=NegotiationRuleResponse,
    status_code=201,
    tags=["negotiation-rules"],
)
def create_negotiation_rule(
    rule: NegotiationRuleCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> NegotiationRule:
    _hotel_exists(db, rule.hotel_id)
    _require_tenant(rule.hotel_id, current_user)
    if rule.room_id is not None:
        room = _get_or_404(db, Room, rule.room_id, "Room not found")
        _require_tenant(room.hotel_id, current_user)
    new_rule = NegotiationRule(**rule.model_dump())
    db.add(new_rule)
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> list[NegotiationRuleResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(NegotiationRule).where(NegotiationRule.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/negotiation-rules/{rule_id}",
    response_model=NegotiationRuleResponse,
    tags=["negotiation-rules"],
)
def get_negotiation_rule(
    rule_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> NegotiationRule:
    return _get_owned(db, NegotiationRule, rule_id, "Negotiation rule not found", current_user)


@router.patch(
    "/negotiation-rules/{rule_id}",
    response_model=NegotiationRuleResponse,
    tags=["negotiation-rules"],
)
def update_negotiation_rule(
    rule_id: int,
    rule: NegotiationRuleUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> NegotiationRule:
    existing = _get_owned(db, NegotiationRule, rule_id, "Negotiation rule not found", current_user)
    update_data = rule.model_dump(exclude_unset=True)
    if update_data.get("room_id") is not None:
        room = _get_or_404(db, Room, update_data["room_id"], "Room not found")
        _require_tenant(room.hotel_id, current_user)
    _apply_update(existing, update_data)
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    rule = _get_owned(db, NegotiationRule, rule_id, "Negotiation rule not found", current_user)
    db.delete(rule)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post("/guests", response_model=GuestResponse, status_code=201, tags=["guests"])
def create_guest(
    guest: GuestCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Guest:
    _hotel_exists(db, guest.hotel_id)
    _require_tenant(guest.hotel_id, current_user)
    new_guest = Guest(**guest.model_dump())
    db.add(new_guest)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_guest)
    return new_guest


@router.get("/guests", response_model=list[GuestResponse], tags=["guests"])
def get_guests(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[GuestResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Guest).where(Guest.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get("/guests/{guest_id}", response_model=GuestResponse, tags=["guests"])
def get_guest(
    guest_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Guest:
    return _get_owned(db, Guest, guest_id, "Guest not found", current_user)


@router.patch("/guests/{guest_id}", response_model=GuestResponse, tags=["guests"])
def update_guest(
    guest_id: int,
    guest: GuestUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Guest:
    existing = _get_owned(db, Guest, guest_id, "Guest not found", current_user)
    _apply_update(existing, guest.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/guests/{guest_id}", status_code=204, tags=["guests"])
def delete_guest(
    guest_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    guest = _get_owned(db, Guest, guest_id, "Guest not found", current_user)
    db.delete(guest)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/bookings",
    response_model=BookingResponse,
    status_code=201,
    tags=["bookings"],
)
def create_booking(
    booking: BookingCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Booking:
    _get_or_404(db, Hotel, booking.hotel_id, "Hotel not found")
    _require_tenant(booking.hotel_id, current_user)
    try:
        new_booking = create_booking_record(
            db,
            hotel_id=booking.hotel_id,
            guest_id=booking.guest_id,
            room_id=booking.room_id,
            check_in=booking.check_in,
            check_out=booking.check_out,
            number_of_guests=booking.number_of_guests,
            final_price=booking.final_price,
            booking_status=booking.booking_status,
            actor_type="api",
        )
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Booking conflicts with existing data"
        ) from None
    db.refresh(new_booking)
    logger.info(
        "booking.created via API: booking %s (hotel %s) by staff user %s",
        new_booking.id,
        new_booking.hotel_id,
        current_user.id,
    )
    return new_booking


@router.post(
    "/bookings/quote",
    response_model=BookingQuoteResponse,
    tags=["bookings"],
)
def quote_booking(
    request: BookingQuoteRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> BookingQuoteResponse:
    """Deterministic price quote for a stay, computed from configured rates."""
    hotel_id = request.hotel_id
    room_id = request.room_id
    _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    _require_tenant(hotel_id, current_user)
    room = _get_or_404(db, Room, room_id, "Room not found")
    if room.hotel_id != hotel_id:
        raise HTTPException(status_code=422, detail="Room does not belong to this hotel")
    try:
        quote = quote_booking_price(db, room_id, request.check_in, request.check_out)
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc
    return BookingQuoteResponse(
        room_id=quote.room_id,
        check_in=quote.check_in,
        check_out=quote.check_out,
        currency=quote.currency,
        nights=[NightQuoteResponse(date=n.date, price=n.price) for n in quote.nights],
        total=quote.total,
        missing_dates=quote.missing_dates,
        fully_priced=quote.fully_priced,
    )


@router.get(
    "/bookings/availability-check",
    tags=["bookings"],
)
def booking_availability_check(
    room_id: int,
    check_in: date,
    check_out: date,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> dict:
    """Per-night availability for a room type over a date range."""
    room = _get_or_404(db, Room, room_id, "Room not found")
    _require_tenant(room.hotel_id, current_user)
    try:
        nights = service_check_availability(db, room_id, check_in, check_out)
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc
    return {
        "room_id": room_id,
        "check_in": check_in,
        "check_out": check_out,
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


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingResponse,
    tags=["bookings"],
)
def cancel_booking_endpoint(
    booking_id: int,
    reason: str | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Booking:
    booking = _get_owned(db, Booking, booking_id, "Booking not found", current_user)
    try:
        booking = cancel_booking_record(db, booking_id, actor_type="api", reason=reason)
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Booking conflicts with existing data"
        ) from None
    db.refresh(booking)
    logger.info(
        "booking.cancelled via API: booking %s (hotel %s) by staff user %s",
        booking.id,
        booking.hotel_id,
        current_user.id,
    )
    return booking


@router.post(
    "/negotiation/evaluate",
    response_model=NegotiationEvaluateResponse,
    tags=["negotiation"],
)
def evaluate_negotiation_offer(
    request: NegotiationEvaluateRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> NegotiationEvaluateResponse:
    _get_or_404(db, Hotel, request.hotel_id, "Hotel not found")
    _require_tenant(request.hotel_id, current_user)
    room = _get_or_404(db, Room, request.room_id, "Room not found")
    if room.hotel_id != request.hotel_id:
        raise HTTPException(status_code=422, detail="Room does not belong to this hotel")
    try:
        result = evaluate_price_offer(
            db,
            hotel_id=request.hotel_id,
            room_id=request.room_id,
            check_in=request.check_in,
            check_out=request.check_out,
            offered_price=request.offered_price,
        )
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc
    return NegotiationEvaluateResponse(
        accepted=result.accepted,
        requires_approval=result.requires_approval,
        base_price=result.base_price,
        offered_price=result.offered_price,
        minimum_acceptable_price=result.minimum_acceptable_price,
        maximum_discount_percent=result.maximum_discount_percent,
        reason=result.reason,
    )


@router.get(
    "/bookings",
    response_model=list[BookingResponse],
    tags=["bookings"],
)
def get_bookings(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[BookingResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Booking).where(Booking.hotel_id == scoped_hotel_id)
    if guest_id is not None:
        _require_filter_tenant(db, Guest, guest_id, current_user)
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
    current_user: HotelUser = Depends(get_current_user),
) -> Booking:
    return _get_owned(db, Booking, booking_id, "Booking not found", current_user)


@router.patch(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    tags=["bookings"],
)
def update_booking(
    booking_id: int,
    booking: BookingUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Booking:
    existing = _get_owned(db, Booking, booking_id, "Booking not found", current_user)
    update_data = booking.model_dump(exclude_unset=True)
    audit_changes: dict[str, str] = {}

    new_status = update_data.get("booking_status")
    if new_status is not None and new_status != existing.booking_status:
        try:
            validate_status_transition(existing.booking_status, new_status)
        except BookingError as exc:
            raise _booking_error_to_http(exc) from exc
        audit_changes["booking_status"] = f"{existing.booking_status} -> {new_status}"
        existing.booking_status = new_status

    try:
        update_booking_dates_guests(
            db,
            existing,
            check_in=update_data.get("check_in"),
            check_out=update_data.get("check_out"),
            number_of_guests=update_data.get("number_of_guests"),
            actor_type="staff",
            actor_id=current_user.id,
        )
    except BookingError as exc:
        raise _booking_error_to_http(exc) from exc

    if "final_price" in update_data:
        # Price overrides are only allowed when no deterministic rate card
        # covers the stay; otherwise the computed price stands.
        try:
            quote = quote_booking_price(db, existing.room_id, existing.check_in, existing.check_out)
        except BookingError as exc:
            raise _booking_error_to_http(exc) from exc
        if quote.fully_priced and update_data["final_price"] != quote.total:
            raise HTTPException(
                status_code=422,
                detail=(
                    "final_price does not match the computed stay price "
                    f"{quote.total}. Prices are computed from configured rates."
                ),
            )
        if update_data["final_price"] != existing.final_price:
            audit_changes["final_price"] = f"{existing.final_price} -> {update_data['final_price']}"
        existing.final_price = update_data["final_price"]

    if audit_changes:
        # Date/guest-count changes are audited inside update_booking_dates_guests;
        # this covers status and price overrides made through the API.
        log_action(
            db,
            hotel_id=existing.hotel_id,
            actor_type="staff",
            actor_id=current_user.id,
            action="booking.modified",
            entity_type="booking",
            entity_id=existing.id,
            details=audit_changes,
        )

    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/bookings/{booking_id}", status_code=204, tags=["bookings"])
def delete_booking(
    booking_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    booking = _get_owned(db, Booking, booking_id, "Booking not found", current_user)
    db.delete(booking)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/menu-items",
    response_model=MenuItemResponse,
    status_code=201,
    tags=["menu-items"],
)
def create_menu_item(
    menu_item: MenuItemCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> MenuItem:
    _hotel_exists(db, menu_item.hotel_id)
    _require_tenant(menu_item.hotel_id, current_user)
    new_item = MenuItem(**menu_item.model_dump())
    db.add(new_item)
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> list[MenuItemResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(MenuItem).where(MenuItem.hotel_id == scoped_hotel_id)
    return db.scalars(stmt).all()


@router.get(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
    tags=["menu-items"],
)
def get_menu_item(
    menu_item_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> MenuItem:
    return _get_owned(db, MenuItem, menu_item_id, "Menu item not found", current_user)


@router.patch(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
    tags=["menu-items"],
)
def update_menu_item(
    menu_item_id: int,
    menu_item: MenuItemUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> MenuItem:
    existing = _get_owned(db, MenuItem, menu_item_id, "Menu item not found", current_user)
    _apply_update(existing, menu_item.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    item = _get_owned(db, MenuItem, menu_item_id, "Menu item not found", current_user)
    db.delete(item)
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=201,
    tags=["orders"],
)
def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Order:
    _hotel_exists(db, order.hotel_id)
    _require_tenant(order.hotel_id, current_user)
    guest = _get_or_404(db, Guest, order.guest_id, "Guest not found")

    if guest.hotel_id != order.hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Guest does not belong to this hotel",
        )
    if order.room_id is not None:
        _require_tenant(_hotel_room_hotel_id(db, order.room_id), current_user)

    new_order = Order(**order.model_dump())
    db.add(new_order)
    db.flush()
    log_action(
        db,
        hotel_id=new_order.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order.created",
        entity_type="order",
        entity_id=new_order.id,
        details={"order_type": new_order.order_type, "guest_id": new_order.guest_id},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_order)
    return new_order


@router.get("/orders", response_model=list[OrderResponse], tags=["orders"])
def get_orders(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[OrderResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Order).where(Order.hotel_id == scoped_hotel_id)
    if guest_id is not None:
        _require_filter_tenant(db, Guest, guest_id, current_user)
        stmt = stmt.where(Order.guest_id == guest_id)
    return db.scalars(stmt).all()


@router.get("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def get_order(
    order_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Order:
    return _get_owned(db, Order, order_id, "Order not found", current_user)


@router.patch("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def update_order(
    order_id: int,
    order: OrderUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Order:
    existing = _get_owned(db, Order, order_id, "Order not found", current_user)
    update_data = order.model_dump(exclude_unset=True)
    if update_data.get("room_id") is not None:
        _require_tenant(_hotel_room_hotel_id(db, update_data["room_id"]), current_user)
    _apply_update(existing, update_data)
    db.flush()
    if update_data:
        log_action(
            db,
            hotel_id=existing.hotel_id,
            actor_type="staff",
            actor_id=current_user.id,
            action="order.modified",
            entity_type="order",
            entity_id=existing.id,
            details={"changed": sorted(update_data)},
        )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/orders/{order_id}", status_code=204, tags=["orders"])
def delete_order(
    order_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    order = _get_owned(db, Order, order_id, "Order not found", current_user)
    order_hotel_id, deleted_order_id = order.hotel_id, order.id
    db.delete(order)
    log_action(
        db,
        hotel_id=order_hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order.deleted",
        entity_type="order",
        entity_id=deleted_order_id,
    )
    _commit_or_409(db, _CONFLICT_DETAIL)


@router.post(
    "/order-items",
    response_model=OrderItemResponse,
    status_code=201,
    tags=["order-items"],
)
def create_order_item(
    item: OrderItemCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> OrderItem:
    order = _get_or_404(db, Order, item.order_id, "Order not found")
    _require_tenant(order.hotel_id, current_user)
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
    log_action(
        db,
        hotel_id=order.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order_item.created",
        entity_type="order_item",
        entity_id=new_item.id,
        details={
            "order_id": order.id,
            "menu_item_id": new_item.menu_item_id,
            "quantity": new_item.quantity,
        },
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> list[OrderItemResponse]:
    if order_id is not None:
        order = _get_or_404(db, Order, order_id, "Order not found")
        _require_tenant(order.hotel_id, current_user)
        stmt = select(OrderItem).where(OrderItem.order_id == order_id)
    else:
        stmt = (
            select(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.hotel_id == current_user.hotel_id)
        )
    return db.scalars(stmt).all()


@router.get(
    "/order-items/{order_item_id}",
    response_model=OrderItemResponse,
    tags=["order-items"],
)
def get_order_item(
    order_item_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> OrderItem:
    item = _get_or_404(db, OrderItem, order_item_id, "Order item not found")
    order = _get_or_404(db, Order, item.order_id, "Order not found")
    _require_tenant(order.hotel_id, current_user)
    return item


@router.patch(
    "/order-items/{order_item_id}",
    response_model=OrderItemResponse,
    tags=["order-items"],
)
def update_order_item(
    order_item_id: int,
    item: OrderItemUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> OrderItem:
    existing = _get_or_404(db, OrderItem, order_item_id, "Order item not found")
    order = _get_or_404(db, Order, existing.order_id, "Order not found")
    _require_tenant(order.hotel_id, current_user)

    update_data = item.model_dump(exclude_unset=True)
    menu_item_id = update_data.get("menu_item_id", existing.menu_item_id)
    menu_item = _get_owned(db, MenuItem, menu_item_id, "Menu item not found", current_user)

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
    log_action(
        db,
        hotel_id=order.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order_item.modified",
        entity_type="order_item",
        entity_id=existing.id,
        details={"changed": sorted(update_data)},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
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
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    item = _get_or_404(db, OrderItem, order_item_id, "Order item not found")
    order = _get_or_404(db, Order, item.order_id, "Order not found")
    _require_tenant(order.hotel_id, current_user)
    item_hotel_id, deleted_item_id, parent_order_id = order.hotel_id, item.id, order.id
    db.delete(item)
    db.flush()
    _recalculate_order_total(db, order)
    log_action(
        db,
        hotel_id=item_hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order_item.deleted",
        entity_type="order_item",
        entity_id=deleted_item_id,
        details={"order_id": parent_order_id},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)


# --------------------------------------------------------------------- #
# Hotel rooms (physical rooms)                                           #
# --------------------------------------------------------------------- #
@router.post(
    "/hotel-rooms",
    response_model=HotelRoomResponse,
    status_code=201,
    tags=["hotel-rooms"],
)
def create_hotel_room(
    payload: HotelRoomCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelRoom:
    _hotel_exists(db, payload.hotel_id)
    _require_tenant(payload.hotel_id, current_user)
    room = _get_or_404(db, Room, payload.room_id, "Room not found")
    if room.hotel_id != payload.hotel_id:
        raise HTTPException(status_code=422, detail="Room does not belong to this hotel")
    new_room = HotelRoom(**payload.model_dump())
    db.add(new_room)
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_room)
    return new_room


@router.get(
    "/hotel-rooms",
    response_model=list[HotelRoomResponse],
    tags=["hotel-rooms"],
)
def get_hotel_rooms(
    hotel_id: int | None = None,
    room_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[HotelRoomResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(HotelRoom).where(HotelRoom.hotel_id == scoped_hotel_id)
    if room_id is not None:
        _require_tenant(_room_hotel_id(db, room_id), current_user)
        stmt = stmt.where(HotelRoom.room_id == room_id)
    return db.scalars(stmt).all()


@router.get(
    "/hotel-rooms/{hotel_room_id}",
    response_model=HotelRoomResponse,
    tags=["hotel-rooms"],
)
def get_hotel_room(
    hotel_room_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelRoom:
    return _get_owned(db, HotelRoom, hotel_room_id, "Hotel room not found", current_user)


@router.patch(
    "/hotel-rooms/{hotel_room_id}",
    response_model=HotelRoomResponse,
    tags=["hotel-rooms"],
)
def update_hotel_room(
    hotel_room_id: int,
    payload: HotelRoomUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelRoom:
    existing = _get_owned(db, HotelRoom, hotel_room_id, "Hotel room not found", current_user)
    _apply_update(existing, payload.model_dump(exclude_unset=True))
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/hotel-rooms/{hotel_room_id}", status_code=204, tags=["hotel-rooms"])
def delete_hotel_room(
    hotel_room_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    hotel_room = _get_owned(db, HotelRoom, hotel_room_id, "Hotel room not found", current_user)
    db.delete(hotel_room)
    _commit_or_409(db, _CONFLICT_DETAIL)


# --------------------------------------------------------------------- #
# Service requests                                                       #
# --------------------------------------------------------------------- #
def _validate_service_request_parties(
    db: Session,
    hotel_id: int,
    guest_id: int,
    service_id: int,
    current_user: HotelUser,
) -> None:
    _hotel_exists(db, hotel_id)
    _require_tenant(hotel_id, current_user)
    guest = _get_owned(db, Guest, guest_id, "Guest not found", current_user)
    service = _get_owned(db, Service, service_id, "Service not found", current_user)
    if guest.hotel_id != hotel_id:
        raise HTTPException(status_code=422, detail="Guest does not belong to this hotel")
    if service.hotel_id != hotel_id:
        raise HTTPException(status_code=422, detail="Service does not belong to this hotel")


@router.post(
    "/service-requests",
    response_model=ServiceRequestResponse,
    status_code=201,
    tags=["service-requests"],
)
def create_service_request_endpoint(
    payload: ServiceRequestCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> ServiceRequest:
    _validate_service_request_parties(
        db, payload.hotel_id, payload.guest_id, payload.service_id, current_user
    )
    new_request = ServiceRequest(**payload.model_dump())
    db.add(new_request)
    db.flush()
    log_action(
        db,
        hotel_id=new_request.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="service_request.created",
        entity_type="service_request",
        entity_id=new_request.id,
        details={"service_id": new_request.service_id, "guest_id": new_request.guest_id},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(new_request)
    return new_request


@router.get(
    "/service-requests",
    response_model=list[ServiceRequestResponse],
    tags=["service-requests"],
)
def get_service_requests(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[ServiceRequestResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(ServiceRequest).where(ServiceRequest.hotel_id == scoped_hotel_id)
    if guest_id is not None:
        _require_filter_tenant(db, Guest, guest_id, current_user)
        stmt = stmt.where(ServiceRequest.guest_id == guest_id)
    if status is not None:
        stmt = stmt.where(ServiceRequest.status == status.upper())
    return db.scalars(stmt.order_by(ServiceRequest.id.desc())).all()


@router.get(
    "/service-requests/{request_id}",
    response_model=ServiceRequestResponse,
    tags=["service-requests"],
)
def get_service_request(
    request_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> ServiceRequest:
    return _get_owned(db, ServiceRequest, request_id, "Service request not found", current_user)


@router.patch(
    "/service-requests/{request_id}",
    response_model=ServiceRequestResponse,
    tags=["service-requests"],
)
def update_service_request(
    request_id: int,
    payload: ServiceRequestUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> ServiceRequest:
    existing = _get_owned(db, ServiceRequest, request_id, "Service request not found", current_user)
    update_data = payload.model_dump(exclude_unset=True)
    _apply_update(existing, update_data)
    log_action(
        db,
        hotel_id=existing.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="service_request.modified",
        entity_type="service_request",
        entity_id=existing.id,
        details={"changed": sorted(update_data)},
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(existing)
    return existing


@router.delete("/service-requests/{request_id}", status_code=204, tags=["service-requests"])
def delete_service_request(
    request_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    request = _get_owned(db, ServiceRequest, request_id, "Service request not found", current_user)
    request_hotel_id, deleted_request_id = request.hotel_id, request.id
    db.delete(request)
    log_action(
        db,
        hotel_id=request_hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="service_request.deleted",
        entity_type="service_request",
        entity_id=deleted_request_id,
    )
    _commit_or_409(db, _CONFLICT_DETAIL)


# --------------------------------------------------------------------- #
# Conversations & messages                                               #
# --------------------------------------------------------------------- #
@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=201,
    tags=["conversations"],
)
def create_conversation_endpoint(
    payload: ConversationCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Conversation:
    from app.agent import conversation as conversation_store

    _hotel_exists(db, payload.hotel_id)

    _require_tenant(payload.hotel_id, current_user)
    try:
        conversation = conversation_store.create_conversation(
            db,
            hotel_id=payload.hotel_id,
            guest_id=payload.guest_id,
            channel=payload.channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(conversation)
    return conversation


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    tags=["conversations"],
)
def get_conversations(
    hotel_id: int | None = None,
    guest_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[ConversationResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Conversation).order_by(Conversation.id.desc())
    stmt = stmt.where(Conversation.hotel_id == scoped_hotel_id)
    if guest_id is not None:
        _require_filter_tenant(db, Guest, guest_id, current_user)
        stmt = stmt.where(Conversation.guest_id == guest_id)
    return db.scalars(stmt).all()


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["conversations"],
)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Conversation:
    return _get_owned(db, Conversation, conversation_id, "Conversation not found", current_user)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    tags=["conversations"],
)
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[MessageResponse]:
    _get_owned(db, Conversation, conversation_id, "Conversation not found", current_user)
    return db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ).all()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    tags=["conversations"],
)
def post_conversation_message(
    conversation_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Message:
    from app.agent import conversation as conversation_store

    _get_owned(db, Conversation, conversation_id, "Conversation not found", current_user)
    message = conversation_store.add_message(
        db,
        conversation_id,
        sender_type=payload.sender_type,
        message=payload.message,
        message_type=payload.message_type,
    )
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(message)
    return message


# --------------------------------------------------------------------- #
# Audit logs & notifications (read)                                      #
# --------------------------------------------------------------------- #
@router.get(
    "/audit-logs",
    response_model=list[AuditLogResponse],
    tags=["system"],
)
def get_audit_logs(
    hotel_id: int | None = None,
    action: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[AuditLogResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = (
        select(AuditLog)
        .order_by(AuditLog.id.desc())
        .limit(min(limit, 500))
        .where(AuditLog.hotel_id == scoped_hotel_id)
    )
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return db.scalars(stmt).all()


@router.get(
    "/notifications",
    response_model=list[NotificationResponse],
    tags=["system"],
)
def get_notifications(
    hotel_id: int | None = None,
    user_id: int | None = None,
    unread_only: bool = False,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[NotificationResponse]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    stmt = select(Notification).order_by(Notification.id.desc())
    stmt = stmt.where(Notification.hotel_id == scoped_hotel_id)
    if user_id is not None:
        _require_filter_tenant(db, HotelUser, user_id, current_user)
        stmt = stmt.where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return db.scalars(stmt).all()


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    tags=["system"],
)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> Notification:
    notification = _get_owned(
        db, Notification, notification_id, "Notification not found", current_user
    )
    notification.is_read = True
    _commit_or_409(db, _CONFLICT_DETAIL)
    db.refresh(notification)
    return notification


# --------------------------------------------------------------------- #
# AI agent chat                                                          #
# --------------------------------------------------------------------- #
@router.post(
    "/agent/chat",
    response_model=ChatResponse,
    tags=["agent"],
    responses={429: {"description": "Rate limit exceeded — retry after the Retry-After delay"}},
)
def agent_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_chat),
) -> ChatResponse:
    """Chat with the StayFlow AI concierge for a hotel."""
    from app.agent.config import AgentConfig

    _get_or_404(db, Hotel, payload.hotel_id, "Hotel not found")
    config = AgentConfig.from_settings(settings)
    try:
        result = run_chat(
            db,
            hotel_id=payload.hotel_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            guest_id=payload.guest_id,
            channel=payload.channel,
            config=config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Metadata only: never log the guest's message or the reply (PII).
    logger.info(
        "agent.chat hotel=%s conversation=%s channel=%s iterations=%s degraded=%s tools=%s",
        payload.hotel_id,
        result.conversation_id,
        payload.channel,
        result.iterations,
        result.degraded,
        len(result.tool_trace),
    )
    return ChatResponse(
        reply=result.reply,
        conversation_id=result.conversation_id,
        iterations=result.iterations,
        degraded=result.degraded,
        tool_trace=[ToolTraceResponse(**entry.__dict__) for entry in result.tool_trace],
    )
