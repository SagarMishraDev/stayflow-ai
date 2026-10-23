# Analytics Master Revision — Report (2026-10-23)

Implements the corrective master prompt: Analytics-only redesign
scope, four-month Revenue Trend, grouped-bar Room Popularity,
realistic test data, and Render keep-alive. Builds on the HMS upgrade
(commit `d19ce30`) and supersedes the global part of the View 2
redesign (`b6112bc`). Nothing was committed, pushed or deployed by the
implementing agent; the parent agent releases.

## 1. Theme-scope correction (Part A) — what was reverted

The owner reversed the global part of the View 2 redesign: only the
Analytics page may carry the new design. The global dashboard theme
was restored to the pre-View-2 state, byte-identical to commit
`d19ce30` (verified with `git show` diffs):

- `frontend/dashboard/tailwind.config.js` — restored tokens
  (paper `#FFFFFF`, ink `#2B2B2B`, sun `#FFD23F`, coral `#FF6B6B`,
  teal `#1BA39C`, deep-teal `#08756F`, mist `#EFF8F6`, line `#DBDBDB`).
- `frontend/dashboard/src/index.css` — restored (Barlow Condensed
  uppercase headings, pill buttons, mist panels).
- `frontend/dashboard/src/components/Layout.tsx` — restored
  (deep-teal sidebar, sun active pill; NAV items/roles identical to
  the View 2 version, no functional loss).
- `frontend/dashboard/src/pages/Login.tsx` — restored (sun brand tile).
- `frontend/dashboard/index.html` — restored, with ONE additive
  change: the Inter family was added to the Google Fonts URL so the
  Analytics page can use it. No other page's font stack changes
  (global config again resolves to Barlow/Nunito/IBM Plex Mono).

The Analytics page keeps the View 2 design but is now SELF-CONTAINED:

- New `frontend/dashboard/src/pages/analytics.css`, imported only by
  `Analytics.tsx`. Every rule is scoped under `.analytics-root`
  (palette as CSS variables `--ax-*`, `.ax-card`, `.ax-btn`,
  `.ax-select`, `.ax-label`, `.ax-table`, and an `h1/h2/h3` override
  so the global Barlow-uppercase base layer does not leak in).
- `Analytics.tsx` wraps everything in `.analytics-root` and renders
  its own header (the shared `PageHeader` is no longer used here, so
  its global styling is untouched).
- All analytics components (`components/analytics/*`) were audited:
  every theme-token class (`bg-paper`, `text-ink-*`, `border-line`,
  `bg-mist`, `bg-pale`, `shadow-card`, `bg-sun`, …) was replaced with
  explicit hex / arbitrary-value classes from the Analytics palette.
- Grep proof: the View 2 hexes `#062F33`, `#F4F7FA`, `#102A43`
  (case-insensitive) occur ONLY in `src/pages/Analytics.tsx`,
  `src/pages/analytics.css` and `src/components/analytics/*` —
  nowhere else in `src/`, `index.html` or `tailwind.config.js`.

## 2. Revenue Trend — four months in one chart (Part B)

`components/analytics/RevenueTrendChart.tsx` was rewritten.

- **Windows**: the month containing the selected range's END date,
  plus the three preceding calendar months, chronological. The end
  date is resolved client-side mirroring the backend's
  `resolve_range` (presets → their real last day; custom → the chosen
  To date). Each month is fetched separately via the existing
  `GET /analytics/series` with `range=custom` for that calendar month
  (4 parallel React Query queries) — the API contract is unchanged.
- **Colours** (fixed by spec, chronological): `#0F9D94`, `#3B82F6`,
  `#8B5CF6`, `#F59E0B`. The month summary cards above the chart are
  the legend: colour chip, real month name + year, month total, and
  growth % vs the previous displayed month — computed with the shared
  `pctChange`, which returns null for a zero baseline, in which case
  the card shows "No baseline" instead of a fabricated percentage.
- **Alignment**: day grouping → shared day-of-month axis (1–31);
  week grouping → week-of-month index (weeks are the API's
  Monday-keyed buckets); month/year grouping → each month window
  aggregates to a single point, axis labelled "Month total". Buckets
  the API did not return for a month are **gaps** (null): the path
  breaks, no dot is drawn, and the tooltip says "No data". Returned
  zero-revenue buckets plot as genuine zeros. Light area fill (10%
  opacity) per series; Catmull-Rom smoothing as before.
- **Tooltip**: bucket label + per-month rows (colour, month, revenue
  in ₹, booking count, or "No data").
- **Hourly exception (documented choice)**: the series API's hourly
  grouping always describes *today's* hours and ignores the range, so
  a four-month overlay would plot the same day four times. For
  `groupBy=hour` the card instead renders the single hourly series
  (`HourlyTrendChart`) with an explicit note in the card.
- The old trend's dashed comparison line is gone (replaced by the
  four-month overlay). The page-level **Compare with** selector is
  NOT dead: it still drives all KPI deltas, exactly as before.

## 3. Room Popularity — grouped vertical bars (Part C)

The bubble chart was removed. New component `RoomPopularityBars`
(same file, `components/analytics/RoomPopularityChart.tsx`):

- **New backend endpoint** `GET /api/v1/analytics/popularity-series`
  (hotel-scoped, `analytics.view`-gated — cross-hotel is 403, no
  token is 401, bad `group_by` is 422). Query: `hotel_id`, `range` /
  `start` / `end`, `group_by` ∈ day|week|month|year.
  Response: `{ group_by, period_days, buckets: [{ period, rooms:
  [{ room_type, bookings, revenue }] }], room_types: [ …totals +
  occupancy… ] }`. Buckets cover every bucket intersecting the range;
  EVERY room type appears in EVERY bucket (zero-filled), so
  zero-booking types stay visible. Accounting matches the existing
  popularity endpoint: non-CANCELLED bookings, earned by check-in
  date; occupancy = overlap room-nights / (total_rooms × days) for
  active types. Bucket counts are capped at 366 for safety.
- **Chart**: grouped vertical bars, X = time buckets, one bar per
  room type, height = bookings. Period control Day/Week/Month/Year
  (the endpoint's `group_by`), plus the page's date range. Dense day
  views scroll horizontally inside the card rather than crushing
  labels. Hover highlights a bar and drives a detail strip (period,
  type, bookings, revenue, range occupancy); native `<title>`
  tooltips carry the same data.
- **Colours**: pinned by name — Heritage Suite `#0F9D94`, Deluxe King
  Room `#3B82F6`, Executive Twin Room `#F59E0B`; further types take an
  extended palette (`#8B5CF6`, `#10B981`, `#EF4444`, `#087E78`,
  `#18B8AC`, `#8293A5`) assigned deterministically (alphabetical
  among unpinned types) via `buildRoomColorMap`, shared by chart,
  legend, category donut and table indicators.
- **Sorting** (Bookings / Revenue / Occupancy) reorders chart groups,
  legend and table together. Most-booked / least-booked panels are
  retained, listing ALL tied types.
- **Performance table** (scoped `.ax-table`, horizontal scroll on
  mobile): Room Type (colour dot), Total Bookings, Total Revenue,
  Average Daily Bookings (bookings ÷ period days, 2dp; "—" for
  open-ended ranges), Occupancy Rate (+ occupied/available
  room-nights, retained), Trend Sparkline (real per-bucket booking
  counts from the same endpoint), Status. Compact progress bars for
  bookings, revenue and occupancy.

## 4. Filter additions (Part D)

- **Rolling presets** `last_7_days` ("Last 7 days": today + previous
  6 days) and `last_30_days` ("Last 30 days": today + previous 29
  days) added end-to-end: `resolve_range` + `RANGE_KEYS` in
  `backend/app/services/analytics.py`, `RANGE_OPTIONS` in
  `analyticsApi.ts`, service + endpoint tests.
- **Comparison "Previous period"** (`previous_period`): the
  equal-length window immediately before the selected range,
  resolved in the compare endpoint from range A's bounds via
  `previous_period_bounds` (open-ended `all` → 422). Frontend option
  in the new `COMPARE_OPTIONS`; it is now the default comparison.
  Existing options (named ranges incl. Last month / Last year, and
  client-side "No comparison") are unchanged.

## 5. Seed data (Part E)

`backend/scripts/seed_analytics_demo.py` (full docs:
`docs/ANALYTICS_DEMO_DATA.md`).

- Target: `ANALYTICS_DEMO_DATABASE_URL` only, default
  `sqlite:///./analytics_demo.db`. Hard guards refuse (exit 2) any
  URL whose host contains `neon.tech` or `render.com`, or a URL equal
  to the app's `DATABASE_URL` when that is remote. The production
  database is never touched.
- Creates schema via `Base.metadata.create_all`, then the demo hotel
  **"StayFlow Analytics Demo Hotel"** (marker email
  `stayflow-analytics-demo@demo.example`), the 3 standard room types,
  140 synthetic guests (`@demo.example`), and **520 bookings**
  (RNG seed 42): check-ins from 1 Jan of last year to ~45 days ahead;
  statuses PENDING/CONFIRMED/CHECKED_IN/CHECKED_OUT/CANCELLED (~8%);
  sources direct/website/walk_in/agent_chat/unknown; stays 1–7
  nights; rates vary by season/weekend/jitter; per-type nightly
  concurrency never exceeds `total_rooms`. Payments follow the real
  schema (full captured, partial advance + pending remainder, pending
  only, ~30% of paid cancellations fully refunded, ~12% of completed
  stays partially refunded; UPI/card/cash/bank_transfer; `DEMO-`
  reference prefix). By construction the Heritage Suite has zero
  bookings in June of the first seeded year.
- Idempotent (marker lookup → "already seeded", inserts nothing);
  `--cleanup` deletes ONLY the demo hotel's rows (payments → bookings
  → guests → rooms → hotel) with counts.
- **Verification (live run of the CLI, 2026-10-23)**: inserted 520
  bookings, 520 distinct ids; per year {2025: 240, 2026: 280};
  statuses {CHECKED_OUT: 424, CONFIRMED: 48, CANCELLED: 35,
  PENDING: 11, CHECKED_IN: 2}; 556 payments, 62 refund rows; captured
  by method {upi: 193, card: 146, cash: 66, bank_transfer: 49};
  total non-cancelled revenue ₹1,00,64,750; all six self-checks OK.
  Re-run reported "already seeded"; `--cleanup` deleted exactly
  {payments: 556, bookings: 520, guests: 140, rooms: 3}; the
  neon.tech guard exited 2.
- Tests (`tests/test_analytics_demo_seed.py`, 5 tests): seed on a tmp
  SQLite file (count=60) asserts ≥60 unique bookings over 2 years,
  idempotent re-run, cleanup leaves an unrelated hotel untouched,
  guard refusals, and — at full count=520 — that the analytics
  services return 4 DISTINCT monthly revenue totals for Jun–Sep 2026
  and consistent popularity-series buckets/totals.
- **Switching demo/real**: run the app with
  `DATABASE_URL=sqlite:///./analytics_demo.db` (plus a staff user via
  `scripts/seed_admin.py --hotel "StayFlow Analytics Demo Hotel"`)
  for demo data; start with the normal `DATABASE_URL` for real data.
  The two datasets never mix.

## 6. Render keep-alive (Part F)

- **Health**: `GET /api/v1/health` already exists and is DB-free
  (returns `{status, service, version}` from settings only) — verified
  in `app/api/router.py`; no duplicate was added. The authenticated
  `/api/v1/db-check` remains the separate readiness check.
- **Script**: `backend/scripts/keep_render_awake.py` — stdlib only;
  `KEEP_ALIVE_URL` required (clear error + exit 2 when unset; no
  hardcoded URL), `KEEP_ALIVE_INTERVAL_MINUTES` default 12, clamped
  5–30; 30s timeout; one attempt per cycle; logs timestamp + status
  + latency; `--once` mode for cron; clean SIGINT/SIGTERM stop.
- **Docs**: `docs/KEEP_ALIVE.md` — env vars, local run, verification
  (curl, Render logs), disabling, and the honest limitation: a script
  inside the sleeping service cannot wake it, so the pinger must run
  externally (the owner's Muse cron pinger, cron-job.org,
  UptimeRobot, or a cron entry on any always-on machine). No plan or
  billing change, no background worker, no startup loop was added.

## 7. Files changed / created

Backend:
- `backend/app/services/analytics.py` — rolling ranges,
  `previous_period_bounds`, `popularity_series` (+ one pre-existing
  over-length line wrapped).
- `backend/app/api/analytics.py` — `previous_period` compare,
  `GET /analytics/popularity-series`.
- `backend/tests/test_analytics.py` — +6 tests (rolling presets,
  previous-period math + endpoint, popularity-series month/day/week
  boundaries + zero types, hotel isolation/role gating); one
  pre-existing unused variable removed.
- `backend/scripts/seed_analytics_demo.py` — NEW.
- `backend/scripts/keep_render_awake.py` — NEW.
- `backend/tests/test_analytics_demo_seed.py` — NEW (5 tests).

Frontend:
- Restored to `d19ce30`: `tailwind.config.js`, `src/index.css`,
  `src/components/Layout.tsx`, `src/pages/Login.tsx`; `index.html`
  restored + Inter added to the font URL.
- `frontend/dashboard/src/pages/analytics.css` — NEW (scoped).
- `frontend/dashboard/src/pages/Analytics.tsx` — rewritten wiring
  (scoped root/header, four-month queries, popularity-series,
  enhanced table, COMPARE_OPTIONS).
- `components/analytics/RevenueTrendChart.tsx` — rewritten
  (four-month chart + hourly fallback).
- `components/analytics/RoomPopularityChart.tsx` — rewritten
  (grouped bars; bubbles removed).
- `components/analytics/ChartCard.tsx`, `KpiCard.tsx`,
  `BreakdownCharts.tsx`, `RecentActivity.tsx` — token classes →
  scoped hex classes; card shells use `.ax-card`.
- `components/analytics/format.ts` — month colours/labels,
  room-type colour map helpers.
- `src/lib/analyticsApi.ts` — rolling range options,
  `COMPARE_OPTIONS`, `fetchPopularitySeries` + types.

Docs: `docs/ANALYTICS_DEMO_DATA.md`, `docs/KEEP_ALIVE.md` — NEW.
This report: `ANALYTICS_MASTER_REPORT.md`.

## 8. Validation

- Backend suite (recipe: `DATABASE_URL=sqlite:///./stayflow_e2e.db`,
  pytest from `backend/`): **295 passed / 2 failed / 2 deselected**
  in 193s. The 2 failures are exactly the pre-existing SQLite-env
  pair (`test_hotel_crud_and_validation`,
  `test_ingest_document_creates_chunks_and_embeddings`), unchanged
  from the 284-passed baseline — +11 new tests, zero regressions.
- Ruff (`app tests scripts`): all checks passed (4 findings in the
  new seed script fixed, plus 2 pre-existing findings — an
  over-length line in `recent_activity` and an unused variable in the
  activity test — fixed with behavior-neutral edits).
- Dashboard: `npm run build` ✓ and `npm run build:demo` ✓
  (tsc --noEmit clean; only the pre-existing >500 kB chunk warning).
- Theme scoping: file-level diffs vs `d19ce30` + grep proof (see §1).

## 9. Known limits / notes

- Responsive behaviour at the spec's seven widths was implemented
  with fluid grids, viewBox-scaling SVGs, and in-card horizontal
  scroll for dense bar/table views, but was NOT browser-verified in
  this environment (no browser pass was run for this revision).
- The four-month chart fetches each month with the SELECTED
  `group_by`; for `hour` it falls back to the honest single-day
  hourly view (see §2).
- KPI sparklines still come from the selected range's series (real
  data, as before); the trend card no longer consumes the comparison
  series — comparison drives KPI deltas only.
- "Previous period" is the new default comparison; for the
  open-ended "All time" range it returns 422 from the compare
  endpoint and KPI deltas simply hide (same failure mode as any
  failed compare fetch before this change).
- The seed's `CHECKED_IN` count is small by construction (only stays
  spanning "today"), and F&B department revenue stays ₹0 in the demo
  dataset (no synthetic orders — bookings/payments only, per spec).
- The demo database file (`backend/analytics_demo.db`) is created by
  running the seed; it is a local artifact, not part of the app.
