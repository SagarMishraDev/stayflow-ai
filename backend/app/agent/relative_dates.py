"""Deterministic relative-date resolution for guest messages.

Guests rarely type ISO dates. They say "next weekend", "kal",
"parso", or "agle Shukravar" — and the concierge must turn that into
exact calendar dates the same way every time, without asking the LLM
to do calendar arithmetic. This module is the single place that
happens: a pure function of (text, today), where ``today`` is the
current date **in the hotel's timezone** (the runner computes it).

Semantics (documented so support and tests can rely on them):

- A "weekend" stay is Saturday check-in -> Sunday check-out (1 night).
- "this weekend" is the imminent Saturday: today itself when today is
  a Saturday. On a Sunday the current weekend's Saturday is already
  past, so "this weekend" means the coming Saturday.
- "next weekend" is the Saturday one week after "this weekend"
  (so on a Friday, this weekend starts tomorrow and next weekend is
  8 days out; on a Saturday, next weekend starts in 7 days).
- "tomorrow" / "kal" -> check-in tomorrow, 1 night.
- "day after tomorrow" / "parso" -> check-in in 2 days, 1 night.
- "next week" -> check-in on the same weekday next week, 1 night.
- Weekday names (English + common Roman-Hindi + Devanagari):
  "this/coming <weekday>" (or a bare weekday) is the imminent
  occurrence of that weekday (today counts); "next <weekday>" /
  "agle <weekday>" is the imminent occurrence too, except that when
  today IS that weekday it means the one a week later. Check-in on
  that day, 1 night.

Every resolution is restated to the guest in words by the caller
before anything is confirmed — an interpreted date is never booked
silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# Weekday number (Mon=0 .. Sun=6) for every accepted spelling.
_WEEKDAYS: dict[str, int] = {
    # English, full and abbreviated.
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
    # Roman Hindi.
    "somvar": 0,
    "somvaar": 0,
    "mangalvar": 1,
    "mangalvaar": 1,
    "budhvar": 2,
    "budhvaar": 2,
    "guruvar": 3,
    "guruvaar": 3,
    "shukravar": 4,
    "shukravaar": 4,
    "shanivar": 5,
    "shanivaar": 5,
    "ravivar": 6,
    "ravivaar": 6,
    "itvaar": 6,
    # Devanagari Hindi.
    "सोमवार": 0,
    "मंगलवार": 1,
    "बुधवार": 2,
    "गुरुवार": 3,
    "शुक्रवार": 4,
    "शनिवार": 5,
    "रविवार": 6,
}

_WEEKDAY_PATTERN = "|".join(
    sorted((re.escape(w) for w in _WEEKDAYS), key=len, reverse=True)
)
_WEEKDAY_RE = re.compile(
    rf"(?:\b(next|coming|this)\s+|\b(agle|agli|is)\s+)?({_WEEKDAY_PATTERN})\b",
    re.IGNORECASE,
)

_DAY_AFTER_TOMORROW_RE = re.compile(
    r"day after tomorrow|\bparson?\b|परसों|परसो", re.IGNORECASE
)
_NEXT_WEEKEND_RE = re.compile(
    r"next weekend|agle weekend|agla weekend|next week'?s weekend|अगला सप्ताहांत",
    re.IGNORECASE,
)
_THIS_WEEKEND_RE = re.compile(
    r"this weekend|is weekend|weekend|इस सप्ताहांत|सप्ताहांत", re.IGNORECASE
)
_NEXT_WEEK_RE = re.compile(r"next week|agle hafte|agla hafta", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"tomorrow|\bkal\b|कल", re.IGNORECASE)


@dataclass(frozen=True)
class RelativeStay:
    """A relative phrase resolved to an exact stay."""

    check_in: date
    check_out: date
    key: str  # "next_weekend" | "this_weekend" | "tomorrow" | ...
    label: str  # short English label, e.g. "Next weekend"

    def words(self) -> str:
        """The stay in plain words, for restating to the guest."""
        return f"{_words(self.check_in)} to {_words(self.check_out)}"


def _words(day: date) -> str:
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


def _this_saturday(today: date) -> date:
    """The imminent Saturday (today when today is a Saturday)."""
    return today + timedelta(days=(5 - today.weekday()) % 7)


def _stay(check_in: date, key: str, label: str, nights: int = 1) -> RelativeStay:
    return RelativeStay(
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
        key=key,
        label=label,
    )


def resolve_relative_stay(text: str, today: date) -> RelativeStay | None:
    """Resolve a relative-date phrase in `text` against `today`.

    Returns the stay for the most specific phrase found, or None when
    the text carries no recognised relative phrase. Explicit calendar
    dates are NOT this module's job (see the providers' date parsers).
    """
    if not text:
        return None

    if _DAY_AFTER_TOMORROW_RE.search(text):
        return _stay(today + timedelta(days=2), "day_after_tomorrow", "Day after tomorrow")

    if _NEXT_WEEKEND_RE.search(text):
        return _stay(_this_saturday(today) + timedelta(days=7), "next_weekend", "Next weekend")
    if _THIS_WEEKEND_RE.search(text):
        return _stay(_this_saturday(today), "this_weekend", "This weekend")

    if _TOMORROW_RE.search(text):
        return _stay(today + timedelta(days=1), "tomorrow", "Tomorrow")

    if _NEXT_WEEK_RE.search(text):
        return _stay(today + timedelta(days=7), "next_week", "Next week")

    match = _WEEKDAY_RE.search(text)
    if match:
        prefix = (match.group(1) or match.group(2) or "").lower()
        target = _WEEKDAYS[match.group(3).lower()]
        delta = (target - today.weekday()) % 7
        if prefix in ("next", "agle", "agli") and delta == 0:
            delta = 7
        day_name = match.group(3)
        label_day = day_name.capitalize() if day_name.isascii() else day_name
        label = f"Next {label_day}" if prefix in ("next", "agle", "agli") else label_day
        key = "weekday_next" if prefix in ("next", "agle", "agli") else "weekday"
        return _stay(today + timedelta(days=delta), key, label)

    return None


__all__ = ["RelativeStay", "resolve_relative_stay"]
