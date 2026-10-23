"""Phase 2 (HMS upgrade): multilingual agent behaviour.

Covers deterministic language detection, script-correct mock replies,
mid-conversation switching, explicit language requests, booking
confirmation/cancellation language, and the food-order safety flow from
Sagar's 2026-10-23 screenshot (a Roman-Hinglish pre-order request that
previously got a garbled Devanagari "confirmation").
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select

from app.agent.language import DetectedLanguage, ResponseLanguage, detect_language
from app.db.session import get_db
from app.models.order import Order
from tests._helpers import (
    client,
    future,
    make_guest,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
    uid,
)

DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI.search(text))


_GUESTS: dict[int, int] = {}


def _chat(hotel_id, message, *, anon=False, **kw):
    """Chat helper. Tests use a dedicated guest per hotel so each test gets
    its own rate-limit bucket (the chat limiter keys by guest_id, falling back
    to a shared anonymous bucket); the screenshot regression stays anonymous,
    like the real widget guest."""
    body = {"hotel_id": hotel_id, "message": message, **kw}
    if not anon:
        if hotel_id not in _GUESTS:
            _GUESTS[hotel_id] = make_guest(hotel_id)["id"]
        body.setdefault("guest_id", _GUESTS[hotel_id])
    r = client.post("/api/v1/agent/chat", json=body)
    ok(r, 200)
    return r.json()


def _seed(price=3000):
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe", capacity=2, total_rooms=5)
    start = future(60)
    seed_rates_availability(room["id"], start, 4, price=price, available=5)
    return hotel, room, start


# --------------------------------------------------------------------- #
# Detection (pure, deterministic)                                        #
# --------------------------------------------------------------------- #
def test_detect_devanagari_hindi():
    d = detect_language("नमस्ते, क्या आपके होटल में कमरा खाली है?")
    assert d.detected is DetectedLanguage.HINDI
    assert d.response_language is ResponseLanguage.HINDI


def test_detect_roman_hinglish():
    d = detect_language("Bhai, hotel mein room available hai kya?")
    assert d.response_language is ResponseLanguage.HINGLISH


def test_detect_english():
    d = detect_language("Hello, do you have any rooms available?")
    assert d.detected is DetectedLanguage.ENGLISH
    assert d.response_language is ResponseLanguage.ENGLISH


def test_detect_mixed_devanagari_with_english_terms_is_hindi():
    d = detect_language("क्या early check-in मिल सकता है?")
    assert d.response_language is ResponseLanguage.HINDI


def test_detect_mixed_english_hindi_is_hinglish():
    d = detect_language("Can I book a room kal ke liye?")
    assert d.response_language is ResponseLanguage.HINGLISH


def test_detect_explicit_language_request_wins():
    d = detect_language("Please reply in English. Kya room khali hai?")
    assert d.explicit_request is ResponseLanguage.ENGLISH
    assert d.response_language is ResponseLanguage.ENGLISH
    d2 = detect_language("मुझे हिंदी में जवाब दो, what are the charges?")
    assert d2.response_language is ResponseLanguage.HINDI
    d3 = detect_language("hinglish me batao, room hai kya?")
    assert d3.response_language is ResponseLanguage.HINGLISH


def test_detect_neutral_message_has_no_language():
    d = detect_language("23/11/2026")
    assert d.detected is DetectedLanguage.NEUTRAL
    assert d.response_language is None


def test_detect_screenshot_sentence_is_hinglish():
    d = detect_language(
        "sagar mishra or room number to chrck in ke baad milega na to "
        "hamari chrck in date ke lie khana pahle se book kar do"
    )
    assert d.response_language is ResponseLanguage.HINGLISH


# --------------------------------------------------------------------- #
# Chat-level script correctness (mock provider)                          #
# --------------------------------------------------------------------- #
def test_hindi_availability_reply_is_devanagari():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(
        hotel["id"],
        f"क्या Deluxe कमरा {start} से {end} तक खाली है?",
    )
    assert body["response_language"] == "hindi"
    assert _has_devanagari(body["reply"])
    assert "उपलब्ध" in body["reply"]


def test_hinglish_availability_reply_is_roman():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(
        hotel["id"],
        f"Bhai, Deluxe room {start} se {end} tak available hai kya?",
    )
    assert body["response_language"] == "hinglish"
    assert not _has_devanagari(body["reply"])
    assert "available hai" in body["reply"]


def test_english_availability_reply_is_english():
    hotel, room, start = _seed()
    end = start + timedelta(days=2)
    body = _chat(
        hotel["id"],
        f"Is the Deluxe room available from {start} to {end}?",
    )
    assert body["response_language"] == "english"
    assert not _has_devanagari(body["reply"])
    assert "available" in body["reply"]


def test_hindi_price_question_reply_is_hindi():
    hotel, room, start = _seed()
    body = _chat(hotel["id"], "Deluxe कमरे की कीमत क्या है?")
    assert body["response_language"] == "hindi"
    assert _has_devanagari(body["reply"])


def test_language_switching_mid_conversation():
    hotel, room, start = _seed()
    body1 = _chat(hotel["id"], "What is the price of the Deluxe room?")
    assert body1["response_language"] == "english"
    body2 = _chat(
        hotel["id"],
        "Deluxe room ki price kya hai?",
        conversation_id=body1["conversation_id"],
    )
    assert body2["response_language"] == "hinglish"
    assert not _has_devanagari(body2["reply"])
    body3 = _chat(
        hotel["id"],
        "क्या Deluxe कमरा खाली है?",
        conversation_id=body1["conversation_id"],
    )
    assert body3["response_language"] == "hindi"
    assert _has_devanagari(body3["reply"])


def test_neutral_reply_keeps_conversation_language():
    hotel, room, start = _seed()
    body1 = _chat(hotel["id"], "Bhai, Deluxe room ki price kya hai?")
    assert body1["response_language"] == "hinglish"
    body2 = _chat(hotel["id"], "2026-12-01", conversation_id=body1["conversation_id"])
    # A bare date carries no language signal; the conversation's
    # established Hinglish preference must be kept, not reset to English.
    assert body2["response_language"] == "hinglish"
    assert not _has_devanagari(body2["reply"])


def test_explicit_request_overrides_message_language():
    hotel, room, start = _seed()
    body = _chat(
        hotel["id"],
        "Please reply in English only. Deluxe room ki price kya hai?",
    )
    assert body["response_language"] == "english"
    assert not _has_devanagari(body["reply"])


# --------------------------------------------------------------------- #
# Booking confirmation / cancellation in the guest's language            #
# --------------------------------------------------------------------- #
def test_hinglish_booking_flow_and_confirmation():
    hotel, room, start = _seed(price=4000)
    end = start + timedelta(days=2)
    email = f"{uid('hg')}@t.co"
    body = _chat(
        hotel["id"],
        f"Deluxe room book kar do 2 guests ke liye, {start} se {end} tak, "
        f"mera naam Hing Guest, email {email}",
    )
    assert body["response_language"] == "hinglish"
    assert "confirm kar doon" in body["reply"]
    assert "create_booking" not in [t["tool"] for t in body["tool_trace"]]

    body2 = _chat(hotel["id"], "haan, confirm kar do", conversation_id=body["conversation_id"])
    assert body2["response_language"] == "hinglish"
    assert "confirm ho gayi" in body2["reply"]
    assert not _has_devanagari(body2["reply"])
    assert "create_booking" in [t["tool"] for t in body2["tool_trace"]]


def test_hindi_cancellation_reply():
    hotel, room, start = _seed()
    guest = make_guest(hotel["id"])
    end = start + timedelta(days=2)
    r = client.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hotel["id"],
            "room_id": room["id"],
            "guest_id": guest["id"],
            "check_in": str(start),
            "check_out": str(end),
            "number_of_guests": 2,
            "booking_status": "CONFIRMED",
        },
    )
    ok(r, 201)
    bid = r.json()["id"]
    body = _chat(hotel["id"], f"मेरी बुकिंग {bid} रद्द कर दो")
    assert body["response_language"] == "hindi"
    assert _has_devanagari(body["reply"])
    assert "रद्द" in body["reply"]
    assert "cancel_booking" in [t["tool"] for t in body["tool_trace"]]


# --------------------------------------------------------------------- #
# Food-order safety (the screenshot regression)                          #
# --------------------------------------------------------------------- #
def _seed_menu(hotel_id, name="Rajasthani Thali", price=650):
    r = client.post(
        "/api/v1/menu-items",
        json={"hotel_id": hotel_id, "name": uid(name), "price": price},
    )
    ok(r, 201)
    return r.json()


def _orders_for(hotel_id):
    db = next(get_db())
    try:
        return db.scalars(select(Order).where(Order.hotel_id == hotel_id)).all()
    finally:
        db.close()


def test_screenshot_preorder_asks_clarification_never_confirms():
    hotel = make_hotel()
    item = _seed_menu(hotel["id"])
    body = _chat(
        hotel["id"],
        "sagar mishra or room number to chrck in ke baad milega na to "
        "hamari chrck in date ke lie khana pahle se book kar do",
        anon=True,
    )
    # Hinglish in, Hinglish out — Roman script only, and no order may be
    # fabricated from a request missing item, quantity and timing.
    assert body["response_language"] == "hinglish"
    assert not _has_devanagari(body["reply"])
    assert "confirm" not in body["reply"].lower().replace("confirm kar", "")
    assert _orders_for(hotel["id"]) == []
    assert "create_food_order" not in [t["tool"] for t in body["tool_trace"]]

    # Guest then supplies item + quantity + timing — but the order tool
    # still needs an identified guest, so the bot must ask for identity
    # instead of confirming an anonymous order.
    body2 = _chat(
        hotel["id"],
        f"{item['name']} 4 plate, kal raat 8 baje chahiye",
        conversation_id=body["conversation_id"],
        anon=True,
    )
    assert body2["response_language"] == "hinglish"
    assert _orders_for(hotel["id"]) == []

    # With identity supplied, the order is finally created — with
    # backend (menu) pricing, never a guest/LLM-invented total.
    body3 = _chat(
        hotel["id"],
        "mera naam Sagar Mishra, phone 9876543210",
        conversation_id=body["conversation_id"],
        anon=True,
    )
    assert body3["response_language"] == "hinglish"
    assert not _has_devanagari(body3["reply"])
    assert "confirm ho gaya" in body3["reply"]
    orders = _orders_for(hotel["id"])
    assert len(orders) == 1
    assert float(orders[0].total_amount) == 4 * 650


def test_food_order_missing_quantity_asks_not_confirms():
    hotel = make_hotel()
    item = _seed_menu(hotel["id"], name="Paneer Tikka", price=350)
    body = _chat(hotel["id"], "khana order karna hai")
    assert _orders_for(hotel["id"]) == []
    body2 = _chat(hotel["id"], item["name"], conversation_id=body["conversation_id"])
    assert _orders_for(hotel["id"]) == []
    assert "create_food_order" not in [t["tool"] for t in body2["tool_trace"]]
    # The bot asks for quantity/timing instead of confirming.
    assert "kitne" in body2["reply"] or "How many" in body2["reply"]
