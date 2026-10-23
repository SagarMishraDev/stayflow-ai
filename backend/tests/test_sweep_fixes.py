"""Regression tests for the 2026-10-23 multi-language live sweep fixes
(see SWEEP_FIXES_REPORT.md at the repo root).

Bug A — the conversation language stuck across conversations: a "new
    conversation" request (no conversation_id) on web/widget channels
    silently resumed the guest's previous conversation — history and
    stored language preference included.
Bug B — a Roman-Hinglish booking conversation flipped to English on a
    weak slot reply ("Deluxe room chalega, 2 guests, ..."), so the
    booking summary/preview rendered in pure English.
Bug C — name capture failed across scripts: "मेरा नाम Test Guest है"
    (Devanagari lead-in, Latin name) parsed to nothing, and the Hindi
    ask-contact reply wasn't even recognised as a pending booking.
Bug D — Hindi FAQ/knowledge grounding: "स्विमिंग पूल का समय क्या है?"
    retrieved nothing although the knowledge base documents the
    Serenity Spa plunge pool.
"""

from __future__ import annotations

from sqlalchemy import select

from app.agent.language import ResponseLanguage, detect_language
from app.agent.providers.mock import _contact_args, _modification_summary_text
from app.agent.query_terms import expand_query
from app.db.session import SessionLocal
from app.knowledge import KnowledgeRepository, default_embedding_provider
from app.models.faq import FAQ
from app.models.guest import Guest
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

_ANON_IPS: dict[int, str] = {}


def _chat(hotel, message, guest_id=None, conversation_id=None, anon=False):
    body = {"hotel_id": hotel["id"], "message": message}
    if guest_id is not None:
        body["guest_id"] = guest_id
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    headers = {}
    if anon:
        ip = _ANON_IPS.setdefault(hotel["id"], uid("ip") + ".example")
        headers["x-forwarded-for"] = ip
    r = client.post("/api/v1/agent/chat", json=body, headers=headers)
    ok(r, 200)
    return r.json()


def _guest_row(hotel_id, name):
    db = SessionLocal()
    try:
        return db.scalar(
            select(Guest).where(Guest.hotel_id == hotel_id, Guest.name == name)
        )
    finally:
        db.close()


def _has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


# --------------------------------------------------------------------- #
# Bug A — language must not stick across conversations                   #
# --------------------------------------------------------------------- #


def test_new_conversation_starts_in_its_own_language():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])["id"]

    first = _chat(
        hotel, "मुझे अगले सप्ताहांत के लिए एक कमरा बुक करना है।", guest_id=guest
    )
    assert first["response_language"] == "hindi"

    # "New conversation" on a web/widget client = no conversation_id.
    # It must be a NEW conversation whose language comes from ITS first
    # message — never the previous conversation's Hindi.
    second = _chat(hotel, "Book a room for this weekend", guest_id=guest)
    assert second["conversation_id"] != first["conversation_id"]
    assert second["response_language"] == "english"
    assert not _has_devanagari(second["reply"])


def test_new_conversation_mirror_hindi_after_english():
    hotel = make_hotel()
    guest = make_guest(hotel["id"])["id"]

    first = _chat(
        hotel, "Hello, do you have any rooms available?", guest_id=guest
    )
    assert first["response_language"] == "english"

    second = _chat(hotel, "मुझे एक कमरा बुक करना है", guest_id=guest)
    assert second["conversation_id"] != first["conversation_id"]
    assert second["response_language"] == "hindi"
    assert _has_devanagari(second["reply"])


def test_confident_detection_overrides_preference_mid_conversation():
    """Within one conversation: weak slot replies keep the established
    language; a confident new-language sentence switches it."""
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe")["id"]
    guest = make_guest(hotel["id"])["id"]
    start, end = future(80), future(82)
    seed_rates_availability(room, start, 3)

    t1 = _chat(hotel, "Mujhe room book karna hai", guest_id=guest)
    assert t1["response_language"] == "hinglish"
    t2 = _chat(
        hotel,
        f"Deluxe room chalega, 2 guests, {start.isoformat()} se "
        f"{end.isoformat()} tak",
        guest_id=guest,
        conversation_id=t1["conversation_id"],
    )
    assert t2["response_language"] == "hinglish"  # weak reply: no flip

    t3 = _chat(
        hotel,
        "Actually, what is the check-in time at this hotel?",
        guest_id=guest,
        conversation_id=t1["conversation_id"],
    )
    assert t3["response_language"] == "english"  # confident switch wins


def test_weak_roman_slot_replies_are_neutral():
    # English content words alone are Hinglish loanwords — not evidence
    # of a language switch.
    assert detect_language("Deluxe room chalega, 2 guests").response_language is None
    assert detect_language("Deluxe King Room").response_language is None
    assert detect_language("Room chahiye please").response_language is None
    # A real English sentence (grammar words present) is confident.
    assert (
        detect_language("Book a room for this weekend").response_language
        is ResponseLanguage.ENGLISH
    )
    assert (
        detect_language("What is the price of the Deluxe room?").response_language
        is ResponseLanguage.ENGLISH
    )


# --------------------------------------------------------------------- #
# Bug B — Hinglish booking summary / templates                           #
# --------------------------------------------------------------------- #


def test_hinglish_booking_summary_is_hinglish():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe")["id"]
    guest = make_guest(hotel["id"])["id"]
    start, end = future(90), future(92)
    seed_rates_availability(room, start, 3)

    t1 = _chat(hotel, "Mujhe room book karna hai", guest_id=guest)
    assert t1["response_language"] == "hinglish"

    t2 = _chat(
        hotel,
        f"Deluxe room chalega, 2 guests, {start.isoformat()} se "
        f"{end.isoformat()} tak",
        guest_id=guest,
        conversation_id=t1["conversation_id"],
    )
    assert t2["response_language"] == "hinglish"
    assert "Aapki booking ka summary" in t2["reply"]
    assert "Kya main ye booking confirm kar doon?" in t2["reply"]
    # No English template sentences leak into the Hinglish summary.
    assert "Here's your booking summary" not in t2["reply"]
    assert "Total price" not in t2["reply"]
    assert "Would you like me to confirm" not in t2["reply"]

    t3 = _chat(
        hotel,
        "Ha, confirm kar do",
        guest_id=guest,
        conversation_id=t1["conversation_id"],
    )
    assert "booking confirm ho gayi" in t3["reply"]


def test_modification_summary_templates_per_language():
    data = {
        "old": {
            "room_type": "Deluxe",
            "check_in": "2026-11-14",
            "check_out": "2026-11-15",
            "number_of_guests": 2,
            "total_price": "4950.00",
        },
        "new": {
            "room_type": "Deluxe",
            "check_in": "2026-11-21",
            "check_out": "2026-11-22",
            "number_of_guests": 2,
            "total_price": "4950.00",
        },
        "currency": "INR",
        "amount_due": "0.00",
        "refund_due": "0.00",
        "difference": "0.00",
    }
    hinglish = _modification_summary_text(data, ResponseLanguage.HINGLISH)
    assert "ka summary" in hinglish
    assert "Kul price" in hinglish and "antar" in hinglish
    assert "Total price" not in hinglish and "difference" not in hinglish
    assert "Kya main ye change apply kar doon?" in hinglish

    english = _modification_summary_text(data, ResponseLanguage.ENGLISH)
    assert "Total price" in english and "difference" in english

    hindi = _modification_summary_text(data, ResponseLanguage.HINDI)
    assert "कुल कीमत" in hindi and "अंतर" in hindi


# --------------------------------------------------------------------- #
# Bug C — cross-script name capture                                      #
# --------------------------------------------------------------------- #


def test_name_capture_across_scripts():
    # Devanagari lead-in + Latin name (the exact sweep failure).
    args = _contact_args("मेरा नाम Test Guest है", 1)
    assert args is not None and args["name"] == "Test Guest"
    # Devanagari lead-in + Devanagari name.
    args = _contact_args("मेरा नाम टेस्ट गेस्ट है", 1)
    assert args is not None and args["name"] == "टेस्ट गेस्ट"
    # English lead-in + Devanagari name.
    args = _contact_args("My name is टेस्ट गेस्ट", 1)
    assert args is not None and args["name"] == "टेस्ट गेस्ट"
    # Roman-Hindi lead-in: a trailing "hai" is filler, not part of the name.
    args = _contact_args("mera naam Test Guest hai", 1)
    assert args is not None and args["name"] == "Test Guest"
    # Name + phone in one message: both captured, name stays clean.
    args = _contact_args("mera naam Test Guest, phone 9876543210", 1)
    assert args is not None and args["name"] == "Test Guest"
    assert args["phone_number"] == "9876543210"


def test_bare_name_replies_only_in_contact_context():
    args = _contact_args("Test Guest", 1, allow_bare_name=True)
    assert args is not None and args["name"] == "Test Guest"
    args = _contact_args("टेस्ट गेस्ट", 1, allow_bare_name=True)
    assert args is not None and args["name"] == "टेस्ट गेस्ट"
    # Without the contact-context flag a bare name is not identity.
    assert _contact_args("Test Guest", 1) is None
    # Flow answers must never be read as names, even in contact context.
    assert _contact_args("Deluxe room", 1, allow_bare_name=True) is None
    assert _contact_args("Do log", 1, allow_bare_name=True) is None
    assert _contact_args("Kal se parso tak", 1, allow_bare_name=True) is None


def test_hindi_conversation_captures_latin_name_and_continues():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe")["id"]
    start, end = future(100), future(102)
    seed_rates_availability(room, start, 3)

    t1 = _chat(
        hotel,
        f"मुझे Deluxe कमरा {start.isoformat()} से {end.isoformat()} तक "
        "2 लोगों के लिए बुक करना है",
        anon=True,
    )
    assert t1["response_language"] == "hindi"
    assert "नाम" in t1["reply"]  # the bot asked for identity, in Hindi

    t2 = _chat(
        hotel,
        "मेरा नाम Test Guest है",
        conversation_id=t1["conversation_id"],
        anon=True,
    )
    # The name was understood: a guest exists and the flow moved on to
    # the (Hindi) booking summary instead of the no-answer fallback.
    assert _guest_row(hotel["id"], "Test Guest") is not None
    assert "सारांश" in t2["reply"]
    assert "इसका जवाब अभी मेरे पास नहीं है" not in t2["reply"]


def test_english_conversation_captures_devanagari_name():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type="Deluxe")["id"]
    start, end = future(110), future(112)
    seed_rates_availability(room, start, 3)

    t1 = _chat(
        hotel,
        f"I want to book the Deluxe room from {start.isoformat()} to "
        f"{end.isoformat()} for 2 guests",
        anon=True,
    )
    assert "share your name" in t1["reply"]

    t2 = _chat(
        hotel,
        "My name is टेस्ट गेस्ट",
        conversation_id=t1["conversation_id"],
        anon=True,
    )
    assert _guest_row(hotel["id"], "टेस्ट गेस्ट") is not None
    assert "booking summary" in t2["reply"]


# --------------------------------------------------------------------- #
# Bug D — Hindi FAQ / knowledge grounding                                #
# --------------------------------------------------------------------- #


def test_expand_query_maps_hindi_terms():
    expanded = expand_query("स्विमिंग पूल का समय क्या है?")
    assert "pool" in expanded and "timings" in expanded
    assert "नाश्ता कितने बजे मिलता है" in expand_query(
        "नाश्ता कितने बजे मिलता है?"
    )
    assert "breakfast" in expand_query("नाश्ता कितने बजे मिलता है?")
    # Plain English passes through untouched.
    english = "What are the swimming pool timings?"
    assert expand_query(english) == english


def _seed_spa_knowledge_and_faq(hotel_id):
    db = SessionLocal()
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        repo.create_document(
            hotel_id=hotel_id,
            title="Spa and wellness",
            content=(
                "Our Serenity Spa is open daily from 9 AM to 9 PM. The "
                "wellness area features a sauna, a steam room, and a "
                "temperature-controlled plunge pool, complimentary for "
                "in-house guests."
            ),
            source="test",
        )
        db.add(
            FAQ(
                hotel_id=hotel_id,
                question="Is there a swimming pool at the hotel?",
                answer=(
                    "We do not have a full-size swimming pool; the "
                    "Serenity Spa has a temperature-controlled plunge "
                    "pool, complimentary for in-house guests."
                ),
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()


def test_hindi_pool_question_surfaces_plunge_pool():
    hotel = make_hotel()
    _seed_spa_knowledge_and_faq(hotel["id"])

    reply = _chat(hotel, "स्विमिंग पूल का समय क्या है?", anon=True)
    assert reply["response_language"] == "hindi"
    # Grounded in the knowledge base, not the no-answer fallback.
    assert "plunge pool" in reply["reply"]
    assert "इसका जवाब अभी मेरे पास नहीं है" not in reply["reply"]


def test_hindi_pool_question_via_faq_tool():
    """The FAQ tool itself (the path a real LLM takes) retrieves the
    pool entry for the Hindi query after expansion."""
    from app.agent.tools.hotel_tools import SearchFaqArgs, search_faq
    from app.agent.tools.registry import ToolContext

    hotel = make_hotel()
    _seed_spa_knowledge_and_faq(hotel["id"])
    db = SessionLocal()
    try:
        result = search_faq(
            db,
            ToolContext(hotel_id=hotel["id"]),
            SearchFaqArgs(hotel_id=hotel["id"], query="स्विमिंग पूल का समय क्या है?"),
        )
    finally:
        db.close()
    answers = " ".join(f["answer"] for f in result["results"])
    assert "plunge pool" in answers


# ---------------------------------------------------------------------------
# Round 2 (post-deploy live re-test): retrieval for Bug D was fixed, but
# the Mercury generation layer still garbled the grounded content — it
# transliterated "plunge pool" into nonsense Devanagari, dropped the
# name "Serenity Spa", and in a Hindi booking opener stated the wrong
# weekend dates in prose before the deterministic quote corrected them.
# These tests pin the prompt-level rules added for both failure modes.
# ---------------------------------------------------------------------------


def _system_prompt() -> str:
    from app.agent.prompts import build_system_prompt
    from app.agent.providers.base import ProviderContext

    ctx = ProviderContext(
        hotel_id=1,
        hotel_name="StayFlow Grand Hotel",
        currency="INR",
        today="2026-10-23",
        room_types=[],
        guest_id=None,
        guest_name=None,
    )
    return build_system_prompt(ctx)


def test_system_prompt_keeps_proper_nouns_in_original_english_spelling():
    """Facility/room names from retrieved knowledge must be quoted
    verbatim — never transliterated or translated — in every language."""
    prompt = _system_prompt()
    assert "ORIGINAL English spelling" in prompt
    assert "Serenity Spa plunge pool" in prompt
    assert "never a transliteration or" in prompt
    # Facts the knowledge contains are stated; a missing detail (timings)
    # is admitted honestly without dropping the facility's name.
    assert "say so honestly" in prompt
    assert "never drop the name" in prompt


def test_system_prompt_date_resolution_note_is_exclusive():
    """When a DETERMINISTIC DATE RESOLUTION note is present, its dates
    are the ONLY dates the reply may state — no other date in prose."""
    prompt = _system_prompt()
    assert "DETERMINISTIC DATE RESOLUTION note" in prompt
    assert "are the ONLY dates you" in prompt
    assert "never mention any other date" in prompt


def test_language_instructions_keep_proper_nouns_untransliterated():
    """The per-turn Hindi/Hinglish instructions carry the same rule,
    since they sit closest to generation."""
    from app.agent.language import build_language_instruction

    for language in (ResponseLanguage.HINDI, ResponseLanguage.HINGLISH):
        instruction = build_language_instruction(language)
        assert "original English spelling" in instruction
        assert "never transliterate or translate a proper noun" in instruction
