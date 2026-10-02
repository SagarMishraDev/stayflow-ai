"""Audit-trail coverage for security-relevant mutations.

The engineering audit requires audit-log rows for: auth logins, booking,
order, service-request and offer mutations, and cross-hotel attempts.
Bookings are audited inside ``booking_service``; cross-hotel attempts via
``log_super_admin_cross_hotel_access`` (see test_rbac.py). This file covers
the remaining router-level mutations.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.hotel_user import HotelUser
from tests._helpers import client, make_guest, make_hotel, ok, uid

plain = TestClient(app)

_LOGIN_PASSWORD = "AuditTrail-Pass-1"


def _make_staff(hotel_id: int) -> HotelUser:
    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel_id,
            name="Audit Tester",
            email=f"{uid('audituser')}@example.com",
            role="admin",
            password_hash=hash_password(_LOGIN_PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _audit_actions(hotel_id: int) -> list[tuple[str, str | None, int | None]]:
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(AuditLog).where(AuditLog.hotel_id == hotel_id).order_by(AuditLog.id)
        ).all()
        return [(r.action, r.entity_type, r.entity_id) for r in rows]
    finally:
        db.close()


def test_successful_login_is_audited():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])

    r = plain.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": _LOGIN_PASSWORD},
    )
    ok(r, 200)

    actions = _audit_actions(hotel["id"])
    assert ("auth.login", "hotel_user", user.id) in actions


def test_failed_login_is_audited():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])

    r = plain.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password"},
    )
    assert r.status_code == 401

    actions = _audit_actions(hotel["id"])
    assert ("auth.login_failed", "hotel_user", user.id) in actions


def test_offer_lifecycle_is_audited():
    hotel = make_hotel()
    today = date.today()
    r = client.post(
        "/api/v1/offers",
        json={
            "hotel_id": hotel["id"],
            "name": uid("Diwali Deal"),
            "discount_type": "PERCENT",
            "discount_value": "15.00",
            "valid_from": str(today),
            "valid_until": str(today + timedelta(days=30)),
        },
    )
    ok(r, 201)
    offer = r.json()

    r = client.patch(f"/api/v1/offers/{offer['id']}", json={"is_active": False})
    ok(r, 200)
    r = client.delete(f"/api/v1/offers/{offer['id']}")
    assert r.status_code == 204

    actions = _audit_actions(hotel["id"])
    assert ("offer.created", "offer", offer["id"]) in actions
    assert ("offer.modified", "offer", offer["id"]) in actions
    assert ("offer.deleted", "offer", offer["id"]) in actions


def test_order_and_order_items_are_audited():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])

    r = client.post(
        "/api/v1/menu-items",
        json={
            "hotel_id": hotel["id"],
            "name": uid("Thali"),
            "price": "499.00",
            "is_active": True,
            "is_available": True,
        },
    )
    ok(r, 201)
    menu_item = r.json()

    r = client.post(
        "/api/v1/orders",
        json={"hotel_id": hotel["id"], "guest_id": guest["id"], "order_type": "DINE_IN"},
    )
    ok(r, 201)
    order = r.json()

    r = client.post(
        "/api/v1/order-items",
        json={"order_id": order["id"], "menu_item_id": menu_item["id"], "quantity": 2},
    )
    ok(r, 201)
    item = r.json()

    r = client.patch(f"/api/v1/order-items/{item['id']}", json={"quantity": 3})
    ok(r, 200)
    r = client.delete(f"/api/v1/order-items/{item['id']}")
    assert r.status_code == 204
    r = client.delete(f"/api/v1/orders/{order['id']}")
    assert r.status_code == 204

    actions = _audit_actions(hotel["id"])
    assert ("order.created", "order", order["id"]) in actions
    assert ("order_item.created", "order_item", item["id"]) in actions
    assert ("order_item.modified", "order_item", item["id"]) in actions
    assert ("order_item.deleted", "order_item", item["id"]) in actions
    assert ("order.deleted", "order", order["id"]) in actions


def test_service_request_lifecycle_is_audited():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])

    r = client.post(
        "/api/v1/services",
        json={"hotel_id": hotel["id"], "name": uid("Laundry"), "is_active": True},
    )
    ok(r, 201)
    service = r.json()

    r = client.post(
        "/api/v1/service-requests",
        json={
            "hotel_id": hotel["id"],
            "guest_id": guest["id"],
            "service_id": service["id"],
            "room_number": "101",
            "request_text": "Extra towels please",
        },
    )
    ok(r, 201)
    request = r.json()

    r = client.patch(f"/api/v1/service-requests/{request['id']}", json={"status": "IN_PROGRESS"})
    ok(r, 200)
    r = client.delete(f"/api/v1/service-requests/{request['id']}")
    assert r.status_code == 204

    actions = _audit_actions(hotel["id"])
    assert ("service_request.created", "service_request", request["id"]) in actions
    assert ("service_request.modified", "service_request", request["id"]) in actions
    assert ("service_request.deleted", "service_request", request["id"]) in actions
