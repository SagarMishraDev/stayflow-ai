#!/usr/bin/env python3
"""Seed a large, realistic ANALYTICS demo dataset (500+ bookings).

This is a companion to ``scripts/seed_demo.py`` — that script builds
the small "StayFlow Grand Hotel" showcase dataset; this one builds a
SEPARATE, clearly-marked demo hotel ("StayFlow Analytics Demo Hotel")
with 500+ synthetic bookings spread over two calendar years so every
Analytics graph, aggregation, filter, comparison and CSV export can be
verified against real rows through the normal API/service pipeline.

SAFETY — read before running:

- The target database comes ONLY from the ``ANALYTICS_DEMO_DATABASE_URL``
  environment variable, defaulting to a local file
  ``sqlite:///./analytics_demo.db`` in ``backend/``.
- The script REFUSES to run (exit code 2) when the target URL's host
  contains ``neon.tech`` or ``render.com``, or when the target equals
  the application's ``DATABASE_URL`` and that URL points at a remote
  host. It never reads from or writes to the production database.
- All synthetic guests use ``@demo.example`` addresses and obviously
  fake names. No real guest data is involved.

Idempotent: the demo hotel is looked up by its marker email; a re-run
reports "already seeded" and inserts nothing. ``--cleanup`` deletes
ONLY this demo hotel's rows (payments → bookings → guests → rooms →
hotel, FK-safe order) and reports the counts.

Usage::

    cd backend
    .venv/bin/python scripts/seed_analytics_demo.py            # seed 520 bookings
    .venv/bin/python scripts/seed_analytics_demo.py --count 800
    ANALYTICS_DEMO_DATABASE_URL=sqlite:///./analytics_demo.db \
        .venv/bin/python scripts/seed_analytics_demo.py --cleanup

See docs/ANALYTICS_DEMO_DATA.md for how to run the app against the
demo database and how to switch back.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

DEMO_HOTEL_NAME = "StayFlow Analytics Demo Hotel"
DEMO_HOTEL_EMAIL = "stayflow-analytics-demo@demo.example"
GUEST_EMAIL_DOMAIN = "demo.example"
PAYMENT_REFERENCE_PREFIX = "DEMO-"
DEFAULT_TARGET = "sqlite:///./analytics_demo.db"
REMOTE_HOST_MARKERS = ("neon.tech", "render.com")
DEFAULT_COUNT = 520
RNG_SEED = 42

# (room_type, capacity, total_rooms, base nightly rate INR) — the same
# three room types as scripts/seed_demo.py's showcase hotel.
ROOM_TYPES = [
    ("Deluxe King Room", 2, 20, Decimal("4500")),
    ("Executive Twin Room", 2, 15, Decimal("5500")),
    ("Heritage Suite", 4, 6, Decimal("12000")),
]

ROOM_TYPE_WEIGHTS = [0.45, 0.35, 0.20]
SOURCES = ["direct", "website", "walk_in", "agent_chat", "unknown"]
SOURCE_WEIGHTS = [0.30, 0.25, 0.15, 0.20, 0.10]
PAYMENT_METHODS = ["upi", "card", "cash", "bank_transfer"]
PAYMENT_METHOD_WEIGHTS = [0.45, 0.30, 0.15, 0.10]
STAY_NIGHTS = [1, 2, 3, 4, 5, 6, 7]
STAY_NIGHT_WEIGHTS = [0.18, 0.30, 0.25, 0.12, 0.07, 0.04, 0.04]

# Seasonal demand by calendar month (Dec peak, Jun trough) so monthly
# revenue totals genuinely differ across the four-month trend chart.
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
# By construction, this (year-offset, month) is a quiet month in which
# the Heritage Suite gets NO bookings — guarantees a zero-booking room
# type in a month that otherwise has activity.
QUIET_YEAR_OFFSET = 0  # 0 = the earlier of the two years
QUIET_MONTH = 6
QUIET_ROOM_TYPE = "Heritage Suite"

FIRST_NAMES = [
    "Aarav", "Ananya", "Arjun", "Diya", "Ishaan", "Kavya", "Kiran", "Meera",
    "Nikhil", "Priya", "Rahul", "Riya", "Rohan", "Sanya", "Vikram", "Neha",
    "Aditya", "Pooja", "Kunal", "Shruti", "Manish", "Divya", "Sanjay", "Tara",
]
LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Reddy", "Iyer", "Khan", "Gupta", "Nair",
    "Singh", "Mehta", "Rao", "Joshi", "Kulkarni", "Das", "Malhotra", "Chopra",
]


class UnsafeTargetError(RuntimeError):
    """Raised when the seed target looks like a production database."""


def _is_local_url(url: str) -> bool:
    if url.startswith("sqlite:"):
        return True
    return "localhost" in url or "127.0.0.1" in url or "[::1]" in url


def assert_safe_target(url: str, app_database_url: str | None = None) -> None:
    """Refuse targets that could be the production database.

    Rules (deliberately conservative):
    - any URL whose host part mentions neon.tech or render.com;
    - a URL identical to the app's own DATABASE_URL when that URL is
      not a local database.
    """
    lowered = url.lower()
    for marker in REMOTE_HOST_MARKERS:
        if marker in lowered:
            raise UnsafeTargetError(
                f"refusing to seed: target URL contains '{marker}' — "
                "this looks like a hosted/production database"
            )
    if app_database_url is None:
        app_database_url = os.environ.get("DATABASE_URL", "")
    if app_database_url and url == app_database_url and not _is_local_url(app_database_url):
        raise UnsafeTargetError(
            "refusing to seed: target URL is identical to the app's DATABASE_URL "
            "and that database is remote — point ANALYTICS_DEMO_DATABASE_URL at a "
            "dedicated local/test database instead"
        )


def resolve_target_url() -> str:
    return os.environ.get("ANALYTICS_DEMO_DATABASE_URL") or DEFAULT_TARGET


def _engine_and_session(url: str):
    assert_safe_target(url)
    import app.models  # noqa: F401  (registers every model on Base)
    from app.db.base import Base

    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autoflush=False)


def _month_starts(first: date, last_exclusive: date) -> list[date]:
    months = []
    current = first.replace(day=1)
    while current < last_exclusive:
        months.append(current)
        month = current.month + 1
        current = date(current.year + (month - 1) // 12, ((month - 1) % 12) + 1, 1)
    return months


def _round50(value: Decimal) -> Decimal:
    return (value / Decimal("50")).quantize(Decimal("1")) * Decimal("50")


def _generate_bookings(
    db: Session,
    *,
    hotel,
    rooms: list,
    guests: list,
    base_rates: dict[int, Decimal],
    count: int,
    rng: random.Random,
    today: date,
) -> dict:
    """Create ``count`` bookings (+ their payments). Returns counters."""
    from app.models.booking import Booking
    from app.models.payment import Payment

    window_start = date(today.year - 1, 1, 1)
    horizon = today + timedelta(days=45)  # future CONFIRMED/PENDING stays
    months = _month_starts(window_start, horizon + timedelta(days=1))

    def month_weight(month_start: date) -> float:
        growth = 1.15 if month_start.year == today.year else 1.0
        return MONTH_SEASONALITY[month_start.month] * growth

    weights = [month_weight(m) for m in months]
    total_weight = sum(weights)
    # Allocate the requested count across months (largest remainder).
    raw = [count * w / total_weight for w in weights]
    allocation = [int(x) for x in raw]
    for i in sorted(range(len(months)), key=lambda i: raw[i] - allocation[i], reverse=True)[
        : count - sum(allocation)
    ]:
        allocation[i] += 1

    occupied: Counter = Counter()  # (room_id, night) -> concurrent stays
    counters: Counter = Counter()
    seq = 0

    for month_start, month_count in zip(months, allocation, strict=True):
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        days_in_month = (next_month - month_start).days
        quiet = (
            month_start.year == window_start.year + QUIET_YEAR_OFFSET
            and month_start.month == QUIET_MONTH
        )
        for _ in range(month_count):
            placed = None
            for _attempt in range(30):
                type_idx = rng.choices(range(len(rooms)), weights=ROOM_TYPE_WEIGHTS)[0]
                room = rooms[type_idx]
                if quiet and room.room_type == QUIET_ROOM_TYPE:
                    continue
                check_in = month_start + timedelta(days=rng.randrange(days_in_month))
                if check_in > horizon:
                    continue
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
                created_date, time(hour=rng.randrange(8, 22), minute=rng.randrange(60)), tzinfo=UTC
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
                status = "CHECKED_IN"
            else:
                status = "CONFIRMED" if rng.random() < 0.75 else "PENDING"

            seq += 1
            booking = Booking(
                hotel_id=hotel.id,
                guest_id=rng.choice(guests).id,
                room_id=room.id,
                check_in=check_in,
                check_out=check_out,
                number_of_guests=rng.randint(1, room.capacity),
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
                        reference=f"{PAYMENT_REFERENCE_PREFIX}{_seq:05d}-{status_[:4]}",
                        created_at=datetime.combine(
                            when, time(hour=12, minute=rng.randrange(60)), tzinfo=UTC
                        ),
                    )
                )
                counters["payments"] += 1
                counters[f"payment_{status_}"] += 1
                counters[f"method_{method}"] += 1

            method = rng.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS)[0]
            pay_day = min(created_date + timedelta(days=rng.randrange(0, 3)), today)
            if status == "CANCELLED":
                if rng.random() < 0.30:  # paid, then fully refunded
                    add_payment(final_price, method, "captured", pay_day)
                    add_payment(final_price, method, "refunded",
                                min(pay_day + timedelta(days=rng.randrange(1, 6)), today))
            elif status in ("CHECKED_OUT", "CHECKED_IN"):
                add_payment(final_price, method, "captured", pay_day)
                if rng.random() < 0.12:  # partial refund on some stays
                    part = _round50(final_price * Decimal(str(round(rng.uniform(0.10, 0.50), 2))))
                    if part > 0:
                        add_payment(part, method, "refunded",
                                    min(pay_day + timedelta(days=rng.randrange(1, 10)), today))
            elif status == "CONFIRMED":
                roll = rng.random()
                if roll < 0.45:  # partial advance + pending remainder
                    part = _round50(final_price * Decimal(str(round(rng.uniform(0.30, 0.60), 2))))
                    add_payment(part, method, "captured", pay_day)
                    add_payment(final_price - part, method, "pending", pay_day)
                elif roll < 0.75:  # nothing captured yet
                    add_payment(final_price, method, "pending", pay_day)
            elif status == "PENDING" and rng.random() < 0.70:
                add_payment(final_price, method, "pending", pay_day)
    return counters


def seed_database(
    url: str,
    *,
    count: int = DEFAULT_COUNT,
    seed: int = RNG_SEED,
    today: date | None = None,
) -> dict:
    """Seed the analytics demo hotel into ``url``. Idempotent.

    Returns a verification summary dict. Raises UnsafeTargetError for
    production-looking targets.
    """
    from app.models.guest import Guest
    from app.models.hotel import Hotel
    from app.models.room import Room

    today = today or date.today()
    engine, session_factory = _engine_and_session(url)
    db: Session = session_factory()
    try:
        existing = db.scalars(
            select(Hotel).where(Hotel.email == DEMO_HOTEL_EMAIL)
        ).first()
        if existing is not None:
            summary = verify_database(db, existing.id)
            summary["already_seeded"] = True
            summary["inserted"] = 0
            return summary

        rng = random.Random(seed)
        hotel = Hotel(
            name=DEMO_HOTEL_NAME,
            city="Jaipur",
            currency="INR",
            timezone="Asia/Kolkata",
            description="Synthetic analytics demo property — not a real hotel.",
            address="1 Demo Plaza, Jaipur, Rajasthan 302001",
            phone="+91 141 000 0000",
            email=DEMO_HOTEL_EMAIL,
            check_in_time="14:00",
            check_out_time="11:00",
        )
        db.add(hotel)
        db.flush()

        rooms = []
        base_rates: dict[int, Decimal] = {}
        for room_type, capacity, total_rooms, base in ROOM_TYPES:
            room = Room(
                hotel_id=hotel.id,
                room_type=room_type,
                description=f"Synthetic demo room type: {room_type}.",
                capacity=capacity,
                total_rooms=total_rooms,
                is_active=True,
            )
            db.add(room)
            db.flush()
            base_rates[room.id] = base
            rooms.append(room)

        guests = []
        for i in range(140):
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            guest = Guest(
                hotel_id=hotel.id,
                name=f"Demo Guest {name}" if i % 3 == 0 else name,
                email=f"demo.guest{i:03d}@{GUEST_EMAIL_DOMAIN}",
            )
            db.add(guest)
            db.flush()
            guests.append(guest)

        counters = _generate_bookings(
            db,
            hotel=hotel,
            rooms=rooms,
            guests=guests,
            base_rates=base_rates,
            count=count,
            rng=rng,
            today=today,
        )
        db.commit()

        summary = verify_database(db, hotel.id)
        summary["already_seeded"] = False
        summary["inserted"] = counters["bookings"]
        summary["skipped_no_capacity"] = counters["skipped_no_capacity"]
        return summary
    finally:
        db.close()
        engine.dispose()


def verify_database(db: Session, hotel_id: int) -> dict:
    """Recompute the verification summary from stored rows."""
    from app.models.booking import Booking
    from app.models.payment import Payment

    bookings = list(db.scalars(select(Booking).where(Booking.hotel_id == hotel_id)).all())
    payments = list(db.scalars(select(Payment).where(Payment.hotel_id == hotel_id)).all())
    years = Counter(b.check_in.year for b in bookings)
    months_with_revenue = {
        (b.check_in.year, b.check_in.month)
        for b in bookings
        if b.booking_status != "CANCELLED"
    }
    per_month_type: Counter = Counter(
        (b.check_in.year, b.check_in.month, b.room_id)
        for b in bookings
        if b.booking_status != "CANCELLED"
    )
    months_seen = {(y, m) for (y, m, _r) in per_month_type}
    room_ids = {b.room_id for b in bookings}
    zero_type_month = any(
        any((y, m, rid) not in per_month_type for rid in room_ids)
        for (y, m) in months_seen
    )
    revenue = sum(
        (b.final_price for b in bookings if b.booking_status != "CANCELLED"), Decimal("0")
    )
    summary = {
        "hotel_id": hotel_id,
        "total_bookings": len(bookings),
        "distinct_bookings": len({b.id for b in bookings}),
        "per_year": dict(sorted(years.items())),
        "per_status": dict(Counter(b.booking_status for b in bookings)),
        "per_source": dict(Counter(b.source or "unknown" for b in bookings)),
        "per_payment_method": dict(
            Counter(p.method for p in payments if p.status == "captured")
        ),
        "payments": len(payments),
        "refunds": sum(1 for p in payments if p.status == "refunded"),
        "total_revenue_non_cancelled": str(revenue),
        "checks": {
            "at_least_target_bookings": len(bookings) >= 500,
            "spans_two_years": len(years) >= 2,
            "at_least_four_revenue_months": len(months_with_revenue) >= 4,
            "at_least_three_sources": len({b.source or "unknown" for b in bookings}) >= 3,
            "refunds_present": any(p.status == "refunded" for p in payments),
            "zero_booking_type_in_some_month": zero_type_month,
        },
    }
    return summary


def cleanup_database(url: str) -> dict:
    """Delete ONLY the analytics demo hotel's dataset from ``url``."""
    from app.models.booking import Booking
    from app.models.guest import Guest
    from app.models.hotel import Hotel
    from app.models.payment import Payment
    from app.models.room import Room

    engine, session_factory = _engine_and_session(url)
    db: Session = session_factory()
    try:
        hotel = db.scalars(select(Hotel).where(Hotel.email == DEMO_HOTEL_EMAIL)).first()
        if hotel is None:
            return {"found": False, "deleted": {}}
        counts = {}
        for model, label in (
            (Payment, "payments"),
            (Booking, "bookings"),
            (Guest, "guests"),
            (Room, "rooms"),
        ):
            rows = list(db.scalars(select(model).where(model.hotel_id == hotel.id)).all())
            counts[label] = len(rows)
            for row in rows:
                db.delete(row)
            db.flush()
        db.delete(hotel)
        db.commit()
        return {"found": True, "deleted": counts}
    finally:
        db.close()
        engine.dispose()


def _print_summary(summary: dict) -> None:
    print(f"demo hotel id={summary['hotel_id']}")
    print(f"bookings: {summary['total_bookings']} (distinct ids: {summary['distinct_bookings']})")
    print(f"per year: {summary['per_year']}")
    print(f"per status: {summary['per_status']}")
    print(f"per source: {summary['per_source']}")
    print(f"payments: {summary['payments']} (refunds: {summary['refunds']})")
    print(f"captured by method: {summary['per_payment_method']}")
    print(f"total non-cancelled revenue: ₹{summary['total_revenue_non_cancelled']}")
    for name, ok_ in summary["checks"].items():
        print(f"  check {name}: {'OK' if ok_ else 'FAILED'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the StayFlow analytics demo dataset.")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT,
                        help=f"bookings to generate (default: {DEFAULT_COUNT})")
    parser.add_argument("--seed", type=int, default=RNG_SEED,
                        help=f"random seed (default: {RNG_SEED})")
    parser.add_argument("--cleanup", action="store_true",
                        help="delete ONLY the analytics demo hotel's data, then exit")
    args = parser.parse_args()

    url = resolve_target_url()
    try:
        assert_safe_target(url)
    except UnsafeTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"target: {url}")

    if args.cleanup:
        result = cleanup_database(url)
        if not result["found"]:
            print("no analytics demo hotel found — nothing to clean up")
            return 0
        print(f"cleanup complete: deleted {result['deleted']}")
        return 0

    try:
        summary = seed_database(url, count=args.count, seed=args.seed)
    except UnsafeTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if summary["already_seeded"]:
        print("already seeded — no rows inserted (use --cleanup first to regenerate)")
    else:
        print(f"inserted {summary['inserted']} bookings")
    _print_summary(summary)
    failed = [name for name, ok_ in summary["checks"].items() if not ok_]
    if failed and not summary["already_seeded"]:
        print(f"warning: verification checks failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
