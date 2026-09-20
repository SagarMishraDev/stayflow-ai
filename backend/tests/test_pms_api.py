from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def ok(r, *codes):
    assert r.status_code in codes, f"{r.status_code}: {r.text}"


def uid(prefix):
    return f"{prefix}-{uuid4().hex[:8]}"


def test_pms_full_smoke():
    # Hotel
    r = client.post(
        "/api/v1/hotels",
        json={
            "name": uid("PMS Test Hotel"),
            "city": "Jaipur",
            "description": "Automated PMS test",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    hotel = r.json()
    hid = hotel["id"]

    ok(client.get("/api/v1/hotels"), 200)
    ok(client.get(f"/api/v1/hotels/{hid}"), 200)
    ok(client.patch(f"/api/v1/hotels/{hid}", json={"phone": "7777777777"}), 200)

    # Room
    r = client.post(
        "/api/v1/rooms",
        json={
            "hotel_id": hid,
            "room_type": uid("Deluxe"),
            "description": "Test room",
            "capacity": 2,
            "total_rooms": 5,
            "amenities": "WiFi, AC",
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    room = r.json()
    rid = room["id"]
    ok(client.get("/api/v1/rooms"), 200)
    ok(client.get(f"/api/v1/rooms/{rid}"), 200)
    ok(client.patch(f"/api/v1/rooms/{rid}", json={"capacity": 3}), 200)

    future = date.today() + timedelta(days=30)

    # Rates
    r = client.post(
        "/api/v1/rates",
        json={
            "room_id": rid,
            "date": str(future),
            "price": 3500,
            "currency": "INR",
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    rate = r.json()
    ok(client.get("/api/v1/rates"), 200)
    ok(client.get(f"/api/v1/rates/{rate['id']}"), 200)
    ok(client.patch(f"/api/v1/rates/{rate['id']}", json={"price": 3600}), 200)
    ok(client.delete(f"/api/v1/rates/{rate['id']}"), 204)

    # Availability
    r = client.post(
        "/api/v1/availability",
        json={
            "room_id": rid,
            "date": str(future),
            "available_rooms": 5,
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    av = r.json()
    ok(client.get("/api/v1/availability"), 200)
    ok(client.get(f"/api/v1/availability/{av['id']}"), 200)
    ok(client.patch(f"/api/v1/availability/{av['id']}", json={"available_rooms": 4}), 200)
    ok(client.delete(f"/api/v1/availability/{av['id']}"), 204)

    # Policies + FAQs
    for path, payload in [
        (
            "/api/v1/policies",
            {
                "hotel_id": hid,
                "policy_type": "check_in",
                "title": "Check-in",
                "description": "After 2 PM",
                "is_active": True,
            },
        ),
        (
            "/api/v1/faqs",
            {
                "hotel_id": hid,
                "question": "Check-in time?",
                "answer": "2 PM",
                "category": "check_in",
                "is_active": True,
            },
        ),
    ]:
        r = client.post(path, json=payload)
        ok(r, 200, 201)
        item = r.json()
        ok(client.get(path), 200)
        ok(client.get(f"{path}/{item['id']}"), 200)
        ok(client.patch(f"{path}/{item['id']}", json={}), 200)
        ok(client.delete(f"{path}/{item['id']}"), 204)

    # Services
    r = client.post(
        "/api/v1/services",
        json={
            "hotel_id": hid,
            "name": uid("Airport Transfer"),
            "description": "Test service",
            "price": 1200,
            "category": "transport",
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    service = r.json()
    ok(client.get("/api/v1/services"), 200)
    ok(client.get(f"/api/v1/services/{service['id']}"), 200)
    ok(client.patch(f"/api/v1/services/{service['id']}", json={"price": 1500}), 200)
    ok(client.delete(f"/api/v1/services/{service['id']}"), 204)

    # Offer
    start = date.today()
    r = client.post(
        "/api/v1/offers",
        json={
            "hotel_id": hid,
            "name": uid("Offer"),
            "description": "Test offer",
            "discount_type": "PERCENT",
            "discount_value": 10,
            "valid_from": str(start),
            "valid_until": str(start + timedelta(days=30)),
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    offer = r.json()
    ok(client.get("/api/v1/offers"), 200)
    ok(client.get(f"/api/v1/offers/{offer['id']}"), 200)
    ok(client.patch(f"/api/v1/offers/{offer['id']}", json={"discount_value": 15}), 200)
    ok(client.delete(f"/api/v1/offers/{offer['id']}"), 204)

    # Negotiation rule
    r = client.post(
        "/api/v1/negotiation-rules",
        json={
            "hotel_id": hid,
            "room_id": rid,
            "is_enabled": True,
            "minimum_price": 2500,
            "maximum_discount_percent": 20,
            "requires_approval": False,
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    rule = r.json()
    ok(client.get("/api/v1/negotiation-rules"), 200)
    ok(client.get(f"/api/v1/negotiation-rules/{rule['id']}"), 200)
    ok(
        client.patch(
            f"/api/v1/negotiation-rules/{rule['id']}", json={"maximum_discount_percent": 15}
        ),
        200,
    )
    ok(client.delete(f"/api/v1/negotiation-rules/{rule['id']}"), 204)

    # Guest
    r = client.post(
        "/api/v1/guests",
        json={
            "hotel_id": hid,
            "name": uid("Guest"),
            "phone": "8888888888",
            "email": f"{uuid4().hex[:8]}@example.com",
            "nationality": "Indian",
            "preferences": "Quiet room",
            "notes": "Test",
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    guest = r.json()
    gid = guest["id"]
    ok(client.get("/api/v1/guests"), 200)
    ok(client.get(f"/api/v1/guests/{gid}"), 200)
    ok(client.patch(f"/api/v1/guests/{gid}", json={"notes": "Updated"}), 200)

    # Booking
    check_in = date.today() + timedelta(days=40)
    r = client.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hid,
            "guest_id": gid,
            "room_id": rid,
            "check_in": str(check_in),
            "check_out": str(check_in + timedelta(days=2)),
            "number_of_guests": 2,
            "final_price": 7000,
            "booking_status": "CONFIRMED",
        },
    )
    ok(r, 200, 201)
    booking = r.json()
    ok(client.get("/api/v1/bookings"), 200)
    ok(client.get(f"/api/v1/bookings/{booking['id']}"), 200)
    ok(client.patch(f"/api/v1/bookings/{booking['id']}", json={"booking_status": "CANCELLED"}), 200)

    # Menu + order + order item
    r = client.post(
        "/api/v1/menu-items",
        json={
            "hotel_id": hid,
            "name": uid("Test Pizza"),
            "description": "Test food",
            "category": "pizza",
            "price": 399,
            "is_available": True,
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    menu = r.json()
    mid = menu["id"]
    ok(client.get("/api/v1/menu-items"), 200)
    ok(client.get(f"/api/v1/menu-items/{mid}"), 200)
    ok(client.patch(f"/api/v1/menu-items/{mid}", json={"price": 449}), 200)

    r = client.post(
        "/api/v1/orders",
        json={
            "hotel_id": hid,
            "guest_id": gid,
            "order_type": "TAKEAWAY",
            "table_number": None,
            "status": "PENDING",
            "total_amount": 0,
            "is_active": True,
        },
    )
    ok(r, 200, 201)
    order = r.json()
    oid = order["id"]
    ok(client.get("/api/v1/orders"), 200)
    ok(client.get(f"/api/v1/orders/{oid}"), 200)

    r = client.post(
        "/api/v1/order-items",
        json={
            "order_id": oid,
            "menu_item_id": mid,
            "quantity": 2,
            "unit_price": 399,
            "customization": "No onion",
        },
    )
    ok(r, 200, 201)
    item = r.json()
    assert float(item["subtotal"]) == 898
    assert float(client.get(f"/api/v1/orders/{oid}").json()["total_amount"]) == 898

    ok(client.patch(f"/api/v1/orders/{oid}", json={"status": "CONFIRMED"}), 200)
    ok(client.patch(f"/api/v1/order-items/{item['id']}", json={"quantity": 3}), 200)
    assert float(client.get(f"/api/v1/orders/{oid}").json()["total_amount"]) == 1347
    ok(client.delete(f"/api/v1/order-items/{item['id']}"), 204)
    ok(client.delete(f"/api/v1/orders/{oid}"), 204)

    # Basic negative checks
    ok(client.get("/api/v1/hotels/999999999"), 404)
    ok(client.get("/api/v1/rooms/999999999"), 404)
    ok(client.get("/api/v1/rates/999999999"), 404)
    ok(
        client.post(
            "/api/v1/rates",
            json={
                "room_id": rid,
                "date": str(future + timedelta(days=1)),
                "price": 0,
                "currency": "INR",
                "is_active": True,
            },
        ),
        422,
    )
