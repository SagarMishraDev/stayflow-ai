# Analytics demo data (500+ synthetic bookings)

`backend/scripts/seed_analytics_demo.py` builds a dedicated,
clearly-marked demo hotel — **"StayFlow Analytics Demo Hotel"** —
with 520+ synthetic bookings so every Analytics chart, aggregation,
filter, comparison and CSV export can be verified against real rows
through the normal API. It is separate from `scripts/seed_demo.py`
(the small "StayFlow Grand Hotel" showcase seed): the two never touch
each other's data.

## Safety rules

- Target database = `ANALYTICS_DEMO_DATABASE_URL`, defaulting to a
  local file `sqlite:///./analytics_demo.db` in `backend/`.
- The script **refuses** (exit code 2) when the target URL's host
  contains `neon.tech` or `render.com`, or equals the app's
  `DATABASE_URL` when that is remote. It never reads/writes the
  production (Neon) database.
- Guests are synthetic: `@demo.example` emails, obviously fake names.
- Re-runs are idempotent (the demo hotel is found by its marker email
  and reported as "already seeded"). `--cleanup` deletes ONLY the demo
  hotel's rows — payments, bookings, guests, rooms, hotel, in FK-safe
  order — and reports the counts.

## What gets generated

- 3 room types (Deluxe King Room ×20, Executive Twin Room ×15,
  Heritage Suite ×6) with base rates, 140 synthetic guests.
- ≥520 bookings (RNG seed 42, reproducible): check-ins spread from
  1 January of last year through ~45 days from now, monthly volumes
  weighted by a seasonal profile (December peak, June trough, +15%
  current-year growth) so monthly revenue totals genuinely differ.
- Statuses from the real model lifecycle (`PENDING`, `CONFIRMED`,
  `CHECKED_IN`, `CHECKED_OUT`, ~8% `CANCELLED`); sources `direct`,
  `website`, `walk_in`, `agent_chat`, `unknown`; stays of 1–7 nights;
  nightly rates vary by season, weekend and jitter; per-type nightly
  concurrency never exceeds the room count.
- Payments follow the real schema: captured in full for completed
  stays, partial advance + pending remainder for some future bookings,
  pending rows for unpaid ones, full refunds for ~30% of paid
  cancellations, partial refunds on ~12% of completed stays. Methods:
  UPI / card / cash / bank transfer. Payment references carry a
  `DEMO-` prefix.
- By construction, the Heritage Suite has **zero bookings in June of
  the first seeded year**, guaranteeing a zero-booking room type in an
  otherwise active month.

On completion the script prints a verification summary (totals,
per-year / per-status / per-source / per-method breakdowns, revenue
total) and self-checks: ≥500 bookings, ≥2 years, ≥4 revenue months,
≥3 sources, refunds present, a zero-booking type/month exists.

## Commands

```bash
cd backend
# Seed (default target: sqlite:///./analytics_demo.db)
.venv/bin/python scripts/seed_analytics_demo.py
# More bookings / different target file
.venv/bin/python scripts/seed_analytics_demo.py --count 800
ANALYTICS_DEMO_DATABASE_URL=sqlite:////tmp/my_demo.db \
  .venv/bin/python scripts/seed_analytics_demo.py
# Remove ONLY the demo dataset
.venv/bin/python scripts/seed_analytics_demo.py --cleanup
```

## Running the app against the demo data

The demo file contains ONLY the analytics demo hotel (no staff user),
so first add an admin for it with the existing seed-admin script
(`--hotel` must match the demo hotel's name so the user attaches to
it). Simplest local flow:

```bash
cd backend
.venv/bin/python scripts/seed_analytics_demo.py          # creates analytics_demo.db
DATABASE_URL=sqlite:///./analytics_demo.db \
  .venv/bin/python scripts/seed_admin.py \
    --hotel "StayFlow Analytics Demo Hotel" --name "Demo Admin" \
    --email admin@demo.example --password 'choose-one-1'
DATABASE_URL=sqlite:///./analytics_demo.db \
  .venv/bin/python -m uvicorn app.main:app --port 8000
```

Then open the dashboard, log in, and select the analytics demo hotel.
All Analytics endpoints (`/analytics/overview`, `/series`,
`/compare`, `/breakdowns`, `/room-popularity`, `/popularity-series`,
`/activity`, `/export`) read the seeded rows through the normal
service layer — nothing in the charts is hardcoded.

## Switching back to real data

Just start the app with your normal `DATABASE_URL` (or unset the
override). The demo database is a standalone file; deleting it (or
running `--cleanup`) removes the synthetic dataset completely. Never
point `ANALYTICS_DEMO_DATABASE_URL` at the production database — the
script's guards refuse hosted targets, and that refusal is a safety
feature, not an obstacle to work around.
