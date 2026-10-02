"""Shared helpers for the StayFlow AI test-suite.

Staff API routes require a JWT (``Authorization: Bearer <token>``) scoped to
a hotel. The shared ``client`` below attaches the right token automatically:
``make_hotel()`` creates a hotel plus a staff user and registers its token,
and each request resolves the token matching the hotel it targets (from the
JSON body, query params, or the object id in the URL). Requests without any
hotel context fall back to the most recently created hotel's token.

Tests that need to assert *unauthenticated* behaviour must use their own
plain ``TestClient`` instead of this shared client.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
)
from app.db.session import SessionLocal
from app.main import app
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.conversation import Conversation
from app.models.faq import FAQ
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.hotel_room import HotelRoom
from app.models.hotel_user import HotelUser
from app.models.menu_item import MenuItem
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

_TEST_PASSWORD = "test-password-123"

# Staff JWT per hotel id, plus the most recently registered hotel.
_hotel_tokens: dict[int, str] = {}
_latest_hotel_id: ContextVar[int | None] = ContextVar("latest_hotel_id", default=None)


def _hotel_of(db, model, object_id: int | None) -> int | None:
    if object_id is None:
        return None
    obj = db.get(model, object_id)
    return obj.hotel_id if obj is not None else None


def _hotel_of_room_child(db, model, object_id: int | None) -> int | None:
    if object_id is None:
        return None
    obj = db.get(model, object_id)
    if obj is None:
        return None
    return _hotel_of(db, Room, obj.room_id)


def _hotel_of_order_item(db, item_id: int | None) -> int | None:
    if item_id is None:
        return None
    item = db.get(OrderItem, item_id)
    if item is None:
        return None
    return _hotel_of(db, Order, item.order_id)


# (path pattern, resolver) — resolves the hotel a request targets.
_ITEM_ROUTES: list[tuple[re.Pattern, object]] = [
    (re.compile(r"/hotels/(\d+)"), lambda db, i: int(i)),
    (re.compile(r"/rooms/(\d+)"), lambda db, i: _hotel_of(db, Room, int(i))),
    (re.compile(r"/rates/(\d+)"), lambda db, i: _hotel_of_room_child(db, Rate, int(i))),
    (
        re.compile(r"/availability/(\d+)"),
        lambda db, i: _hotel_of_room_child(db, Availability, int(i)),
    ),
    (re.compile(r"/policies/(\d+)"), lambda db, i: _hotel_of(db, Policy, int(i))),
    (re.compile(r"/faqs/(\d+)"), lambda db, i: _hotel_of(db, FAQ, int(i))),
    (re.compile(r"/services/(\d+)"), lambda db, i: _hotel_of(db, Service, int(i))),
    (re.compile(r"/offers/(\d+)"), lambda db, i: _hotel_of(db, Offer, int(i))),
    (
        re.compile(r"/negotiation-rules/(\d+)"),
        lambda db, i: _hotel_of(db, NegotiationRule, int(i)),
    ),
    (re.compile(r"/guests/(\d+)"), lambda db, i: _hotel_of(db, Guest, int(i))),
    (
        re.compile(r"/bookings/(\d+)(/cancel)?"),
        lambda db, i: _hotel_of(db, Booking, int(i)),
    ),
    (re.compile(r"/menu-items/(\d+)"), lambda db, i: _hotel_of(db, MenuItem, int(i))),
    (re.compile(r"/orders/(\d+)"), lambda db, i: _hotel_of(db, Order, int(i))),
    (re.compile(r"/order-items/(\d+)"), lambda db, i: _hotel_of_order_item(db, int(i))),
    (
        re.compile(r"/hotel-rooms/(\d+)"),
        lambda db, i: _hotel_of(db, HotelRoom, int(i)),
    ),
    (
        re.compile(r"/service-requests/(\d+)"),
        lambda db, i: _hotel_of(db, ServiceRequest, int(i)),
    ),
    (
        re.compile(r"/conversations/(\d+)(/messages)?"),
        lambda db, i: _hotel_of(db, Conversation, int(i)),
    ),
    (
        re.compile(r"/notifications/(\d+)/read"),
        lambda db, i: _hotel_of(db, Notification, int(i)),
    ),
    (re.compile(r"/hotel-users/(\d+)"), lambda db, i: _hotel_of(db, HotelUser, int(i))),
]


def _resolve_hotel_id(url: str, kwargs: dict) -> int | None:
    json_body = kwargs.get("json") or {}
    params = kwargs.get("params") or {}
    if isinstance(json_body, dict) and json_body.get("hotel_id"):
        return int(json_body["hotel_id"])
    if isinstance(params, dict):
        if params.get("hotel_id"):
            return int(params["hotel_id"])
        if params.get("room_id"):
            db = SessionLocal()
            try:
                return _hotel_of(db, Room, int(params["room_id"]))
            finally:
                db.close()

    path = url.split("?", 1)[0]
    if "://" in path:
        path = "/" + path.split("://", 1)[1].split("/", 1)[1]
    if path.startswith("/api/v1"):
        path = path[len("/api/v1") :]

    db = SessionLocal()
    try:
        for pattern, resolver in _ITEM_ROUTES:
            match = pattern.fullmatch(path)
            if match:
                return resolver(db, match.group(1))
    finally:
        db.close()
    return None


def _token_for_request(url: str, kwargs: dict) -> str | None:
    hotel_id = _resolve_hotel_id(url, kwargs)
    if hotel_id is not None and hotel_id in _hotel_tokens:
        return _hotel_tokens[hotel_id]
    latest = _latest_hotel_id.get()
    if latest is not None:
        return _hotel_tokens.get(latest)
    return None


class AuthedTestClient(TestClient):
    """TestClient that attaches the staff JWT for the targeted hotel."""

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        if not any(key.lower() == "authorization" for key in headers):
            token = _token_for_request(url, kwargs)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return super().request(method, url, headers=headers, **kwargs)


client = AuthedTestClient(app)


def register_hotel_token(hotel_id: int, email: str | None = None) -> str:
    """Create (or reuse) a staff user for a hotel and register its JWT."""
    email = email or f"staff-{hotel_id}-{uuid4().hex[:6]}@example.com"
    db = SessionLocal()
    try:
        user = db.scalars(
            select(HotelUser).where(
                HotelUser.hotel_id == hotel_id,
                HotelUser.email == email,
            )
        ).first()
        if user is None:
            user = HotelUser(
                hotel_id=hotel_id,
                name=f"Staff {hotel_id}",
                email=email,
                role="admin",
                password_hash=hash_password(_TEST_PASSWORD),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_access_token(hotel_user_id=user.id, hotel_id=hotel_id, role=user.role)
    finally:
        db.close()
    _hotel_tokens[hotel_id] = token
    _latest_hotel_id.set(hotel_id)
    return token


def ensure_staff_token() -> None:
    """Guarantee at least one *usable* staff token exists.

    Prunes tokens whose staff user was deleted (e.g. by a test exercising
    staff deletion) and bootstraps a fresh hotel + admin when none remain.
    """
    db = SessionLocal()
    try:
        for hotel_id, token in list(_hotel_tokens.items()):
            try:
                payload = decode_access_token(token)
                user = db.get(HotelUser, int(payload.get("hotel_user_id")))
            except Exception:
                user = None
            if user is None or not user.is_active:
                del _hotel_tokens[hotel_id]
        if _latest_hotel_id.get() not in _hotel_tokens:
            _latest_hotel_id.set(next(iter(_hotel_tokens), None))
        if _hotel_tokens:
            return
        hotel = Hotel(name=uid("Bootstrap Hotel"), city="Testville", currency="INR")
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        hotel_id = hotel.id
    finally:
        db.close()
    register_hotel_token(hotel_id, f"bootstrap-{hotel_id}@example.com")


def ok(r, *codes):
    assert r.status_code in codes, f"{r.status_code}: {r.text}"


def uid(prefix):
    return f"{prefix}-{uuid4().hex[:8]}"


def make_hotel(name=None):
    """Create a hotel via the API and register a staff JWT for it."""
    ensure_staff_token()
    r = client.post(
        "/api/v1/hotels",
        json={"name": name or uid("Hotel"), "city": "Testville", "currency": "INR"},
    )
    ok(r, 201)
    hotel = r.json()
    register_hotel_token(hotel["id"])
    return hotel


def make_room(hotel_id, room_type="Deluxe", capacity=2, total_rooms=5):
    r = client.post(
        "/api/v1/rooms",
        json={
            "hotel_id": hotel_id,
            "room_type": room_type,
            "capacity": capacity,
            "total_rooms": total_rooms,
        },
    )
    ok(r, 201)
    return r.json()


def make_guest(hotel_id, name=None, email=None, phone=None):
    payload = {"hotel_id": hotel_id, "name": name or uid("Guest")}
    if email:
        payload["email"] = email
    if phone:
        payload["phone_number"] = phone
    r = client.post("/api/v1/guests", json=payload)
    ok(r, 201)
    return r.json()


def seed_rates_availability(room_id, start, nights, price=3000, available=5):
    for i in range(nights):
        day = start + timedelta(days=i)
        r = client.post(
            "/api/v1/rates",
            json={"room_id": room_id, "date": str(day), "price": price},
        )
        ok(r, 201)
        r = client.post(
            "/api/v1/availability",
            json={
                "room_id": room_id,
                "date": str(day),
                "available_rooms": available,
            },
        )
        ok(r, 201)


def future(days=30):
    return date.today() + timedelta(days=days)
