# Demo Fill — Report (2026-10-23)

Env-gated synthetic booking batch for the LIVE demo hotel ("StayFlow
Grand Hotel"), built so the owner can populate the live demo's
Analytics graphs with ~180 marked, removable bookings spanning ~24
months. Nothing was committed, pushed or deployed by the implementing
agent, and the fill was never run against any remote database — the
owner flips the switch in Render (see `docs/DEMO_FILL.md`).

## Files changed / created

- `backend/app/demo_fill.py` — NEW. `fill_demo_bookings(db, hotel,
  count=180, rng_seed=7)`, `purge_demo_bookings(db, hotel)`,
  `run_demo_fill_from_env(session_factory)`.
- `backend/app/demo_bootstrap.py` — `prepare_demo_database` now calls
  the new fail-soft `apply_demo_fill()` after the migrate/seed steps
  (whether the hotel was just seeded or already existed). Only the
  demo boot path (`app/demo_main.py`, `DEMO_SEED=1`) reaches this —
  the normal app entrypoint is untouched.
- `render.yaml` — `ANALYTICS_DEMO_FILL` declared with `sync: false`
  plus instructions in comments (add `=1` in the dashboard to fill,
  set `cleanup` to remove the batch, delete the variable when done).
- `backend/tests/test_demo_fill.py` — NEW, 4 tests.
- `docs/DEMO_FILL.md` — NEW: marker scheme, exact Render steps,
  warnings, local/programmatic use.

## How it works

- **Trigger**: boot reads `ANALYTICS_DEMO_FILL`. `1` → fill,
  `cleanup` → purge, anything else/unset → no-op (the check runs
  before any database work). The whole step is wrapped so a failure
  logs and never blocks boot. The demo hotel is resolved by the same
  natural key `scripts/seed_demo.py` uses (name "StayFlow Grand
  Hotel"); zero or multiple matches → skip with an error log.
- **Batch marker** (tag `DEMO-FILL-2026`): batch guests use emails
  `demofill.guestNNN@demo.example` and `Demo Guest …` names; batch
  bookings are those belonging to batch guests (the Booking model has
  no reference/notes column — booking `source` values stay realistic);
  batch payments carry `reference` values prefixed `DEMO-FILL-`.
- **Generation** mirrors `scripts/seed_analytics_demo.py`: same base
  rates (₹4,500 / ₹5,500 / ₹12,000), seasonality, round-to-₹50 nightly
  pricing (`final_price = nightly × nights`), status-by-timing rules
  (~8% cancelled; past → CHECKED_OUT; spanning today →
  CHECKED_IN/CONFIRMED; future → CONFIRMED/PENDING), weighted sources
  (incl. `agent_chat`), 1–7-night stays, 1–4 guests (capped by room
  capacity), per-type nightly concurrency never above `total_rooms`,
  and the same payment shapes (captured in full, pending, partial
  advance + pending remainder, refunds on a slice of paid bookings and
  paid cancellations; methods upi/card/cash/bank_transfer). Every one
  of the ~26 window months gets ≥4 bookings at count=180, the rest
  distributed by seasonality.
- **Idempotent**: a second fill inserts nothing and reports
  `already_filled` with the existing count.
- **Purge** deletes, FK-safe and hotel-scoped: payments of batch
  bookings → batch bookings → batch guests (a batch guest still
  referenced by another table is kept and counted); zero counts when
  no batch exists; non-batch rows are never touched.

## Verification

- New tests (`tests/test_demo_fill.py`, tmp SQLite, fixed
  `today=2026-10-23`, count=48): ≥48 bookings created, check-ins cover
  ≥24 distinct months with ≥1 each, ≥3 statuses and ≥3 sources,
  payments exist with `DEMO-FILL-` references and ≥1 refund; second
  fill inserts 0 and reports `already_filled`; purge removes exactly
  the batch while a pre-existing normal booking + its payment survive
  untouched; purge with no batch returns all zeros. **4 passed**
  (with `tests/test_demo_bootstrap.py`: 19 passed).
- Live smoke of the exact boot path against a scratch SQLite DB at
  full size: fill → 180 bookings / 60 guests / 191 payments / 22
  refunds across 26 months, all five sources; re-run →
  `already_filled` (180 existing, 0 new); `cleanup` → exactly
  191 payments / 180 bookings / 60 guests deleted; variable unset →
  no-op.
- Full backend suite (recipe: `DATABASE_URL=sqlite:///./stayflow_e2e.db`,
  pytest from `backend/`): **299 passed / 2 failed / 2 deselected**
  — baseline 295 + 4 new tests, zero regressions; the 2 failures are
  exactly the pre-existing SQLite-env pair
  (`test_hotel_crud_and_validation`,
  `test_ingest_document_creates_chunks_and_embeddings`).
- Ruff (`app tests scripts`): all checks passed.
- No frontend files were touched.

## Owner steps (Render)

1. Dashboard → `stayflow-ai-demo` → Environment → add
   `ANALYTICS_DEMO_FILL` = `1` → service restarts → Analytics graphs
   fill (boot log: `ANALYTICS_DEMO_FILL: fill done (...)`).
2. To remove: set the variable to `cleanup`, let it restart (log:
   `cleanup done (...)`), then delete the variable.
