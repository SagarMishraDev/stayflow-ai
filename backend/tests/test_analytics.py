"""Phase 4 (HMS upgrade): analytics aggregations against known fixtures.

All expected numbers are computed by hand from the fixture rows and the
accounting rules in HMS_UPGRADE_REPORT.md (earned revenue by check-in
date, non-cancelled only; collected/refunds from payment rows).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.booking import Booking
from app.models.payment import Payment
from tests._helpers import client, make_guest, make_hotel, make_room, ok


def _booking(db, hotel_id, guest_id, room_id, check_in, check_out, price, status, created):
    row = Booking(
        hotel_id=hotel_id,
        guest_id=guest_id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        number_of_guests=2,
        final_price=Decimal(price),
        booking_status=status,
        created_at=datetime(created.year, created.month, created.day, tzinfo=UTC),
    )
    db.add(row)
    db.flush()
    return row


def _payment(db, hotel_id, booking_id, amount, method, status, created):
    row = Payment(
        hotel_id=hotel_id,
        booking_id=booking_id,
        amount=Decimal(amount),
        method=method,
        status=status,
        created_at=datetime(created.year, created.month, created.day, tzinfo=UTC),
    )
    db.add(row)
    db.flush()
    return row


def _fixtures():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    deluxe = make_room(hotel["id"], room_type="Deluxe", capacity=2, total_rooms=5)
    standard = make_room(hotel["id"], room_type="Standard", capacity=2, total_rooms=10)
    make_room(hotel["id"], room_type="Suite", capacity=4, total_rooms=2)
    db = next(get_db())
    try:
        b1 = _booking(
            db,
            hotel["id"],
            guest["id"],
            deluxe["id"],
            date(2026, 10, 10),
            date(2026, 10, 12),
            "8000",
            "CONFIRMED",
            date(2026, 10, 1),
        )
        b2 = _booking(
            db,
            hotel["id"],
            guest["id"],
            deluxe["id"],
            date(2026, 10, 20),
            date(2026, 10, 21),
            "4000",
            "CONFIRMED",
            date(2026, 10, 19),
        )
        _booking(
            db,
            hotel["id"],
            guest["id"],
            standard["id"],
            date(2026, 10, 5),
            date(2026, 10, 7),
            "3000",
            "CANCELLED",
            date(2026, 10, 2),
        )
        _booking(
            db,
            hotel["id"],
            guest["id"],
            standard["id"],
            date(2026, 9, 15),
            date(2026, 9, 17),
            "5000",
            "CONFIRMED",
            date(2026, 9, 1),
        )
        _payment(db, hotel["id"], b1.id, "8000", "upi", "captured", date(2026, 10, 10))
        _payment(db, hotel["id"], b2.id, "2000", "card", "captured", date(2026, 10, 20))
        _payment(db, hotel["id"], b1.id, "500", "upi", "refunded", date(2026, 10, 11))
        db.commit()
    finally:
        db.close()
    return hotel


OCT = {"range": "custom", "start": "2026-10-01", "end": "2026-10-31"}


def test_kpi_overview_matches_hand_computed_values():
    hotel = _fixtures()
    r = client.get("/api/v1/analytics/overview", params={"hotel_id": hotel["id"], **OCT})
    ok(r, 200)
    kpi = r.json()
    assert kpi["total_revenue"] == "12000"
    assert kpi["revenue_collected"] == "10000"
    assert kpi["pending_payments"] == "2000"
    assert kpi["refunds"] == "500"
    assert kpi["total_bookings"] == 3
    assert kpi["confirmed_bookings"] == 2
    assert kpi["cancelled_bookings"] == 1
    assert kpi["occupied_room_nights"] == 3
    assert kpi["available_room_nights"] == 17 * 31
    assert kpi["adr"] == "4000"
    assert round(float(kpi["revpar"]), 2) == round(12000 / (17 * 31), 2)
    assert kpi["average_booking_value"] == "6000"
    assert round(float(kpi["average_daily_revenue"]), 2) == round(12000 / 31, 2)


def test_revenue_series_buckets_by_check_in_date():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/series",
        params={"hotel_id": hotel["id"], "group_by": "day", **OCT},
    )
    ok(r, 200)
    by_day = {row["period"]: row for row in r.json()["series"]}
    assert by_day["2026-10-10"]["revenue"] == "8000"
    assert by_day["2026-10-20"]["revenue"] == "4000"
    # Cancelled booking contributes neither revenue nor a booking count.
    assert "2026-10-05" not in by_day or by_day["2026-10-05"]["revenue"] == "0"


def test_compare_periods_with_zero_baseline_is_safe():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/compare",
        params={
            "hotel_id": hotel["id"],
            "range_a": "custom",
            "a_start": "2026-10-01",
            "a_end": "2026-10-31",
            "range_b": "custom",
            "b_start": "2026-08-01",
            "b_end": "2026-08-31",
        },
    )
    ok(r, 200)
    body = r.json()
    assert body["current"]["total_revenue"] == "12000"
    assert body["previous"]["total_revenue"] == "0"
    # Zero baseline: percentage is null, never a misleading infinity.
    assert body["deltas"]["revenue_pct"] is None
    assert body["deltas"]["revenue_diff"] == "12000"


def test_breakdowns_by_category_method_status():
    hotel = _fixtures()
    r = client.get("/api/v1/analytics/breakdowns", params={"hotel_id": hotel["id"], **OCT})
    ok(r, 200)
    body = r.json()
    categories = {row["key"]: row for row in body["by_room_category"]}
    assert categories["Deluxe"]["revenue"] == "12000"
    assert "Standard" not in categories  # only a cancelled booking
    methods = {row["key"]: row for row in body["by_payment_method"]}
    assert methods["upi"]["revenue"] == "8000"
    assert methods["card"]["revenue"] == "2000"
    statuses = {row["key"]: row for row in body["by_booking_status"]}
    assert statuses["CANCELLED"]["bookings"] == 0  # stays-based, documented


def test_room_popularity_ties_and_zero_booking_rooms():
    hotel = _fixtures()
    r = client.get("/api/v1/analytics/room-popularity", params={"hotel_id": hotel["id"], **OCT})
    ok(r, 200)
    body = r.json()
    rows = {row["room_type"]: row for row in body["rooms"]}
    assert rows["Deluxe"]["bookings"] == 2
    assert rows["Deluxe"]["revenue"] == "12000"
    assert rows["Standard"]["bookings"] == 0
    assert rows["Suite"]["bookings"] == 0  # zero-booking rooms still appear
    assert [r["room_type"] for r in body["most_booked"]] == ["Deluxe"]
    # Least is a tie and BOTH tied rooms are reported.
    assert {r["room_type"] for r in body["least_booked"]} == {"Standard", "Suite"}


def test_csv_export_matches_filters():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/export",
        params={"hotel_id": hotel["id"], "dataset": "series", **OCT},
    )
    ok(r, 200)
    text = r.text
    assert text.startswith("period,revenue,bookings")
    assert "2026-10-10,8000" in text
    assert "2026-09-15" not in text  # outside the selected range


def test_analytics_requires_authentication():
    hotel = _fixtures()
    plain = TestClient(app)
    r = plain.get("/api/v1/analytics/overview", params={"hotel_id": hotel["id"]})
    assert r.status_code == 401


def test_record_and_list_payments():
    hotel = _fixtures()
    db = next(get_db())
    try:
        booking = (
            db.query(Booking).filter(Booking.hotel_id == hotel["id"]).order_by(Booking.id).first()
        )
        booking_id = booking.id
    finally:
        db.close()
    r = client.post(
        "/api/v1/payments",
        json={
            "hotel_id": hotel["id"],
            "booking_id": booking_id,
            "amount": "1500",
            "method": "cash",
            "status": "captured",
        },
    )
    ok(r, 201)
    r = client.get(
        "/api/v1/payments",
        params={"hotel_id": hotel["id"], "booking_id": booking_id},
    )
    ok(r, 200)
    amounts = {float(row["amount"]) for row in r.json()}
    assert 1500.0 in amounts


def _audit(db, hotel_id, action, booking_id, when):
    from app.models.audit_log import AuditLog

    db.add(
        AuditLog(
            hotel_id=hotel_id,
            actor_type="staff",
            actor_id=None,
            action=action,
            entity_type="booking",
            entity_id=booking_id,
            created_at=when,
        )
    )
    db.flush()


def test_activity_feed_merges_booking_and_payment_events():
    hotel = _fixtures()
    db = next(get_db())
    try:
        bookings = (
            db.query(Booking)
            .filter(Booking.hotel_id == hotel["id"])
            .order_by(Booking.id)
            .all()
        )
        b1, b2, b3 = bookings[0], bookings[1], bookings[2]
        _audit(
            db,
            hotel["id"],
            "booking.created",
            b2.id,
            datetime(2026, 10, 19, 10, 30, tzinfo=UTC),
        )
        _audit(
            db,
            hotel["id"],
            "booking.cancelled",
            b3.id,
            datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
        )
        db.commit()
        b2_id, b3_id = b2.id, b3.id
    finally:
        db.close()

    r = client.get(
        "/api/v1/analytics/activity", params={"hotel_id": hotel["id"], "limit": 50}
    )
    ok(r, 200)
    events = r.json()["events"]
    assert events, "expected a non-empty activity feed"
    # Newest first: the 2026-10-20 captured payment leads.
    assert events[0]["kind"] == "payment_received"
    assert events[0]["amount"] == "2000"
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)
    kinds = [e["kind"] for e in events]
    assert "refund_processed" in kinds  # the 2026-10-11 refunded payment
    assert "booking_cancelled" in kinds  # from the audit row
    # The audited booking appears exactly once as a created/confirmed event
    # (no duplicate fallback row for the same booking).
    b2_created = [
        e
        for e in events
        if e["reference"] == f"#{b2_id}" and e["kind"] == "booking_confirmed"
    ]
    assert len(b2_created) == 1
    # Every event carries the display fields the dashboard renders.
    for e in events:
        assert e["title"] and e["reference"].startswith("#") and e["timestamp"]
    assert b3_id  # silence unused; b3 covered via booking_cancelled above

    r = client.get("/api/v1/analytics/activity", params={"hotel_id": hotel["id"], "limit": 3})
    ok(r, 200)
    assert len(r.json()["events"]) == 3


def test_activity_feed_is_hotel_scoped_and_role_gated():
    hotel = _fixtures()
    other = make_hotel()

    r = client.get(
        "/api/v1/analytics/activity", params={"hotel_id": other["id"], "limit": 50}
    )
    ok(r, 200)
    assert r.json()["events"] == []  # no leakage from the fixture hotel

    # Unauthenticated -> 401.
    plain = TestClient(app)
    r = plain.get("/api/v1/analytics/activity", params={"hotel_id": hotel["id"]})
    assert r.status_code == 401

    # A kitchen user of the same hotel lacks analytics.view -> 403.
    from app.core.security import create_access_token, hash_password
    from app.db.session import SessionLocal
    from app.models.hotel_user import HotelUser

    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel["id"],
            name="Activity Kitchen",
            email=f"activity-kitchen-{hotel['id']}@example.com",
            role="kitchen",
            password_hash=hash_password("activity-pass-123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(
            hotel_user_id=user.id, hotel_id=user.hotel_id, role=user.role
        )
    finally:
        db.close()
    r = plain.get(
        "/api/v1/analytics/activity",
        params={"hotel_id": hotel["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
