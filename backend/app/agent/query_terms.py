"""Deterministic cross-language query expansion for FAQ / knowledge
retrieval (Sweep fix D).

The hotel knowledge base and FAQ answers are written in English, and both
retrieval paths are effectively English-only: ``search_faq`` matches
English words, and the hashed embedding provider tokenises ``[a-z0-9]+``
only, so a Hindi query embeds to a near-zero vector. A guest asking
"स्विमिंग पूल का समय क्या है?" therefore retrieved nothing and got a
"not available" answer, while the same question in English was answered
from the knowledge base (the Serenity Spa plunge pool).

Fix: a small facility/topic term map. Hindi (Devanagari) and Hinglish
(Roman) variants of common hotel topics map to canonical English
keywords; :func:`expand_query` *appends* those keywords to the guest's
query before retrieval. The original text is never rewritten — English
queries pass through unchanged — and matching stays fully deterministic
(no LLM, no translation service, no new dependencies).
"""

from __future__ import annotations

import re

# (variants, canonical English keywords). Devanagari variants match by
# substring; Roman variants match on word boundaries. The canonical
# keywords are what the English FAQ / knowledge documents actually use.
_TERM_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("स्विमिंग पूल", "swimming pool"), "swimming pool"),
    (("पूल", "पुल"), "pool"),
    (("स्पा", "spa"), "spa"),
    (("जिम", "gym", "व्यायामशाला"), "gym fitness centre"),
    (("नाश्ता", "nashta", "ब्रेकफास्ट"), "breakfast"),
    (("वाईफ़ाई", "वाई-फ़ाई", "वायफ़ाय", "वायफाय", "wifi", "wi-fi"), "wifi internet"),
    (("पार्किंग", "parking", "गाड़ी"), "parking"),
    (("चेक-इन", "चेक इन", "check-in", "check in"), "check-in"),
    (("चेक-आउट", "चेक आउट", "check-out", "check out"), "check-out"),
    (("समय", "samay", "timing", "timings", "खुलता", "बंद"), "timings hours open"),
    (("रेस्टोरेंट", "रेस्तरां", "रेस्टराँ", "restaurant"), "restaurant dining"),
    (("रूम सर्विस", "room service"), "room service"),
    (("लॉन्ड्री", "laundry", "कपड़े धोना"), "laundry"),
    (("एयरपोर्ट", "airport", "हवाई अड्डा"), "airport shuttle transfer"),
    (("योगा", "yoga"), "yoga"),
    (("मसाज", "massage"), "massage spa"),
    (("सौना", "sauna"), "sauna"),
    (("खाना", "khana"), "food dining"),
)


def _variant_matches(lowered: str, variant: str) -> bool:
    if any("\u0900" <= ch <= "\u097f" for ch in variant):
        return variant in lowered
    return re.search(r"\b" + re.escape(variant) + r"\b", lowered) is not None


def expand_query(query: str) -> str:
    """Return ``query`` plus canonical English keywords for every
    Hindi/Hinglish facility term it contains. No-op for plain English."""
    text = (query or "").strip()
    if not text:
        return text
    lowered = text.lower()
    additions: list[str] = []
    for variants, canonical in _TERM_MAP:
        if canonical.split()[0] in lowered:
            continue  # the English term is already there
        if any(_variant_matches(lowered, variant) for variant in variants):
            additions.append(canonical)
    if not additions:
        return text
    return text + " " + " ".join(additions)
