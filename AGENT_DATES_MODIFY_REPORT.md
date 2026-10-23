# Agent relative dates + booking modification — build report

Date: 2026-10-23. Scope: `backend/` only. Nothing committed, pushed or
deployed; nothing was run against the live/remote database.

## What existed before

- The mock provider parsed dates only as explicit calendar dates (ISO,
  DD/MM/YYYY day-first, month names) plus the words "today"/"tomorrow"
  evaluated against the **server** date. "Next weekend" was
  unintelligible; the LLM system prompt stated today's date but no
  weekday, no timezone and no weekend definition.
- Booking tools covered create/cancel only. There was no way for a guest
  to see their own bookings through the agent (`get_booking` needs a
  booking id and is staff-shaped) and no modify path at all. The booking
  service had a staff-side `update_booking_dates_guests` (dates/guests
  only, no room change, no repricing, no availability re-check).
- The hotel record already carries a `timezone` field (demo hotel:
  `Asia/Kolkata`), and `app/services/analytics.py` already had a
  hotel-timezone pattern — but the agent never used it.

## Feature 1 — deterministic relative-date resolution

New module `backend/app/agent/relative_dates.py`:
`resolve_relative_stay(text, today) -> RelativeStay | None`, a pure
function of the phrase and an injected `today` (so tests freeze the
clock). It returns explicit `check_in`/`check_out` dates, a machine key
and a human label, and `words()` renders e.g. "Saturday 31 October 2026
to Sunday 1 November 2026".

Coverage (English + Roman Hinglish + common Devanagari):

- "next weekend" / "this weekend" (see semantics below)
- "tomorrow" / "kal" / "कल" (+1 day), "day after tomorrow" / "parso" /
  "परसों" (+2 days)
- "next week" / "agle hafte" (+7 days, 1 night)
- Weekday phrases: "next Friday", "this/coming Monday", bare weekday
  names, Roman-Hindi weekday words (somvar, mangalvar, budhvar,
  guruvar, shukravar, shanivar, ravivar/itvaar) and Devanagari weekday
  names. Bare/this/coming = the imminent occurrence (today counts);
  "next/agle <weekday>" = the imminent occurrence, except when today IS
  that weekday, in which case it means the one a week later.

### Weekend semantics (the documented decision)

Weekend = **Saturday check-in → Sunday check-out** (1 night).

- `this_saturday = today + (5 - weekday) % 7` — the imminent Saturday;
  if today is Saturday, this weekend starts **today**. On Sunday the
  coming Saturday is meant (that weekend's Saturday has passed).
- "this weekend" = `this_saturday`; "next weekend" = `this_saturday + 7`.

Verified: from Friday 2026-10-23 → this weekend 2026-10-24→25, next
weekend 2026-10-31→2026-11-01; from Saturday → this weekend starts
today, next = +7; from Sunday → this weekend 2026-10-31→11-01, next
2026-11-07→08.

### Wiring

- **Hotel-local "today"**: `runner._provider_context` now computes
  today in the hotel's timezone (`Hotel.timezone`, `Asia/Kolkata`
  fallback) and `ProviderContext` carries `timezone`. All mock date
  logic (booking slots, food-order "kal"/timing, modify flow) uses this
  hotel-local today instead of the server date.
- **Mock (deterministic) path**: `_stay_dates()` resolves explicit dates
  first, else a relative phrase, atomically filling check-in/check-out
  in `_gather_booking_slots` (a later explicit date pair overrides the
  phrase). When a preview is summarized, `_relative_date_prefix`
  prepends e.g. "Next weekend — Saturday 31 October 2026 to Sunday 1
  November 2026." so the guest always sees the interpreted dates in
  words before confirming. Nothing is ever booked silently on a
  relative phrase — the normal preview → confirm gate still applies.
- **Real (Mercury) path**: `build_system_prompt` now states "Today is
  {Weekday, DD Month YYYY} ({ISO}) in the hotel's timezone ({tz})", the
  weekend definition, and instructs resolving relative phrases against
  that date, restating them in words and passing explicit ISO dates to
  tools. Additionally the runner appends a `DETERMINISTIC DATE
  RESOLUTION` note to the system prompt whenever the guest's message
  itself resolves through the deterministic resolver — pinning the exact
  ISO dates so Mercury cannot drift from the mock's semantics.

## Feature 2 — modify an upcoming booking

### Design

Two-phase flow mirroring the existing booking-draft pattern, enforced
in the service layer (`app/services/booking_service.py`) so no provider
(mock or Mercury) can bypass it:

1. **Preview** — `validate_modification(...)` checks eligibility,
   requires at least one real change, verifies the room belongs to the
   hotel and fits the guest count, re-checks availability **excluding
   the booking itself**, and reprices the new stay in full via the
   existing `quote_booking_price` (every night must have a rate).
   `issue_modification_token(quote)` returns a signed token
   (HMAC-SHA256 over a base64url JSON payload keyed by the app JWT
   secret, 15-minute expiry — the exact analogue of booking drafts).
2. **Apply** — `modify_booking(db, booking_id, modification_token=...)`
   verifies the token, re-runs the full validation, and refuses if the
   recomputed total differs from the previewed total ("price changed
   since preview"). It then applies room/dates/guests/`final_price`,
   reconciles payments (below) and writes an audit log entry
   `booking.modified` with old→new values, amount due and refund due.

### Eligibility (service-enforced)

A booking is modifiable only when **all** hold, evaluated against
hotel-local today:

- status is `PENDING` or `CONFIRMED` (cancelled → "this booking is
  cancelled…"; checked-in/out etc. → refused with reason), and
- `check_in > today` strictly (check-in day itself or earlier →
  "check-in has already arrived/passed — contact reception").

### Payment rule (implemented exactly as follows)

- `captured` and `refunded` payment rows are **never** altered.
- The booking's outstanding balance is carried by `pending` rows; when
  a booking has payment rows, apply reconciles them to exactly one
  pending row of `max(new_total − net_captured, 0)` (created with
  method `other` / reference `booking-modification` if none existed,
  deleted when the amount due is 0).
- Bookings with **no** payment rows (the normal agent-created case —
  payment happens at the hotel) get none created; staff record payments
  through the existing API as before.
- Overpayment is **reported, never auto-refunded**: the quote/apply
  result carries `refund_due`, and the guest is told reception will
  process it. No fabricated refund records are created.

### Agent surface

Three tools in `app/agent/tools/booking_tools.py`, registered in the
shared registry (so Mercury gets them too, with prompt instructions for
the same two-phase flow):

- `get_my_bookings` (read-only) — the conversation guest's bookings
  with `check_out >= hotel-today`, each flagged `modifiable` +
  `ineligible_reason`.
- `preview_booking_modification` (read-only) — validates and returns
  old → new summary, totals, `amount_due`/`refund_due` and the token.
- `modify_booking` (write) — applies with the token.

Ownership is enforced in the tool layer: when the conversation has a
guest, a booking belonging to a different guest is refused
("belongs to a different guest").

The mock provider runs the same flow deterministically
(`_route_modify`, placed alongside the food-order slot flow): identify
guest (conversation guest → lookup → ask for name+phone/email) → list
bookings → pick target (explicit id / room-type mention / the only
booking / the only modifiable one; a sole ineligible booking is picked
so the guest hears *why* it can't change) → collect change slots
(dates incl. relative phrases — a single date shifts check-in keeping
the night count; room type; guest count) → preview → the shared step-1
confirmation gate applies it via the token. One router fix was needed:
`get_my_bookings` results are no longer treated as a final summary
while a modify flow is open (they are an intermediate step), matching
how `find_or_create_guest` already behaved. All modify replies exist in
English / Hindi / Hinglish via the existing language system.

## Files changed

| File | Change |
| --- | --- |
| `app/agent/relative_dates.py` | **New** — deterministic relative-date resolver |
| `app/agent/providers/base.py` | `ProviderContext.timezone` |
| `app/agent/runner.py` | Hotel-local today + timezone in context; deterministic date-resolution note in the system prompt |
| `app/agent/prompts.py` | Weekday + timezone in the date line; weekend definition; relative-date + modify-flow instructions |
| `app/agent/providers/mock.py` | Relative dates in booking slots + words restated at preview; hotel-local today throughout; full deterministic modify flow; confirmation gate handles modify previews; `get_my_bookings` no longer short-circuits an open modify flow |
| `app/agent/tools/booking_tools.py` | `get_my_bookings`, `preview_booking_modification`, `modify_booking` tools + guest-ownership guard |
| `app/services/booking_service.py` | `modification_ineligibility_reason`, `validate_modification`, `issue_modification_token`, `modify_booking` (apply + payment reconciliation + audit log) |
| `tests/test_agent_dates_modify.py` | **New** — 17 tests (below) |

## Tests

New file `tests/test_agent_dates_modify.py` — **17 tests**:

- Resolver units with frozen clocks: next/this weekend from a Friday;
  Saturday and Sunday edge semantics; tomorrow/kal/कल; day-after-
  tomorrow/parso; weekday phrases in English + Hinglish ("agle
  shukravar"); "next week"; no-phrase → None.
- End-to-end mock conversation: "book a room for next weekend" fills the
  slots with the resolved dates, the reply states them in words, **no
  booking exists before confirmation**, and confirming creates it on
  exactly those dates.
- Runner test: the system prompt carries the deterministic date
  resolution note + hotel timezone context.
- Modify: future CONFIRMED booking modified end-to-end through chat
  (preview changes nothing; confirm applies; total recomputed);
  relative-date modification ("change my booking to next weekend");
  past check-in refused with reason; cancelled refused; unavailable new
  dates refused with the booking untouched; forged/missing token fails
  safely; payment reconciliation (captured untouched, pending adjusted,
  `refund_due` reported without creating a refund); room-type + guest
  count change repriced via the service; tool-level guest-ownership
  enforcement.

Full suite (recipe: `DATABASE_URL=sqlite:///./stayflow_e2e.db pytest`
from `backend/`): **320 passed / 2 failed / 2 deselected** — baseline
was 303/2/2, so +17 new tests and zero regressions; the 2 failures are
the known pre-existing SQLite-env ones
(`test_hotel_crud_and_validation`,
`test_ingest_document_creates_chunks_and_embeddings`). Ruff clean on
all touched files.

One pre-existing flakiness note: running a *subset* of test files
(e.g. only test_agent + test_chat_bugfixes + test_language) can trip
the IP-keyed anonymous chat rate limit and fail
`test_screenshot_preorder_asks_clarification_never_confirms` with a
429. This reproduces identically on the pristine pre-change code; the
full-suite recipe above is unaffected.

## How to live-test (after commit + deploy)

On the guest chat (`/chat`) of the live demo:

**Relative dates**
1. "I want to book a room for next weekend" → the assistant restates
   "Next weekend — Saturday <date> to Sunday <date>" while collecting
   the remaining slots; the booking is created only after you confirm
   the preview.
2. Also try: "room for tomorrow", "kal ke liye room chahiye",
   "agle Shukravar ko room milega?".

**Modify** (book first *in the same conversation* so the guest is
identified, then:)
1. "I want to change my booking" → your bookings are listed.
2. "Move it to next weekend" → a modification summary shows old → new
   dates and old total → new total with the difference; **nothing
   changes yet**.
3. "Yes, confirm please" → "Your booking has been updated…".
4. Refusals to try: ask to change a booking whose check-in is today or
   past, or a cancelled one → the assistant explains why and suggests
   contacting reception.
