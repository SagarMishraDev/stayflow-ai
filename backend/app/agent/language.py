"""Deterministic guest-language detection and response-language policy.

Phase 2 of the HMS upgrade. The agent must answer in the guest's own
language *and script*:

- Devanagari Hindi  -> Hindi in Devanagari script.
- Roman Hindi (Hinglish) -> Hinglish in Roman script (never Devanagari).
- English -> English.

Detection is fully deterministic and server-side (no external API, no
LLM call): it scores Devanagari characters, Roman-Hindi vocabulary and
English vocabulary in the guest's latest message. Explicit requests
("please reply in English", "हिंदी में जवाब दो") always win. Detection
is confidence-tiered: only a *confident* signal (Devanagari script, a
Hindi-vocabulary majority, or English vocabulary backed by grammar
words) classifies a message. Weak or tied evidence — a lone English word inside
a Hinglish slot reply ("Deluxe King Room chalega"), dates, numbers,
"ok", names — is ``NEUTRAL`` so the caller falls back to the
conversation's established preference instead of flipping language on
every short reply. Only confident detections may override the stored
preference; the preference merely breaks ties for ambiguous messages.

The runner threads the result into the system prompt (for real LLMs)
and into ``ProviderContext.response_language`` (for the deterministic
mock). Labels never appear in guest-visible text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ResponseLanguage(StrEnum):
    HINDI = "hindi"  # Devanagari script
    HINGLISH = "hinglish"  # Roman Hindi mixed with English
    ENGLISH = "english"


class DetectedLanguage(StrEnum):
    HINDI = "hindi"
    HINGLISH = "hinglish"
    ENGLISH = "english"
    MIXED = "mixed"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class LanguageDetection:
    detected: DetectedLanguage
    response_language: ResponseLanguage | None  # None when NEUTRAL
    explicit_request: ResponseLanguage | None = None
    devanagari_letters: int = 0
    roman_hindi_hits: int = 0
    english_hits: int = 0


_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_LETTER_RE = re.compile(r"[A-Za-zऀ-ॿ]")
_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")

# A name introduced by a lead-in ("my name is …", "mera naam …",
# "मेरा नाम …") is neutral evidence: guests write their name in either
# script whatever language the conversation runs in, so the name tokens
# themselves must not score as language evidence (a Devanagari name in
# an English sentence is not a switch to Hindi). The lead-in is kept —
# its language *is* evidence — only the name tokens are stripped before
# scoring.
_NAME_SPAN_RE = re.compile(
    r"(my name is|mera naam|मेरा नाम|this is|i am|i'm|myself)"
    r"\s+[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.\-']*"
    r"(?:\s+[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.\-']*){0,3}",
    re.IGNORECASE,
)

# Roman-Hindi vocabulary common in guest messages (roman script). Hotel
# words shared with English (hotel, room, booking) are deliberately NOT
# scored here — they appear in every language.
_ROMAN_HINDI_WORDS = {
    "kya",
    "hai",
    "hain",
    "mein",
    "mai",
    "mera",
    "meri",
    "mere",
    "hamara",
    "hamari",
    "aap",
    "aapka",
    "aapke",
    "tum",
    "mujhe",
    "humein",
    "humko",
    "chahiye",
    "milega",
    "milegi",
    "mil",
    "sakta",
    "sakti",
    "sakte",
    "kar",
    "karo",
    "karna",
    "karke",
    "do",
    "dena",
    "dijiye",
    "batao",
    "bataiye",
    "khana",
    "khali",
    "kamra",
    "kamre",
    "wala",
    "wali",
    "wale",
    "nahi",
    "nahin",
    "na",
    "toh",
    "bhi",
    "aur",
    "ya",
    "ke",
    "ki",
    "ka",
    "ko",
    "se",
    "par",
    "pe",
    "lie",
    "liye",
    "baad",
    "pahle",
    "pehle",
    "kab",
    "kaise",
    "kahan",
    "kidhar",
    "kitna",
    "kitne",
    "kitni",
    "kyun",
    "kyon",
    "bhai",
    "haan",
    "acha",
    "accha",
    "theek",
    "thik",
    "kal",
    "aaj",
    "abhi",
    "subah",
    "sham",
    "shaam",
    "raat",
    "namaste",
    "namaskar",
    "dhanyavad",
    "shukriya",
    "kripya",
    "ho",
    "hoga",
    "hogi",
    "tha",
    "thi",
    "raha",
    "rahi",
    "kr",
    "bhej",
    "bhejo",
}

# English *grammar* words (articles, pronouns, auxiliaries, prepositions,
# question words). A confident English detection requires at least one of
# these: English content words alone ("room", "guests", "price",
# "booking") are everyday loanwords in Hinglish, so a telegraphic slot
# reply like "Deluxe room chalega, 2 guests" must not count as an
# English language switch.
_ENGLISH_FUNCTION_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "you",
    "your",
    "have",
    "has",
    "any",
    "can",
    "could",
    "would",
    "should",
    "i",
    "we",
    "my",
    "me",
    "want",
    "need",
    "what",
    "when",
    "where",
    "how",
    "much",
    "many",
    "for",
    "to",
    "and",
    "or",
    "of",
    "in",
    "on",
    "at",
    "with",
    "without",
}

_ENGLISH_WORDS = {
    "the",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "you",
    "your",
    "have",
    "has",
    "any",
    "please",
    "can",
    "could",
    "would",
    "should",
    "i",
    "we",
    "my",
    "me",
    "want",
    "need",
    "what",
    "when",
    "where",
    "how",
    "much",
    "many",
    "for",
    "to",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "on",
    "at",
    "with",
    "without",
    "available",
    "availability",
    "book",
    "booking",
    "reserve",
    "reservation",
    "check",
    "price",
    "cost",
    "room",
    "rooms",
    "hotel",
    "guest",
    "guests",
    "night",
    "nights",
    "today",
    "tomorrow",
    "hello",
    "hi",
    "thanks",
    "thank",
}

# Phrases that are unmistakably Roman Hindi even with shared words.
_ROMAN_HINDI_PHRASES = (
    "hai kya",
    "milega na",
    "ke liye",
    "ke lie",
    "kar do",
    "kar dijiye",
    "bata do",
    "hai to",
    "khali hai",
    "kya aap",
    "mujhe chahiye",
    "hamari",
    "aapka",
    "check in ke",
    "check-in ke",
)

_EXPLICIT_PATTERNS: list[tuple[re.Pattern[str], ResponseLanguage]] = [
    # Devanagari requests.
    (re.compile(r"हिंदी\s*में|हिन्दी\s*में|हिंदी\s*मे"), ResponseLanguage.HINDI),
    (re.compile(r"अंग्रेज़ी\s*में|अंग्रेजी\s*में"), ResponseLanguage.ENGLISH),
    # Roman requests.
    (
        re.compile(
            r"\b(in|reply in|answer in|respond in|baat)\s+hindi\b|\bhindi\s+(me|mein)\b",
            re.IGNORECASE,
        ),
        ResponseLanguage.HINDI,
    ),
    (
        re.compile(
            r"\b(in|reply in|answer in|respond in)\s+english\b|\benglish\s+(me|mein)\b",
            re.IGNORECASE,
        ),
        ResponseLanguage.ENGLISH,
    ),
    (re.compile(r"\bhinglish\b", re.IGNORECASE), ResponseLanguage.HINGLISH),
]


def detect_language(text: str) -> LanguageDetection:
    """Classify one guest message. Pure function — no I/O, no state."""
    raw = text or ""
    for pattern, language in _EXPLICIT_PATTERNS:
        if pattern.search(raw):
            return LanguageDetection(
                detected=DetectedLanguage.MIXED,
                response_language=language,
                explicit_request=language,
            )

    scored = _NAME_SPAN_RE.sub(r"\1", raw)
    devanagari = len(_DEVANAGARI_RE.findall(scored))
    letters = len(_LETTER_RE.findall(scored))
    lowered = scored.lower()
    words = _WORD_RE.findall(lowered)
    hindi_hits = sum(1 for w in words if w in _ROMAN_HINDI_WORDS)
    english_hits = sum(1 for w in words if w in _ENGLISH_WORDS)
    for phrase in _ROMAN_HINDI_PHRASES:
        if phrase in lowered:
            hindi_hits += 2

    if letters == 0:
        return LanguageDetection(DetectedLanguage.NEUTRAL, None)

    dev_ratio = devanagari / letters
    if devanagari >= 4 and dev_ratio >= 0.35:
        # Devanagari-dominant: Hindi reply (English hotel terms are fine
        # inside a Hindi reply, per the spec's mixed example).
        return LanguageDetection(
            DetectedLanguage.HINDI,
            ResponseLanguage.HINDI,
            devanagari_letters=devanagari,
            roman_hindi_hits=hindi_hits,
            english_hits=english_hits,
        )
    if devanagari >= 4:
        # Some Devanagari but Roman-dominant text.
        if hindi_hits >= english_hits:
            return LanguageDetection(
                DetectedLanguage.MIXED,
                ResponseLanguage.HINGLISH,
                devanagari_letters=devanagari,
                roman_hindi_hits=hindi_hits,
                english_hits=english_hits,
            )
        return LanguageDetection(
            DetectedLanguage.MIXED,
            ResponseLanguage.ENGLISH,
            devanagari_letters=devanagari,
            roman_hindi_hits=hindi_hits,
            english_hits=english_hits,
        )

    # Pure Roman script from here.
    if hindi_hits >= 2 and english_hits >= 2:
        # Genuinely mixed: natural Hinglish when the Hindi share is real,
        # otherwise the dominant language (English).
        if hindi_hits >= english_hits or hindi_hits >= 3:
            return LanguageDetection(
                DetectedLanguage.MIXED,
                ResponseLanguage.HINGLISH,
                roman_hindi_hits=hindi_hits,
                english_hits=english_hits,
            )
        return LanguageDetection(
            DetectedLanguage.MIXED,
            ResponseLanguage.ENGLISH,
            roman_hindi_hits=hindi_hits,
            english_hits=english_hits,
        )
    if hindi_hits > english_hits:
        # A clear Hindi majority — even one unambiguous Hindi word against
        # no English evidence — is a confident Hinglish signal.
        return LanguageDetection(
            DetectedLanguage.HINGLISH,
            ResponseLanguage.HINGLISH,
            roman_hindi_hits=hindi_hits,
            english_hits=english_hits,
        )
    english_function_hits = sum(1 for w in words if w in _ENGLISH_FUNCTION_WORDS)
    if (
        english_hits >= 2
        and english_function_hits >= 1
        and english_hits > hindi_hits
    ):
        # Confident English needs real evidence: at least two English
        # vocabulary hits AND at least one grammar/function word. Content
        # words alone ("room", "guests" inside the slot reply "Deluxe
        # room chalega, 2 guests") are Hinglish loanwords, NOT a language
        # switch — such weak signals stay NEUTRAL below so the
        # conversation's established language breaks the tie instead of
        # being overridden by them.
        return LanguageDetection(
            DetectedLanguage.ENGLISH,
            ResponseLanguage.ENGLISH,
            roman_hindi_hits=hindi_hits,
            english_hits=english_hits,
        )
    # Weak or tied evidence (0–1 dictionary hits either way, or an exact
    # Hindi/English tie), a single unknown word, a date, a number, "yes" /
    # "ok": no confident signal — NEUTRAL, so resolution falls back to the
    # conversation's history / stored preference.
    return LanguageDetection(
        DetectedLanguage.NEUTRAL,
        None,
        roman_hindi_hits=hindi_hits,
        english_hits=english_hits,
    )


def resolve_response_language(
    latest_text: str,
    history_texts: list[str],
    stored_preference: str | None,
) -> tuple[ResponseLanguage, LanguageDetection]:
    """Effective response language for this turn.

    Priority: explicit request in the latest message > detection of the
    latest message > most recent classifiable guest message in history >
    stored conversation preference > English.
    """
    detection = detect_language(latest_text)
    if detection.response_language is not None:
        return detection.response_language, detection
    for past in reversed(history_texts):
        past_detection = detect_language(past)
        if past_detection.response_language is not None:
            return past_detection.response_language, detection
    if stored_preference:
        try:
            return ResponseLanguage(stored_preference), detection
        except ValueError:
            pass
    return ResponseLanguage.ENGLISH, detection


_LANGUAGE_INSTRUCTIONS: dict[ResponseLanguage, str] = {
    ResponseLanguage.HINDI: (
        "RESPONSE LANGUAGE FOR THIS TURN: Hindi. Write the ENTIRE reply in "
        "natural, grammatically correct Hindi using the Devanagari script. "
        "Use simple, everyday Hindi — write only real Hindi words; NEVER "
        "invent transliterated non-words. Common English hotel terms "
        "(check-in, check-out, room service, booking) may stay in English "
        "where a Hindi speaker would naturally use them. Keep names, "
        "prices, dates, times and IDs exactly as the tools returned them, "
        "and keep facility and room names (e.g. Serenity Spa plunge pool) "
        "in their original English spelling — never transliterate or "
        "translate a proper noun."
    ),
    ResponseLanguage.HINGLISH: (
        "RESPONSE LANGUAGE FOR THIS TURN: Hinglish. Write the ENTIRE reply "
        "in Roman script only — absolutely NO Devanagari characters. Use "
        "natural Roman Hindi mixed with familiar English hotel words, the "
        "way the guest is writing (e.g. 'Bilkul, room available hai — aap "
        "check-in date bata dijiye'). Write only real words; NEVER invent "
        "garbled transliterations. Keep names, prices, dates, times and "
        "IDs exactly as the tools returned them, and keep facility and "
        "room names (e.g. Serenity Spa plunge pool) in their original "
        "English spelling — never transliterate or translate a proper noun."
    ),
    ResponseLanguage.ENGLISH: (
        "RESPONSE LANGUAGE FOR THIS TURN: English. Write the entire reply "
        "in clear, natural English. Keep names, prices, dates, times and "
        "IDs exactly as the tools returned them."
    ),
}


def build_language_instruction(language: ResponseLanguage) -> str:
    """Per-turn language instruction appended to the system prompt."""
    return _LANGUAGE_INSTRUCTIONS[language]


def script_of(text: str) -> str:
    """'devanagari' if the text contains Devanagari, else 'roman'."""
    return "devanagari" if _DEVANAGARI_RE.search(text or "") else "roman"
