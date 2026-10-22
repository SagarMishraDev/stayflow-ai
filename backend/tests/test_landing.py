"""Public landing page payload tests.

Covers GET /api/v1/public/hotels/{public_id}/landing and
GET /api/v1/public/featured-hotel/landing: the payload aggregates only
the resolved hotel's own public content (rooms with real DB rates,
active offers, services, FAQs, policies, menu highlights), never leaks
another hotel's data, never exposes the internal integer hotel id, and
404s for unknown public ids. Also checks the landing page itself is
served at "/" without breaking the other mounted surfaces.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import reset_rate_limit_state
from app.db.session import SessionLocal
from app.main import app
from app.models.faq import FAQ
from app.models.hotel import Hotel
from app.models.menu_item import MenuItem
from app.models.offer import Offer
from app.models.policy import Policy
from app.models.rate import Rate
from app.models.room import Room
from app.models.service import Service

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


def _make_hotel_with_content(marker: str) -> Hotel:
    """Create a hotel plus one of each public content type, all carrying
    the unique ``marker`` so cross-hotel leakage is detectable by string."""
    today = date.today()
    with SessionLocal() as db:
        hotel = Hotel(
            name=f"Landing Hotel {marker}",
            city="Testville",
            description=f"A hotel about {marker}",
            address=f"1 {marker} Street",
            phone="+91 90000 00000",
            email=f"stay@{marker}.example",
            check_in_time="14:00",
            check_out_time="11:00",
        )
        db.add(hotel)
        db.flush()
        room = Room(
            hotel_id=hotel.id,
            room_type=f"{marker} Signature Room",
            description=f"Room for {marker}",
            capacity=3,
            total_rooms=4,
            amenities="Wi-Fi, Breakfast",
        )
        db.add(room)
        db.flush()
        db.add(
            Rate(
                room_id=room.id,
                date=today + timedelta(days=7),
                price=Decimal("7777.00"),
                currency="INR",
            )
        )
        db.add(
            Offer(
                hotel_id=hotel.id,
                name=f"{marker} Special Offer",
                description="Seasonal deal",
                discount_type="percentage",
                discount_value=Decimal("15"),
                valid_from=today - timedelta(days=1),
                valid_until=today + timedelta(days=30),
            )
        )
        db.add(
            Offer(  # expired — must NOT appear in the landing payload
                hotel_id=hotel.id,
                name=f"{marker} Expired Offer",
                description="Old deal",
                discount_type="percentage",
                discount_value=Decimal("50"),
                valid_from=today - timedelta(days=60),
                valid_until=today - timedelta(days=30),
            )
        )
        db.add(
            Service(
                hotel_id=hotel.id,
                name=f"{marker} Spa",
                description="Wellness",
                price=Decimal("1500"),
                category="wellness",
            )
        )
        db.add(
            FAQ(
                hotel_id=hotel.id,
                question=f"Question about {marker}?",
                answer=f"Answer about {marker}.",
                category="general",
            )
        )
        db.add(
            Policy(
                hotel_id=hotel.id,
                policy_type="cancellation",
                title=f"{marker} Cancellation Policy",
                description="Free cancellation up to 48 hours before check-in.",
            )
        )
        db.add(
            MenuItem(
                hotel_id=hotel.id,
                name=f"{marker} Thali",
                description="Signature dish",
                category="mains",
                price=Decimal("499"),
            )
        )
        db.add(
            MenuItem(  # unavailable — must NOT appear as a highlight
                hotel_id=hotel.id,
                name=f"{marker} Unavailable Dish",
                description="Not served today",
                category="mains",
                price=Decimal("299"),
                is_available=False,
            )
        )
        db.commit()
        db.refresh(hotel)
        db.expunge(hotel)
        return hotel


def _all_keys(node) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


def test_landing_payload_contains_own_rooms_offers_and_content():
    marker = uuid4().hex[:8]
    hotel = _make_hotel_with_content(marker)

    r = client.get(f"/api/v1/public/hotels/{hotel.public_id}/landing")
    assert r.status_code == 200, r.text
    payload = r.json()

    assert payload["hotel"]["public_id"] == hotel.public_id
    assert payload["hotel"]["name"] == f"Landing Hotel {marker}"
    assert payload["hotel"]["check_in_time"] == "14:00"
    assert payload["hotel"]["check_out_time"] == "11:00"
    assert payload["hotel"]["address"] == f"1 {marker} Street"

    rooms = payload["rooms"]
    assert len(rooms) == 1
    assert rooms[0]["room_type"] == f"{marker} Signature Room"
    assert rooms[0]["capacity"] == 3
    # Nightly rate comes from the real Rate row created above.
    assert Decimal(rooms[0]["nightly_rate"]) == Decimal("7777.00")
    assert rooms[0]["currency"] == "INR"

    offer_names = [o["name"] for o in payload["offers"]]
    assert offer_names == [f"{marker} Special Offer"]  # expired one excluded
    assert [s["name"] for s in payload["services"]] == [f"{marker} Spa"]
    assert payload["faqs"][0]["question"] == f"Question about {marker}?"
    assert payload["policies"][0]["policy_type"] == "cancellation"
    menu_names = [m["name"] for m in payload["menu_highlights"]]
    assert menu_names == [f"{marker} Thali"]  # unavailable dish excluded


def test_landing_payload_is_hotel_isolated():
    marker_a = uuid4().hex[:8]
    marker_b = uuid4().hex[:8]
    hotel_a = _make_hotel_with_content(marker_a)
    _make_hotel_with_content(marker_b)

    r = client.get(f"/api/v1/public/hotels/{hotel_a.public_id}/landing")
    assert r.status_code == 200, r.text
    blob = json.dumps(r.json())
    assert marker_a in blob
    assert marker_b not in blob


def test_landing_unknown_public_id_404():
    r = client.get(f"/api/v1/public/hotels/{uuid4().hex}/landing")
    assert r.status_code == 404
    # The internal integer id of a real hotel must not resolve either.
    hotel = _make_hotel_with_content(uuid4().hex[:8])
    r = client.get(f"/api/v1/public/hotels/{hotel.id}/landing")
    assert r.status_code == 404


def test_landing_payload_has_no_internal_hotel_id_anywhere():
    hotel = _make_hotel_with_content(uuid4().hex[:8])
    r = client.get(f"/api/v1/public/hotels/{hotel.public_id}/landing")
    assert r.status_code == 200, r.text
    payload = r.json()
    keys = _all_keys(payload)
    assert "hotel_id" not in keys
    assert "id" not in keys
    assert payload["hotel"]["public_id"] == hotel.public_id


def test_featured_hotel_landing_returns_a_valid_payload():
    hotel = _make_hotel_with_content(uuid4().hex[:8])
    r = client.get("/api/v1/public/featured-hotel/landing")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["hotel"]["public_id"]  # some active hotel resolved
    assert "rooms" in payload and "offers" in payload
    keys = _all_keys(payload)
    assert "hotel_id" not in keys and "id" not in keys
    # Sanity: the featured hotel is a real one — its own landing matches.
    featured_id = payload["hotel"]["public_id"]
    r2 = client.get(f"/api/v1/public/hotels/{featured_id}/landing")
    assert r2.status_code == 200
    assert r2.json()["hotel"]["name"] == payload["hotel"]["name"]
    assert hotel.public_id  # created hotel exists alongside


def test_landing_page_served_at_root_and_other_surfaces_intact():
    r = client.get("/")
    assert r.status_code == 200, r.text
    assert "landing" in r.text.lower()
    assert client.get("/landing/styles.css").status_code == 200
    assert client.get("/landing/app.js").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/widget.js").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
