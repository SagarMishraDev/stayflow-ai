#!/usr/bin/env python3
"""Seed the hotel knowledge base (RAG) with demo documents (Prompt-2).

Ingests 5 sample documents for a hotel: airport pickup, check-in
instructions, spa, restaurant, and a long-form cancellation policy.

Idempotent: documents are skipped when a document with the same title
already exists for the hotel. Re-running never creates duplicates.

Usage::

    export DATABASE_URL=<redacted>
    uv run python scripts/seed_knowledge.py --hotel-id 1
    # or: HOTEL_ID=1 uv run python scripts/seed_knowledge.py
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.knowledge import (
    KnowledgeRepository,
    default_embedding_provider,
)
from app.models.hotel import Hotel

SOURCE = "seed"

DOCS: list[tuple[str, str]] = [
    (
        "Airport pickup and transfers",
        """Getting to and from the airport is easy. Our complimentary shuttle runs
        every 30 minutes between the hotel lobby and Terminal 2 of the
        international airport from 5:00 AM to 11:30 PM daily. The ride takes
        about 25 minutes depending on traffic, and no reservation is needed —
        just wait at the clearly marked shuttle bay outside the main entrance.

        For private transfers, our front desk can arrange an air-conditioned
        sedan (up to 3 guests with luggage) or an SUV (up to 6 guests) with a
        professional driver. Sedan transfers cost a flat fee and take roughly
        25 minutes; SUVs are recommended for families with extra baggage. We
        ask for at least 2 hours notice for private pickups, though we will
        always try to accommodate last-minute requests.

        Guests arriving on late-night or early-morning flights can request a
        meet-and-greet service: our driver waits at the arrivals hall with a
        name placard and assists with luggage. Flight tracking is included, so
        if your flight is delayed, your driver will be too. Contact the front
        desk with your flight number to arrange this free of charge.""",
    ),
    (
        "Check-in instructions",
        """Check-in begins at 2:00 PM and check-out is until 12:00 noon. Early
        check-in from 10:00 AM and late check-out until 2:00 PM are available
        on request and subject to availability; a half-day charge may apply
        during peak season.

        At the front desk, please present a valid government-issued photo ID
        for each adult guest and the credit card used for the reservation. A
        pre-authorization hold is placed for incidentals and released within
        5 to 7 working days after check-out.

        Guests arriving after 11:00 PM are requested to inform us in advance
        so we can keep your room guaranteed for late arrival. Self check-in
        kiosks in the lobby are available around the clock; our night team is
        happy to help with luggage and room orientation at any hour.

        Complimentary Wi-Fi details, breakfast timings, and a map of the
        property are handed over in the welcome envelope at check-in. If you
        need anything during your stay — extra pillows, a late checkout, or
        restaurant reservations — dial 0 from your room phone or message us
        on WhatsApp.""",
    ),
    (
        "Spa and wellness",
        """Our Serenity Spa on the third floor is open daily from 9:00 AM to
        9:00 PM. Signature treatments include the 60-minute aromatherapy
        massage, the deep-tissue sports massage, and the traditional hot-stone
        therapy. Facials range from a 30-minute express glow to the 90-minute
        royal radiance ritual using natural botanical products.

        The wellness area also features a Finnish sauna, a steam room, and a
        temperature-controlled plunge pool, all complimentary for in-house
        guests. Couples' treatment suites are available for private sessions,
        and we recommend booking at least one day in advance, especially on
        weekends.

        Morning yoga sessions are held on the rooftop deck at 7:00 AM from
        Monday to Saturday, led by our certified instructor. Mats and herbal
        tea are provided. The fully equipped fitness center next to the spa is
        open 24 hours and includes cardio machines, free weights, and a
        personal trainer on request.""",
    ),
    (
        "Restaurants and dining",
        """Saffron Court, our all-day multi-cuisine restaurant on the ground
        floor, serves breakfast from 7:00 AM to 10:30 AM, lunch from 12:30 PM
        to 3:00 PM, and dinner from 7:00 PM to 11:00 PM. The breakfast buffet
        features live counters for dosas and omelettes, fresh tropical fruits,
        and artisanal breads. Dinner includes themed nights — Rajasthani on
        Tuesdays, coastal seafood on Fridays.

        For a fine-dining evening, Azure on the rooftop offers pan-Asian
        cuisine with sunset views over the city, open 7:00 PM to 11:30 PM
        (closed Mondays). Reservations are recommended. The Lobby Lounge
        serves coffee, high tea from 4:00 PM to 6:00 PM, and light bites until
        midnight.

        In-room dining is available 24 hours with a condensed menu after
        11:00 PM. Jain, vegan, and gluten-free options are available across
        all outlets — please inform our team of any allergies when ordering.""",
    ),
    (
        "Cancellation policy (detailed)",
        """We understand plans change. This page explains our cancellation and
        refund policy in full so there are no surprises.

        Standard flexible rates: cancel free of charge until 24 hours before
        the check-in date (2:00 PM local time). Cancellations made within 24
        hours of check-in, or no-shows, are charged one night's room rate
        including taxes. To cancel, use the link in your confirmation email,
        call the front desk, or reply to your booking confirmation message.

        Advance-purchase and promotional rates: these discounted rates require
        full prepayment at the time of booking and are non-refundable. Date
        changes are permitted once, up to 72 hours before check-in, subject to
        rate differences for the new dates.

        Refunds for eligible cancellations are processed to the original
        payment method within 7 to 10 working days. For bookings made through
        third-party websites or travel agents, cancellation terms of that
        channel apply and refunds must be requested through them.

        In exceptional circumstances — documented medical emergencies or
        government-issued travel restrictions — our team may waive charges at
        its discretion. Early check-outs after the first night are charged
        50% of the remaining nights' rate. If you are unsure which rate plan
        you booked, share your confirmation number and we will clarify.""",
    ),
]


def seed_hotel_knowledge(hotel_id: int, db=None) -> dict[str, int]:
    """Ingest the demo documents for ``hotel_id``.

    Returns ``{"created": n, "skipped": m}``. Safe to call repeatedly.
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        hotel = db.get(Hotel, hotel_id)
        if hotel is None:
            raise ValueError(f"Hotel {hotel_id} not found")
        repo = KnowledgeRepository(db, default_embedding_provider())
        created = skipped = 0
        for title, content in DOCS:
            if repo.document_exists(hotel_id, title):
                skipped += 1
                continue
            repo.create_document(hotel_id=hotel_id, title=title, content=content, source=SOURCE)
            created += 1
        db.commit()
        return {"created": created, "skipped": skipped}
    finally:
        if own_session:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the hotel knowledge base.")
    parser.add_argument(
        "--hotel-id",
        type=int,
        default=int(os.environ.get("HOTEL_ID", "0") or 0),
        help="Hotel id to seed (or set HOTEL_ID)",
    )
    args = parser.parse_args()
    if not args.hotel_id:
        parser.error("provide --hotel-id or set HOTEL_ID")
    result = seed_hotel_knowledge(args.hotel_id)
    print(
        f"Hotel {args.hotel_id}: created {result['created']} documents, "
        f"skipped {result['skipped']} (already present)."
    )


if __name__ == "__main__":
    main()
