"""Regression test for the dashboard Hotel Settings → Hotel profile save.

The settings form PATCHes the full profile (address, phone, email,
check-in/check-out times included). A live bug report claimed those fields
did not persist; the break turned out to be in the dashboard form's
client-side validation (see MASTER_BUILD_REPORT.md), but the endpoint's
persistence contract is pinned here end-to-end: PATCH, re-read through the
API, and verify the database row itself.
"""

from app.db.session import SessionLocal
from app.models.hotel import Hotel
from tests._helpers import client, make_hotel, ok

PROFILE = {
    "address": "12, Pearl Tower, C-Scheme, Jaipur, Rajasthan 302001",
    "phone": "+91 141 400 2233",
    "email": "reservations@stayflowgrand.example",
    "check_in_time": "14:00",
    "check_out_time": "11:00",
}


def test_hotel_profile_update_persists_all_fields():
    hotel = make_hotel()
    hid = hotel["id"]
    # Freshly created hotels start with the profile fields empty.
    assert hotel["address"] is None
    assert hotel["phone"] is None
    assert hotel["email"] is None
    assert hotel["check_in_time"] is None
    assert hotel["check_out_time"] is None

    # Exactly what the settings form sends on Save.
    payload = {
        "name": hotel["name"],
        "description": "Updated from the settings form",
        "city": hotel["city"],
        **PROFILE,
        "timezone": "Asia/Kolkata",
        "currency": "INR",
        "is_active": True,
    }
    response = client.patch(f"/api/v1/hotels/{hid}", json=payload)
    ok(response, 200)
    body = response.json()
    for field, expected in PROFILE.items():
        assert body[field] == expected, f"PATCH response: {field}={body[field]!r}"

    # Re-read through the API, as the dashboard does after invalidating
    # its cached hotel query.
    response = client.get(f"/api/v1/hotels/{hid}")
    ok(response, 200)
    body = response.json()
    for field, expected in PROFILE.items():
        assert body[field] == expected, f"GET after PATCH: {field}={body[field]!r}"
    assert body["description"] == "Updated from the settings form"

    # And the database row itself, so a response-echo bug cannot hide here.
    db = SessionLocal()
    try:
        row = db.get(Hotel, hid)
        assert row is not None
        assert row.address == PROFILE["address"]
        assert row.phone == PROFILE["phone"]
        assert row.email == PROFILE["email"]
        assert row.check_in_time == PROFILE["check_in_time"]
        assert row.check_out_time == PROFILE["check_out_time"]
    finally:
        db.close()


def test_hotel_profile_update_rejects_invalid_times():
    hotel = make_hotel()
    hid = hotel["id"]
    for field in ("check_in_time", "check_out_time"):
        response = client.patch(f"/api/v1/hotels/{hid}", json={field: "25:99"})
        ok(response, 422)
    # The rejected updates must not have modified the stored values.
    response = client.get(f"/api/v1/hotels/{hid}")
    ok(response, 200)
    assert response.json()["check_in_time"] is None
    assert response.json()["check_out_time"] is None
