"""Hotel analytics aggregations (HMS upgrade Phase 4).

Every number here is computed from real database rows — bookings,
payments, orders, rooms — for ONE hotel. Nothing is estimated, mocked
or extrapolated. The accounting rules are documented in
HMS_UPGRADE_REPORT.md (Phase 1) and restated in each function:

- Earned revenue: sum of ``final_price`` for non-CANCELLED bookings
  whose check-in date falls in the period.
- Booking count: bookings CREATED in the period (hotel-local date),
  non-CANCELLED unless stated.
- Occupied room-nights: overlap of [check_in, check_out) with the
  period, non-CANCELLED bookings only.
- Available room-nights: active room types' total_rooms × period days.
- Collected / refunds: payment rows by status and payment date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.order import Order
from app.models.payment import Payment
from app.models.room import Room

ZERO = Decimal("0")


def _money(value: Decimal) -> str:
    """Canonical money string: no scientific notation, no trailing zeros."""
    return format(value.normalize(), "f")


RANGE_KEYS = (
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "week",
    "last_week",
    "month",
    "last_month",
    "quarter",
    "last_quarter",
    "year",
    "last_year",
    "custom",
    "all",
)


def _hotel_tz(db: Session, hotel_id: int) -> ZoneInfo:
    hotel = db.get(Hotel, hotel_id)
    try:
        return ZoneInfo(hotel.timezone if hotel else "Asia/Kolkata")
    except Exception:  # noqa: BLE001 - a bad tz string must not kill analytics
        return ZoneInfo("Asia/Kolkata")


def _local_date(dt: datetime, tz: ZoneInfo) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz).date()


def resolve_range(
    range_key: str,
    *,
    today: date,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date | None, date | None]:
    """Return (start_inclusive, end_exclusive) local dates for a range key."""
    if range_key == "all":
        return None, None
    if range_key == "today":
        return today, today + timedelta(days=1)
    if range_key == "yesterday":
        return today - timedelta(days=1), today
    if range_key == "last_7_days":
        # Rolling window: today and the six days before it (7 days total).
        return today - timedelta(days=6), today + timedelta(days=1)
    if range_key == "last_30_days":
        # Rolling window: today and the 29 days before it (30 days total).
        return today - timedelta(days=29), today + timedelta(days=1)
    if range_key in ("week", "last_week"):
        monday = today - timedelta(days=today.weekday())
        if range_key == "last_week":
            monday -= timedelta(days=7)
        return monday, monday + timedelta(days=7)
    if range_key in ("month", "last_month"):
        first = today.replace(day=1)
        if range_key == "last_month":
            first = (first - timedelta(days=1)).replace(day=1)
        next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return first, next_month
    if range_key in ("quarter", "last_quarter"):
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        first = date(today.year, q_start_month, 1)
        if range_key == "last_quarter":
            first = (first - timedelta(days=1)).replace(day=1)
            first = date(first.year, ((first.month - 1) // 3) * 3 + 1, 1)
        month = first.month + 3
        year = first.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        return first, date(year, month, 1)
    if range_key in ("year", "last_year"):
        year = today.year - (1 if range_key == "last_year" else 0)
        return date(year, 1, 1), date(year + 1, 1, 1)
    if range_key == "custom":
        if custom_start is None or custom_end is None:
            raise ValueError("custom range requires start and end dates")
        if custom_end < custom_start:
            raise ValueError("custom range end must not be before start")
        return custom_start, custom_end + timedelta(days=1)
    raise ValueError(f"unknown range: {range_key}")


def previous_period_bounds(
    bounds: tuple[date | None, date | None],
) -> tuple[date, date]:
    """The equal-length period immediately before ``bounds``.

    Used by the compare endpoint for the ``previous_period`` comparison:
    for a selected range of N days, the comparison is the N days that
    end exactly where the selected range starts. Open-ended ranges
    (``all``) have no previous period and raise ``ValueError``.
    """
    start, end = bounds
    if start is None or end is None:
        raise ValueError("previous_period is not available for open-ended ranges")
    length = end - start
    return start - length, start


def _days(start: date | None, end: date | None) -> int:
    if start is None or end is None:
        return 0
    return max((end - start).days, 0)


def _effective_window(
    bookings: list[Booking], start: date | None, end: date | None, *, today: date
) -> tuple[date | None, date | None]:
    """Fill open range bounds from the hotel's own stay activity.

    Bounded ranges are returned unchanged. For an open bound (the
    ``all`` range) the denominator window becomes the hotel's actual
    activity span — first non-cancelled check-in through the later of
    the last check-out and tomorrow — so available room-nights,
    occupancy, RevPAR and daily averages are computed over a real
    period instead of silently collapsing to zero. A hotel with no
    non-cancelled stays keeps its open bounds (denominators stay 0,
    which the UI renders as an honest empty state).
    """
    if start is not None and end is not None:
        return start, end
    stays = [b for b in bookings if b.booking_status != "CANCELLED"]
    if not stays:
        return start, end
    eff_start = start if start is not None else min(b.check_in for b in stays)
    eff_end = (
        end
        if end is not None
        else max(max(b.check_out for b in stays), today + timedelta(days=1))
    )
    return eff_start, eff_end


def _bookings(db: Session, hotel_id: int) -> list[Booking]:
    return list(db.scalars(select(Booking).where(Booking.hotel_id == hotel_id)).all())


def _earned(bookings: list[Booking], start: date | None, end: date | None) -> Decimal:
    total = ZERO
    for b in bookings:
        if b.booking_status == "CANCELLED":
            continue
        if start is not None and b.check_in < start:
            continue
        if end is not None and b.check_in >= end:
            continue
        total += b.final_price
    return total


def _stay_bookings(bookings: list[Booking], start: date | None, end: date | None) -> list[Booking]:
    """Non-cancelled bookings whose check-in falls in the period."""
    return [
        b
        for b in bookings
        if b.booking_status != "CANCELLED"
        and (start is None or b.check_in >= start)
        and (end is None or b.check_in < end)
    ]


def _occupied_room_nights(bookings: list[Booking], start: date | None, end: date | None) -> int:
    nights = 0
    for b in bookings:
        if b.booking_status == "CANCELLED":
            continue
        lo = b.check_in if start is None else max(b.check_in, start)
        hi = b.check_out if end is None else min(b.check_out, end)
        if hi > lo:
            nights += (hi - lo).days
    return nights


def _available_room_nights(db: Session, hotel_id: int, days: int) -> int:
    total_rooms = sum(
        r.total_rooms
        for r in db.scalars(
            select(Room).where(Room.hotel_id == hotel_id, Room.is_active.is_(True))
        ).all()
    )
    return total_rooms * days


def _payments_in_period(
    db: Session, hotel_id: int, tz: ZoneInfo, start: date | None, end: date | None
) -> list[Payment]:
    rows = db.scalars(select(Payment).where(Payment.hotel_id == hotel_id)).all()
    out = []
    for p in rows:
        d = _local_date(p.created_at, tz)
        if start is not None and d < start:
            continue
        if end is not None and d >= end:
            continue
        out.append(p)
    return list(out)


def kpi_overview(
    db: Session, hotel_id: int, start: date | None, end: date | None, *, today: date
) -> dict:
    tz = _hotel_tz(db, hotel_id)
    bookings = _bookings(db, hotel_id)
    # Denominators (available nights, occupancy, RevPAR, daily average,
    # period_days) use the effective window: identical to the requested
    # bounds for bounded ranges, the hotel's activity span for "all".
    days = _days(*_effective_window(bookings, start, end, today=today))
    earned = _earned(bookings, start, end)
    stays = _stay_bookings(bookings, start, end)

    created_in_period = [
        b
        for b in bookings
        if (start is None or _local_date(b.created_at, tz) >= start)
        and (end is None or _local_date(b.created_at, tz) < end)
    ]
    confirmed = [b for b in created_in_period if b.booking_status != "CANCELLED"]
    cancelled = [b for b in created_in_period if b.booking_status == "CANCELLED"]

    payments = _payments_in_period(db, hotel_id, tz, start, end)
    collected = sum((p.amount for p in payments if p.status == "captured"), ZERO)
    refunds = sum((p.amount for p in payments if p.status == "refunded"), ZERO)
    stay_ids = {b.id for b in stays}
    captured_for_stays = sum(
        (
            p.amount
            for p in db.scalars(select(Payment).where(Payment.hotel_id == hotel_id)).all()
            if p.status == "captured" and p.booking_id in stay_ids
        ),
        ZERO,
    )
    pending_amount = max(earned - captured_for_stays, ZERO)

    occupied = _occupied_room_nights(bookings, start, end)
    available = _available_room_nights(db, hotel_id, days) if days else 0
    occupancy = (occupied / available * 100) if available else 0.0
    adr = (earned / occupied) if occupied else ZERO
    revpar = (earned / available) if available else ZERO
    avg_value = (earned / len(stays)) if stays else ZERO

    tonight_occupied = sum(
        1 for b in bookings if b.booking_status != "CANCELLED" and b.check_in <= today < b.check_out
    )
    total_inventory = sum(
        r.total_rooms
        for r in db.scalars(
            select(Room).where(Room.hotel_id == hotel_id, Room.is_active.is_(True))
        ).all()
    )
    return {
        "total_revenue": _money(earned),
        "revenue_collected": _money(collected),
        "pending_payments": _money(pending_amount),
        "refunds": _money(refunds),
        "total_bookings": len(created_in_period),
        "confirmed_bookings": len(confirmed),
        "cancelled_bookings": len(cancelled),
        "average_daily_revenue": _money((earned / days) if days else ZERO),
        "adr": _money(adr),
        "revpar": _money(revpar),
        "occupancy_rate": round(occupancy, 2),
        "average_booking_value": _money(avg_value),
        "occupied_room_nights": occupied,
        "available_room_nights": available,
        "rooms_occupied_tonight": tonight_occupied,
        "rooms_available_tonight": max(total_inventory - tonight_occupied, 0),
        "period_days": days,
    }


def _bucket_key(d: date, group_by: str) -> str:
    if group_by == "day":
        return d.isoformat()
    if group_by == "week":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat()
    if group_by == "month":
        return d.strftime("%Y-%m")
    if group_by == "year":
        return str(d.year)
    raise ValueError(f"unsupported group_by: {group_by}")


def revenue_series(
    db: Session,
    hotel_id: int,
    start: date | None,
    end: date | None,
    *,
    group_by: str = "day",
    today: date,
) -> list[dict]:
    """Revenue (by check-in date) + booking count (by creation date) buckets."""
    tz = _hotel_tz(db, hotel_id)
    bookings = _bookings(db, hotel_id)
    buckets: dict[str, dict] = {}

    def bucket(key: str) -> dict:
        return buckets.setdefault(key, {"period": key, "revenue": ZERO, "bookings": 0})

    if group_by == "hour":
        # Hourly only makes sense for a single day: use `today`.
        for hour in range(24):
            bucket(f"{today.isoformat()} {hour:02d}:00")
        for b in bookings:
            created_local = _local_date(b.created_at, tz)
            if created_local != today:
                continue
            hour = b.created_at.astimezone(tz).hour if b.created_at.tzinfo else b.created_at.hour
            entry = bucket(f"{today.isoformat()} {hour:02d}:00")
            entry["bookings"] += 1
            if b.booking_status != "CANCELLED":
                entry["revenue"] += b.final_price
        return [
            {"period": k, "revenue": _money(v["revenue"]), "bookings": v["bookings"]}
            for k, v in sorted(buckets.items())
        ]

    for b in _stay_bookings(bookings, start, end):
        entry = bucket(_bucket_key(b.check_in, group_by))
        entry["revenue"] += b.final_price
    for b in bookings:
        created = _local_date(b.created_at, tz)
        if start is not None and created < start:
            continue
        if end is not None and created >= end:
            continue
        if b.booking_status == "CANCELLED":
            continue
        bucket(_bucket_key(created, group_by))["bookings"] += 1
    return [
        {"period": k, "revenue": _money(v["revenue"]), "bookings": v["bookings"]}
        for k, v in sorted(buckets.items())
    ]


def _pct_change(current: Decimal, baseline: Decimal) -> float | None:
    """Percent change; None when the baseline is zero (never misleading)."""
    if baseline == 0:
        return None
    return round(float((current - baseline) / baseline * 100), 2)


def compare_periods(
    db: Session,
    hotel_id: int,
    a: tuple[date | None, date | None],
    b: tuple[date | None, date | None],
    *,
    today: date,
) -> dict:
    ka = kpi_overview(db, hotel_id, a[0], a[1], today=today)
    kb = kpi_overview(db, hotel_id, b[0], b[1], today=today)
    series_a = revenue_series(db, hotel_id, a[0], a[1], group_by="day", today=today)
    series_b = revenue_series(db, hotel_id, b[0], b[1], group_by="day", today=today)
    rev_a, rev_b = Decimal(ka["total_revenue"]), Decimal(kb["total_revenue"])
    book_a, book_b = ka["confirmed_bookings"], kb["confirmed_bookings"]
    val_a, val_b = Decimal(ka["average_booking_value"]), Decimal(kb["average_booking_value"])
    return {
        "current": ka,
        "previous": kb,
        "series": {"current": series_a, "previous": series_b},
        "deltas": {
            "revenue_diff": _money(rev_a - rev_b),
            "revenue_pct": _pct_change(rev_a, rev_b),
            "bookings_diff": book_a - book_b,
            "bookings_pct": _pct_change(Decimal(book_a), Decimal(book_b)),
            "avg_booking_value_diff": _money(val_a - val_b),
            "avg_booking_value_pct": _pct_change(val_a, val_b),
            "occupancy_diff_points": round(ka["occupancy_rate"] - kb["occupancy_rate"], 2),
        },
    }


def breakdowns(
    db: Session, hotel_id: int, start: date | None, end: date | None, *, today: date
) -> dict:
    tz = _hotel_tz(db, hotel_id)
    bookings = _bookings(db, hotel_id)
    stays = _stay_bookings(bookings, start, end)
    rooms = {r.id: r for r in db.scalars(select(Room).where(Room.hotel_id == hotel_id)).all()}

    def add(table: dict, key: str, amount: Decimal, count: int = 0) -> None:
        entry = table.setdefault(key, {"revenue": ZERO, "bookings": 0})
        entry["revenue"] += amount
        entry["bookings"] += count

    by_category: dict[str, dict] = {}
    by_room: dict[str, dict] = {}
    by_source: dict[str, dict] = {}
    by_status: dict[str, dict] = {}
    for b in bookings:
        room = rooms.get(b.room_id)
        category = room.room_type if room else "unknown"
        in_period = b in stays
        add(
            by_status, b.booking_status, b.final_price if in_period else ZERO, 1 if in_period else 0
        )
        if in_period:
            add(by_category, category, b.final_price, 1)
            add(by_room, f"{category} (#{b.room_id})", b.final_price, 1)
            add(by_source, b.source or "unknown", b.final_price, 1)

    payments = _payments_in_period(db, hotel_id, tz, start, end)
    by_method: dict[str, dict] = {}
    for p in payments:
        if p.status == "captured":
            add(by_method, p.method, p.amount, 1)

    orders = [
        o
        for o in db.scalars(select(Order).where(Order.hotel_id == hotel_id)).all()
        if o.status != "CANCELLED"
        and (start is None or _local_date(o.created_at, tz) >= start)
        and (end is None or _local_date(o.created_at, tz) < end)
    ]
    order_revenue = sum((o.total_amount for o in orders), ZERO)
    by_department = {
        "rooms": {"revenue": _earned(bookings, start, end), "bookings": len(stays)},
        "food_and_beverage": {"revenue": order_revenue, "bookings": len(orders)},
    }

    def render(table: dict[str, dict]) -> list[dict]:
        return [
            {"key": k, "revenue": _money(v["revenue"]), "bookings": v["bookings"]}
            for k, v in sorted(table.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
        ]

    return {
        "by_room_category": render(by_category),
        "by_room": render(by_room),
        "by_booking_source": render(by_source),
        "by_payment_method": render(by_method),
        "by_booking_status": render(by_status),
        "by_department": render(by_department),
    }


def room_popularity(
    db: Session, hotel_id: int, start: date | None, end: date | None, *, today: date
) -> dict:
    """Per room-type popularity. Booking count, revenue and occupancy are
    three distinct metrics and are reported side by side, never merged."""
    tz = _hotel_tz(db, hotel_id)
    bookings = _bookings(db, hotel_id)
    days = _days(*_effective_window(bookings, start, end, today=today))
    rooms = list(db.scalars(select(Room).where(Room.hotel_id == hotel_id)).all())
    rows: list[dict] = []
    for room in rooms:
        room_bookings = [b for b in bookings if b.room_id == room.id]
        created = [
            b
            for b in room_bookings
            if b.booking_status != "CANCELLED"
            and (start is None or _local_date(b.created_at, tz) >= start)
            and (end is None or _local_date(b.created_at, tz) < end)
        ]
        revenue = _earned(room_bookings, start, end)
        occupied = _occupied_room_nights(room_bookings, start, end)
        available = room.total_rooms * days if room.is_active else 0
        rows.append(
            {
                "room_id": room.id,
                "room_type": room.room_type,
                "is_active": room.is_active,
                "total_rooms": room.total_rooms,
                "bookings": len(created),
                "revenue": _money(revenue),
                "occupied_room_nights": occupied,
                "available_room_nights": available,
                "occupancy_rate": round(occupied / available * 100, 2) if available else 0.0,
            }
        )
    rows.sort(key=lambda r: (-r["bookings"], r["room_type"]))
    if rows:
        max_count = max(r["bookings"] for r in rows)
        min_count = min(r["bookings"] for r in rows)
        most = [r for r in rows if r["bookings"] == max_count]
        least = [r for r in rows if r["bookings"] == min_count]
    else:
        most, least = [], []
    return {"rooms": rows, "most_booked": most, "least_booked": least}


def _bucket_starts(start: date, end: date, group_by: str) -> list[date]:
    """First day of every bucket intersecting [start, end)."""
    starts: list[date] = []
    if group_by == "day":
        current = start
        while current < end:
            starts.append(current)
            current += timedelta(days=1)
    elif group_by == "week":
        current = start - timedelta(days=start.weekday())  # Monday of start's week
        while current < end:
            starts.append(current)
            current += timedelta(days=7)
    elif group_by == "month":
        current = start.replace(day=1)
        while current < end:
            starts.append(current)
            month = current.month + 1
            current = date(current.year + (month - 1) // 12, ((month - 1) % 12) + 1, 1)
    elif group_by == "year":
        current = date(start.year, 1, 1)
        while current < end:
            starts.append(current)
            current = date(current.year + 1, 1, 1)
    else:
        raise ValueError(f"unsupported group_by: {group_by}")
    return starts


def popularity_series(
    db: Session,
    hotel_id: int,
    start: date | None,
    end: date | None,
    *,
    group_by: str = "day",
    today: date,
) -> dict:
    """Per-room-type bookings/revenue bucketed over time.

    Powers the grouped bar chart on the Analytics page. Accounting
    follows the same conventions as :func:`room_popularity` and
    :func:`revenue_series`: only non-CANCELLED bookings, attributed by
    CHECK-IN date ("earned"). Every room type of the hotel appears in
    every bucket — with zeroes where it had no stays — so zero-booking
    types stay visible. The range-level ``room_types`` rows carry the
    totals plus the occupancy figures (occupied room-nights by overlap,
    available = total_rooms × period days for active types), computed
    exactly as in :func:`room_popularity`.
    """
    if group_by not in ("day", "week", "month", "year"):
        raise ValueError(f"unsupported group_by: {group_by}")
    bookings = _bookings(db, hotel_id)
    days = _days(*_effective_window(bookings, start, end, today=today))
    rooms = list(db.scalars(select(Room).where(Room.hotel_id == hotel_id)).all())
    stays = _stay_bookings(bookings, start, end)

    # Bucket window: for open-ended ranges ("all") fall back to the
    # span of the hotel's stay bookings themselves.
    if start is None or end is None:
        if stays:
            eff_start = start if start is not None else min(b.check_in for b in stays)
            eff_end = end if end is not None else max(b.check_in for b in stays) + timedelta(days=1)
        else:
            eff_start = eff_end = today
    else:
        eff_start, eff_end = start, end
    starts = _bucket_starts(eff_start, eff_end, group_by) if eff_end > eff_start else []
    # Safety cap: a day-grouped multi-decade range must not produce an
    # unbounded payload (366 buckets ≈ one leap year of days). The cap
    # bounds ONLY this rendered bucket list — the ``room_types`` totals
    # below are aggregated from the full stay set and always cover the
    # entire selected range.
    starts = starts[:366]

    per_bucket: dict[str, dict[int, dict]] = {
        _bucket_key(s, group_by): {
            r.id: {"bookings": 0, "revenue": ZERO} for r in rooms
        }
        for s in starts
    }
    for b in stays:
        key = _bucket_key(b.check_in, group_by)
        cell = per_bucket.get(key, {}).get(b.room_id)
        if cell is not None:
            cell["bookings"] += 1
            cell["revenue"] += b.final_price

    # Range totals are aggregated from the stays themselves, NEVER from
    # the bucket list: the bucket list is capped at 366 entries for
    # payload size, so totals derived from it silently dropped every
    # booking past the cap on wide ranges (e.g. day-grouped "all").
    totals_by_room: dict[int, dict] = {
        room.id: {"bookings": 0, "revenue": ZERO} for room in rooms
    }
    for b in stays:
        entry = totals_by_room.get(b.room_id)
        if entry is not None:
            entry["bookings"] += 1
            entry["revenue"] += b.final_price

    room_type_rows: list[dict] = []
    for room in rooms:
        room_bookings = [b for b in bookings if b.room_id == room.id]
        occupied = _occupied_room_nights(room_bookings, start, end)
        available = room.total_rooms * days if room.is_active else 0
        totals = totals_by_room[room.id]
        room_type_rows.append(
            {
                "room_id": room.id,
                "room_type": room.room_type,
                "is_active": room.is_active,
                "total_rooms": room.total_rooms,
                "bookings": totals["bookings"],
                "revenue": _money(totals["revenue"]),
                "occupied_room_nights": occupied,
                "available_room_nights": available,
                "occupancy_rate": round(occupied / available * 100, 2) if available else 0.0,
            }
        )

    return {
        "group_by": group_by,
        "period_days": days,
        "buckets": [
            {
                "period": key,
                "rooms": [
                    {
                        "room_type": room.room_type,
                        "bookings": per_bucket[key][room.id]["bookings"],
                        "revenue": _money(per_bucket[key][room.id]["revenue"]),
                    }
                    for room in rooms
                ],
            }
            for key in (_bucket_key(s, group_by) for s in starts)
        ],
        "room_types": room_type_rows,
    }


# Payment lifecycle -> activity feed wording. Statuses not listed here
# (e.g. "failed") are deliberately not surfaced as activity.
_PAYMENT_ACTIVITY = {
    "captured": ("payment_received", "Payment received"),
    "pending": ("payment_pending", "Payment pending"),
    "refunded": ("refund_processed", "Refund processed"),
}


def recent_activity(db: Session, hotel_id: int, *, limit: int = 10) -> list[dict]:
    """Latest real booking/payment events for one hotel, newest first.

    Booking events come from the audit log (``booking.created`` /
    ``booking.cancelled``), which carries trustworthy timestamps for
    both. Bookings with no ``booking.created`` audit row (e.g. seeded
    directly) fall back to their ``created_at`` so the feed is never
    silently missing them. Payment events come from payment rows by
    status (captured / pending / refunded). Nothing is fabricated:
    a hotel with no bookings or payments gets an empty feed.
    """
    events: list[dict] = []

    bookings = {b.id: b for b in _bookings(db, hotel_id)}
    guests = {
        g.id: g
        for g in db.scalars(select(Guest).where(Guest.hotel_id == hotel_id)).all()
    }
    rooms = {
        r.id: r
        for r in db.scalars(select(Room).where(Room.hotel_id == hotel_id)).all()
    }

    def booking_summary(booking: Booking) -> str:
        parts = []
        guest = guests.get(booking.guest_id)
        if guest is not None:
            parts.append(guest.name)
        room = rooms.get(booking.room_id)
        if room is not None:
            parts.append(room.room_type)
        return " · ".join(parts)

    def created_event(booking: Booking, when: datetime) -> dict:
        confirmed = booking.booking_status == "CONFIRMED"
        return {
            "kind": "booking_confirmed" if confirmed else "booking_created",
            "title": "Booking confirmed" if confirmed else "New booking",
            "reference": f"#{booking.id}",
            "summary": booking_summary(booking),
            "amount": _money(booking.final_price),
            "timestamp": when,
        }

    audit_rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.hotel_id == hotel_id,
            AuditLog.action.in_(("booking.created", "booking.cancelled")),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(200)
    ).all()
    audited_created: set[int] = set()
    for row in audit_rows:
        booking = bookings.get(row.entity_id) if row.entity_id else None
        if booking is None:
            continue
        if row.action == "booking.created":
            audited_created.add(booking.id)
            events.append(created_event(booking, row.created_at))
        else:  # booking.cancelled
            events.append(
                {
                    "kind": "booking_cancelled",
                    "title": "Booking cancelled",
                    "reference": f"#{booking.id}",
                    "summary": booking_summary(booking),
                    "amount": _money(booking.final_price),
                    "timestamp": row.created_at,
                }
            )
    for booking in bookings.values():
        if booking.id not in audited_created:
            events.append(created_event(booking, booking.created_at))

    payments = db.scalars(
        select(Payment)
        .where(Payment.hotel_id == hotel_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(200)
    ).all()
    for payment in payments:
        wording = _PAYMENT_ACTIVITY.get(payment.status)
        if wording is None:
            continue
        kind, title = wording
        events.append(
            {
                "kind": kind,
                "title": title,
                "reference": f"#{payment.booking_id}",
                "summary": (
                    f"{payment.method.replace('_', ' ').title()} · Booking #{payment.booking_id}"
                ),
                "amount": _money(payment.amount),
                "timestamp": payment.created_at,
            }
        )

    def sort_key(event: dict) -> datetime:
        ts = event["timestamp"]
        # SQLite may hand back naive datetimes; treat them as UTC so
        # aware/naive rows can be ordered together.
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)

    events.sort(key=sort_key, reverse=True)
    return [
        {**event, "timestamp": sort_key(event).isoformat()}
        for event in events[:limit]
    ]
