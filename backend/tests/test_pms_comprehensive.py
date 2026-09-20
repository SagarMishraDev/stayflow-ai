from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def assert_status(response, *expected: int) -> None:
    assert response.status_code in expected, (
        f"Expected {expected}, got {response.status_code}: {response.text}"
    )


def create_hotel(name_prefix: str = "Comprehensive Test Hotel") -> dict:
    response = client.post(
        "/api/v1/hotels",
        json={
            "name": uid(name_prefix),
            "city": "Jaipur",
            "description": "Automated comprehensive PMS test",
            "address": "Test Address",
            "phone": "7777777777",
            "email": f"{uuid4().hex[:8]}@example.com",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
            "is_active": True,
        },
    )
    assert_status(response, 201)
    return response.json()


def create_room(hotel_id: int, capacity: int = 2) -> dict:
    response = client.post(
        "/api/v1/rooms",
        json={
            "hotel_id": hotel_id,
            "room_type": uid("Deluxe"),
            "description": "Automated test room",
            "capacity": capacity,
            "total_rooms": 5,
            "amenities": "WiFi, AC",
            "is_active": True,
        },
    )
    assert_status(response, 201)
    return response.json()


def create_guest(hotel_id: int) -> dict:
    response = client.post(
        "/api/v1/guests",
        json={
            "hotel_id": hotel_id,
            "name": uid("Guest"),
            "phone": "8888888888",
            "email": f"{uuid4().hex[:8]}@example.com",
            "nationality": "Indian",
            "preferences": "Quiet room",
            "notes": "Automated test guest",
            "is_active": True,
        },
    )
    assert_status(response, 201)
    return response.json()


def test_system_endpoints():
    response = client.get("/api/v1/health")
    assert_status(response, 200)
    assert response.json()["status"] == "ok"

    response = client.get("/api/v1/db-check")
    assert_status(response, 200)


def test_hotel_crud_and_validation():
    hotel = create_hotel()
    hid = hotel["id"]

    response = client.get("/api/v1/hotels")
    assert_status(response, 200)
    assert any(item["id"] == hid for item in response.json())

    response = client.get(f"/api/v1/hotels/{hid}")
    assert_status(response, 200)
    assert response.json()["id"] == hid

    response = client.patch(
        f"/api/v1/hotels/{hid}",
        json={"phone": "9999999999", "description": "Updated hotel"},
    )
    assert_status(response, 200)
    assert response.json()["phone"] == "9999999999"

    assert_status(client.get("/api/v1/hotels/999999999"), 404)
    assert_status(
        client.post(
            "/api/v1/hotels",
            json={"city": "Jaipur"},
        ),
        422,
    )

    # Empty hotel can be deleted safely.
    empty_hotel = create_hotel("Delete Test Hotel")
    assert_status(client.delete(f"/api/v1/hotels/{empty_hotel['id']}"), 204)
    assert_status(client.get(f"/api/v1/hotels/{empty_hotel['id']}"), 404)


def test_room_crud_and_foreign_key_validation():
    hotel = create_hotel()
    hid = hotel["id"]
    room = create_room(hid)
    rid = room["id"]

    response = client.get("/api/v1/rooms")
    assert_status(response, 200)
    assert any(item["id"] == rid for item in response.json())

    response = client.get(f"/api/v1/rooms/{rid}")
    assert_status(response, 200)
    assert response.json()["hotel_id"] == hid

    response = client.patch(
        f"/api/v1/rooms/{rid}",
        json={"capacity": 3, "total_rooms": 7},
    )
    assert_status(response, 200)
    assert response.json()["capacity"] == 3
    assert response.json()["total_rooms"] == 7

    assert_status(client.get("/api/v1/rooms/999999999"), 404)

    assert_status(
        client.post(
            "/api/v1/rooms",
            json={
                "hotel_id": 999999999,
                "room_type": "Invalid",
                "capacity": 2,
                "total_rooms": 1,
            },
        ),
        404,
    )

    assert_status(client.delete(f"/api/v1/rooms/{rid}"), 204)
    assert_status(client.get(f"/api/v1/rooms/{rid}"), 404)


def test_rates_crud_and_validation():
    hotel = create_hotel()
    room = create_room(hotel["id"])
    rid = room["id"]
    target_date = date.today() + timedelta(days=30)

    response = client.post(
        "/api/v1/rates",
        json={
            "room_id": rid,
            "date": str(target_date),
            "price": 3500,
            "currency": "INR",
            "is_active": True,
        },
    )
    assert_status(response, 201)
    rate = response.json()
    rate_id = rate["id"]
    assert float(rate["price"]) == 3500

    assert_status(client.get("/api/v1/rates"), 200)
    assert_status(client.get(f"/api/v1/rates/{rate_id}"), 200)

    response = client.patch(
        f"/api/v1/rates/{rate_id}",
        json={"price": 3600},
    )
    assert_status(response, 200)
    assert float(response.json()["price"]) == 3600

    assert_status(client.delete(f"/api/v1/rates/{rate_id}"), 204)
    assert_status(client.get(f"/api/v1/rates/{rate_id}"), 404)

    assert_status(
        client.get("/api/v1/rates/999999999"),
        404,
    )
    assert_status(
        client.post(
            "/api/v1/rates",
            json={
                "room_id": 999999999,
                "date": str(target_date),
                "price": 3500,
                "currency": "INR",
                "is_active": True,
            },
        ),
        404,
    )
    assert_status(
        client.post(
            "/api/v1/rates",
            json={
                "room_id": rid,
                "date": str(target_date + timedelta(days=1)),
                "price": -1,
                "currency": "INR",
                "is_active": True,
            },
        ),
        422,
    )


def test_availability_crud_and_validation():
    hotel = create_hotel()
    room = create_room(hotel["id"])
    rid = room["id"]
    target_date = date.today() + timedelta(days=31)

    response = client.post(
        "/api/v1/availability",
        json={
            "room_id": rid,
            "date": str(target_date),
            "available_rooms": 5,
            "is_active": True,
        },
    )
    assert_status(response, 201)
    availability = response.json()
    aid = availability["id"]

    assert_status(client.get("/api/v1/availability"), 200)
    assert_status(client.get(f"/api/v1/availability/{aid}"), 200)

    response = client.patch(
        f"/api/v1/availability/{aid}",
        json={"available_rooms": 4},
    )
    assert_status(response, 200)
    assert response.json()["available_rooms"] == 4

    assert_status(client.delete(f"/api/v1/availability/{aid}"), 204)
    assert_status(client.get(f"/api/v1/availability/{aid}"), 404)

    assert_status(
        client.post(
            "/api/v1/availability",
            json={
                "room_id": 999999999,
                "date": str(target_date),
                "available_rooms": 1,
                "is_active": True,
            },
        ),
        404,
    )
    assert_status(
        client.post(
            "/api/v1/availability",
            json={
                "room_id": rid,
                "date": str(target_date + timedelta(days=1)),
                "available_rooms": -1,
                "is_active": True,
            },
        ),
        422,
    )


def test_policy_and_faq_crud():
    hotel = create_hotel()
    hid = hotel["id"]

    policy = client.post(
        "/api/v1/policies",
        json={
            "hotel_id": hid,
            "policy_type": "check_in",
            "title": "Check-in",
            "description": "After 2 PM",
            "is_active": True,
        },
    )
    assert_status(policy, 201)
    policy_id = policy.json()["id"]

    assert_status(client.get("/api/v1/policies"), 200)
    assert_status(client.get(f"/api/v1/policies/{policy_id}"), 200)
    assert_status(
        client.patch(
            f"/api/v1/policies/{policy_id}",
            json={"description": "After 3 PM"},
        ),
        200,
    )
    assert_status(client.delete(f"/api/v1/policies/{policy_id}"), 204)
    assert_status(client.get(f"/api/v1/policies/{policy_id}"), 404)

    faq = client.post(
        "/api/v1/faqs",
        json={
            "hotel_id": hid,
            "question": "What is check-in time?",
            "answer": "2 PM",
            "category": "check_in",
            "is_active": True,
        },
    )
    assert_status(faq, 201)
    faq_id = faq.json()["id"]

    assert_status(client.get("/api/v1/faqs"), 200)
    assert_status(client.get(f"/api/v1/faqs/{faq_id}"), 200)
    assert_status(
        client.patch(
            f"/api/v1/faqs/{faq_id}",
            json={"answer": "3 PM"},
        ),
        200,
    )
    assert_status(client.delete(f"/api/v1/faqs/{faq_id}"), 204)
    assert_status(client.get(f"/api/v1/faqs/{faq_id}"), 404)

    assert_status(
        client.post(
            "/api/v1/policies",
            json={
                "hotel_id": 999999999,
                "policy_type": "test",
                "title": "Invalid",
                "description": "Invalid",
            },
        ),
        404,
    )


def test_services_offers_and_negotiation_rules():
    hotel = create_hotel()
    hid = hotel["id"]
    room = create_room(hid)
    rid = room["id"]

    service = client.post(
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
    assert_status(service, 201)
    service_id = service.json()["id"]

    assert_status(client.get("/api/v1/services"), 200)
    assert_status(client.get(f"/api/v1/services/{service_id}"), 200)
    assert_status(
        client.patch(
            f"/api/v1/services/{service_id}",
            json={"price": 1500},
        ),
        200,
    )
    assert_status(client.delete(f"/api/v1/services/{service_id}"), 204)

    start = date.today()
    offer = client.post(
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
    assert_status(offer, 201)
    offer_id = offer.json()["id"]

    assert_status(client.get("/api/v1/offers"), 200)
    assert_status(client.get(f"/api/v1/offers/{offer_id}"), 200)
    assert_status(
        client.patch(
            f"/api/v1/offers/{offer_id}",
            json={"discount_value": 15},
        ),
        200,
    )
    assert_status(client.delete(f"/api/v1/offers/{offer_id}"), 204)

    rule = client.post(
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
    assert_status(rule, 201)
    rule_id = rule.json()["id"]

    assert_status(client.get("/api/v1/negotiation-rules"), 200)
    assert_status(client.get(f"/api/v1/negotiation-rules/{rule_id}"), 200)
    assert_status(
        client.patch(
            f"/api/v1/negotiation-rules/{rule_id}",
            json={"maximum_discount_percent": 15},
        ),
        200,
    )
    assert_status(client.delete(f"/api/v1/negotiation-rules/{rule_id}"), 204)

    assert_status(
        client.post(
            "/api/v1/negotiation-rules",
            json={
                "hotel_id": hid,
                "room_id": 999999999,
                "is_enabled": True,
                "minimum_price": 2500,
                "maximum_discount_percent": 20,
                "requires_approval": False,
                "is_active": True,
            },
        ),
        404,
    )


def test_guest_and_booking_workflows_and_validation():
    hotel = create_hotel()
    hid = hotel["id"]
    room = create_room(hid, capacity=2)
    rid = room["id"]
    guest = create_guest(hid)
    gid = guest["id"]

    assert_status(client.get("/api/v1/guests"), 200)
    assert_status(client.get(f"/api/v1/guests/{gid}"), 200)

    response = client.patch(
        f"/api/v1/guests/{gid}",
        json={"notes": "Updated guest notes"},
    )
    assert_status(response, 200)
    assert response.json()["notes"] == "Updated guest notes"

    check_in = date.today() + timedelta(days=40)
    check_out = check_in + timedelta(days=2)

    booking = client.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hid,
            "guest_id": gid,
            "room_id": rid,
            "check_in": str(check_in),
            "check_out": str(check_out),
            "number_of_guests": 2,
            "final_price": 7000,
            "booking_status": "CONFIRMED",
        },
    )
    assert_status(booking, 201)
    booking_id = booking.json()["id"]

    assert_status(client.get("/api/v1/bookings"), 200)
    assert_status(client.get(f"/api/v1/bookings/{booking_id}"), 200)

    response = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"booking_status": "CANCELLED"},
    )
    assert_status(response, 200)
    assert response.json()["booking_status"] == "CANCELLED"

    assert_status(client.get("/api/v1/guests/999999999"), 404)
    assert_status(client.get("/api/v1/bookings/999999999"), 404)

    # Invalid date range must be rejected.
    assert_status(
        client.post(
            "/api/v1/bookings",
            json={
                "hotel_id": hid,
                "guest_id": gid,
                "room_id": rid,
                "check_in": str(check_out),
                "check_out": str(check_in),
                "number_of_guests": 1,
                "final_price": 3000,
                "booking_status": "PENDING",
            },
        ),
        400,
        422,
    )

    # Exceeding room capacity must be rejected.
    assert_status(
        client.post(
            "/api/v1/bookings",
            json={
                "hotel_id": hid,
                "guest_id": gid,
                "room_id": rid,
                "check_in": str(check_in + timedelta(days=10)),
                "check_out": str(check_out + timedelta(days=10)),
                "number_of_guests": 3,
                "final_price": 3000,
                "booking_status": "PENDING",
            },
        ),
        400,
        422,
    )

    # Non-existent guest/room/hotel references must not create a booking.
    assert_status(
        client.post(
            "/api/v1/bookings",
            json={
                "hotel_id": hid,
                "guest_id": 999999999,
                "room_id": rid,
                "check_in": str(check_in + timedelta(days=20)),
                "check_out": str(check_out + timedelta(days=20)),
                "number_of_guests": 1,
                "final_price": 3000,
                "booking_status": "PENDING",
            },
        ),
        404,
    )


def test_menu_order_and_order_item_workflows():
    hotel = create_hotel()
    hid = hotel["id"]
    guest = create_guest(hid)
    gid = guest["id"]

    menu = client.post(
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
    assert_status(menu, 201)
    menu_id = menu.json()["id"]

    assert_status(client.get("/api/v1/menu-items"), 200)
    assert_status(client.get(f"/api/v1/menu-items/{menu_id}"), 200)

    response = client.patch(
        f"/api/v1/menu-items/{menu_id}",
        json={"price": 449},
    )
    assert_status(response, 200)
    assert float(response.json()["price"]) == 449

    order = client.post(
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
    assert_status(order, 201)
    order_id = order.json()["id"]

    assert_status(client.get("/api/v1/orders"), 200)
    assert_status(client.get(f"/api/v1/orders/{order_id}"), 200)

    # Current menu price is 449. The backend should use its trusted price,
    # rather than trusting an arbitrary client-supplied unit_price.
    item = client.post(
        "/api/v1/order-items",
        json={
            "order_id": order_id,
            "menu_item_id": menu_id,
            "quantity": 2,
            "unit_price": 1,
            "customization": "No onion",
        },
    )
    assert_status(item, 201)
    item_data = item.json()
    item_id = item_data["id"]

    assert float(item_data["unit_price"]) == 449
    assert float(item_data["subtotal"]) == 898
    assert float(
        client.get(f"/api/v1/orders/{order_id}").json()["total_amount"]
    ) == 898

    assert_status(client.get("/api/v1/order-items"), 200)
    assert_status(client.get(f"/api/v1/order-items/{item_id}"), 200)

    response = client.patch(
        f"/api/v1/order-items/{item_id}",
        json={"quantity": 3},
    )
    assert_status(response, 200)
    assert float(response.json()["subtotal"]) == 1347

    assert float(
        client.get(f"/api/v1/orders/{order_id}").json()["total_amount"]
    ) == 1347

    assert_status(
        client.patch(
            f"/api/v1/orders/{order_id}",
            json={"status": "CONFIRMED"},
        ),
        200,
    )

    assert_status(client.delete(f"/api/v1/order-items/{item_id}"), 204)
    assert float(
        client.get(f"/api/v1/orders/{order_id}").json()["total_amount"]
    ) == 0

    assert_status(client.delete(f"/api/v1/orders/{order_id}"), 204)
    assert_status(client.get(f"/api/v1/orders/{order_id}"), 404)

    # Invalid order/menu references.
    assert_status(
        client.post(
            "/api/v1/order-items",
            json={
                "order_id": 999999999,
                "menu_item_id": menu_id,
                "quantity": 1,
                "unit_price": 449,
            },
        ),
        404,
    )

    assert_status(
        client.post(
            "/api/v1/order-items",
            json={
                "order_id": 999999999,
                "menu_item_id": 999999999,
                "quantity": 1,
                "unit_price": 449,
            },
        ),
        404,
    )

    assert_status(client.delete(f"/api/v1/menu-items/{menu_id}"), 204)
    assert_status(client.get(f"/api/v1/menu-items/{menu_id}"), 404)


def test_cross_hotel_isolation():
    hotel_a = create_hotel("Isolation Hotel A")
    hotel_b = create_hotel("Isolation Hotel B")

    room_a = create_room(hotel_a["id"])
    guest_a = create_guest(hotel_a["id"])

    # A room belonging to hotel A must not be accepted as hotel B's room.
    response = client.post(
        "/api/v1/guests",
        json={
            "hotel_id": hotel_b["id"],
            "name": uid("Cross Hotel Guest"),
            "phone": "8111111111",
            "email": f"{uuid4().hex[:8]}@example.com",
            "is_active": True,
        },
    )
    assert_status(response, 201)

    check_in = date.today() + timedelta(days=80)
    response = client.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hotel_b["id"],
            "guest_id": guest_a["id"],
            "room_id": room_a["id"],
            "check_in": str(check_in),
            "check_out": str(check_in + timedelta(days=1)),
            "number_of_guests": 1,
            "final_price": 3000,
            "booking_status": "PENDING",
        },
    )
    assert_status(response, 400, 404, 422)
