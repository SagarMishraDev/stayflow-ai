"""Operational workflow API (HMS upgrade Phase 5).

Role-focused queues and state machines built on the existing models:

- Kitchen order queue + status transitions (accept / reject-with-reason /
  preparing / ready / delivered), with role notifications on events.
- Housekeeping cleaning lifecycle per physical room
  (DIRTY → CLEANING → CLEAN → INSPECTED → READY). A CLEAN room is not
  bookable-ready: inspection is a separate, separately-authorized step.
- Reception arrivals / departures quick views and checkout, which
  raises the housekeeping notification.
- A notification feed that understands role queues (target_role) as
  well as personal notifications.

All endpoints are staff-JWT protected and hotel-scoped (cross-hotel
access = 403, super admin exempt).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles import is_super_admin, normalize_role
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models.booking import Booking
from app.models.hotel import Hotel
from app.models.hotel_room import HotelRoom
from app.models.hotel_user import HotelUser
from app.models.notification import Notification
from app.models.order import Order
from app.schemas.booking import BookingResponse
from app.schemas.hotel_room import HotelRoomResponse
from app.schemas.ops import NotificationResponse
from app.schemas.order import OrderResponse
from app.services.audit import log_action
from app.services.notifications import notify_role

router = APIRouter(tags=["ops"])

_KITCHEN = require_roles(
    "hotel_admin", "super_admin", "manager", "kitchen", "staff", "receptionist"
)
_HOUSEKEEPING = require_roles(
    "hotel_admin", "super_admin", "manager", "housekeeping", "staff", "receptionist"
)
_INSPECTORS = require_roles("hotel_admin", "super_admin", "manager", "staff", "receptionist")
_FRONT_DESK = require_roles("hotel_admin", "super_admin", "manager", "receptionist", "staff")
_ANY_STAFF = get_current_user

ORDER_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("PREPARING", "CANCELLED"),
    "PREPARING": ("READY", "CANCELLED"),
    "READY": ("DELIVERED",),
    "DELIVERED": (),
    "CANCELLED": (),
}

CLEANING_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DIRTY": ("CLEANING",),
    "CLEANING": ("CLEAN", "DIRTY"),
    "CLEAN": ("INSPECTED", "DIRTY"),
    "INSPECTED": ("READY", "DIRTY"),
    "READY": ("DIRTY",),
}

# Steps that complete an inspection: housekeeping staff may clean, but
# marking a room inspected/ready needs an inspector role (spec §3E).
_INSPECTION_STEPS = {"INSPECTED", "READY"}


def _scope_hotel(db: Session, hotel_id: int, current_user: HotelUser) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    if not is_super_admin(current_user.role) and hotel.id != current_user.hotel_id:
        raise HTTPException(status_code=403, detail="Hotel access denied")
    return hotel


def _owned(db: Session, model, object_id: int, detail: str, current_user: HotelUser):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    _scope_hotel(db, obj.hotel_id, current_user)
    return obj


# --------------------------------------------------------------------- #
# Kitchen                                                                #
# --------------------------------------------------------------------- #
@router.get("/ops/kitchen-queue", response_model=list[OrderResponse])
def kitchen_queue(
    hotel_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_KITCHEN),
) -> list[Order]:
    _scope_hotel(db, hotel_id, current_user)
    stmt = (
        select(Order)
        .where(
            Order.hotel_id == hotel_id,
            Order.status.not_in(("DELIVERED", "CANCELLED")),
        )
        .order_by(Order.scheduled_for.asc().nulls_last(), Order.created_at.asc())
    )
    return list(db.scalars(stmt).all())


class OrderTransition(BaseModel):
    status: str = Field(pattern="^(CONFIRMED|PREPARING|READY|DELIVERED|CANCELLED)$")
    reason: str | None = None


@router.post("/ops/orders/{order_id}/transition", response_model=OrderResponse)
def transition_order(
    order_id: int,
    payload: OrderTransition,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_KITCHEN),
) -> Order:
    order = _owned(db, Order, order_id, "Order not found", current_user)
    allowed = ORDER_TRANSITIONS.get(order.status, ())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move order from {order.status} to {payload.status}",
        )
    if payload.status == "CANCELLED" and not (payload.reason or "").strip():
        raise HTTPException(
            status_code=422, detail="A reason is required to reject/cancel an order"
        )
    previous = order.status
    order.status = payload.status
    if payload.status == "CANCELLED":
        order.status_reason = payload.reason
    db.flush()
    log_action(
        db,
        hotel_id=order.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="order.transition",
        entity_type="order",
        entity_id=order.id,
        details={"from": previous, "to": payload.status},
    )
    if payload.status == "READY":
        for role in ("receptionist", "staff"):
            notify_role(
                db,
                hotel_id=order.hotel_id,
                target_role=role,
                type="order.ready",
                title="Order ready for delivery",
                message=f"Order #{order.id} is ready.",
                reference_type="order",
                reference_id=order.id,
            )
    if payload.status == "CANCELLED":
        notify_role(
            db,
            hotel_id=order.hotel_id,
            target_role="receptionist",
            type="order.cancelled",
            title="Order cancelled",
            message=f"Order #{order.id} was cancelled: {payload.reason}",
            reference_type="order",
            reference_id=order.id,
        )
    db.commit()
    db.refresh(order)
    return order


def order_is_delayed(order: Order, *, now: datetime | None = None) -> bool:
    """An active order is delayed 45+ minutes after its due/created time."""
    if order.status in ("DELIVERED", "CANCELLED"):
        return False
    now = now or datetime.now(UTC)
    due = order.scheduled_for or order.created_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return now - due > timedelta(minutes=45)


# --------------------------------------------------------------------- #
# Housekeeping                                                           #
# --------------------------------------------------------------------- #
class CleaningStatusUpdate(BaseModel):
    status: str = Field(pattern="^(DIRTY|CLEANING|CLEAN|INSPECTED|READY)$")


@router.patch(
    "/ops/hotel-rooms/{hotel_room_id}/cleaning-status",
    response_model=HotelRoomResponse,
)
def update_cleaning_status(
    hotel_room_id: int,
    payload: CleaningStatusUpdate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_HOUSEKEEPING),
) -> HotelRoom:
    room = _owned(db, HotelRoom, hotel_room_id, "Hotel room not found", current_user)
    if payload.status in _INSPECTION_STEPS:
        role = normalize_role(current_user.role)
        if role is not None and role.value == "housekeeping":
            raise HTTPException(
                status_code=403,
                detail="Housekeeping cannot mark a room inspected/ready",
            )
    allowed = CLEANING_TRANSITIONS.get(room.cleaning_status, ())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move cleaning status from {room.cleaning_status} to {payload.status}",
        )
    room.cleaning_status = payload.status
    db.flush()
    log_action(
        db,
        hotel_id=room.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="room.cleaning_status",
        entity_type="hotel_room",
        entity_id=room.id,
        details={"status": payload.status},
    )
    if payload.status == "READY":
        notify_role(
            db,
            hotel_id=room.hotel_id,
            target_role="receptionist",
            type="room.ready",
            title="Room ready",
            message=f"Room {room.room_number} is cleaned, inspected and ready.",
            reference_type="hotel_room",
            reference_id=room.id,
        )
    db.commit()
    db.refresh(room)
    return room


# --------------------------------------------------------------------- #
# Front desk                                                             #
# --------------------------------------------------------------------- #
@router.get("/ops/arrivals", response_model=list[BookingResponse])
def arrivals(
    hotel_id: int,
    on: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_FRONT_DESK),
) -> list[Booking]:
    _scope_hotel(db, hotel_id, current_user)
    day = on or date.today()
    stmt = select(Booking).where(
        Booking.hotel_id == hotel_id,
        Booking.check_in == day,
        Booking.booking_status.not_in(("CANCELLED",)),
    )
    return list(db.scalars(stmt.order_by(Booking.id)).all())


@router.get("/ops/departures", response_model=list[BookingResponse])
def departures(
    hotel_id: int,
    on: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_FRONT_DESK),
) -> list[Booking]:
    _scope_hotel(db, hotel_id, current_user)
    day = on or date.today()
    stmt = select(Booking).where(
        Booking.hotel_id == hotel_id,
        Booking.check_out == day,
        Booking.booking_status.not_in(("CANCELLED",)),
    )
    return list(db.scalars(stmt.order_by(Booking.id)).all())


@router.post("/ops/bookings/{booking_id}/checkout", response_model=BookingResponse)
def checkout_booking(
    booking_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_FRONT_DESK),
) -> Booking:
    booking = _owned(db, Booking, booking_id, "Booking not found", current_user)
    if booking.booking_status != "CHECKED_IN":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only a CHECKED_IN booking can be checked out (current: {booking.booking_status})"
            ),
        )
    booking.booking_status = "CHECKED_OUT"
    db.flush()
    log_action(
        db,
        hotel_id=booking.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="booking.checked_out",
        entity_type="booking",
        entity_id=booking.id,
        details={},
    )
    notify_role(
        db,
        hotel_id=booking.hotel_id,
        target_role="housekeeping",
        type="housekeeping.cleaning_task",
        title="New cleaning task",
        message=(
            f"Booking #{booking.id} checked out. The room needs cleaning "
            "and inspection before it can be sold again."
        ),
        reference_type="booking",
        reference_id=booking.id,
    )
    db.commit()
    db.refresh(booking)
    return booking


# --------------------------------------------------------------------- #
# Notification feed (personal + role queues)                             #
# --------------------------------------------------------------------- #
@router.get("/ops/notifications", response_model=list[NotificationResponse])
def ops_notifications(
    hotel_id: int,
    unread_only: bool = False,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANY_STAFF),
) -> list[Notification]:
    _scope_hotel(db, hotel_id, current_user)
    role = normalize_role(current_user.role)
    role_value = role.value if role else None
    stmt = (
        select(Notification)
        .where(
            Notification.hotel_id == hotel_id,
            (Notification.user_id == current_user.id) | (Notification.target_role == role_value),
        )
        .order_by(Notification.id.desc())
        .limit(200)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(db.scalars(stmt).all())
