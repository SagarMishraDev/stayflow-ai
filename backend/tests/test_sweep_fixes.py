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


# ---------------------------------------------------------------------------
# Round 3 (post-deploy live re-test #2 + variance runs):
# 1. Knowledge pre-retrieval — retrieval worked when CALLED, but on the
#    live Mercury path the model repeatedly answered the Hindi pool
#    question without calling the knowledge tools, so the plunge-pool
#    chunk never reached generation (the reply guessed, transliterated
#    the facility's name, or dropped it). The runner now pre-retrieves
#    for LLM-backed providers and injects matches into the system
#    prompt; the mock path is untouched.
# 2. Empty-completion retry — the Hindi "unsure" fallback ("माफ़ कीजिए,
#    मैं समझ नहीं पाया…") fired intermittently on the Mercury path for
#    ordinary Hindi messages (booking AND FAQ turns). It is emitted by
#    the runner (runner.py, the "unsure" entry of _FALLBACKS) exactly
#    when the provider returns a final answer with no content and no
#    tool calls — an empty completion. The runner now re-asks once;
#    only a second empty completion earns the fallback.
# 3. Devanagari weekend phrases — "अगले सप्ताहांत" (the oblique form
#    Hindi grammar requires before के लिए) matched only the bare
#    सप्ताहांत pattern and resolved as THIS weekend, so the
#    DETERMINISTIC DATE RESOLUTION note itself pinned 24–25 Oct and
#    the model's prose faithfully restated the wrong dates; वीकेंड
#    matched nothing at all.
# ---------------------------------------------------------------------------

from app.agent.providers.base import LLMResponse  # noqa: E402
from app.agent.runner import run_chat  # noqa: E402


class _CapturingLlmProvider:
    """Records what the runner hands an LLM-backed provider."""

    name = "capturing-llm"

    def __init__(self, content="Noted."):
        self.messages = None
        self.context = None
        self.calls = 0
        self._content = content

    def chat(self, messages, tools, context):
        self.calls += 1
        self.messages = messages
        self.context = context
        return LLMResponse(content=self._content)


def _run_with_provider(hotel_id, message, provider):
    db = SessionLocal()
    try:
        return run_chat(db, hotel_id=hotel_id, message=message, provider=provider)
    finally:
        db.close()


def test_llm_turn_injects_matching_knowledge_for_hindi_pool_query():
    hotel = make_hotel()
    _seed_spa_knowledge_and_faq(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "स्विमिंग पूल का समय क्या है?", provider)
    system = provider.messages[0]["content"]
    assert "RETRIEVED HOTEL KNOWLEDGE" in system
    # The grounded chunk reaches generation even though the provider
    # never asked for a tool call.
    assert "Serenity Spa" in system
    assert "plunge pool" in system


def test_llm_turn_injects_nothing_for_unrelated_message():
    hotel = make_hotel()
    _seed_spa_knowledge_and_faq(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "hello", provider)
    system = provider.messages[0]["content"]
    assert "RETRIEVED HOTEL KNOWLEDGE" not in system


def _seed_borealis_knowledge_and_faq(hotel_id):
    db = SessionLocal()
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        repo.create_document(
            hotel_id=hotel_id,
            title="Borealis Spa guide",
            content=(
                "The Borealis Spa swimming pool and plunge pool are open "
                "24 hours. The Borealis wellness area also has a sauna."
            ),
            source="test",
        )
        db.add(
            FAQ(
                hotel_id=hotel_id,
                question="Is there a swimming pool?",
                answer="Yes, the Borealis Spa swimming pool is open 24 hours.",
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()


def test_llm_turn_never_injects_another_hotels_knowledge():
    hotel_a = make_hotel()
    _seed_spa_knowledge_and_faq(hotel_a["id"])
    hotel_b = make_hotel()
    _seed_borealis_knowledge_and_faq(hotel_b["id"])

    provider = _CapturingLlmProvider()
    _run_with_provider(hotel_a["id"], "स्विमिंग पूल का समय क्या है?", provider)
    system = provider.messages[0]["content"]
    assert "Serenity Spa" in system  # hotel A's own knowledge is injected
    assert "Borealis" not in system  # hotel B's never leaks across hotels


class _EmptyThenAnswerProvider:
    """First turn: an empty completion. Second: a real answer."""

    name = "empty-then-answer"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools, context):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="")
        return LLMResponse(content="Here is your answer.")


class _AlwaysEmptyProvider:
    name = "always-empty"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools, context):
        self.calls += 1
        return LLMResponse(content="")


def test_empty_completion_is_retried_once_before_unsure_fallback():
    hotel = make_hotel()
    provider = _EmptyThenAnswerProvider()
    result = _run_with_provider(hotel["id"], "मुझे कमरा बुक करना है", provider)
    assert provider.calls == 2  # the empty completion was re-asked once
    assert result.reply == "Here is your answer."
    assert result.degraded is False


def test_second_empty_completion_still_earns_unsure_fallback():
    hotel = make_hotel()
    provider = _AlwaysEmptyProvider()
    result = _run_with_provider(hotel["id"], "मुझे कमरा बुक करना है", provider)
    assert provider.calls == 2  # initial call + exactly one retry
    # The exact live-observed Hindi fallback text.
    assert result.reply == (
        "माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप इसे दूसरे शब्दों में बता सकते हैं?"
    )


def test_resolver_devanagari_weekend_phrases_frozen_clock():
    from datetime import date

    from app.agent.relative_dates import resolve_relative_stay

    friday = date(2026, 10, 23)  # a Friday

    # The exact live opener: oblique अगले + सप्ताहांत = NEXT weekend.
    stay = resolve_relative_stay(
        "मुझे अगले सप्ताहांत के लिए कमरा बुक करना है", friday
    )
    assert stay is not None and stay.key == "next_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 31), date(2026, 11, 1))

    stay = resolve_relative_stay("इस सप्ताहांत कमरा चाहिए", friday)
    assert stay is not None and stay.key == "this_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))

    stay = resolve_relative_stay("सप्ताहांत पर आना है", friday)
    assert stay is not None and stay.key == "this_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))

    # वीकेंड forms previously matched nothing at all.
    stay = resolve_relative_stay("अगले वीकेंड कमरा चाहिए", friday)
    assert stay is not None and stay.key == "next_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 31), date(2026, 11, 1))

    stay = resolve_relative_stay("इस वीकेंड कमरा चाहिए", friday)
    assert stay is not None and stay.key == "this_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))

    stay = resolve_relative_stay("वीकेंड पर आना है", friday)
    assert stay is not None and stay.key == "this_weekend"
    assert (stay.check_in, stay.check_out) == (date(2026, 10, 24), date(2026, 10, 25))


def test_hindi_next_weekend_note_reaches_prompt_with_correct_dates():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    hotel = make_hotel()
    provider = _CapturingLlmProvider()
    _run_with_provider(
        hotel["id"], "मुझे अगले सप्ताहांत के लिए कमरा बुक करना है", provider
    )
    system = provider.messages[0]["content"]
    assert "DETERMINISTIC DATE RESOLUTION" in system
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    imminent_saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    next_saturday = imminent_saturday + timedelta(days=7)
    # The note pins NEXT weekend's Saturday as check-in — not this
    # weekend's (the pre-fix resolver resolved अगले सप्ताहांत to the
    # imminent Saturday and the note carried those wrong dates).
    assert f"check-in {next_saturday.isoformat()}" in system
    assert f"check-in {imminent_saturday.isoformat()}" not in system


# ---------------------------------------------------------------------------
# Round 4 (post-deploy live re-test #3): the Round-3 pre-retrieval note
# still failed the Hindi pool question live, 0/2 — but the replies
# quoted the CHECK-IN chunk (welcome envelope), proving injection ran
# and surfaced the wrong material. Diagnosis against the REAL demo
# knowledge set (the 5 documents of scripts/seed_knowledge.py and the
# 4 FAQs of scripts/seed_demo.py, hashed embeddings):
#
# - Hindi pool query: the plunge-pool chunk ranked 6th of 10 chunks
#   (cosine 0.0950), behind both cancellation chunks and the check-in
#   chunk — generic expansion words ("timings", "hours", "open") are
#   scattered across every document, the discriminative word "pool"
#   sits in ONE 120-word chunk, and "swimming" occurs nowhere in the
#   knowledge base. Top-3 cut => the spa chunk was never injected.
# - Hinglish "pool ka timing kya hai?" ranked it 4th (0.2281).
# - search_faq (no ranking, ANY-word match) returned ONLY the
#   airport-transfers FAQ for the Hindi pool query — matched via the
#   word "hours" in "book at least 4 hours ahead".
# - The greeting "hello" scored 0.1075 against the spa chunk through
#   a pure hash-bucket collision (no shared token) and WAS injected.
#
# The Round-1/3 fixtures never showed any of this: a lone short spa
# document + a pool FAQ have no competitors. These tests therefore
# seed the actual demo content, competitors included.
# ---------------------------------------------------------------------------


def _seed_realistic_demo_content(hotel_id):
    """Seed the content the live demo actually runs: the 5 documents
    from scripts/seed_knowledge.py (check-in instructions with the
    welcome-envelope text competing against the spa document) and the
    4 FAQs from scripts/seed_demo.py (none of them about a pool)."""
    import importlib.util
    from pathlib import Path

    scripts = Path(__file__).resolve().parent.parent / "scripts"

    def _load(name):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    seed_knowledge = _load("seed_knowledge")
    seed_demo = _load("seed_demo")

    db = SessionLocal()
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        for title, content in seed_knowledge.DOCS:
            repo.create_document(
                hotel_id=hotel_id, title=title, content=content, source="test"
            )
        for question, answer, category in seed_demo.FAQS:
            db.add(
                FAQ(
                    hotel_id=hotel_id,
                    question=question,
                    answer=answer,
                    category=category,
                    is_active=True,
                )
            )
        db.commit()
    finally:
        db.close()


def _injected_note(system_prompt: str) -> str:
    """The RETRIEVED HOTEL KNOWLEDGE section of a captured prompt."""
    assert "RETRIEVED HOTEL KNOWLEDGE" in system_prompt
    return system_prompt.split("RETRIEVED HOTEL KNOWLEDGE", 1)[1].split(
        "Answer the guest's question", 1
    )[0]


def test_hindi_pool_query_injects_plunge_pool_from_realistic_demo_content():
    hotel = make_hotel()
    _seed_realistic_demo_content(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "स्विमिंग पूल का समय क्या है?", provider)
    note = _injected_note(provider.messages[0]["content"])
    # The grounded facility chunk reaches generation, first in the note.
    assert "plunge pool" in note
    assert "Serenity Spa" in note
    assert note.index("plunge pool") < note.index("welcome envelope")
    # The airport FAQ matched the pre-fix note only via the generic
    # word "hours"; the topic filter drops it for a pool question.
    assert "airport transfers" not in note.lower()


def test_english_pool_query_injects_plunge_pool_from_realistic_demo_content():
    hotel = make_hotel()
    _seed_realistic_demo_content(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "What are the swimming pool timings?", provider)
    note = _injected_note(provider.messages[0]["content"])
    assert "plunge pool" in note
    assert "Serenity Spa" in note


def test_hinglish_pool_query_injects_plunge_pool_from_realistic_demo_content():
    hotel = make_hotel()
    _seed_realistic_demo_content(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "pool ka timing kya hai?", provider)
    note = _injected_note(provider.messages[0]["content"])
    # Pre-fix this query ranked the plunge-pool chunk 4th — outside
    # the injected top-3 — and injected the fitness chunk instead.
    assert "plunge pool" in note
    assert "Serenity Spa" in note


def test_greeting_injects_nothing_from_realistic_demo_content():
    hotel = make_hotel()
    _seed_realistic_demo_content(hotel["id"])
    provider = _CapturingLlmProvider()
    _run_with_provider(hotel["id"], "hello", provider)
    system = provider.messages[0]["content"]
    # Pre-fix, "hello" scored 0.1075 against the spa chunk through a
    # hash-bucket collision (no shared token) and it WAS injected.
    assert "RETRIEVED HOTEL KNOWLEDGE" not in system


def test_exact_term_scan_never_crosses_hotels():
    hotel_a = make_hotel()
    _seed_realistic_demo_content(hotel_a["id"])
    hotel_b = make_hotel()
    db = SessionLocal()
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        repo.create_document(
            hotel_id=hotel_b["id"],
            title="Zorblax Spa guide",
            content=(
                "The Zorblax Spa plunge pool is open around the clock "
                "for Zorblax guests only."
            ),
            source="test",
        )
        db.commit()
    finally:
        db.close()

    provider = _CapturingLlmProvider()
    _run_with_provider(hotel_a["id"], "स्विमिंग पूल का समय क्या है?", provider)
    system = provider.messages[0]["content"]
    assert "Serenity Spa" in system  # hotel A's own chunk, via the scan
    assert "Zorblax" not in system  # hotel B's chunk never leaks


def test_targeted_terms_and_matching_helpers():
    from app.agent.query_terms import targeted_terms, text_matches_term

    hindi = targeted_terms("स्विमिंग पूल का समय क्या है?")
    assert "pool" in hindi
    # The generic time entry never counts as a targeted term.
    assert "timings hours open" not in hindi
    assert "pool" in targeted_terms("pool ka timing kya hai?")
    assert "pool" in targeted_terms("What are the swimming pool timings?")
    assert "check-in" in targeted_terms("चेक-इन का समय क्या है?")
    assert targeted_terms("hello") == []

    # Token-boundary matching: no substring false positives, and
    # hyphenation differences do not hide a real match.
    assert text_matches_term("The wellness area has a plunge pool.", "pool")
    assert not text_matches_term("The pool is spacious.", "spa")
    assert text_matches_term("Is Wi-Fi free?", "wifi internet")
    assert text_matches_term("Check-in is from 2 PM.", "check-in")
    # Generic time words alone never make a text "about" a term.
    assert not text_matches_term("Book at least 4 hours ahead.", "pool")
