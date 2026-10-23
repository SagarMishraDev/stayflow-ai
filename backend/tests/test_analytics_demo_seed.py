"""Tests for scripts/seed_analytics_demo.py.

The seed runs against a throwaway SQLite file in tmp_path — never the
suite database, never a remote host. A fixed ``today`` keeps the
two-year window deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scripts.seed_analytics_demo import (
    UnsafeTargetError,
    assert_safe_target,
    cleanup_database,
    seed_database,
)

TODAY = date(2026, 10, 23)


def _url(tmp_path) -> str:
    return f"sqlite:///{tmp_path}/analytics_demo.db"


def test_seed_creates_bookings_spanning_two_years(tmp_path):
    summary = seed_database(_url(tmp_path), count=60, today=TODAY)
    assert summary["already_seeded"] is False
    assert summary["total_bookings"] >= 60
    assert summary["distinct_bookings"] == summary["total_bookings"]
    assert len(summary["per_year"]) >= 2
    assert summary["checks"]["at_least_three_sources"]
    assert summary["checks"]["refunds_present"]
    assert summary["checks"]["zero_booking_type_in_some_month"]


def test_seed_is_idempotent(tmp_path):
    url = _url(tmp_path)
    first = seed_database(url, count=60, today=TODAY)
    second = seed_database(url, count=60, today=TODAY)
    assert second["already_seeded"] is True
    assert second["inserted"] == 0
    assert second["total_bookings"] == first["total_bookings"]


def test_cleanup_removes_only_the_demo_hotel(tmp_path):
    url = _url(tmp_path)
    summary = seed_database(url, count=60, today=TODAY)

    # An unrelated hotel + booking in the SAME database.
    import app.models  # noqa: F401
    from app.db.base import Base
    from app.models.booking import Booking
    from app.models.guest import Guest
    from app.models.hotel import Hotel
    from app.models.room import Room

    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        other = Hotel(name="Unrelated Hotel", city="Elsewhere", email="real@example.com")
        db.add(other)
        db.flush()
        room = Room(hotel_id=other.id, room_type="Standard", capacity=2, total_rooms=3)
        guest = Guest(hotel_id=other.id, name="Real Guest", email="real.guest@example.com")
        db.add_all([room, guest])
        db.flush()
        db.add(
            Booking(
                hotel_id=other.id,
                guest_id=guest.id,
                room_id=room.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 3),
                number_of_guests=1,
                final_price=Decimal("7000"),
                booking_status="CONFIRMED",
            )
        )
        db.commit()
        other_id = other.id
    finally:
        db.close()

    result = cleanup_database(url)
    assert result["found"] is True
    assert result["deleted"]["bookings"] == summary["total_bookings"]

    db = sessionmaker(bind=engine)()
    try:
        assert db.get(Hotel, summary["hotel_id"]) is None  # demo hotel gone
        assert db.get(Hotel, other_id) is not None  # unrelated hotel intact
        remaining = db.scalars(select(Booking).where(Booking.hotel_id == other_id)).all()
        assert len(remaining) == 1
    finally:
        db.close()
        engine.dispose()


def test_seed_refuses_production_looking_targets(tmp_path):
    with pytest.raises(UnsafeTargetError):
        seed_database(
            "postgresql+psycopg://u:p@ep-x.us-east-2.aws.neon.tech/db", count=5, today=TODAY
        )
    with pytest.raises(UnsafeTargetError):
        assert_safe_target("https://example.onrender.com/db")
    with pytest.raises(UnsafeTargetError):
        assert_safe_target(
            "postgresql+psycopg://u:p@db.internal.example.com/stayflow",
            app_database_url="postgresql+psycopg://u:p@db.internal.example.com/stayflow",
        )
    # Local targets are fine.
    assert_safe_target(_url(tmp_path))
    assert_safe_target("postgresql://u:p@localhost:5432/demo")


def test_seeded_data_flows_through_analytics_services(tmp_path):
    """The charts' data pipeline (analytics service functions) must see
    four distinct monthly revenue totals and per-type buckets."""
    from app.services import analytics as svc

    url = _url(tmp_path)
    summary = seed_database(url, count=520, today=TODAY)
    assert summary["checks"]["at_least_target_bookings"]

    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        hotel_id = summary["hotel_id"]
        # Four months ending Sep 2026: Jun–Sep 2026.
        totals = []
        for offset in (3, 2, 1, 0):
            first = date(2026, 9 - offset, 1)
            nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            rows = svc.revenue_series(
                db, hotel_id, first, nxt, group_by="month", today=TODAY
            )
            totals.append(sum(Decimal(r["revenue"]) for r in rows))
        assert len(set(totals)) == 4, f"expected 4 distinct monthly totals, got {totals}"
        assert all(t > 0 for t in totals)

        series = svc.popularity_series(
            db,
            hotel_id,
            date(2026, 9, 1),
            date(2026, 10, 1),
            group_by="day",
            today=TODAY,
        )
        assert len(series["buckets"]) == 30
        assert {row["room_type"] for row in series["room_types"]} == {
            "Deluxe King Room",
            "Executive Twin Room",
            "Heritage Suite",
        }
        # Bucket cells sum to the range totals per type.
        for row in series["room_types"]:
            cell_sum = sum(
                cell["bookings"]
                for bucket in series["buckets"]
                for cell in bucket["rooms"]
                if cell["room_type"] == row["room_type"]
            )
            assert cell_sum == row["bookings"]
    finally:
        db.close()
        engine.dispose()
