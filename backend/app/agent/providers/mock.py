"""Deterministic mock LLM provider.

Two modes:

1. **Scripted** (used by automated tests): ``script`` is a list of steps that
   are consumed in order. A step is either
   ``{"content": "..."}`` or
   ``{"tool_calls": [{"name": "...", "arguments": {...}}, ...]}``.

2. **Keyword router** (used for demos without an LLM): the last guest message
   is matched against simple keyword rules and mapped to tool calls.
   Anything it cannot handle gets a clarifying reply — it never invents
   prices, availability, or bookings.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from app.agent.language import ResponseLanguage
from app.agent.providers.base import (
    LLMResponse,
    ProviderContext,
    ToolCallRequest,
)

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Day-first numeric dates (Indian locale): 23/11/2026, 23-11-2026, 23.11.2026
# all mean 23 Nov 2026. A US-style 11/23/2026 yields month=23, which is
# invalid and gets skipped by _make_date.
_DMY_DATE_RE = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})")
_MONTH_NAME_DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.IGNORECASE
)
_MONTH_FIRST_DATE_RE = re.compile(
    r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.IGNORECASE
)
_MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_GUESTS_RE = re.compile(r"(\d+)\s*(guest|person|people|adult|pax|मेहमान|लोग)", re.IGNORECASE)
_BOOKING_ID_RE = re.compile(
    r"(?:booking|बुकिंग)\s*(?:id|#|number|नंबर)?\s*[:#]?\s*(\d+)", re.IGNORECASE
)
_CONFIRM_RE = re.compile(
    r"\b(yes|confirm|confirmed|proceed|go ahead|book it|haan|bilkul|pakka|"
    r"confirm kar do)\b|हाँ|कन्फर्म|ठीक है",
    re.IGNORECASE,
)
_GUEST_EMAIL_RE = re.compile(r"[\w.\-]+@[\w.\-]+\.\w+")
_GUEST_PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{6,}\d)")
_GUEST_NAME_RE = re.compile(
    r"(?:my name is|mera naam|this is|i am|i'm)\s+"
    r"([a-zA-Z][a-zA-Z\s.\-']{1,40}?)(?:\s*,|\s+and\s+|\s*$)",
    re.IGNORECASE,
)
# Guest questions that belong to the hotel's unstructured knowledge base
# (handbook, spa, dining, transfers, local guides) rather than to the SQL
# tools. Checked before the FAQ fallback; price/availability/policy/booking
# keywords above always win.
_KNOWLEDGE_KEYWORDS = (
    "spa",
    "wellness",
    "sauna",
    "massage",
    "airport",
    "flight",
    "shuttle",
    "taxi",
    "transfer",
    "pickup",
    "pick-up",
    "pick up",
    "restaurant",
    "dining",
    "dinner",
    "lunch",
    "breakfast",
    "buffet",
    "cuisine",
    "cafe",
    "bar",
    "lounge",
    "pool",
    "swimming",
    "gym",
    "fitness",
    "sightseeing",
    "attraction",
    "nearby",
    "concierge",
    "wifi",
    "internet",
    "handbook",
    "local guide",
)


def _lang(context: ProviderContext) -> ResponseLanguage:
    try:
        return ResponseLanguage(context.response_language or "english")
    except ValueError:
        return ResponseLanguage.ENGLISH


# Guest-facing template strings per response language. Core flows only —
# data-driven answers (FAQ text, knowledge chunks, policy text) come from
# the hotel's own content and are returned verbatim in every language.
_STRINGS: dict[str, dict[ResponseLanguage, str]] = {
    "help": {
        ResponseLanguage.ENGLISH: (
            "I can help with room availability, prices, policies, bookings, "
            "food orders, and service requests. What would you like to do?"
        ),
        ResponseLanguage.HINDI: (
            "मैं आपकी मदद कर सकता हूँ — कमरे की उपलब्धता, कीमतें, नीतियाँ, "
            "बुकिंग, खाने के ऑर्डर और सेवा अनुरोधों में। आप क्या करना चाहेंगे?"
        ),
        ResponseLanguage.HINGLISH: (
            "Main aapki help kar sakta hoon — room availability, prices, "
            "policies, bookings, food orders aur service requests mein. "
            "Aap kya karna chahenge?"
        ),
    },
    "avail_ask_dates": {
        ResponseLanguage.ENGLISH: (
            "I can check availability{room_hint}. Which dates? "
            "Please share check-in and check-out dates (YYYY-MM-DD)."
        ),
        ResponseLanguage.HINDI: (
            "मैं उपलब्धता देख सकता हूँ{room_hint}। कौन-सी तारीख़ें चाहिए? "
            "कृपया चेक-इन और चेक-आउट की तारीख़ें बताइए (YYYY-MM-DD)।"
        ),
        ResponseLanguage.HINGLISH: (
            "Main availability check kar sakta hoon{room_hint}. Kaun-si "
            "dates chahiye? Please check-in aur check-out dates bata "
            "dijiye (YYYY-MM-DD)."
        ),
    },
    "price_ask": {
        ResponseLanguage.ENGLISH: (
            "I can share exact pricing. Which room type and dates "
            "(check-in / check-out, YYYY-MM-DD) should I quote?"
        ),
        ResponseLanguage.HINDI: (
            "मैं सही कीमत बता सकता हूँ। कौन-सा कमरा और कौन-सी तारीख़ें (चेक-इन / चेक-आउट, YYYY-MM-DD) देखूँ?"
        ),
        ResponseLanguage.HINGLISH: (
            "Main exact price bata sakta hoon. Kaun-sa room type aur kaun-si "
            "dates (check-in / check-out, YYYY-MM-DD) quote karoon?"
        ),
    },
    "cancel_ask_id": {
        ResponseLanguage.ENGLISH: "I can cancel your booking. Please share your booking ID.",
        ResponseLanguage.HINDI: "मैं आपकी बुकिंग रद्द कर सकता हूँ। कृपया अपना बुकिंग ID बताइए।",
        ResponseLanguage.HINGLISH: (
            "Main aapki booking cancel kar sakta hoon. Please apna booking ID bata dijiye."
        ),
    },
    "booking_missing": {
        ResponseLanguage.ENGLISH: "Happy to help with the booking! I still need: {missing}.",
        ResponseLanguage.HINDI: "बुकिंग में खुशी से मदद करूँगा! मुझे अभी चाहिए: {missing}।",
        ResponseLanguage.HINGLISH: (
            "Booking mein khushi se help karunga! Mujhe abhi chahiye: {missing}."
        ),
    },
    "booking_ask_contact": {
        ResponseLanguage.ENGLISH: (
            "I'd be happy to book that for you. Could you share your "
            "name and an email or phone number so I can hold the room?"
        ),
        ResponseLanguage.HINDI: (
            "मैं खुशी से यह बुकिंग कर दूँगा। कृपया अपना नाम और ईमेल या "
            "फ़ोन नंबर बताइए, ताकि मैं कमरा आपके लिए रख सकूँ।"
        ),
        ResponseLanguage.HINGLISH: (
            "Main khushi se ye booking kar dunga. Please apna naam aur "
            "email ya phone number bata dijiye, taaki main room aapke "
            "liye hold kar sakoon."
        ),
    },
    "draft_failed": {
        ResponseLanguage.ENGLISH: (
            "I wasn't able to prepare that booking draft. Could you "
            "tell me the room type and dates again so I can retry?"
        ),
        ResponseLanguage.HINDI: (
            "माफ़ कीजिए, मैं यह बुकिंग ड्राफ़्ट तैयार नहीं कर पाया। क्या आप "
            "कमरे का प्रकार और तारीख़ें फिर से बता सकते हैं?"
        ),
        ResponseLanguage.HINGLISH: (
            "Sorry, main ye booking draft prepare nahi kar paya. Kya aap "
            "room type aur dates phir se bata sakte hain, taaki main retry karoon?"
        ),
    },
    "order_ask_contact": {
        ResponseLanguage.ENGLISH: (
            "Almost done — I just need your name and a phone number or "
            "email to place the order against your stay."
        ),
        ResponseLanguage.HINDI: (
            "बस एक चीज़ और — ऑर्डर के लिए कृपया अपना नाम और फ़ोन नंबर या ईमेल बता दीजिए।"
        ),
        ResponseLanguage.HINGLISH: (
            "Bas ek cheez aur — order ke liye please apna naam aur phone "
            "number ya email bata dijiye."
        ),
    },
    "order_ask_item": {
        ResponseLanguage.ENGLISH: (
            "Sure! What would you like to order? Our menu has: {items}. "
            "Tell me the item, quantity, and when you want it."
        ),
        ResponseLanguage.HINDI: (
            "बिल्कुल! आप क्या ऑर्डर करना चाहेंगे? हमारे मेनू में है: {items}। आइटम, मात्रा और समय बता दीजिए।"
        ),
        ResponseLanguage.HINGLISH: (
            "Bilkul! Aap kya order karna chahenge? Hamare menu mein hai: "
            "{items}. Item, quantity aur time bata dijiye."
        ),
    },
    "order_ask_qty": {
        ResponseLanguage.ENGLISH: "How many {item} would you like, and when should we serve it?",
        ResponseLanguage.HINDI: "आपको कितने {item} चाहिए, और यह कब चाहिए?",
        ResponseLanguage.HINGLISH: "Aapko kitne {item} chahiye, aur ye kab chahiye?",
    },
    "order_ask_when": {
        ResponseLanguage.ENGLISH: (
            "Noted: {item} × {qty}. When would you like it — a date/time, "
            "or after check-in? (Room number is fine to share later, "
            "after check-in.)"
        ),
        ResponseLanguage.HINDI: (
            "ठीक है: {item} × {qty}। यह आपको कब चाहिए — कोई तारीख़/समय, "
            "या चेक-इन के बाद? (कमरा नंबर चेक-इन के बाद देना ठीक है।)"
        ),
        ResponseLanguage.HINGLISH: (
            "Noted: {item} × {qty}. Ye aapko kab chahiye — koi date/time, "
            "ya check-in ke baad? (Room number check-in ke baad dena "
            "bilkul theek hai.)"
        ),
    },
}


def _t(lang: ResponseLanguage, key: str, **fmt: Any) -> str:
    template = _STRINGS[key][lang]
    return template.format(**fmt) if fmt else template


def _summarize(
    tool_name: str, data: dict[str, Any], lang: ResponseLanguage = ResponseLanguage.ENGLISH
) -> str | None:
    """Render a tool result as a short guest-facing message."""
    if tool_name == "check_room_availability":
        nights = data.get("nights", [])
        if data.get("fully_available"):
            if lang is ResponseLanguage.HINDI:
                return (
                    f"अच्छी खबर! {data.get('room_type')} कमरा आपकी तारीख़ों के लिए "
                    f"उपलब्ध है ({data.get('check_in')} से {data.get('check_out')})। "
                    "क्या मैं कीमत बताऊँ या बुकिंग शुरू करूँ?"
                )
            if lang is ResponseLanguage.HINGLISH:
                return (
                    f"Good news! {data.get('room_type')} room aapki dates ke liye "
                    f"available hai ({data.get('check_in')} se {data.get('check_out')}). "
                    "Kya main price bataun ya booking start karoon?"
                )
            return (
                f"Good news! The {data.get('room_type')} room is available for your "
                f"dates ({data.get('check_in')} to {data.get('check_out')}). "
                "Would you like me to share the price or start a booking?"
            )
        bad = [n["date"] for n in nights if not n.get("available")]
        if lang is ResponseLanguage.HINDI:
            return (
                f"माफ़ कीजिए, {data.get('room_type')} कमरा इन तारीख़ों पर उपलब्ध "
                f"नहीं है: {', '.join(bad)}। क्या आप दूसरी तारीख़ें देखना चाहेंगे?"
            )
        if lang is ResponseLanguage.HINGLISH:
            return (
                f"Sorry, {data.get('room_type')} room in dates par available "
                f"nahi hai: {', '.join(bad)}. Kya aap dusri dates try karna chahenge?"
            )
        return (
            f"Unfortunately the {data.get('room_type')} room is not available on "
            f"{', '.join(bad)}. Would you like to try different dates?"
        )
    if tool_name == "get_room_rate":
        if data.get("fully_priced"):
            if lang is ResponseLanguage.HINDI:
                return (
                    f"{data.get('room_type')} कमरे की कुल कीमत {data.get('total')} "
                    f"{data.get('currency')} है, {data.get('check_in')} से "
                    f"{data.get('check_out')} के लिए।"
                )
            if lang is ResponseLanguage.HINGLISH:
                return (
                    f"{data.get('room_type')} room ki total price {data.get('total')} "
                    f"{data.get('currency')} hai, {data.get('check_in')} se "
                    f"{data.get('check_out')} ke liye."
                )
            return (
                f"The {data.get('room_type')} room costs {data.get('total')} "
                f"{data.get('currency')} in total for {data.get('check_in')} to "
                f"{data.get('check_out')}."
            )
        if lang is ResponseLanguage.HINDI:
            return "इन तारीख़ों की पूरी कीमत अभी मेरे पास नहीं है। मैं होटल से पता करके बताता हूँ।"
        if lang is ResponseLanguage.HINGLISH:
            return (
                "In dates ki complete pricing abhi mere paas nahi hai. "
                "Main hotel se check karke batata hoon."
            )
        return "I don't have complete pricing for those dates yet. Let me check with the hotel."
    if tool_name == "get_hotel_policy":
        policies = data.get("policies", [])
        if not policies:
            return "I couldn't find that policy. Is there something else I can help with?"
        lines = "; ".join(f"{p['title']}: {p['description']}" for p in policies)
        return f"Here's our policy: {lines}."
    if tool_name == "search_faq":
        results = data.get("results", [])
        if not results:
            if lang is ResponseLanguage.HINDI:
                return "माफ़ कीजिए, इसका जवाब अभी मेरे पास नहीं है। क्या मैं आपको फ्रंट डेस्क से जोड़ दूँ?"
            if lang is ResponseLanguage.HINGLISH:
                return (
                    "Sorry, iska jawab abhi mere paas nahi hai. Kya main aapko "
                    "front desk se connect kar doon?"
                )
            return (
                "I don't have an answer for that yet. Would you like me to connect "
                "you with the front desk?"
            )
        top = results[0]
        return top["answer"]
    if tool_name == "search_hotel_knowledge":
        results = data.get("results", [])
        if not results:
            if lang is ResponseLanguage.HINDI:
                return "इसकी विस्तृत जानकारी अभी हमारी होटल गाइड में नहीं है। क्या मैं फ्रंट डेस्क से पता करूँ?"
            if lang is ResponseLanguage.HINGLISH:
                return (
                    "Iski detailed information abhi hamari hotel guide mein "
                    "nahi hai. Kya main front desk se check karoon?"
                )
            return (
                "I don't have detailed information on that in our hotel guide "
                "yet. Shall I check with the front desk?"
            )
        return results[0]["content"]
    if tool_name == "list_rooms":
        rooms = data.get("rooms", [])
        if not rooms:
            return "We don't have any room types configured right now."
        lines = ", ".join(f"{r['room_type']} (sleeps {r['capacity']})" for r in rooms)
        return f"We have the following room types: {lines}."
    if tool_name == "get_services":
        services = data.get("services", [])
        if not services:
            return "We don't have any services listed right now."
        lines = ", ".join(s["name"] for s in services)
        return f"Available services: {lines}."
    if tool_name == "get_offers":
        offers = data.get("offers", [])
        if not offers:
            return "There are no active offers right now."
        lines = "; ".join(f"{o['name']}: {o['description']}" for o in offers)
        return f"Current offers: {lines}."
    if tool_name == "get_menu":
        items = data.get("items", [])
        if not items:
            if lang is ResponseLanguage.HINDI:
                return "अभी मेनू खाली है।"
            if lang is ResponseLanguage.HINGLISH:
                return "Abhi menu khali hai."
            return "The menu is empty right now."
        lines = ", ".join(f"{i['name']} ({i['price']})" for i in items[:10])
        if lang is ResponseLanguage.HINDI:
            return f"हमारा मेनू: {lines}। ऑर्डर करना हो तो आइटम, मात्रा और समय बता दीजिए।"
        if lang is ResponseLanguage.HINGLISH:
            return f"Hamara menu: {lines}. Order karna ho to item, quantity aur time bata dijiye."
        return f"Here's our menu: {lines}."
    if tool_name == "preview_booking":
        d = data.get("details", {})
        if lang is ResponseLanguage.HINDI:
            return (
                "आपकी बुकिंग का सारांश:\n"
                f"- कमरा: {d.get('room_type')}\n"
                f"- चेक-इन: {d.get('check_in')}, चेक-आउट: {d.get('check_out')}\n"
                f"- मेहमान: {d.get('number_of_guests')}\n"
                f"- कुल कीमत: {d.get('total_price')} {d.get('currency', '')}\n"
                "क्या मैं यह बुकिंग कन्फर्म कर दूँ?"
            )
        if lang is ResponseLanguage.HINGLISH:
            return (
                "Aapki booking ka summary:\n"
                f"- Room: {d.get('room_type')}\n"
                f"- Check-in: {d.get('check_in')}, Check-out: {d.get('check_out')}\n"
                f"- Guests: {d.get('number_of_guests')}\n"
                f"- Total price: {d.get('total_price')} {d.get('currency', '')}\n"
                "Kya main ye booking confirm kar doon?"
            )
        return (
            "Here's your booking summary:\n"
            f"- Room: {d.get('room_type')}\n"
            f"- Check-in: {d.get('check_in')}, Check-out: {d.get('check_out')}\n"
            f"- Guests: {d.get('number_of_guests')}\n"
            f"- Total price: {d.get('total_price')} {d.get('currency', '')}\n"
            "Would you like me to confirm this booking?"
        )
    if tool_name == "create_booking":
        if lang is ResponseLanguage.HINDI:
            return (
                f"आपकी बुकिंग कन्फर्म हो गई है! बुकिंग ID {data.get('booking_id')}, "
                f"{data.get('room_type')}, {data.get('check_in')} से {data.get('check_out')}, "
                f"कुल {data.get('final_price')}।"
            )
        if lang is ResponseLanguage.HINGLISH:
            return (
                f"Aapki booking confirm ho gayi hai! Booking ID {data.get('booking_id')}, "
                f"{data.get('room_type')}, {data.get('check_in')} se {data.get('check_out')}, "
                f"total {data.get('final_price')}."
            )
        return (
            f"Your booking is confirmed! Booking ID {data.get('booking_id')}, "
            f"{data.get('room_type')}, {data.get('check_in')} to {data.get('check_out')}, "
            f"total {data.get('final_price')}."
        )
    if tool_name == "cancel_booking":
        if lang is ResponseLanguage.HINDI:
            return (
                f"बुकिंग {data.get('booking_id')} रद्द कर दी गई है "
                f"(स्थिति: {data.get('booking_status')})।"
            )
        if lang is ResponseLanguage.HINGLISH:
            return (
                f"Booking {data.get('booking_id')} cancel kar di gayi hai "
                f"(status: {data.get('booking_status')})."
            )
        return (
            f"Booking {data.get('booking_id')} has been cancelled "
            f"(status: {data.get('booking_status')})."
        )
    if tool_name == "get_booking":
        return (
            f"Booking {data.get('booking_id')}: {data.get('room_type')}, "
            f"{data.get('check_in')} to {data.get('check_out')}, "
            f"status {data.get('booking_status')}, total {data.get('final_price')}."
        )
    if tool_name == "create_food_order":
        items = data.get("items", [])
        item_lines = ", ".join(f"{i.get('name')} × {i.get('quantity')}" for i in items)
        if lang is ResponseLanguage.HINDI:
            return (
                f"आपका खाने का ऑर्डर कन्फर्म हो गया है! ऑर्डर ID {data.get('order_id')}"
                + (f", आइटम: {item_lines}" if item_lines else "")
                + f", कुल {data.get('total_amount')}।"
            )
        if lang is ResponseLanguage.HINGLISH:
            return (
                f"Aapka food order confirm ho gaya hai! Order ID {data.get('order_id')}"
                + (f", items: {item_lines}" if item_lines else "")
                + f", total {data.get('total_amount')}."
            )
        return (
            f"Your food order is confirmed! Order ID {data.get('order_id')}, "
            f"total {data.get('total_amount')}."
        )
    if tool_name == "create_service_request":
        return (
            f"Done! I've raised your request for {data.get('service_name')} "
            f"(request ID {data.get('service_request_id')}). Our team will attend shortly."
        )
    if tool_name == "evaluate_price_offer":
        if data.get("accepted"):
            return f"Great news — your offer of {data.get('offered_price')} is accepted!"
        if data.get("requires_approval"):
            return (
                f"Your offer of {data.get('offered_price')} needs staff approval. "
                f"{data.get('reason')}"
            )
        return f"I'm afraid we can't accept {data.get('offered_price')}. {data.get('reason')}"
    if tool_name == "find_or_create_guest":
        return None  # internal step; let the router continue
    return None


def _make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_dates(text: str) -> list[date]:
    """All real calendar dates mentioned in `text`, in mention order.

    Supports ISO (2026-11-23), day-first numeric (23/11/2026, 23-11-2026,
    23.11.2026), month names (23 Nov 2026 / Nov 23, 2026), and the relative
    words today / tomorrow. Invalid dates (e.g. 31/02/2026) are skipped.
    Each matched span is blanked out before the next pattern runs so one
    date is never counted twice in two different formats.
    """
    found: list[date] = []
    work = text
    for match in _DATE_RE.finditer(work):
        parsed = _make_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed is not None:
            found.append(parsed)
    work = _DATE_RE.sub(" ", work)
    for match in _DMY_DATE_RE.finditer(work):
        # Day-first: group(1)=day, group(2)=month (Indian locale).
        parsed = _make_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if parsed is not None:
            found.append(parsed)
    work = _DMY_DATE_RE.sub(" ", work)
    for match in _MONTH_NAME_DATE_RE.finditer(work):
        month = _MONTH_NUMBERS.get(match.group(2)[:3].lower())
        if month is None:
            continue
        parsed = _make_date(int(match.group(3)), month, int(match.group(1)))
        if parsed is not None:
            found.append(parsed)
    work = _MONTH_NAME_DATE_RE.sub(" ", work)
    for match in _MONTH_FIRST_DATE_RE.finditer(work):
        month = _MONTH_NUMBERS.get(match.group(1)[:3].lower())
        if month is None:
            continue
        parsed = _make_date(int(match.group(3)), month, int(match.group(2)))
        if parsed is not None:
            found.append(parsed)
    lowered = text.lower()
    if "tomorrow" in lowered:
        parsed = date.today() + timedelta(days=1)
        if parsed not in found:
            found.append(parsed)
    if "today" in lowered:
        parsed = date.today()
        if parsed not in found:
            found.append(parsed)
    return found


def _strip_date_mentions(text: str) -> str:
    """Remove every date mention (all supported formats) from `text`."""
    work = _DATE_RE.sub(" ", text)
    work = _DMY_DATE_RE.sub(" ", work)
    work = _MONTH_NAME_DATE_RE.sub(" ", work)
    return _MONTH_FIRST_DATE_RE.sub(" ", work)


def _contact_args(text: str, hotel_id: int) -> dict[str, Any] | None:
    """find_or_create_guest arguments parsed from a guest message, if any."""
    email_match = _GUEST_EMAIL_RE.search(text)
    # Dates in any supported format must not be mistaken for phone numbers.
    phone_match = _GUEST_PHONE_RE.search(_strip_date_mentions(text))
    name_match = _GUEST_NAME_RE.search(text)
    if not (email_match or phone_match or name_match):
        return None
    args: dict[str, Any] = {"hotel_id": hotel_id}
    if name_match:
        args["name"] = name_match.group(1).strip()
    if email_match:
        args["email"] = email_match.group(0)
    if phone_match:
        args["phone_number"] = re.sub(r"[\s\-]", "", phone_match.group(1))
    return args


def _gather_booking_slots(
    messages: list[dict[str, Any]], room_types: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[date], int | None]:
    """Collect booking slots from ALL guest messages (oldest first).

    Slot carryover: a room named two turns ago plus dates given now (or
    vice versa) must complete the booking. The most recent mention wins
    for room and guest count; dates accumulate in mention order,
    de-duplicated (first = check-in, second = check-out).
    """
    room: dict[str, Any] | None = None
    dates: list[date] = []
    guests: int | None = None
    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = str(msg.get("content", ""))
        matched = _match_room_type(text, room_types)
        if matched is not None:
            room = matched
        for parsed in _extract_dates(text):
            if parsed not in dates:
                dates.append(parsed)
        guests_match = _GUESTS_RE.search(text)
        if guests_match:
            guests = int(guests_match.group(1))
    return room, dates, guests


def _match_room_type(text: str, room_types: list[dict[str, Any]]) -> dict[str, Any] | None:
    lowered = text.lower()
    for room in room_types:
        name = str(room.get("room_type", ""))
        if name and name.lower() in lowered:
            return room
    return None


class MockProvider:
    """Deterministic stand-in for an LLM. Safe default when no LLM is configured."""

    name = "mock"

    def __init__(self, script: list[dict[str, Any]] | None = None) -> None:
        self.script = list(script or [])

    @property
    def available_tools(self) -> list[str]:
        from app.agent.tools.registry import build_registry

        return build_registry().names

    # ------------------------------------------------------------------ #
    # main entry point                                                    #
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: ProviderContext,
    ) -> LLMResponse:
        if self.script:
            return self._play_script_step()
        return self._route_keywords(messages, context)

    def _play_script_step(self) -> LLMResponse:
        step = self.script.pop(0)
        calls = [
            ToolCallRequest(name=c["name"], arguments=dict(c.get("arguments", {})))
            for c in step.get("tool_calls", [])
        ]
        return LLMResponse(content=step.get("content", ""), tool_calls=calls)

    # ------------------------------------------------------------------ #
    # keyword router                                                       #
    # ------------------------------------------------------------------ #
    def _route_keywords(
        self, messages: list[dict[str, Any]], context: ProviderContext
    ) -> LLMResponse:
        lang = _lang(context)
        # If we already called tools for the latest user message, summarize
        # the newest tool result instead of calling again (prevents loops).
        summary = self._summarize_latest_tool_result(messages, lang)
        if summary is not None:
            return LLMResponse(content=summary)

        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = str(msg.get("content", ""))
                break
        lowered = user_text.lower()
        room = _match_room_type(user_text, context.room_types)
        dates = _extract_dates(user_text)

        # 1. Confirmation of a pending booking draft: the guest said yes after
        # preview_booking summarized the draft, so confirm it via create_booking.
        # The preview may live in an earlier turn's history, so search the
        # whole conversation — not just tools that ran after the latest message.
        if _CONFIRM_RE.search(lowered):
            preview = self._latest_tool_result(messages, "preview_booking")
            if preview is not None:
                if preview.get("draft_id"):
                    return LLMResponse(
                        tool_calls=[
                            ToolCallRequest(
                                name="create_booking",
                                arguments={
                                    "hotel_id": context.hotel_id,
                                    "draft_id": preview["draft_id"],
                                },
                            )
                        ]
                    )
                return LLMResponse(content=_t(lang, "draft_failed"))

        # 1b. Continue a booking after the guest lookup finished.
        guest_result = self._last_tool_result(messages, "find_or_create_guest")
        if (
            guest_result
            and guest_result.get("guest_id")
            and any(w in lowered for w in ("book", "reserve", "reservation"))
            and not self._last_tool_call(messages, "preview_booking")
        ):
            guests_match = _GUESTS_RE.search(user_text)
            guests = int(guests_match.group(1)) if guests_match else 2
            if room and len(dates) >= 2:
                return LLMResponse(
                    tool_calls=[
                        ToolCallRequest(
                            name="preview_booking",
                            arguments={
                                "hotel_id": context.hotel_id,
                                "room_id": room["id"],
                                "guest_id": guest_result["guest_id"],
                                "check_in": dates[0].isoformat(),
                                "check_out": dates[1].isoformat(),
                                "number_of_guests": guests,
                            },
                        )
                    ]
                )

        # 2. Booking cancellation: "cancel booking 123" / "बुकिंग 123 रद्द".
        if ("cancel" in lowered and "book" in lowered) or (
            "रद्द" in user_text and ("बुकिंग" in user_text or "booking" in lowered)
        ):
            match = _BOOKING_ID_RE.search(user_text)
            if match:
                return LLMResponse(
                    tool_calls=[
                        ToolCallRequest(
                            name="cancel_booking",
                            arguments={
                                "hotel_id": context.hotel_id,
                                "booking_id": int(match.group(1)),
                            },
                        )
                    ]
                )
            return LLMResponse(content=_t(lang, "cancel_ask_id"))

        # 2a. Food orders (before booking/policy routes): a food-order
        # request must never be answered with a fabricated confirmation.
        # The deterministic slot flow asks for item, quantity and timing
        # until all three are known, and only then calls the order tool.
        order_response = self._route_food_order(messages, context, lang)
        if order_response is not None:
            return order_response

        # 2b. Pending-booking slot replies: a booking is in progress and
        # this short reply carries slot info (a date, a room, a guest
        # count, or contact details). Complete the slots from the whole
        # conversation (slot carryover) and either continue the booking
        # or ask ONLY for the pieces still missing — such a reply must
        # never fall through to the FAQ / no-answer fallback.
        if self._booking_pending(messages) and not any(
            w in lowered
            for w in (
                "price",
                "rate",
                "cost",
                "how much",
                "tariff",
                "availab",
                "polic",
                "menu",
                "food",
                "offer",
                "discount",
                "service",
            )
        ):
            slot_now = (
                bool(dates)
                or room is not None
                or _GUESTS_RE.search(user_text) is not None
                or user_text.strip().isdigit()
                or _contact_args(user_text, context.hotel_id) is not None
            )
            if slot_now:
                g_room, g_dates, g_guests = _gather_booking_slots(messages, context.room_types)
                if g_room is not None and len(g_dates) >= 2:
                    return self._continue_booking(
                        room=g_room,
                        dates=g_dates,
                        guests=g_guests or 2,
                        messages=messages,
                        context=context,
                        contact_text=user_text,
                    )
                missing = []
                if g_room is None:
                    missing.append("room type")
                if len(g_dates) == 0:
                    missing.append("check-in and check-out dates")
                elif len(g_dates) == 1:
                    missing.append("check-out date")
                noted = ""
                if len(g_dates) == 1:
                    if lang is ResponseLanguage.HINDI:
                        noted = f"मैंने चेक-इन नोट कर लिया है: {g_dates[0].isoformat()}। "
                    elif lang is ResponseLanguage.HINGLISH:
                        noted = f"Maine check-in note kar liya hai: {g_dates[0].isoformat()}. "
                    else:
                        noted = f"I've noted check-in: {g_dates[0].isoformat()}. "
                elif g_room is not None:
                    if lang is ResponseLanguage.HINDI:
                        noted = f"मैंने {g_room['room_type']} नोट कर लिया है। "
                    elif lang is ResponseLanguage.HINGLISH:
                        noted = f"Maine {g_room['room_type']} note kar liya hai. "
                    else:
                        noted = f"I've noted the {g_room['room_type']}. "
                if lang is ResponseLanguage.HINDI:
                    return LLMResponse(content=f"{noted}मुझे अभी चाहिए: {', '.join(missing)}।")
                if lang is ResponseLanguage.HINGLISH:
                    return LLMResponse(content=f"{noted}Mujhe abhi chahiye: {', '.join(missing)}.")
                return LLMResponse(content=f"{noted}I still need: {', '.join(missing)}.")

        # 3. Availability questions (English / Hinglish / Hindi keywords).
        if (
            any(w in lowered for w in ("availab", "vacan", "free room", "any room", "khali"))
            or "खाली" in user_text
            or "उपलब्ध" in user_text
        ):
            if len(dates) >= 2:
                args: dict[str, Any] = {
                    "hotel_id": context.hotel_id,
                    "check_in": dates[0].isoformat(),
                    "check_out": dates[1].isoformat(),
                }
                if room:
                    args["room_id"] = room["id"]
                return LLMResponse(
                    tool_calls=[ToolCallRequest(name="check_room_availability", arguments=args)]
                )
            if lang is ResponseLanguage.HINDI:
                room_hint = f" {room['room_type']} कमरे के लिए" if room else ""
            elif lang is ResponseLanguage.HINGLISH:
                room_hint = f" {room['room_type']} room ke liye" if room else ""
            else:
                room_hint = f" for the {room['room_type']} room" if room else ""
            return LLMResponse(content=_t(lang, "avail_ask_dates", room_hint=room_hint))

        # 4. Price / rate questions.
        if (
            any(
                w in lowered
                for w in ("price", "rate", "cost", "how much", "tariff", "fare", "kitna", "kitne")
            )
            or "कीमत" in user_text
            or "दाम" in user_text
        ):
            if room and len(dates) >= 2:
                return LLMResponse(
                    tool_calls=[
                        ToolCallRequest(
                            name="get_room_rate",
                            arguments={
                                "hotel_id": context.hotel_id,
                                "room_id": room["id"],
                                "check_in": dates[0].isoformat(),
                                "check_out": dates[1].isoformat(),
                            },
                        )
                    ]
                )
            return LLMResponse(content=_t(lang, "price_ask"))

        # 5. Policies.
        if (
            any(
                w in lowered
                for w in ("polic", "check-in", "check in", "check-out", "check out", "cancellation")
            )
            or "चेक-इन" in user_text
            or "चेक-आउट" in user_text
            or "नीति" in user_text
        ):
            policy_type = "general"
            if "check-in" in lowered or "check in" in lowered or "चेक-इन" in user_text:
                policy_type = "check_in"
            elif "check-out" in lowered or "check out" in lowered or "चेक-आउट" in user_text:
                policy_type = "check_out"
            elif "cancel" in lowered:
                policy_type = "cancellation"
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(
                        name="get_hotel_policy",
                        arguments={"hotel_id": context.hotel_id, "policy_type": policy_type},
                    )
                ]
            )

        # 6. Hotel content: rooms, services, offers, menu.
        if re.search(r"\brooms?\b", lowered) and "book" not in lowered:
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(name="list_rooms", arguments={"hotel_id": context.hotel_id})
                ]
            )
        if "service" in lowered:
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(name="get_services", arguments={"hotel_id": context.hotel_id})
                ]
            )
        if any(w in lowered for w in ("offer", "discount", "deal", "promo")):
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(name="get_offers", arguments={"hotel_id": context.hotel_id})
                ]
            )
        if "menu" in lowered or "food" in lowered:
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(name="get_menu", arguments={"hotel_id": context.hotel_id})
                ]
            )

        # 7. New booking request.
        if (
            any(w in lowered for w in ("book", "reserve", "reservation"))
            or "बुकिंग" in user_text
            or "बुक" in user_text
        ):
            guests_match = _GUESTS_RE.search(user_text)
            guests = int(guests_match.group(1)) if guests_match else 2
            if room and len(dates) >= 2:
                return self._continue_booking(
                    room=room,
                    dates=dates,
                    guests=guests,
                    messages=messages,
                    context=context,
                    contact_text=user_text,
                )
            missing = []
            if not room:
                missing.append("room type")
            if len(dates) < 2:
                missing.append("check-in and check-out dates (YYYY-MM-DD)")
            return LLMResponse(content=_t(lang, "booking_missing", missing=", ".join(missing)))

        # 7b. Hotel knowledge base (RAG): spa, dining, transfers, local
        # guides — unstructured knowledge, never prices/availability.
        if any(w in lowered for w in _KNOWLEDGE_KEYWORDS):
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(
                        name="search_hotel_knowledge",
                        arguments={"query": user_text.strip()},
                    )
                ]
            )

        # 8. Fallback: search FAQs, else clarify.
        if len(user_text.strip()) >= 3:
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(
                        name="search_faq",
                        arguments={"hotel_id": context.hotel_id, "query": user_text.strip()},
                    )
                ]
            )
        return LLMResponse(content=_t(lang, "help"))

    # ------------------------------------------------------------------ #
    # food-order slot flow                                                #
    # ------------------------------------------------------------------ #
    _FOOD_WORDS = ("khana", "food", "thali", "breakfast", "lunch", "dinner", "snacks")
    _ORDER_VERBS = (
        "order",
        "book kar",
        "book karo",
        "mangwana",
        "mangwa",
        "chahiye",
        "bhej",
        "pre-book",
        "prebook",
        "book",
    )
    _QTY_WORDS = {
        "ek": 1,
        "one": 1,
        "do": 2,
        "two": 2,
        "teen": 3,
        "three": 3,
        "char": 4,
        "chaar": 4,
        "four": 4,
        "paanch": 5,
        "five": 5,
    }
    _TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm|baje)\b", re.IGNORECASE)

    @classmethod
    def _order_intent(cls, lowered: str) -> bool:
        has_food = any(w in lowered for w in cls._FOOD_WORDS)
        has_verb = any(w in lowered for w in cls._ORDER_VERBS)
        return has_food and has_verb

    @classmethod
    def _parse_quantity(cls, text: str) -> int | None:
        lowered = text.lower()
        qty: int | None = None
        for match in re.finditer(r"[x×]\s*(\d{1,2})\b", lowered):
            qty = int(match.group(1))
        for match in re.finditer(r"(\d{1,2})\s*(plate|plates|pc|pcs|nos?|item|items)?", lowered):
            value = int(match.group(1))
            # Skip numbers that are part of a date (handled elsewhere):
            # a bare 4-digit year or a day<=31 followed by a month digit
            # pattern is unlikely as a quantity when a unit word exists.
            if match.group(2):
                qty = value
        if qty is None:
            for word, value in cls._QTY_WORDS.items():
                if re.search(rf"\b{word}\b", lowered):
                    qty = value
        return qty

    @classmethod
    def _parse_timing(cls, text: str) -> str | None:
        lowered = text.lower()
        dates = _extract_dates(text)
        if dates:
            return dates[0].isoformat()
        if cls._TIME_RE.search(text):
            return "time-mentioned"
        if any(w in lowered for w in ("abhi", "right now", "now", "turant")):
            return "now"
        return None

    def _route_food_order(
        self,
        messages: list[dict[str, Any]],
        context: ProviderContext,
        lang: ResponseLanguage,
    ) -> LLMResponse | None:
        user_texts = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
        if not user_texts:
            return None
        latest = user_texts[-1]
        intent = self._order_intent(latest.lower())

        menu = self._latest_tool_result(messages, "get_menu")
        if menu is None:
            if not intent:
                return None
            # Need the real menu before any item can be ordered.
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(name="get_menu", arguments={"hotel_id": context.hotel_id})
                ]
            )

        items = menu.get("items", [])
        item_names = [str(i.get("name", "")) for i in items if i.get("name")]
        combined = "\n".join(user_texts)
        matched_item: str | None = None
        for name in item_names:
            if name.lower() in combined.lower():
                matched_item = name
        qty = self._parse_quantity(combined)
        timing = self._parse_timing(combined)

        if matched_item is None and qty is None and timing is None and not intent:
            return None  # not an order conversation; let other routes run

        if matched_item is None:
            listing = ", ".join(item_names[:8]) or "—"
            return LLMResponse(content=_t(lang, "order_ask_item", items=listing))
        if qty is None:
            return LLMResponse(content=_t(lang, "order_ask_qty", item=matched_item))
        if timing is None:
            return LLMResponse(content=_t(lang, "order_ask_when", item=matched_item, qty=qty))
        # All slots known. The order tool needs an identified guest:
        # resolve identity first (same pattern as the booking flow) and
        # never place an order for an anonymous conversation.
        guest_id = context.guest_id
        if not guest_id:
            found = self._latest_tool_result(messages, "find_or_create_guest")
            if found and found.get("guest_id"):
                guest_id = found["guest_id"]
        if not guest_id:
            guest_args = None
            for past in reversed(user_texts):
                guest_args = _contact_args(past, context.hotel_id)
                if guest_args is not None:
                    break
            if guest_args is not None:
                return LLMResponse(
                    tool_calls=[ToolCallRequest(name="find_or_create_guest", arguments=guest_args)]
                )
            return LLMResponse(content=_t(lang, "order_ask_contact"))
        return LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    name="create_food_order",
                    arguments={
                        "hotel_id": context.hotel_id,
                        "guest_id": guest_id,
                        "order_type": "ROOM_SERVICE",
                        "items": [{"menu_item_name": matched_item, "quantity": qty}],
                    },
                )
            ]
        )

    @staticmethod
    def _booking_pending(messages: list[dict[str, Any]]) -> bool:
        """True when a booking was started but not yet previewed.

        Signals are this provider's own deterministic artefacts: a
        list_rooms result, or an assistant reply that asked for the
        missing booking details or the guest's identity. A preview_booking
        or create_booking after the latest signal closes the pending state.
        """
        last_done = -1
        signal = -1
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "tool" and msg.get("name") in ("preview_booking", "create_booking"):
                last_done = i
            if role == "tool" and msg.get("name") == "list_rooms":
                signal = i
            if role == "assistant":
                content = str(msg.get("content", "")).lower()
                if (
                    "still need" in content
                    or "abhi chahiye" in content
                    or "अभी चाहिए" in content
                    or "happy to help with the booking" in content
                    or "khushi se help" in content
                    or "खुशी से मदद" in content
                    or "could you share your name" in content
                    or "hold kar sakoon" in content
                ):
                    signal = i
        return signal >= 0 and signal > last_done

    def _continue_booking(
        self,
        *,
        room: dict[str, Any],
        dates: list[date],
        guests: int,
        messages: list[dict[str, Any]],
        context: ProviderContext,
        contact_text: str,
    ) -> LLMResponse:
        """Room + dates are known: preview now, or resolve the guest first.

        Shared by the direct booking route (step 7) and the pending-booking
        slot-carryover guard (step 2b). The deterministic confirmation gate
        is untouched: this only ever calls preview_booking, never
        create_booking.
        """
        guest_id = context.guest_id
        if not guest_id:
            found = self._latest_tool_result(messages, "find_or_create_guest")
            if found and found.get("guest_id"):
                guest_id = found["guest_id"]
        if guest_id:
            return LLMResponse(
                tool_calls=[
                    ToolCallRequest(
                        name="preview_booking",
                        arguments={
                            "hotel_id": context.hotel_id,
                            "room_id": room["id"],
                            "guest_id": guest_id,
                            "check_in": dates[0].isoformat(),
                            "check_out": dates[1].isoformat(),
                            "number_of_guests": guests,
                        },
                    )
                ]
            )
        # No known guest yet: look them up from contact details — the
        # current message first, then earlier guest messages.
        guest_args = _contact_args(contact_text, context.hotel_id)
        if guest_args is None:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    guest_args = _contact_args(str(msg.get("content", "")), context.hotel_id)
                    if guest_args is not None:
                        break
        if guest_args is not None:
            return LLMResponse(
                tool_calls=[ToolCallRequest(name="find_or_create_guest", arguments=guest_args)]
            )
        return LLMResponse(content=_t(_lang(context), "booking_ask_contact"))

    @staticmethod
    def _summarize_latest_tool_result(
        messages: list[dict[str, Any]], lang: ResponseLanguage = ResponseLanguage.ENGLISH
    ) -> str | None:
        """Turn the newest tool result into a guest-facing reply.

        Returns None when no tool has run yet for the latest user message.
        """
        last_user_idx = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_idx = i
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") != "tool":
                continue
            # Only summarize tools that ran after the latest user message.
            if i < last_user_idx:
                return None
            name = msg.get("name", "")
            content = str(msg.get("content", ""))
            if content.startswith("ERROR:"):
                return f"I ran into an issue: {content[6:].strip()} Could you try rephrasing?"
            try:
                import ast
                import json as _json

                try:
                    data = _json.loads(content)
                except ValueError:
                    data = ast.literal_eval(content)
            except (ValueError, SyntaxError):
                return None
            if not isinstance(data, dict):
                return None
            return _summarize(name, data, lang)
        return None

    @staticmethod
    def _latest_tool_result(messages: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        """Newest result dict for tool `name` anywhere in the conversation.

        Unlike :meth:`_last_tool_result`, this is not restricted to tools that
        ran after the latest user message — needed when the guest confirms a
        draft that was previewed in an earlier turn.
        """
        for msg in reversed(messages):
            if msg.get("role") == "tool" and msg.get("name") == name:
                content = str(msg.get("content", ""))
                if content.startswith("ERROR:"):
                    return {}
                try:
                    data = json.loads(content)
                    return data if isinstance(data, dict) else None
                except ValueError:
                    return None
        return None

    @staticmethod
    def _last_tool_result(messages: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        """Newest result dict for tool `name` after the latest user message."""
        last_user_idx = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_idx = i
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") == "tool" and msg.get("name") == name and i > last_user_idx:
                content = str(msg.get("content", ""))
                if content.startswith("ERROR:"):
                    return None
                try:
                    import json as _json

                    data = _json.loads(content)
                    return data if isinstance(data, dict) else None
                except ValueError:
                    return None
        return None

    @staticmethod
    def _last_tool_call(messages: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        for msg in reversed(messages):
            for call in msg.get("tool_calls", []) or []:
                if call.get("name") == name:
                    return call
        return None


class ScriptedProvider:
    """Deterministic provider that plays a fixed script of responses.

    Each ``chat`` call pops the next scripted ``LLMResponse`` (a response
    object or a thunk returning one, so tests can raise ProviderError).
    When the script is exhausted it returns a polite closing message.
    """

    name = "scripted"

    def __init__(self, script: list[Any]):
        self.script = list(script)

    @property
    def available_tools(self) -> list[str]:
        from app.agent.tools.registry import build_registry

        return build_registry().names

    def chat(
        self,
        messages: list[dict[str, Any]],
        context: ProviderContext,
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if not self.script:
            return LLMResponse(content="Thanks for chatting!")
        step = self.script.pop(0)
        if callable(step):
            return step()
        if isinstance(step, ToolCallRequest):
            return LLMResponse(tool_calls=[step])
        return step
