#!/usr/bin/env python3
"""Seed a hotel and its first staff admin user (Prompt-1 section 3).

Creates the hotel (by name, if it does not exist yet) and an admin
``HotelUser`` for it. The password is **always** stored as an argon2 hash —
this script never writes plaintext passwords.

Usage::

    export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/stayflow"
    uv run python scripts/seed_admin.py \
        --hotel "Grand Plaza" --city "Jaipur" \
        --name "Asha Admin" --email "admin@grandplaza.example" --role admin

If ``--password`` is omitted, it is read securely via getpass (never echoed).
Re-running for the same hotel + email updates the password hash instead of
creating a duplicate user.
"""

from __future__ import annotations

import argparse
import getpass
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.hotel import Hotel
from app.models.hotel_user import HotelUser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a hotel admin staff user.")
    parser.add_argument("--hotel", required=True, help="Hotel name")
    parser.add_argument("--city", default="Jaipur", help="Hotel city")
    parser.add_argument("--name", required=True, help="Staff user full name")
    parser.add_argument("--email", required=True, help="Staff user login email")
    parser.add_argument("--role", default="admin", help="Staff role (default: admin)")
    parser.add_argument(
        "--password",
        default=None,
        help="Password (omit to be prompted securely via getpass)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = args.password or getpass.getpass("Staff password: ")
    if len(password) < 8:
        print("error: password must be at least 8 characters", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        hotel = db.scalars(select(Hotel).where(Hotel.name == args.hotel)).first()
        if hotel is None:
            hotel = Hotel(name=args.hotel, city=args.city)
            db.add(hotel)
            db.flush()
            print(f"created hotel id={hotel.id} name={hotel.name!r}")
        else:
            print(f"reusing hotel id={hotel.id} name={hotel.name!r}")

        user = db.scalars(
            select(HotelUser).where(
                HotelUser.hotel_id == hotel.id,
                HotelUser.email == args.email,
            )
        ).first()
        if user is None:
            user = HotelUser(
                hotel_id=hotel.id,
                name=args.name,
                email=args.email,
                role=args.role,
                password_hash=hash_password(password),
            )
            db.add(user)
            db.flush()
            print(f"created staff user id={user.id} email={user.email!r} role={user.role!r}")
        else:
            user.password_hash = hash_password(password)
            user.name = args.name
            user.role = args.role
            user.is_active = True
            print(f"updated staff user id={user.id} email={user.email!r} (password re-hashed)")

        db.commit()
    finally:
        db.close()
    print("done. Log in via POST /api/v1/auth/login with the email + password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
