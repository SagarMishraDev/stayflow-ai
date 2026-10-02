"""Deterministic booking rules: pricing, availability, lifecycle, negotiation."""

from datetime import timedelta
from uuid import uuid4

from tests._helpers import (
    client,
    future,
    make_guest,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
    uid,
)


def _setup(nights=2, price=3000, available=5, capacity=2, total_rooms=5):
    hotel = make_hotel()
    room = make_room(
        hotel["id"], capacity=capacity, total_rooms=total_rooms, room_type=uid("Deluxe")
    )
    guest = make_guest(hotel["id"], email=f"{uuid4().hex[:8]}@t.co")
    start = future(40)
    seed_rates_availability(room["id"], start, nights, price=price, available=available)
    return hotel, room, guest, start


def _booking_payload(hotel, room, guest, start, nights=2, **extra):
    payload = {
        "hotel_id": hotel["id"],
        "room_id": room["id"],
        "guest_id": guest["id"],
        "check_in": str(start),
        "check_out": str(start + timedelta(days=nights)),
        "number_of_guests": 2,
        "booking_status": "CONFIRMED",
    }
    payload.update(extra)
    return payload


def test_quote_returns_per_night_breakdown():
    hotel, room, guest, start = _setup(nights=2, price=2500)
    r = client.post(
        "/api/v1/bookings/quote",
        json={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "check_in": str(start),
            "check_out": str(start + timedelta(days=2)),
            "number_of_guests": 2,
        },
    )
    ok(r, 200)
    body = r.json()
    assert float(body["total"]) == 5000.0
    assert len(body["nights"]) == 2
    assert body["fully_priced"] is True
    assert body["currency"] == "INR"


def test_booking_enforces_server_price():
    hotel, room, guest, start = _setup(nights=2, price=3000)
    payload = _booking_payload(hotel, room, guest, start, final_price=1.0)
    r = client.post("/api/v1/bookings", json=payload)
    assert r.status_code == 422, r.text
    assert "price" in r.json()["detail"].lower()


def test_booking_ignores_missing_rates_price_when_allowed():
    # When no rates exist at all, a supplied price is accepted (legacy quote).
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("NoRate"))
    guest = make_guest(hotel["id"])
    start = future(45)
    r = client.post(
        "/api/v1/availability",
        json={"room_id": room["id"], "date": str(start), "available_rooms": 5},
    )
    ok(r, 201)
    r = client.post(
        "/api/v1/availability",
        json={
            "room_id": room["id"],
            "date": str(start + timedelta(days=1)),
            "available_rooms": 5,
        },
    )
    ok(r, 201)
    payload = _booking_payload(hotel, room, guest, start, final_price=999.0)
    r = client.post("/api/v1/bookings", json=payload)
    ok(r, 201)
    assert float(r.json()["final_price"]) == 999.0


def test_sold_out_booking_rejected():
    hotel, room, guest, start = _setup(nights=2, price=3000, available=0)
    r = client.post("/api/v1/bookings", json=_booking_payload(hotel, room, guest, start))
    assert r.status_code == 422, r.text
    assert "availability" in r.json()["detail"].lower()


def test_over_capacity_rejected():
    hotel, room, guest, start = _setup(nights=2, capacity=2)
    payload = _booking_payload(hotel, room, guest, start, number_of_guests=5)
    r = client.post("/api/v1/bookings", json=payload)
    assert r.status_code == 422, r.text


def test_bad_dates_rejected():
    hotel, room, guest, start = _setup()
    payload = _booking_payload(hotel, room, guest, start)
    payload["check_out"] = payload["check_in"]
    r = client.post("/api/v1/bookings", json=payload)
    assert r.status_code == 422, r.text


def test_cancel_releases_inventory_and_audits():
    hotel, room, guest, start = _setup(nights=2, price=3000, available=1)
    r = client.post("/api/v1/bookings", json=_booking_payload(hotel, room, guest, start))
    ok(r, 201)
    booking = r.json()
    bid = booking["id"]

    before = client.get(
        "/api/v1/bookings/availability-check",
        params={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "check_in": str(start),
            "check_out": str(start + timedelta(days=2)),
        },
    )
    ok(before, 200)
    assert before.json()["fully_available"] is False

    r = client.post(f"/api/v1/bookings/{bid}/cancel")
    ok(r, 200)
    assert r.json()["booking_status"] == "CANCELLED"

    after = client.get(
        "/api/v1/bookings/availability-check",
        params={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "check_in": str(start),
            "check_out": str(start + timedelta(days=2)),
        },
    )
    ok(after, 200)
    assert after.json()["fully_available"] is True

    r = client.post(f"/api/v1/bookings/{bid}/cancel")
    assert r.status_code == 422, r.text

    logs = client.get("/api/v1/audit-logs", params={"hotel_id": hotel["id"]})
    ok(logs, 200)
    actions = {entry["action"] for entry in logs.json()}
    assert "booking.created" in actions
    assert "booking.cancelled" in actions


def test_illegal_status_transition_rejected():
    hotel, room, guest, start = _setup()
    r = client.post("/api/v1/bookings", json=_booking_payload(hotel, room, guest, start))
    ok(r, 201)
    bid = r.json()["id"]
    r = client.patch(f"/api/v1/bookings/{bid}", json={"booking_status": "PENDING"})
    assert r.status_code == 422, r.text


def test_duplicate_rate_rejected():
    hotel, room, guest, start = _setup(nights=1)
    r = client.post(
        "/api/v1/rates",
        json={"room_id": room["id"], "date": str(start), "price": 100},
    )
    assert r.status_code == 409, r.text


def test_duplicate_availability_rejected():
    hotel, room, guest, start = _setup(nights=1)
    r = client.post(
        "/api/v1/availability",
        json={"room_id": room["id"], "date": str(start), "available_rooms": 1},
    )
    assert r.status_code == 409, r.text


def _make_rule(hotel, room, **kw):
    payload = {
        "hotel_id": hotel["id"],
        "room_id": room["id"],
        "minimum_price": 2000,
        "maximum_discount_percent": 10,
    }
    payload.update(kw)
    r = client.post("/api/v1/negotiation-rules", json=payload)
    ok(r, 201)
    return r.json()


def _evaluate(hotel, room, start, offered_price):
    r = client.post(
        "/api/v1/negotiation/evaluate",
        json={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "check_in": str(start),
            "check_out": str(start + timedelta(days=2)),
            "offered_price": offered_price,
        },
    )
    ok(r, 200)
    return r.json()


def test_negotiation_accept_and_reject():
    hotel, room, guest, start = _setup(nights=2, price=3000)
    _make_rule(hotel, room, minimum_price=4000, maximum_discount_percent=20)
    # 5500 >= minimum 4000 and within 20% discount of base 6000 -> accept
    assert _evaluate(hotel, room, start, 5500)["accepted"] is True
    # 3000 < minimum 4000 -> reject without approval
    body = _evaluate(hotel, room, start, 3000)
    assert body["accepted"] is False
    assert body["requires_approval"] is False


def test_negotiation_below_discount_floor_requires_approval():
    hotel, room, guest, start = _setup(nights=2, price=3000)
    _make_rule(
        hotel,
        room,
        minimum_price=1000,
        maximum_discount_percent=10,
        requires_approval=True,
    )
    # 5000 is a ~17% discount off base 6000, above minimum 1000
    body = _evaluate(hotel, room, start, 5000)
    assert body["accepted"] is False
    assert body["requires_approval"] is True


def test_negotiation_rule_room_must_belong_to_hotel():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    room_b = make_room(hotel_b["id"], room_type=uid("Other"))
    r = client.post(
        "/api/v1/negotiation-rules",
        json={"hotel_id": hotel_a["id"], "room_id": room_b["id"]},
    )
    assert r.status_code == 422, r.text


def test_order_room_must_belong_to_hotel():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    guest_a = make_guest(hotel_a["id"])
    room_b = make_room(hotel_b["id"], room_type=uid("Other"))
    hr = client.post(
        "/api/v1/hotel-rooms",
        json={"hotel_id": hotel_b["id"], "room_id": room_b["id"], "room_number": "X1"},
    )
    ok(hr, 201)
    r = client.post(
        "/api/v1/orders",
        json={
            "hotel_id": hotel_a["id"],
            "guest_id": guest_a["id"],
            "hotel_room_id": hr.json()["id"],
            "order_type": "FOOD",
            "total_amount": 100,
        },
    )
    assert r.status_code == 422, r.text


def test_hotel_room_crud_and_mismatch():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("Phys"))
    r = client.post(
        "/api/v1/hotel-rooms",
        json={"hotel_id": hotel["id"], "room_id": room["id"], "room_number": "101"},
    )
    ok(r, 201)
    hr = r.json()
    ok(client.get(f"/api/v1/hotel-rooms/{hr['id']}"), 200)
    ok(
        client.patch(f"/api/v1/hotel-rooms/{hr['id']}", json={"status": "OCCUPIED"}),
        200,
    )
    other_hotel = make_hotel()
    r = client.post(
        "/api/v1/hotel-rooms",
        json={
            "hotel_id": other_hotel["id"],
            "room_id": room["id"],
            "room_number": "999",
        },
    )
    assert r.status_code == 422, r.text
    ok(client.delete(f"/api/v1/hotel-rooms/{hr['id']}"), 204)


def test_service_request_crud_and_mismatch():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    svc = client.post(
        "/api/v1/services",
        json={"hotel_id": hotel["id"], "name": uid("Laundry"), "category": "housekeeping"},
    )
    ok(svc, 201)
    r = client.post(
        "/api/v1/service-requests",
        json={
            "hotel_id": hotel["id"],
            "guest_id": guest["id"],
            "service_id": svc.json()["id"],
            "notes": "ASAP",
        },
    )
    ok(r, 201)
    sr = r.json()
    assert sr["status"] == "PENDING"
    ok(client.get(f"/api/v1/service-requests/{sr['id']}"), 200)
    ok(
        client.patch(f"/api/v1/service-requests/{sr['id']}", json={"status": "IN_PROGRESS"}),
        200,
    )
    other = make_hotel()
    other_guest = make_guest(other["id"])
    r = client.post(
        "/api/v1/service-requests",
        json={
            "hotel_id": hotel["id"],
            "guest_id": other_guest["id"],
            "service_id": svc.json()["id"],
        },
    )
    # Cross-hotel guest reference is rejected with 403 (tenant isolation).
    assert r.status_code == 403, r.text


def test_conversation_message_flow():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    r = client.post(
        "/api/v1/conversations",
        json={"hotel_id": hotel["id"], "guest_id": guest["id"]},
    )
    ok(r, 201)
    conv = r.json()
    r = client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"sender_type": "guest", "message": "Hello"},
    )
    ok(r, 201)
    msgs = client.get(f"/api/v1/conversations/{conv['id']}/messages")
    ok(msgs, 200)
    assert len(msgs.json()) == 1
    assert msgs.json()[0]["message"] == "Hello"


def test_notification_read():
    hotel = make_hotel()
    r = client.get("/api/v1/notifications", params={"hotel_id": hotel["id"]})
    ok(r, 200)
    assert r.json() == []


def test_availability_cannot_exceed_room_inventory():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("Cap"), total_rooms=3)
    start = future(50)
    r = client.post(
        "/api/v1/availability",
        json={"room_id": room["id"], "date": str(start), "available_rooms": 10},
    )
    assert r.status_code == 422, r.text
    r = client.post(
        "/api/v1/availability",
        json={"room_id": room["id"], "date": str(start), "available_rooms": 3},
    )
    ok(r, 201)
    aid = r.json()["id"]
    r = client.patch(f"/api/v1/availability/{aid}", json={"available_rooms": 99})
    assert r.status_code == 422, r.text


def test_booking_rejects_terminal_initial_status():
    hotel, room, guest, start = _setup()
    payload = _booking_payload(hotel, room, guest, start, booking_status="CANCELLED")
    r = client.post("/api/v1/bookings", json=payload)
    assert r.status_code == 422, r.text
    payload = _booking_payload(hotel, room, guest, start, booking_status="PENDING")
    r = client.post("/api/v1/bookings", json=payload)
    ok(r, 201)
    assert r.json()["booking_status"] == "PENDING"


def test_concurrent_bookings_cannot_oversell_last_room():
    """Two simultaneous bookings for the last available room: one wins.

    ``create_booking_record`` locks the availability rows (SELECT ... FOR
    UPDATE), so the loser re-reads inventory after the winner commits and
    fails with 422 instead of overselling the night.
    """
    import threading

    from app.db.session import SessionLocal
    from app.services.booking_service import BookingError, create_booking_record

    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("Solo"), capacity=2, total_rooms=1)
    start = future(55)
    seed_rates_availability(room["id"], start, 1, price=3000, available=1)
    guest_a = make_guest(hotel["id"], email=f"{uuid4().hex[:8]}@t.co")
    guest_b = make_guest(hotel["id"], email=f"{uuid4().hex[:8]}@t.co")

    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def attempt(name: str, guest_id: int):
        db = SessionLocal()
        try:
            barrier.wait(timeout=30)
            create_booking_record(
                db,
                hotel_id=hotel["id"],
                guest_id=guest_id,
                room_id=room["id"],
                check_in=start,
                check_out=start + timedelta(days=1),
                number_of_guests=1,
                booking_status="CONFIRMED",
                actor_type="test",
            )
            db.commit()
            outcomes[name] = "booked"
        except BookingError as exc:
            db.rollback()
            outcomes[name] = f"rejected:{exc.status_code}"
        except Exception as exc:  # noqa: BLE001 - record unexpected failures
            db.rollback()
            outcomes[name] = f"error:{type(exc).__name__}"
        finally:
            db.close()

    threads = [
        threading.Thread(target=attempt, args=("a", guest_a["id"])),
        threading.Thread(target=attempt, args=("b", guest_b["id"])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert sorted(outcomes.values()) == ["booked", "rejected:422"], outcomes

    # Exactly one active booking occupies the night.
    db = SessionLocal()
    try:
        from sqlalchemy import func, select

        from app.models.booking import Booking

        count = db.scalar(
            select(func.count())
            .select_from(Booking)
            .where(
                Booking.room_id == room["id"],
                Booking.booking_status.in_(("PENDING", "CONFIRMED", "CHECKED_IN")),
            )
        )
        assert count == 1
    finally:
        db.close()
