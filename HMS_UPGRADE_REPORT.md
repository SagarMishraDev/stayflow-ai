# StayFlow AI — Advanced HMS Upgrade Report

Upgrade of the existing StayFlow AI codebase against the "Advanced Hotel
Management System" master prompt (2026-10-23). Work follows the prompt's
phase order: audit → language → RBAC → analytics → operations → validation.
Nothing here is claimed complete unless its backend, frontend (where
applicable) and tests all pass; see the final section for exact status.

---

## Phase 1 — Audit of the existing system (before changes)

### Architecture found

- **Backend**: FastAPI + SQLAlchemy 2.0 + Alembic (head `c4d8e2a91b07`,
  32 migrations) + PostgreSQL (Neon in the live demo; SQLite for the local
  test recipe). Versioned API under `/api/v1` in `backend/app/api/router.py`
  plus public/widget/integration/webhook routers.
- **Agent**: provider abstraction (`mock`, `ollama`, `inception`/Mercury)
  behind `app/agent/runner.py`; 18 validated tools; deterministic booking
  gate (preview → explicit confirm → create); hotel-isolated RAG for
  unstructured knowledge only.
- **Dashboard**: React + TS + Vite + Tailwind (no chart library installed),
  17 pages, role-gated routes for admin-only pages.
- **Auth/RBAC (pre-upgrade)**: three roles only — `SUPER_ADMIN`,
  `HOTEL_ADMIN`, `STAFF` (`app/core/roles.py`); JWT (argon2 hashing) with
  the role claim cross-checked against the DB row on every request, so a
  forged claim fails; deactivated users are rejected in `get_current_user`.
  Audit log model + endpoints exist. Notifications are per-user rows.
- **Data model gaps vs the spec**:
  - **No payment records at all.** Bookings carry only `final_price`.
    "Revenue collected / pending / refunds" cannot be computed honestly
    without a payments table → Phase 4 adds one (see accounting rules).
  - `Order.status` is a free string with a documented status set
    (PENDING/CONFIRMED/PREPARING/READY/DELIVERED/CANCELLED); no
    accept/reject-with-reason fields, no scheduled-for time — the
    screenshot bug (a food order "confirmed" for check-in day with no
    room/date) had no structured place to record *when* food was wanted.
  - `HotelRoom` (physical rooms) has only `is_active`; no cleaning status,
    so housekeeping flow needs a field.
  - `Conversation` has no language preference field.
  - `HotelUser` has no department/shift/token-version fields; session
    revocation on role change currently works only because the JWT role
    claim is cross-checked against the DB (a role change invalidates old
    tokens with 401 — verified in `get_current_user`). Deactivation also
    rejects old tokens. This mechanism is kept and documented; a
    `token_version` column is added so password/privilege changes can
    revoke sessions even when the role itself does not change.
- **Language handling (pre-upgrade)**: the system prompt said "reply in the
  guest's language" and nothing else. No detection, no script rules, no
  tests. The mock provider answered everything in English. This is exactly
  how the screenshot failure happened with the real LLM: a Roman-Hinglish
  message got a Devanagari reply containing invented non-words
  ("हिनकेक नंबर", "कीवद", "योरेक") — an unconstrained model transliterating
  instead of answering in the guest's script with verified content.

### Spec conflicts and safest resolutions

1. **Seven new roles vs three existing roles / live logins.** Resolution:
   extend the role enum; map legacy roles without breaking logins
   (`HOTEL_ADMIN` stays the Admin/Owner role; `STAFF` stays a valid generic
   staff role). New roles: `MANAGER`, `RECEPTIONIST`, `KITCHEN`,
   `HOUSEKEEPING`, `ACCOUNTANT`, `MAINTENANCE`. Permission matrix lives in
   one backend module (`app/core/permissions.py`) and the frontend reads
   the same role→capability mapping for menus (UX only).
2. **"Revenue collected/pending/refunds" without any payment data.**
   Resolution: add a real `payments` table (booking-linked, method,
   status captured/pending/refunded/failed). Until a payment row exists, a
   booking's money is *pending*, never "collected". No dummy figures.
3. **Booking source / payment method breakdowns.** Bookings have no source
   column → Phase 4 adds `bookings.source` (nullable; values like
   `agent_chat`, `dashboard`, `widget`, `integration`, `walk_in`). Legacy
   rows report as `unknown`, honestly labelled.
4. **Department revenue.** Orders are tagged by type (room service /
   dine-in / takeaway) — reported as "food & beverage" department revenue
   from real order totals; no other department has financial records, so
   no other department revenue is shown.
5. **Bubble chart library.** No chart library is installed; the spec
   prefers the library already present. All analytics charts (including
   circle packing) are hand-rolled SVG — deterministic layout, no new
   dependency. Noted here per instructions.
6. **Room popularity counting unit.** Bookings attach to a room *type*
   (`rooms`), while physical rooms are `hotel_rooms`. Popularity is
   therefore computed per room type AND per physical room where bookings
   can be attributed; physical rooms with no attributed bookings still
   appear with zero counts (the booking flow does not assign a physical
   room today, so per-physical-room counts are honestly mostly zero —
   see Phase 4 notes).

### Accounting definitions (used consistently by every analytics endpoint)

- **Booking count**: rows in `bookings` whose `created_at` (hotel-local
  date) falls in the period and whose status is not `CANCELLED`, unless a
  view explicitly reports cancellations. Cancelled bookings are counted
  separately as *cancelled bookings*.
- **Revenue (earned)**: sum of `final_price` for non-cancelled bookings
  whose **check-in date** falls in the period (revenue is attributed to
  the stay, not the booking creation). Multi-night stays attribute the
  full `final_price` to the check-in date's period — documented
  simplification; per-night proration is *not* applied, and the same rule
  is used everywhere so periods stay comparable.
- **Collected**: sum of `payments.amount` with status `captured` in the
  period (by payment date). **Pending**: earned revenue for the period
  minus captured payments linked to those bookings (floor 0), plus
  payments in `pending` status. **Refunds**: sum of payments with status
  `refunded` in the period. A booking with no payment row is fully
  pending. Payments are never fabricated by the system; staff record
  them, and a captured payment is a *record*, not proof of bank
  settlement (per spec §7).
- **Occupied room-nights**: for each non-cancelled booking overlapping the
  period, nights = overlap days between [check_in, check_out) and the
  period. **Available room-nights**: sum over room types of
  `total_rooms × days in period` (active room types only).
  **Occupancy %** = occupied / available × 100 (0 when available = 0).
- **ADR** = room revenue (earned, as above) / occupied room-nights.
  **RevPAR** = room revenue / available room-nights.
- **Average booking value** = earned revenue / booking count.
- **Average daily revenue** = earned revenue / days in period.
- **Complimentary stays**: bookings with `final_price = 0` count as
  bookings and occupied nights, contribute 0 revenue (they lower ADR —
  standard practice) and are excluded from average booking value's
  revenue but included in its count denominator only when the view says
  so; default: included (documented here).
- **Taxes**: `final_price` is treated as the stored total (the booking
  service already computes it); analytics do not add or strip tax.

---

## Phase 2 — Multilingual AI (implemented)

- **Detection** (`backend/app/agent/language.py`): pure deterministic
  classifier — Devanagari letter ratio, Roman-Hindi vocabulary/phrase
  scoring, English vocabulary scoring; explicit requests ("reply in
  English", "हिंदी में जवाब दो", "hinglish me batao") override detection;
  short neutral messages (dates/numbers) return no language so the
  conversation preference carries. Classes: hindi / hinglish / english /
  mixed (resolved to the dominant language, Hinglish for genuinely mixed
  Hindi-English) / neutral.
- **Threading**: the runner resolves the effective language per turn
  (explicit > latest message > recent history > stored preference >
  English), persists it on `conversations.preferred_language` (migration
  `d5e6f7a8b9c0`), injects a per-turn RESPONSE LANGUAGE instruction into
  the system prompt for real LLMs, and sets
  `ProviderContext.response_language` for the mock. The system prompt
  gained a mandatory language-policy section (script rules, no invented
  transliterations, numbers/IDs preserved verbatim, confirmations and
  errors in the same language). `ChatResult`/`ChatResponse` expose
  `detected_language`/`response_language` as metadata only.
- **Mock provider**: localized templates for greetings/help, availability
  and price prompts, booking slot/confirmation/cancellation summaries,
  menu and FAQ fallbacks; Hindi/Hinglish intent keywords added
  (खाली/उपलब्ध, कीमत, बुकिंग, रद्द, "khali", "kitna", "book kar do"…);
  Hinglish confirmations ("haan, confirm kar do") complete the booking
  gate. Devanagari is never emitted in Hinglish/English replies and vice
  versa (asserted by tests).
- **Food-order safety** (the screenshot case): a deterministic slot flow
  — real menu first, then item → quantity → timing → identified guest —
  and only then `create_food_order` with backend menu pricing. A request
  missing any slot gets a clarification in the guest's language; the
  confirmation the screenshot showed (garbled, for an unspecified
  check-in day, no room) is impossible in this flow. Room number is
  explicitly treated as "can be shared after check-in".
- **Tests**: `backend/tests/test_language.py` (19 tests) — detection for
  all spec table rows, explicit override, neutral continuity, switching,
  Hindi availability/pricing, Hinglish booking + confirmation, Hindi
  cancellation, the exact screenshot sentence as a regression (Hinglish
  out, zero Devanagari, zero orders created), and the full order flow
  completing only after item+quantity+timing+identity exist.

## Phase 4 — Analytics (implemented)

- **Schema**: `payments` table (booking-linked; method; status
  pending/captured/refunded/failed; reference) + `bookings.source`
  (agent bookings are stamped `agent_chat`; API accepts the field;
  legacy rows read as `unknown`). Migration `d5e6f7a8b9c0`.
- **Service** (`app/services/analytics.py`): KPI overview, revenue
  series (hour/day/week/month/year), period comparison with zero-safe
  percentages, breakdowns (room category, room, booking source, payment
  method, booking status, department = rooms + food & beverage from
  real order totals — no other department has financial records, so none
  is shown), room popularity with most/least including ALL ties and
  zero-booking room types. All hotel-scoped and timezone-aware.
- **API** (`app/api/analytics.py`): `/analytics/overview|series|compare|
  breakdowns|room-popularity|export` (CSV matching the filters) and
  `/payments` record/list. Role-gated (admin/manager/accountant views;
  reception can record payments).
- **Frontend**: `pages/Analytics.tsx` — KPI cards, range + grouping +
  comparison controls, SVG revenue trend with comparison overlay,
  breakdown bars, CSV export, and the room-popularity **bubble chart**
  (deterministic circle packing, area ∝ booking count, hover/click
  details, legend, most/least cards with ties, ranked table). Hand-rolled
  SVG — no chart library exists in the project and none was added.
- **Physical rooms caveat**: bookings attach to room *types* today, so
  popularity is per room type (where the data honestly lives). Physical
  rooms (`hotel_rooms`) carry the housekeeping lifecycle instead.
- **Tests**: `tests/test_analytics.py` (8 tests) — hand-computed KPI
  fixture (revenue 12000, collected 10000, pending 2000, refunds 500,
  ADR 4000, occupancy nights 3/527), series bucketing, zero-baseline
  comparison, breakdowns, ties + zero-booking rooms, CSV content,
  401 for anonymous, payment record/list.

## Phase 5 — Operational workflows (implemented)

- **Kitchen**: `GET /ops/kitchen-queue`, `POST /ops/orders/{id}/transition`
  with a strict status machine; reject/cancel requires a reason (stored
  on `orders.status_reason`); READY notifies the receptionist/staff role
  queues, CANCELLED notifies reception. New agent food orders notify the
  KITCHEN role queue. `orders.scheduled_for` records pre-order timing.
- **Housekeeping**: `PATCH /ops/hotel-rooms/{id}/cleaning-status` with
  DIRTY → CLEANING → CLEAN → INSPECTED → READY; housekeeping role cannot
  perform the INSPECTED/READY steps (inspection is separately
  authorized); READY notifies reception. A room never becomes
  bookable-ready by cleaning alone.
- **Front desk**: `GET /ops/arrivals`, `GET /ops/departures`,
  `POST /ops/bookings/{id}/checkout` (CHECKED_IN → CHECKED_OUT only),
  which raises the housekeeping cleaning-task notification.
- **Notifications**: `notifications.target_role` added (user_id now
  nullable — a row targets a user OR a role); `GET /ops/notifications`
  returns the caller's personal + role-queue feed; payloads carry
  operational facts only (no payment/guest-contact data).
- **Tests**: `tests/test_ops_workflows.py` (5 tests) — full kitchen
  transition chain + ready notification, reject-reason enforcement,
  queue filtering, housekeeping lifecycle + invalid jumps (409),
  checkout → housekeeping notification, arrivals.

## Phase 3 — RBAC + staff hierarchy + role dashboards (implemented)

- **Roles**: `StaffRole` extended from 3 to 9 values — `super_admin`,
  `hotel_admin` (Admin/Owner), `manager`, `staff` (generic legacy),
  `receptionist`, `kitchen`, `housekeeping`, `accountant`,
  `maintenance`. Existing accounts keep working (no role renames).
- **Permission matrix**: new `app/core/permissions.py` is the single
  source of truth (`has_permission`, `require_permission`,
  `require_any_permission`; unknown role/capability fails closed;
  SUPER_ADMIN holds all known capabilities). Key assignments:
  `analytics.view` = admin/manager/accountant; `analytics.finance` =
  admin/accountant only; `bookings.manage`/`checkin.manage` =
  admin/manager/staff/receptionist; `orders.kitchen` = kitchen+
  (kitchen cannot touch payments); `housekeeping.manage`,
  `maintenance.manage`, `menu.manage` (kitchen included);
  `staff.create_staff`/`staff.manage` = admin/manager;
  `settings.manage` = admin only; `audit.view` =
  admin/manager/accountant. The dashboard mirrors the same map in
  `src/lib/roles.ts` for UX only — the backend is authoritative.
- **Staff lifecycle rules** (enforced in handlers, not just the
  matrix): a MANAGER creates/manages only {receptionist, kitchen,
  housekeeping, accountant, maintenance, staff} and can never create
  or grant hotel_admin/manager/super_admin; SUPER_ADMIN cannot be
  created through the API at all (protected process only); nobody can
  deactivate/delete themselves or raise their own role; hotel_admin
  cannot modify a super_admin. Unique email per hotel and argon2
  hashing unchanged; audit entries on create/update/deactivate and a
  dedicated `role_changed` entry.
- **Session revocation**: JWTs now carry a `tv` (token_version) claim;
  `get_current_user` rejects a token whose `tv` differs from the
  user's current `token_version`. Role change, password change and
  deactivation bump the version, so old sessions die immediately;
  never-bumped users' existing tokens stay valid (missing claim = 0).
- **Endpoint gating added**: staff create/update/delete, `GET
  /audit-logs` (`audit.view`), `PATCH /bookings/{id}`
  (`bookings.manage`), `PATCH /orders/{id}` (`orders.manage` or
  `orders.kitchen`). Analytics and ops endpoints are gated by their
  own capability checks (Phases 4–5). Tenant isolation unchanged
  (cross-hotel = 403).
- **Frontend**: role-aware NAV and route guards (Staff page now open
  to managers with a restricted role picker; Audit log adds
  manager/accountant), a `department` field on staff create/edit/list,
  and role-specific quick-action cards on Home for all nine roles
  reusing existing pages (no duplicated screens).
- **Tests**: `tests/test_rbac_hms.py` (15 tests) — manager creates
  receptionist; manager creating admin/manager/super_admin → 403;
  self-escalation → 403; receptionist/maintenance blocked from audit
  while manager/accountant pass; kitchen can transition orders but
  not create users; housekeeping blocked from booking edits;
  deactivation and role/password changes revoke live tokens (401)
  while fresh logins work; self-deactivation → 403; cross-hotel
  staff access → 403; department round-trip.

## Phase 6 — Validation results (2026-10-23)

- **Full backend suite** (mandated recipe: `DATABASE_URL=sqlite:///./
  stayflow_e2e.db pytest -q` from `backend/`): **282 passed / 2 failed
  / 2 deselected** (191s). Baseline before this upgrade was 235/2/2;
  the +47 are the new tests (19 language + 8 analytics + 5 ops + 15
  RBAC), all passing. The 2 failures are exactly the pre-existing
  SQLite-environment ones — `test_hotel_crud_and_validation` and
  `test_ingest_document_creates_chunks_and_embeddings` — **zero
  regressions**.
- **New-test subsets**: `test_language.py` 19 passed;
  `test_analytics.py` 8 passed; `test_ops_workflows.py` 5 passed;
  `test_rbac_hms.py` 15 passed (also 30 passed together with the
  pre-existing `test_rbac.py` + `test_auth.py`).
- **Ruff**: `ruff check .` clean and `ruff format --check .` clean
  (177 files).
- **Dashboard**: `npm run build` and `npm run build:demo` both pass,
  including `tsc --noEmit`.
- **Migration**: one Alembic revision `d5e6f7a8b9c0` (down_revision
  `c4d8e2a91b07`) applied to the local e2e database; on the production
  Postgres it will run via the existing demo bootstrap
  (`alembic upgrade head`) at next deploy — nothing was deployed by
  this work.

## Known limitations / NOT done (explicit)

- The chat rate limiter (20/min per bucket) is shared by anonymous
  widget guests; the language tests were moved to per-guest buckets
  to keep the suite deterministic. Under unusually fast full-suite
  runs, pre-existing anonymous chat tests (RAG/prompt-injection) can
  still flake on that shared bucket — a harness property, not a
  product regression; the final run above was clean.
- Analytics department breakdown covers rooms + food & beverage from
  real orders only; there is no other departmental revenue source in
  the data model, and none was invented.
- Room popularity is per room TYPE (bookings attach to types);
  physical rooms carry the housekeeping lifecycle only.
- Breakfast/other service revenue is not separated in payments (no
  such field exists); payments are recorded against bookings.
- The embedding provider was NOT switched (sentence-transformer RSS
  vs the 512MB instance limit, as before); analytics/RBAC/language do
  not depend on it.
- No commit, push or deploy was performed — the parent verifies and
  releases. Live re-verification after deploy should cover: the
  screenshot Hinglish sentence in the real widget, an Analytics page
  load for admin/manager/accountant, and a manager creating a
  receptionist in the live dashboard.
