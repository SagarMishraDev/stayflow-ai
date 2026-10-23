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
        b2, b3 = bookings[1], bookings[2]
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


# --------------------------------------------------------------------- #
# Rolling range presets + previous-period comparison (2026-10-23)       #
# --------------------------------------------------------------------- #
def test_resolve_range_rolling_presets():
    from app.services.analytics import resolve_range

    today = date(2026, 10, 23)
    # Last 7 days = today + the six days before it.
    assert resolve_range("last_7_days", today=today) == (date(2026, 10, 17), date(2026, 10, 24))
    # Last 30 days = today + the 29 days before it.
    assert resolve_range("last_30_days", today=today) == (date(2026, 9, 24), date(2026, 10, 24))
    # The endpoints accept the new keys too.
    hotel = _fixtures()
    for key in ("last_7_days", "last_30_days"):
        r = client.get(
            "/api/v1/analytics/overview", params={"hotel_id": hotel["id"], "range": key}
        )
        ok(r, 200)
        assert r.json()["period_days"] == (7 if key == "last_7_days" else 30)


def test_previous_period_bounds_math():
    from app.services.analytics import previous_period_bounds

    # 31-day October -> the 31 days ending where October starts.
    assert previous_period_bounds((date(2026, 10, 1), date(2026, 11, 1))) == (
        date(2026, 8, 31),
        date(2026, 10, 1),
    )
    import pytest

    with pytest.raises(ValueError):
        previous_period_bounds((None, None))


def test_compare_previous_period_uses_equal_length_window_before():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/compare",
        params={
            "hotel_id": hotel["id"],
            "range_a": "custom",
            "a_start": "2026-10-01",
            "a_end": "2026-10-31",
            "range_b": "previous_period",
        },
    )
    ok(r, 200)
    body = r.json()
    assert body["current"]["total_revenue"] == "12000"
    # Previous period = 2026-08-31..2026-10-01, which contains the
    # fixture's 2026-09-15 stay (₹5,000) and nothing else.
    assert body["previous"]["total_revenue"] == "5000"


# --------------------------------------------------------------------- #
# Popularity series (grouped bars)                                       #
# --------------------------------------------------------------------- #
def test_popularity_series_month_bucket_splits_by_room_type():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "month", **OCT},
    )
    ok(r, 200)
    body = r.json()
    assert body["period_days"] == 31
    assert [b["period"] for b in body["buckets"]] == ["2026-10"]
    cells = {c["room_type"]: c for c in body["buckets"][0]["rooms"]}
    assert cells["Deluxe"] == {"room_type": "Deluxe", "bookings": 2, "revenue": "12000"}
    # Zero-booking room types are present in the bucket, zero-filled.
    assert cells["Standard"]["bookings"] == 0
    assert cells["Suite"]["bookings"] == 0
    totals = {row["room_type"]: row for row in body["room_types"]}
    assert totals["Deluxe"]["bookings"] == 2
    assert totals["Deluxe"]["occupied_room_nights"] == 3
    assert totals["Deluxe"]["available_room_nights"] == 5 * 31
    assert totals["Deluxe"]["occupancy_rate"] == round(3 / 155 * 100, 2)


def test_popularity_series_day_and_week_bucket_boundaries():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "day", **OCT},
    )
    ok(r, 200)
    buckets = r.json()["buckets"]
    assert len(buckets) == 31
    assert buckets[0]["period"] == "2026-10-01"
    assert buckets[-1]["period"] == "2026-10-31"
    by_day = {b["period"]: {c["room_type"]: c for c in b["rooms"]} for b in buckets}
    assert by_day["2026-10-10"]["Deluxe"]["revenue"] == "8000"
    assert by_day["2026-10-20"]["Deluxe"]["bookings"] == 1
    # The cancelled Standard stay on 2026-10-05 contributes nothing.
    assert by_day["2026-10-05"]["Standard"]["bookings"] == 0

    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "week", **OCT},
    )
    ok(r, 200)
    weeks = r.json()["buckets"]
    # Weeks are Monday-keyed; Oct 2026 starts on a Thursday, so the
    # first bucket is Mon 2026-09-28 and the last Mon 2026-10-26.
    assert [b["period"] for b in weeks] == [
        "2026-09-28",
        "2026-10-05",
        "2026-10-12",
        "2026-10-19",
        "2026-10-26",
    ]
    by_week = {b["period"]: {c["room_type"]: c for c in b["rooms"]} for b in weeks}
    # Check-in Sat 2026-10-10 lands in the Mon 2026-10-05 bucket.
    assert by_week["2026-10-05"]["Deluxe"]["revenue"] == "8000"
    # Check-in Tue 2026-10-20 lands in the Mon 2026-10-19 bucket.
    assert by_week["2026-10-19"]["Deluxe"]["revenue"] == "4000"


def test_popularity_series_is_hotel_scoped_and_role_gated():
    hotel = _fixtures()
    other = make_hotel()

    # Same-hotel staff token against ANOTHER hotel -> 403 (not 404).
    from app.core.security import create_access_token, hash_password
    from app.db.session import SessionLocal
    from app.models.hotel_user import HotelUser

    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel["id"],
            name="Series Analyst",
            email=f"series-analyst-{hotel['id']}@example.com",
            role="hotel_admin",
            password_hash=hash_password("series-pass-123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(
            hotel_user_id=user.id, hotel_id=user.hotel_id, role=user.role
        )
    finally:
        db.close()
    plain = TestClient(app)
    r = plain.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": other["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    # Unauthenticated -> 401, and a bad group_by -> 422.
    r = plain.get("/api/v1/analytics/popularity-series", params={"hotel_id": hotel["id"]})
    assert r.status_code == 401
    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "hour", **OCT},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------- #
# Regression: wide-range totals and open-ended ("all") denominators     #
# (Analytics chart fixes, 2026-10-23)                                    #
# --------------------------------------------------------------------- #
def _wide_range_fixtures():
    """Three stays spread over ~17 months — beyond the 366-bucket cap."""
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    room = make_room(hotel["id"], room_type="Deluxe", capacity=2, total_rooms=5)
    db = next(get_db())
    try:
        for check_in, price in (
            (date(2025, 1, 5), "1000"),
            (date(2025, 6, 1), "2000"),
            (date(2026, 6, 1), "4000"),
        ):
            _booking(
                db,
                hotel["id"],
                guest["id"],
                room["id"],
                check_in,
                date(check_in.year, check_in.month, check_in.day + 2),
                price,
                "CONFIRMED",
                date(2024, 12, 1),
            )
        db.commit()
    finally:
        db.close()
    return hotel


def test_popularity_series_totals_cover_full_range_beyond_bucket_cap():
    hotel = _wide_range_fixtures()
    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "range": "all", "group_by": "day"},
    )
    ok(r, 200)
    body = r.json()
    # The rendered bucket list stays capped for payload size...
    assert len(body["buckets"]) == 366
    # ...but the range totals must cover ALL stays, including the one
    # checking in on 2026-06-01, far past the last rendered bucket.
    totals = {row["room_type"]: row for row in body["room_types"]}
    assert totals["Deluxe"]["bookings"] == 3
    assert totals["Deluxe"]["revenue"] == "7000"
    # And they must agree with the popularity endpoint for "all".
    r = client.get(
        "/api/v1/analytics/room-popularity",
        params={"hotel_id": hotel["id"], "range": "all"},
    )
    ok(r, 200)
    pop = {row["room_type"]: row for row in r.json()["rooms"]}
    assert pop["Deluxe"]["bookings"] == totals["Deluxe"]["bookings"]
    assert pop["Deluxe"]["revenue"] == totals["Deluxe"]["revenue"]


def test_kpi_overview_all_range_computes_real_denominators():
    hotel = _fixtures()
    r = client.get(
        "/api/v1/analytics/overview", params={"hotel_id": hotel["id"], "range": "all"}
    )
    ok(r, 200)
    body = r.json()
    # Fixture stays: ₹8,000 + ₹4,000 + ₹5,000 earned, 5 occupied nights.
    assert body["total_revenue"] == "17000"
    assert body["occupied_room_nights"] == 5
    # The open-ended range must still produce real denominators from
    # the hotel's activity window — never "of 0 room-nights".
    assert body["available_room_nights"] > 0
    assert body["occupancy_rate"] > 0
    assert Decimal(body["revpar"]) > 0
    assert Decimal(body["average_daily_revenue"]) > 0
    assert body["period_days"] > 0


def test_kpi_overview_all_range_empty_hotel_stays_zero():
    hotel = make_hotel()
    r = client.get(
        "/api/v1/analytics/overview", params={"hotel_id": hotel["id"], "range": "all"}
    )
    ok(r, 200)
    body = r.json()
    assert body["total_revenue"] == "0"
    assert body["available_room_nights"] == 0
    assert body["occupancy_rate"] == 0
    assert body["period_days"] == 0


def test_popularity_series_month_buckets_keep_years_distinct():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])
    room = make_room(hotel["id"], room_type="Deluxe", capacity=2, total_rooms=5)
    db = next(get_db())
    try:
        _booking(
            db, hotel["id"], guest["id"], room["id"],
            date(2025, 10, 10), date(2025, 10, 12), "1000", "CONFIRMED", date(2025, 10, 1),
        )
        _booking(
            db, hotel["id"], guest["id"], room["id"],
            date(2026, 10, 10), date(2026, 10, 12), "2000", "CONFIRMED", date(2026, 10, 1),
        )
        db.commit()
    finally:
        db.close()
    span = {"range": "custom", "start": "2025-01-01", "end": "2026-12-31"}
    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "month", **span},
    )
    ok(r, 200)
    buckets = r.json()["buckets"]
    periods = [b["period"] for b in buckets]
    # Same month name in different years stays two distinct buckets,
    # in chronological order (never merged into one "October").
    assert "2025-10" in periods and "2026-10" in periods
    assert periods == sorted(periods)
    by_period = {b["period"]: {c["room_type"]: c for c in b["rooms"]} for b in buckets}
    assert by_period["2025-10"]["Deluxe"]["revenue"] == "1000"
    assert by_period["2026-10"]["Deluxe"]["revenue"] == "2000"

    r = client.get(
        "/api/v1/analytics/popularity-series",
        params={"hotel_id": hotel["id"], "group_by": "week", **span},
    )
    ok(r, 200)
    week_periods = [b["period"] for b in r.json()["buckets"]]
    assert week_periods == sorted(week_periods)
    assert all(date.fromisoformat(p).weekday() == 0 for p in week_periods)
