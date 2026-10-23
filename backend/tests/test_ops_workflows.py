"""Phase 5 (HMS upgrade): operational workflows — kitchen transitions,
housekeeping lifecycle, front-desk checkout, role notifications."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.db.session import get_db
from app.models.booking import Booking
from app.models.notification import Notification
from tests._helpers import client, make_guest, make_hotel, make_room, ok


def _order(hotel_id, guest_id):
    r = client.post(
        "/api/v1/orders",
        json={
            "hotel_id": hotel_id,
            "guest_id": guest_id,
            "order_type": "ROOM_SERVICE",
            "status": "PENDING",
        },
    )
    ok(r, 201)
    return r.json()


def _notifications(hotel_id, type_):
    db = next(get_db())
    try:
        return list(
            db.scalars(
                select(Notification).where(
                    Notification.hotel_id == hotel_id, Notification.type == type_
                )
            ).all()
        )
    finally:
        db.close()


def test_kitchen_transition_flow_and_ready_notification():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    order = _order(hotel["id"], guest["id"])
    for target in ("CONFIRMED", "PREPARING", "READY", "DELIVERED"):
        r = client.post(f"/api/v1/ops/orders/{order['id']}/transition", json={"status": target})
        ok(r, 200)
        assert r.json()["status"] == target
    ready_notes = _notifications(hotel["id"], "order.ready")
    assert ready_notes and ready_notes[0].target_role in ("receptionist", "staff")
    # Terminal state cannot move again.
    r = client.post(f"/api/v1/ops/orders/{order['id']}/transition", json={"status": "PREPARING"})
    assert r.status_code == 409


def test_reject_requires_reason_and_records_it():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    order = _order(hotel["id"], guest["id"])
    r = client.post(f"/api/v1/ops/orders/{order['id']}/transition", json={"status": "CANCELLED"})
    assert r.status_code == 422
    r = client.post(
        f"/api/v1/ops/orders/{order['id']}/transition",
        json={"status": "CANCELLED", "reason": "Kitchen closed"},
    )
    ok(r, 200)
    assert r.json()["status_reason"] == "Kitchen closed"


def test_kitchen_queue_excludes_finished_orders():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    open_order = _order(hotel["id"], guest["id"])
    done_order = _order(hotel["id"], guest["id"])
    for target in ("CONFIRMED", "PREPARING", "READY", "DELIVERED"):
        r = client.post(
            f"/api/v1/ops/orders/{done_order['id']}/transition", json={"status": target}
        )
        ok(r, 200)
    r = client.get("/api/v1/ops/kitchen-queue", params={"hotel_id": hotel["id"]})
    ok(r, 200)
    ids = [row["id"] for row in r.json()]
    assert open_order["id"] in ids
    assert done_order["id"] not in ids


def test_housekeeping_lifecycle_and_ready_notification():
    hotel = make_hotel()
    room = make_room(hotel["id"])
    r = client.post(
        "/api/v1/hotel-rooms",
        json={"hotel_id": hotel["id"], "room_id": room["id"], "room_number": "101"},
    )
    ok(r, 201)
    hr = r.json()
    # A room cannot jump from READY straight to CLEAN.
    r = client.patch(
        f"/api/v1/ops/hotel-rooms/{hr['id']}/cleaning-status", json={"status": "CLEAN"}
    )
    assert r.status_code == 409
    for target in ("DIRTY", "CLEANING", "CLEAN", "INSPECTED", "READY"):
        r = client.patch(
            f"/api/v1/ops/hotel-rooms/{hr['id']}/cleaning-status",
            json={"status": target},
        )
        ok(r, 200)
        assert r.json()["cleaning_status"] == target
    notes = _notifications(hotel["id"], "room.ready")
    assert notes and notes[0].target_role == "receptionist"


def test_checkout_creates_housekeeping_notification_and_arrivals():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    room = make_room(hotel["id"])
    today = date.today()
    db = next(get_db())
    try:
        booking = Booking(
            hotel_id=hotel["id"],
            guest_id=guest["id"],
            room_id=room["id"],
            check_in=today,
            check_out=today + timedelta(days=1),
            number_of_guests=1,
            final_price=3000,
            booking_status="CHECKED_IN",
        )
        db.add(booking)
        db.commit()
        booking_id = booking.id
    finally:
        db.close()

    r = client.get(
        "/api/v1/ops/arrivals",
        params={"hotel_id": hotel["id"], "on": str(today)},
    )
    ok(r, 200)
    assert booking_id in [row["id"] for row in r.json()]

    r = client.post(f"/api/v1/ops/bookings/{booking_id}/checkout")
    ok(r, 200)
    assert r.json()["booking_status"] == "CHECKED_OUT"
    notes = _notifications(hotel["id"], "housekeeping.cleaning_task")
    assert notes and notes[0].target_role == "housekeeping"
    # Second checkout is a conflict.
    r = client.post(f"/api/v1/ops/bookings/{booking_id}/checkout")
    assert r.status_code == 409
