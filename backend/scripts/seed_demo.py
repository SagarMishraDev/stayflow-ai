#!/usr/bin/env python3
"""Seed the StayFlow Grand Hotel demo dataset (Prompt-2 section 27).

Creates everything a demo needs in one idempotent run:

- the "StayFlow Grand Hotel" hotel (Jaipur)
- 3 room types with nightly rates + availability for the next 90 days
- a few policies, FAQs, offers, services, and menu items
- 5 knowledge-base documents for the RAG concierge (airport pickup,
  check-in instructions, spa, restaurant, cancellation policy)
- one HOTEL_ADMIN staff user (argon2-hashed)

The admin password is **never** a default in code: it comes from the
``SEED_ADMIN_PASSWORD`` environment variable, ``--password``, or a secure
``getpass`` prompt (never echoed).

Idempotent: every row is looked up by its natural key — hotel name, room
type, ``(room, date)`` for rates/availability, policy type, FAQ question,
offer / service / menu-item name, user email — and skipped when it already
exists. Safe to re-run.

Usage::

    export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/stayflow"
    export SEED_ADMIN_PASSWORD="choose-a-strong-password"  # or omit to be prompted
    uv run python scripts/seed_demo.py
    uv run python scripts/seed_demo.py --admin-email ops@stayflowgrand.example --days 30
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import select

from app.core.roles import HOTEL_ADMIN
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.availability import Availability
from app.models.faq import FAQ
from app.models.hotel import Hotel
from app.models.hotel_user import HotelUser
from app.models.menu_item import MenuItem
from app.models.offer import Offer
from app.models.policy import Policy
from app.models.rate import Rate
from app.models.room import Room
from app.models.service import Service

HOTEL_NAME = "StayFlow Grand Hotel"
HOTEL_CITY = "Jaipur"
DEFAULT_ADMIN_EMAIL = "admin@stayflowgrand.example"

ROOM_TYPES = [
    # (room_type, description, capacity, total_rooms, base_price_inr)
    (
        "Deluxe King Room",
        "Spacious room with a king bed, city view, and rain shower.",
        2,
        20,
        Decimal("4500"),
    ),
    (
        "Executive Twin Room",
        "Two queen beds, work desk, and lounge access for business travellers.",
        2,
        15,
        Decimal("5500"),
    ),
    (
        "Heritage Suite",
        "Signature suite with Rajasthani decor, living room, and soaking tub.",
        4,
        6,
        Decimal("12000"),
    ),
]

POLICIES = [
    (
        "CHECK_IN",
        "Check-in & check-out",
        "Check-in from 2:00 PM, check-out until 12:00 noon. Early check-in "
        "and late check-out are subject to availability.",
    ),
    (
        "CANCELLATION",
        "Cancellation policy",
        "Free cancellation up to 48 hours before check-in. Inside 48 hours, "
        "one night's charge applies. No-shows are charged the full stay.",
    ),
    (
        "PETS",
        "Pet policy",
        "Pets are not allowed, except registered service animals.",
    ),
]

FAQS = [
    (
        "What time is check-in and check-out?",
        "Check-in is from 2:00 PM and check-out is until 12:00 noon.",
        "stay",
    ),
    (
        "Is Wi-Fi free?",
        "Yes — complimentary high-speed Wi-Fi is available throughout the hotel.",
        "amenities",
    ),
    (
        "Is breakfast included?",
        "Breakfast is included in Executive Twin and Heritage Suite rates; "
        "Deluxe King guests can add it for INR 450 per person.",
        "dining",
    ),
    (
        "Do you offer airport transfers?",
        "Yes — our Airport Shuttle runs on request for INR 1,200 per trip. "
        "Please book at least 4 hours ahead.",
        "transport",
    ),
]

OFFERS = [
    # (name, description, discount_type, discount_value, valid_days)
    (
        "Monsoon Getaway",
        "15% off all room types for stays in the next 60 days.",
        "PERCENT",
        Decimal("15"),
        60,
    ),
    (
        "Suite Upgrade Week",
        "Flat INR 2,000 off the Heritage Suite, this month only.",
        "FIXED",
        Decimal("2000"),
        30,
    ),
]

SERVICES = [
    # (name, description, price_inr, category)
    ("Airport Shuttle", "Private sedan transfer to/from Jaipur airport.", 1200.0, "transport"),
    ("Spa Session", "60-minute signature massage at the in-house spa.", 2500.0, "wellness"),
    ("Laundry", "Same-day laundry and pressing service.", 150.0, "housekeeping"),
]

MENU_ITEMS = [
    # (name, description, category, price_inr)
    ("Masala Chai", "Traditional spiced Indian tea.", "beverages", Decimal("120")),
    (
        "Rajasthani Thali",
        "Royal platter: dal baati churma, gatte ki sabzi, and more.",
        "mains",
        Decimal("650"),
    ),
    ("Paneer Tikka", "Char-grilled cottage cheese with mint chutney.", "starters", Decimal("320")),
    ("Club Sandwich", "Triple-decker with fries.", "mains", Decimal("280")),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the StayFlow Grand Hotel demo dataset.")
    parser.add_argument(
        "--days", type=int, default=90, help="Days of rates/availability to seed (default: 90)"
    )
    parser.add_argument(
        "--admin-email",
        default=DEFAULT_ADMIN_EMAIL,
        help="Login email for the demo HOTEL_ADMIN user",
    )
    parser.add_argument(
        "--admin-name", default="Demo Admin", help="Display name for the demo HOTEL_ADMIN user"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password (omit to use SEED_ADMIN_PASSWORD or a prompt)",
    )
    parser.add_argument(
        "--skip-knowledge",
        action="store_true",
        help="Skip ingesting the demo knowledge-base documents (RAG).",
    )
    return parser.parse_args()


def _get_or_create(db, model, filters: dict, defaults: dict) -> tuple[object, bool]:
    """Fetch by natural key, else create. Returns (instance, was_created)."""
    stmt = select(model)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    instance = db.scalars(stmt).first()
    if instance is not None:
        return instance, False
    instance = model(**{**filters, **defaults})
    db.add(instance)
    db.flush()
    return instance, True


def main() -> int:
    args = parse_args()
    password = args.password or os.environ.get("SEED_ADMIN_PASSWORD")
    if not password:
        try:
            password = getpass.getpass("Demo admin password: ")
        except (EOFError, OSError):
            password = None
    if not password or len(password) < 8:
        print(
            "error: provide a password of at least 8 characters via --password, "
            "the SEED_ADMIN_PASSWORD environment variable, or the interactive prompt",
            file=sys.stderr,
        )
        return 2

    today = date.today()
    counts = {"created": 0, "skipped": 0}

    def track(created: bool) -> None:
        counts["created" if created else "skipped"] += 1

    db = SessionLocal()
    try:
        hotel, created = _get_or_create(
            db,
            Hotel,
            {"name": HOTEL_NAME},
            {
                "city": HOTEL_CITY,
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "description": "Demo property for the StayFlow AI platform.",
                # Complete guest-facing details so a fresh install renders
                # the full landing page (contact + policies sections hide
                # themselves while these are empty). Demo values only.
                "address": "12, Pearl Tower, C-Scheme, Jaipur, Rajasthan 302001",
                "phone": "+91 141 400 2233",
                "email": "reservations@stayflowgrand.example",
                "check_in_time": "14:00",
                "check_out_time": "11:00",
            },
        )
        track(created)
        print(f"{'created' if created else 'reusing'} hotel id={hotel.id} {hotel.name!r}")

        rooms: list[Room] = []
        for room_type, description, capacity, total_rooms, base_price in ROOM_TYPES:
            room, created = _get_or_create(
                db,
                Room,
                {"hotel_id": hotel.id, "room_type": room_type},
                {"description": description, "capacity": capacity, "total_rooms": total_rooms},
            )
            track(created)
            rooms.append(room)

            for offset in range(args.days):
                day = today + timedelta(days=offset)
                # Modest weekend uplift so the demo rate card looks realistic.
                price = base_price * (Decimal("1.10") if day.weekday() >= 5 else Decimal("1"))
                _, created = _get_or_create(
                    db,
                    Rate,
                    {"room_id": room.id, "date": day},
                    {"price": price, "currency": "INR"},
                )
                track(created)
                _, created = _get_or_create(
                    db,
                    Availability,
                    {"room_id": room.id, "date": day},
                    {"available_rooms": total_rooms},
                )
                track(created)

        for policy_type, title, description in POLICIES:
            _, created = _get_or_create(
                db,
                Policy,
                {"hotel_id": hotel.id, "policy_type": policy_type},
                {"title": title, "description": description},
            )
            track(created)

        for question, answer, category in FAQS:
            _, created = _get_or_create(
                db,
                FAQ,
                {"hotel_id": hotel.id, "question": question},
                {"answer": answer, "category": category},
            )
            track(created)

        for name, description, discount_type, discount_value, valid_days in OFFERS:
            _, created = _get_or_create(
                db,
                Offer,
                {"hotel_id": hotel.id, "name": name},
                {
                    "description": description,
                    "discount_type": discount_type,
                    "discount_value": discount_value,
                    "valid_from": today,
                    "valid_until": today + timedelta(days=valid_days),
                },
            )
            track(created)

        for name, description, price, category in SERVICES:
            _, created = _get_or_create(
                db,
                Service,
                {"hotel_id": hotel.id, "name": name},
                {"description": description, "price": price, "category": category},
            )
            track(created)

        for name, description, category, price in MENU_ITEMS:
            _, created = _get_or_create(
                db,
                MenuItem,
                {"hotel_id": hotel.id, "name": name},
                {"description": description, "category": category, "price": price},
            )
            track(created)

        admin, created = _get_or_create(
            db,
            HotelUser,
            {"hotel_id": hotel.id, "email": args.admin_email},
            {
                "name": args.admin_name,
                "role": HOTEL_ADMIN.value,
                "password_hash": hash_password(password),
            },
        )
        if created:
            print(f"created HOTEL_ADMIN user id={admin.id} email={admin.email!r}")
        else:
            admin.name = args.admin_name
            admin.role = HOTEL_ADMIN.value
            admin.is_active = True
            admin.password_hash = hash_password(password)
            print(
                f"updated HOTEL_ADMIN user id={admin.id} email={admin.email!r} (password re-hashed)"
            )
        track(created)

        if not args.skip_knowledge:
            # Demo knowledge-base documents (RAG): idempotent via
            # scripts/seed_knowledge.py's natural-key check. The embedding
            # backend follows EMBEDDING_PROVIDER (set it to "hashed" for a
            # fast, download-free seed).
            sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
            from seed_knowledge import seed_hotel_knowledge

            kb = seed_hotel_knowledge(hotel.id, db=db)
            counts["created"] += kb["created"]
            counts["skipped"] += kb["skipped"]
            print(f"knowledge documents: {kb['created']} created, {kb['skipped']} already present")

        db.commit()
    finally:
        db.close()

    print(
        f"done: {counts['created']} created, {counts['skipped']} already present. "
        f"Log in via POST /api/v1/auth/login with {args.admin_email}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
