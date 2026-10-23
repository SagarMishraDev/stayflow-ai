"""Env-gated demo data fill for the LIVE demo hotel (StayFlow Grand Hotel).

The public demo (``app.demo_main`` on Render + Neon) seeds only a small
showcase dataset, which leaves the Analytics graphs nearly empty. This
module adds ONE synthetic batch of ~180 realistic bookings (plus their
guests and payments) to the ALREADY-SEEDED demo hotel so the graphs
show meaningful shapes. The owner has explicitly approved filling the
live demo database with this batch; it exists only behind the
``ANALYTICS_DEMO_FILL`` environment switch (see
``app.demo_bootstrap.prepare_demo_database`` and ``docs/DEMO_FILL.md``)
and never runs in the normal application entrypoint.

BATCH MARKER — how every created row is found again for cleanup:

- **Guests**: created only by this module, with emails
  ``demofill.guestNNN@demo.example`` and names prefixed ``Demo Guest``.
- **Bookings**: the ``Booking`` model has no reference/notes column,
  so a batch booking is identified by its guest being a batch guest
  (hotel-scoped join). Booking ``source`` values stay realistic
  (direct / website / walk_in / agent_chat / unknown) on purpose.
- **Payments**: ``reference`` values are prefixed ``DEMO-FILL-``
  (matching the ``DEMO-`` convention of ``scripts/seed_analytics_demo``)
  in addition to belonging to a batch booking.

``purge_demo_bookings`` deletes exactly those rows — payments of batch
bookings, then batch bookings, then batch guests (skipping any batch
guest still referenced by another table, e.g. a conversation) — and
nothing else. ``fill_demo_bookings`` is idempotent: when a batch is
already present it inserts nothing and reports ``already_filled``.

Generation mirrors ``scripts/seed_analytics_demo.py``: the same room
base rates, seasonality, status-by-timing rules and payment shapes, so
a booking's ``final_price`` is always nightly-rate x nights and
per-room-type nightly concurrency never exceeds ``total_rooms``.
"""

from __future__ import annotations

import logging
import os
import random
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# The seeded demo hotel, identified by the same natural key
# scripts/seed_demo.py uses (HOTEL_NAME there).
DEMO_HOTEL_NAME = "StayFlow Grand Hotel"

BATCH_TAG = "DEMO-FILL-2026"
GUEST_EMAIL_PREFIX = "demofill.guest"
GUEST_EMAIL_DOMAIN = "demo.example"
PAYMENT_REFERENCE_PREFIX = "DEMO-FILL-"

DEFAULT_COUNT = 180
DEFAULT_RNG_SEED = 7
WINDOW_DAYS_BACK = 730  # ~24 months of check-in history
HORIZON_DAYS_AHEAD = 30
MIN_PER_MONTH = 4

# Same room base rates (INR/night) as scripts/seed_demo.py and
# scripts/seed_analytics_demo.py; unknown types fall back to DEFAULT.
BASE_RATES = {
    "Deluxe King Room": Decimal("4500"),
    "Executive Twin Room": Decimal("5500"),
    "Heritage Suite": Decimal("12000"),
}
DEFAULT_BASE_RATE = Decimal("4000")
ROOM_TYPE_WEIGHTS = {
    "Deluxe King Room": 0.45,
    "Executive Twin Room": 0.35,
    "Heritage Suite": 0.20,
}
DEFAULT_ROOM_WEIGHT = 0.25

SOURCES = ["direct", "website", "walk_in", "agent_chat", "unknown"]
SOURCE_WEIGHTS = [0.30, 0.25, 0.15, 0.20, 0.10]
PAYMENT_METHODS = ["upi", "card", "cash", "bank_transfer"]
PAYMENT_METHOD_WEIGHTS = [0.45, 0.30, 0.15, 0.10]
STAY_NIGHTS = [1, 2, 3, 4, 5, 6, 7]
STAY_NIGHT_WEIGHTS = [0.18, 0.30, 0.25, 0.12, 0.07, 0.04, 0.04]

# Seasonal demand by calendar month (Dec peak, Jun trough) so monthly
# totals genuinely differ — same table as the analytics seed script.
MONTH_SEASONALITY = {
    1: 1.25,
    2: 1.10,
    3: 1.00,
    4: 0.85,
    5: 0.80,
    6: 0.70,
    7: 0.75,
    8: 0.85,
    9: 0.95,
    10: 1.15,
    11: 1.20,
    12: 1.40,
}

FIRST_NAMES = [
    "Aarav", "Ananya", "Arjun", "Diya", "Ishaan", "Kavya", "Kiran", "Meera",
    "Nikhil", "Priya", "Rahul", "Riya", "Rohan", "Sanya", "Vikram", "Neha",
    "Aditya", "Pooja", "Kunal", "Shruti", "Manish", "Divya", "Sanjay", "Tara",
]
LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Reddy", "Iyer", "Khan", "Gupta", "Nair",
    "Singh", "Mehta", "Rao", "Joshi", "Kulkarni", "Das", "Malhotra", "Chopra",
]


def _round50(value: Decimal) -> Decimal:
    return (value / Decimal("50")).quantize(Decimal("1")) * Decimal("50")


def _month_starts_between(first: date, last: date) -> list[date]:
    """First-of-month dates for every month intersecting [first, last]."""
    months = []
    current = first.replace(day=1)
    while current <= last:
        months.append(current)
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return months


def _batch_guest_ids(db: Session, hotel_id: int) -> list[int]:
    from app.models.guest import Guest

    pattern = f"{GUEST_EMAIL_PREFIX}%@{GUEST_EMAIL_DOMAIN}"
    return list(
        db.scalars(
            select(Guest.id).where(Guest.hotel_id == hotel_id, Guest.email.like(pattern))
        ).all()
    )


def _batch_booking_ids(db: Session, hotel_id: int, guest_ids: list[int]) -> list[int]:
    from app.models.booking import Booking

    if not guest_ids:
        return []
    return list(
        db.scalars(
            select(Booking.id).where(
                Booking.hotel_id == hotel_id, Booking.guest_id.in_(guest_ids)
            )
        ).all()
    )


def _month_allocation(months: list[date], count: int, today: date) -> list[int]:
    """Split ``count`` across months: a per-month floor, then the rest
    by seasonality (largest remainder), so every month has activity and
    monthly totals still differ."""
    floor = MIN_PER_MONTH if count >= MIN_PER_MONTH * len(months) else max(1, count // len(months))
    allocation = [floor] * len(months)
    remainder = count - floor * len(months)
    if remainder <= 0:
        return allocation
    weights = [
        MONTH_SEASONALITY[m.month] * (1.15 if m.year == today.year else 1.0) for m in months
    ]
    total_weight = sum(weights)
    raw = [remainder * w / total_weight for w in weights]
    extra = [int(x) for x in raw]
    for i in sorted(range(len(months)), key=lambda i: raw[i] - extra[i], reverse=True)[
        : remainder - sum(extra)
    ]:
        extra[i] += 1
    return [a + e for a, e in zip(allocation, extra, strict=True)]


def fill_demo_bookings(
    db: Session,
    hotel,
    count: int = DEFAULT_COUNT,
    rng_seed: int = DEFAULT_RNG_SEED,
    today: date | None = None,
) -> dict:
    """Insert the marked synthetic batch for ``hotel`` (and only it).

    Idempotent: if batch bookings already exist for the hotel, nothing
    is inserted and the stats report ``already_filled`` with the
    existing count. Commits on success; on any exception the caller
    should roll back.
    """
    from app.models.booking import Booking
    from app.models.guest import Guest
    from app.models.payment import Payment
    from app.models.room import Room

    today = today or date.today()
    rng = random.Random(rng_seed)

    existing_ids = _batch_booking_ids(db, hotel.id, _batch_guest_ids(db, hotel.id))
    if existing_ids:
        return {
            "batch": BATCH_TAG,
            "already_filled": True,
            "existing_bookings": len(existing_ids),
            "guests_created": 0,
            "bookings": 0,
            "payments": 0,
            "refunds": 0,
        }

    rooms = list(
        db.scalars(
            select(Room).where(Room.hotel_id == hotel.id, Room.is_active.is_(True))
        ).all()
    )
    if not rooms:
        raise ValueError(f"hotel id={hotel.id} has no active rooms to book")

    raw_weights = [ROOM_TYPE_WEIGHTS.get(r.room_type, DEFAULT_ROOM_WEIGHT) for r in rooms]
    weight_total = sum(raw_weights)
    room_weights = [w / weight_total for w in raw_weights]
    base_rates = {r.id: BASE_RATES.get(r.room_type, DEFAULT_BASE_RATE) for r in rooms}

    guest_count = max(12, min(80, count // 3))
    guests = []
    for i in range(guest_count):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        guest = Guest(
            hotel_id=hotel.id,
            name=f"Demo Guest {name}",
            email=f"{GUEST_EMAIL_PREFIX}{i:03d}@{GUEST_EMAIL_DOMAIN}",
        )
        db.add(guest)
        db.flush()
        guests.append(guest)

    window_start = today - timedelta(days=WINDOW_DAYS_BACK)
    horizon = today + timedelta(days=HORIZON_DAYS_AHEAD)
    months = _month_starts_between(window_start, horizon)
    allocation = _month_allocation(months, count, today)

    occupied: Counter = Counter()  # (room_id, night) -> concurrent stays
    counters: Counter = Counter()
    seq = 0

    for month_start, month_count in zip(months, allocation, strict=True):
        next_month = month_start.replace(day=28) + timedelta(days=4)
        next_month = next_month.replace(day=1)
        lo = max(month_start, window_start)
        hi = min(next_month - timedelta(days=1), horizon)
        span_days = (hi - lo).days + 1
        for _ in range(month_count):
            placed = None
            for _attempt in range(30):
                room = rng.choices(rooms, weights=room_weights)[0]
                check_in = lo + timedelta(days=rng.randrange(span_days))
                nights = rng.choices(STAY_NIGHTS, weights=STAY_NIGHT_WEIGHTS)[0]
                check_out = check_in + timedelta(days=nights)
                if all(
                    occupied[(room.id, check_in + timedelta(days=n))] < room.total_rooms
                    for n in range(nights)
                ):
                    placed = (room, check_in, check_out, nights)
                    break
            if placed is None:
                counters["skipped_no_capacity"] += 1
                continue
            room, check_in, check_out, nights = placed
            for n in range(nights):
                occupied[(room.id, check_in + timedelta(days=n))] += 1

            source = rng.choices(SOURCES, weights=SOURCE_WEIGHTS)[0]
            lead = 0 if source == "walk_in" else rng.choices(
                [0, 1, 3, 7, 14, 21, 30, 45], weights=[8, 10, 18, 22, 18, 12, 8, 4]
            )[0]
            created_date = min(check_in - timedelta(days=lead), today)
            created_at = datetime.combine(
                created_date,
                time(hour=rng.randrange(8, 22), minute=rng.randrange(60)),
                tzinfo=UTC,
            )

            seasonal = Decimal(str(MONTH_SEASONALITY[check_in.month]))
            weekend = Decimal("1.10") if check_in.weekday() in (4, 5) else Decimal("1")
            jitter = Decimal(str(round(rng.uniform(0.90, 1.15), 2)))
            nightly = _round50(base_rates[room.id] * seasonal * weekend * jitter)
            final_price = nightly * nights

            if rng.random() < 0.08:
                status = "CANCELLED"
            elif check_out <= today:
                status = "CHECKED_OUT"
            elif check_in <= today:
                status = "CHECKED_IN" if rng.random() < 0.8 else "CONFIRMED"
            else:
                status = "CONFIRMED" if rng.random() < 0.75 else "PENDING"

            seq += 1
            booking = Booking(
                hotel_id=hotel.id,
                guest_id=rng.choice(guests).id,
                room_id=room.id,
                check_in=check_in,
                check_out=check_out,
                number_of_guests=rng.randint(1, min(4, room.capacity)),
                final_price=final_price,
                booking_status=status,
                source=source,
                created_at=created_at,
            )
            db.add(booking)
            db.flush()
            counters["bookings"] += 1
            counters[f"status_{status}"] += 1
            counters[f"source_{source}"] += 1

            def add_payment(
                amount: Decimal,
                method: str,
                status_: str,
                when: date,
                # Bound as defaults so the closure captures THIS booking's
                # values, not the loop variables (ruff B023).
                _booking_id: int = booking.id,
                _seq: int = seq,
            ) -> None:
                db.add(
                    Payment(
                        hotel_id=hotel.id,
                        booking_id=_booking_id,
                        amount=amount,
                        method=method,
                        status=status_,
                        reference=f"{PAYMENT_REFERENCE_PREFIX}{_seq:04d}-{status_[:4]}",
                        created_at=datetime.combine(
                            when, time(hour=12, minute=rng.randrange(60)), tzinfo=UTC
                        ),
                    )
                )
                counters["payments"] += 1
                if status_ == "refunded":
                    counters["refunds"] += 1

            method = rng.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS)[0]
            pay_day = min(created_date + timedelta(days=rng.randrange(0, 3)), today)
            if status == "CANCELLED":
                if rng.random() < 0.30:  # paid, then fully refunded
                    add_payment(final_price, method, "captured", pay_day)
                    add_payment(
                        final_price,
                        method,
                        "refunded",
                        min(pay_day + timedelta(days=rng.randrange(1, 6)), today),
                    )
            elif status in ("CHECKED_OUT", "CHECKED_IN"):
                add_payment(final_price, method, "captured", pay_day)
                if rng.random() < 0.12:  # partial refund on some stays
                    part = _round50(
                        final_price * Decimal(str(round(rng.uniform(0.10, 0.50), 2)))
                    )
                    if part > 0:
                        add_payment(
                            part,
                            method,
                            "refunded",
                            min(pay_day + timedelta(days=rng.randrange(1, 10)), today),
                        )
            elif status == "CONFIRMED":
                roll = rng.random()
                if roll < 0.45:  # partial advance + pending remainder
                    part = _round50(
                        final_price * Decimal(str(round(rng.uniform(0.30, 0.60), 2)))
                    )
                    add_payment(part, method, "captured", pay_day)
                    add_payment(final_price - part, method, "pending", pay_day)
                elif roll < 0.75:  # nothing captured yet
                    add_payment(final_price, method, "pending", pay_day)
            elif status == "PENDING" and rng.random() < 0.70:
                add_payment(final_price, method, "pending", pay_day)

    db.commit()
    return {
        "batch": BATCH_TAG,
        "already_filled": False,
        "existing_bookings": 0,
        "guests_created": len(guests),
        "bookings": counters["bookings"],
        "payments": counters["payments"],
        "refunds": counters["refunds"],
        "skipped_no_capacity": counters["skipped_no_capacity"],
        "months_covered": len(months),
        "per_status": {k[7:]: v for k, v in counters.items() if k.startswith("status_")},
        "per_source": {k[7:]: v for k, v in counters.items() if k.startswith("source_")},
    }


def purge_demo_bookings(db: Session, hotel) -> dict:
    """Delete ONLY this module's batch rows for ``hotel``.

    Order is FK-safe: payments of batch bookings, then batch bookings,
    then batch guests. A batch guest still referenced by another table
    (conversation, order, service request, booking draft) is left in
    place and counted under ``guests_kept_referenced`` — batch guests
    are created by the fill and never used by the agent, so this is
    only a defensive measure. Non-batch rows are never touched.
    Commits on success.
    """
    from app.models.booking import Booking
    from app.models.booking_draft import BookingDraft
    from app.models.conversation import Conversation
    from app.models.guest import Guest
    from app.models.order import Order
    from app.models.payment import Payment
    from app.models.service_request import ServiceRequest

    guest_ids = _batch_guest_ids(db, hotel.id)
    booking_ids = _batch_booking_ids(db, hotel.id, guest_ids)

    payments_deleted = 0
    if booking_ids:
        payments = list(
            db.scalars(select(Payment).where(Payment.booking_id.in_(booking_ids))).all()
        )
        payments_deleted = len(payments)
        for payment in payments:
            db.delete(payment)
        db.flush()
        bookings = list(
            db.scalars(select(Booking).where(Booking.id.in_(booking_ids))).all()
        )
        for booking in bookings:
            db.delete(booking)
        db.flush()

    guests_deleted = 0
    guests_kept = 0
    if guest_ids:
        referenced: set[int] = set()
        for model in (Conversation, Order, ServiceRequest, BookingDraft):
            referenced.update(
                db.scalars(
                    select(model.guest_id).where(model.guest_id.in_(guest_ids))
                ).all()
            )
        for guest in db.scalars(select(Guest).where(Guest.id.in_(guest_ids))).all():
            if guest.id in referenced:
                guests_kept += 1
            else:
                db.delete(guest)
                guests_deleted += 1

    db.commit()
    return {
        "batch": BATCH_TAG,
        "payments": payments_deleted,
        "bookings": len(booking_ids),
        "guests": guests_deleted,
        "guests_kept_referenced": guests_kept,
    }


def run_demo_fill_from_env(session_factory) -> dict | None:
    """Boot hook: apply ``ANALYTICS_DEMO_FILL`` (``1`` = fill,
    ``cleanup`` = purge) to the seeded demo hotel.

    Returns None when the variable is unset or holds any other value
    (checked BEFORE any database work, so normal boots are untouched).
    The demo hotel is resolved by the same natural key
    ``scripts/seed_demo.py`` uses; when it cannot be identified
    unambiguously (zero or several matches) the batch is skipped with a
    loud log line. Failures are logged and swallowed — the fill must
    never prevent the service from booting.
    """
    from app.models.hotel import Hotel

    mode = os.environ.get("ANALYTICS_DEMO_FILL", "").strip().lower()
    if mode not in ("1", "cleanup"):
        return None

    db = session_factory()
    try:
        hotels = list(
            db.scalars(select(Hotel).where(Hotel.name == DEMO_HOTEL_NAME)).all()
        )
        if len(hotels) != 1:
            logger.error(
                "ANALYTICS_DEMO_FILL=%s: expected exactly one hotel named %r, "
                "found %d — skipping demo fill",
                mode,
                DEMO_HOTEL_NAME,
                len(hotels),
            )
            return {"skipped": True, "reason": "demo_hotel_not_unambiguous", "mode": mode}
        hotel = hotels[0]
        if mode == "1":
            stats = fill_demo_bookings(db, hotel)
            logger.info(
                "ANALYTICS_DEMO_FILL: fill done (already_filled=%s, bookings=%s, "
                "guests=%s, payments=%s, refunds=%s)",
                stats["already_filled"],
                stats.get("bookings", stats.get("existing_bookings")),
                stats["guests_created"],
                stats["payments"],
                stats["refunds"],
            )
        else:
            stats = purge_demo_bookings(db, hotel)
            logger.info(
                "ANALYTICS_DEMO_FILL: cleanup done (payments=%s, bookings=%s, "
                "guests=%s, guests_kept_referenced=%s)",
                stats["payments"],
                stats["bookings"],
                stats["guests"],
                stats["guests_kept_referenced"],
            )
        return stats
    except Exception:
        logger.exception("ANALYTICS_DEMO_FILL: failed; continuing boot without it")
        db.rollback()
        return {"error": True, "mode": mode}
    finally:
        db.close()
