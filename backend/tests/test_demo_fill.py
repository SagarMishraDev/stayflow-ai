"""Tests for app/demo_fill.py — the env-gated analytics demo batch.

Runs against a throwaway SQLite file in tmp_path. A fixed ``today``
keeps the 24-month window deterministic. The fixture hotel mirrors
scripts/seed_demo.py's "StayFlow Grand Hotel" (same three room types)
plus one pre-existing NORMAL booking + payment that the purge must
never touch.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

TODAY = date(2026, 10, 23)

ROOM_TYPES = [
    ("Deluxe King Room", 2, 20),
    ("Executive Twin Room", 2, 15),
    ("Heritage Suite", 4, 6),
]


@pytest.fixture()
def db(tmp_path):
    import app.models  # noqa: F401  (registers every model on Base)
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path}/demo_fill.db")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def hotel(db):
    from app.models.hotel import Hotel
    from app.models.room import Room

    hotel = Hotel(name="StayFlow Grand Hotel", city="Jaipur", email="stay@example.com")
    db.add(hotel)
    db.flush()
    for room_type, capacity, total_rooms in ROOM_TYPES:
        db.add(
            Room(
                hotel_id=hotel.id,
                room_type=room_type,
                capacity=capacity,
                total_rooms=total_rooms,
                is_active=True,
            )
        )
    db.commit()
    return hotel


@pytest.fixture()
def normal_booking(db, hotel):
    """A pre-existing, non-batch booking + captured payment."""
    from app.models.booking import Booking
    from app.models.guest import Guest
    from app.models.payment import Payment
    from app.models.room import Room

    room = db.scalars(select(Room).where(Room.hotel_id == hotel.id)).first()
    guest = Guest(hotel_id=hotel.id, name="Real Guest", email="real.guest@example.com")
    db.add(guest)
    db.flush()
    booking = Booking(
        hotel_id=hotel.id,
        guest_id=guest.id,
        room_id=room.id,
        check_in=date(2026, 10, 1),
        check_out=date(2026, 10, 3),
        number_of_guests=2,
        final_price=Decimal("9000"),
        booking_status="CHECKED_OUT",
        source="direct",
    )
    db.add(booking)
    db.flush()
    payment = Payment(
        hotel_id=hotel.id,
        booking_id=booking.id,
        amount=Decimal("9000"),
        method="card",
        status="captured",
        reference="REAL-001",
    )
    db.add(payment)
    db.commit()
    return booking


def _batch_rows(db, hotel):
    from app.models.booking import Booking
    from app.models.guest import Guest
    from app.models.payment import Payment

    guests = list(
        db.scalars(
            select(Guest).where(
                Guest.hotel_id == hotel.id, Guest.email.like("demofill.guest%@demo.example")
            )
        ).all()
    )
    guest_ids = [g.id for g in guests]
    bookings = []
    if guest_ids:
        bookings = list(
            db.scalars(select(Booking).where(Booking.guest_id.in_(guest_ids))).all()
        )
    payments = []
    if bookings:
        payments = list(
            db.scalars(
                select(Payment).where(Payment.booking_id.in_([b.id for b in bookings]))
            ).all()
        )
    return guests, bookings, payments


def test_fill_creates_spread_batch(db, hotel):
    from app.demo_fill import fill_demo_bookings

    stats = fill_demo_bookings(db, hotel, count=48, today=TODAY)
    assert stats["already_filled"] is False
    assert stats["bookings"] >= 48

    guests, bookings, payments = _batch_rows(db, hotel)
    assert len(bookings) == stats["bookings"]
    assert guests and all(g.email.endswith("@demo.example") for g in guests)

    months = {}
    for booking in bookings:
        months.setdefault((booking.check_in.year, booking.check_in.month), 0)
        months[(booking.check_in.year, booking.check_in.month)] += 1
    assert len(months) >= 24
    assert all(n >= 1 for n in months.values())

    assert len({b.booking_status for b in bookings}) >= 3
    assert len({b.source for b in bookings}) >= 3
    assert all(b.check_out > b.check_in for b in bookings)
    assert payments, "expected payments for the batch"
    assert all(p.reference.startswith("DEMO-FILL-") for p in payments)
    assert any(p.status == "refunded" for p in payments)


def test_fill_is_idempotent(db, hotel):
    from app.demo_fill import fill_demo_bookings

    first = fill_demo_bookings(db, hotel, count=48, today=TODAY)
    second = fill_demo_bookings(db, hotel, count=48, today=TODAY)
    assert second["already_filled"] is True
    assert second["bookings"] == 0
    assert second["existing_bookings"] == first["bookings"]
    _guests, bookings, _payments = _batch_rows(db, hotel)
    assert len(bookings) == first["bookings"]


def test_purge_removes_only_the_batch(db, hotel, normal_booking):
    from app.demo_fill import fill_demo_bookings, purge_demo_bookings
    from app.models.booking import Booking
    from app.models.payment import Payment

    fill = fill_demo_bookings(db, hotel, count=48, today=TODAY)
    result = purge_demo_bookings(db, hotel)
    assert result["bookings"] == fill["bookings"]
    assert result["payments"] == fill["payments"]
    assert result["guests"] == fill["guests_created"]
    assert result["guests_kept_referenced"] == 0

    guests, bookings, payments = _batch_rows(db, hotel)
    assert guests == [] and bookings == [] and payments == []

    # The pre-existing normal booking + its payment survive untouched.
    survivor = db.get(Booking, normal_booking.id)
    assert survivor is not None
    assert survivor.booking_status == "CHECKED_OUT"
    remaining = list(
        db.scalars(select(Payment).where(Payment.booking_id == normal_booking.id)).all()
    )
    assert len(remaining) == 1
    assert remaining[0].reference == "REAL-001"


def test_purge_without_batch_is_all_zeros(db, hotel, normal_booking):
    from app.demo_fill import purge_demo_bookings

    result = purge_demo_bookings(db, hotel)
    assert result["payments"] == 0
    assert result["bookings"] == 0
    assert result["guests"] == 0
    assert result["guests_kept_referenced"] == 0
