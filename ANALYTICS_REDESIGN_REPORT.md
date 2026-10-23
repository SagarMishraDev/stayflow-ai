# Analytics "View 2" Redesign — Report

Scope: presentation + shell redesign of the staff dashboard Analytics
experience to the approved View 2 direction. All backend calculations
and API contracts are reused unchanged; the only backend change is one
additive endpoint (below). Nothing was committed, pushed, or deployed —
this is ready for review/release by the owner.

## Design system applied (dashboard-wide)

- `frontend/dashboard/tailwind.config.js` — token names unchanged,
  values remapped to View 2: app background `#F4F7FA` (paper), cards
  white with `#E6ECF1` borders and 14–18px radii, text `#102A43 /
  #52677D / #8293A5`, primary teal `#0F9D94`, dark `#087E78`, deep
  `#075E5A`, bright `#18B8AC`, emerald `#10B981`, sun `#FBBF24`
  (accent only), coral `#EF4444`, warning `#F59E0B`, info `#3B82F6`,
  purple `#8B5CF6`, comparison gray-teal `#B8CDD3`, gridlines
  `#E7EDF2`, dividers `#EDF1F5`, sidebar `#062F33 → #041F25`.
- `frontend/dashboard/index.html` — Inter is now the dashboard font
  (400–800), loaded the same way the previous fonts were.
- `frontend/dashboard/src/index.css` — Inter base typography (page
  titles 26–30px/700, KPI values 24–30px/700, tabular numerals for
  money/stats, no oversized uppercase headings, no decorative
  monospace), teal focus rings, `prefers-reduced-motion` respected,
  panels/buttons/inputs/tables restyled to the card system.
- Other dashboard pages keep their layouts and inherit the new theme
  through the shared tokens/components (verified by a full build).

## Shell (`src/components/Layout.tsx`, rewritten)

- Dark navy-teal gradient sidebar (`#062F33 → #041F25`), ~200px on
  desktop, brand block (teal tile + building icon, "StayFlow" +
  "Grand Hotel"), per-route stroke SVG icons for the existing
  role-filtered nav items (no destinations added or removed), active
  item `#0A6665` with a bright-teal `#18B8AC` left indicator, muted
  `#B9CBD2` inactive items with hover/focus states, user block +
  sign-out in the sidebar footer.
- Mobile/tablet: sidebar collapses behind a Menu toggle (closes on
  route change); header keeps the super-admin hotel switcher,
  notification bell (with unread badge) and sign-out.

## Analytics page (`src/pages/Analytics.tsx`, rewritten) + new components

New components under `src/components/analytics/`:

- `format.ts` — INR formatting (incl. compact ₹k/₹L axis labels),
  period labels, guarded percent-change (null on zero baseline).
- `ChartCard.tsx` — View 2 card wrapper, `EmptyState`, `ChartSkeleton`.
- `KpiCard.tsx` — KPI card with pale-tint icon chip, direction-aware
  delta chip + "vs <period>" caption, and `Sparkline` (drawn only from
  the already-fetched series data).
- `RevenueTrendChart.tsx` — hand-rolled SVG (no new dependency):
  teal line + 15% area fill, dashed `#B8CDD3` comparison series with a
  legend toggle, `#E7EDF2` gridlines, ₹ axis, hover tooltip (period,
  revenue, comparison revenue, bookings), latest point emphasized.
- `RoomPopularityChart.tsx` — the existing deterministic packed-bubble
  algorithm, now placing bubbles in the page's chosen sort order so
  sorting visibly reorders; size ∝ √bookings; teal shades for booked,
  soft amber for zero bookings, gray for inactive; in-bubble labels,
  hover/click detail panel, legend.
- `BreakdownCharts.tsx` — `DonutChart` (stroke segments, centre total,
  legend with amounts + %), `VerticalBars` (booking source),
  `HorizontalBars` (department, with share %).
- `RecentActivity.tsx` — icon/timestamp/amount rows for the activity
  feed, with loading, error and empty states.

Page composition (12-col grid, 20px gaps, responsive to 360px):

- Header: "Analytics" + subtitle "Track your hotel performance and
  revenue insights"; filter card with the existing range selector
  (all `RANGE_OPTIONS` + custom from/to dates) and comparison selector
  — now including a client-side "No comparison" option that skips the
  compare query and hides deltas — plus both existing CSV exports
  (unchanged client behaviour, current filters).
- KPI grid (10 cards): Total Revenue, Collected Payments, Pending
  Payments, Refunds, Total Bookings, Occupancy Rate, ADR, RevPAR,
  Avg Booking Value, Rooms Tonight. Deltas come from the existing
  compare endpoint's previous-period overview and are direction-aware
  (rising pending/refunds is shown as unfavourable, never green);
  occupancy delta is in points; a zero baseline renders "No baseline"
  instead of NaN/Infinity. Sparklines only on Total Revenue and Total
  Bookings, from real series points.
- Row 1: Revenue Trend (7 cols) with the group-by control (Hourly /
  Daily / Weekly / Monthly / Yearly) wired to the real `group_by`
  param; Room Popularity (5 cols) with the working sort control,
  most/least summaries, bubbles and the ranked table (horizontal
  scroll contained to the table wrapper).
- Row 2 (4 cards): Revenue by Room Category (donut; spec colours
  `#087E78, #18B8AC, #FBBF24`, then teal-family extensions); Revenue
  by Booking Source (vertical teal bars with revenue+bookings
  tooltips; labels mapped only for sources the backend actually
  stamps — `agent_chat` → "AI concierge", `widget` → "Website
  widget", `dashboard` → "Front desk", `walk_in` → "Walk-in",
  `integration` → "Integration", `unknown` → "Unknown", anything else
  shown prettified, never invented); Revenue by Payment Method
  (donut; when empty it shows exactly "No payment-method data
  available for this period." with a neutral icon — the expected
  state on the live demo, which has zero payment records); Recent
  Activity.
- Below: Revenue by Department (horizontal bars with share),
  restyled; every section keeps loading / error / empty states.
- No figure is hardcoded anywhere; all values come from the API at
  runtime.

## Preserved behaviour

- All analytics sections and metrics, routes, auth, and role gating
  (`analytics.view`: super_admin / hotel_admin / manager /
  accountant) are unchanged. Backend range resolution, series,
  compare, breakdowns, popularity and CSV export logic untouched.
- `by_room` / `by_booking_status` breakdowns remain API-only (they
  were not displayed before and still are not).

## API addition (one endpoint)

- `GET /api/v1/analytics/activity` (`backend/app/api/analytics.py`),
  backed by `recent_activity()` in `backend/app/services/analytics.py`:
  hotel-scoped, `analytics.view`-gated, `limit` 1–50 (default 10).
  Merges real rows only — audit-log `booking.created` /
  `booking.cancelled` events (with fallback creation events for
  bookings that predate audit coverage, de-duplicated), and payment
  events (captured → "Payment received", pending → "Payment pending",
  refunded → "Refund processed"; failed payments are not activity).
  Each event carries kind, title, booking reference, a
  guest · room-type (or method · booking) summary, amount and ISO
  timestamp, newest first.
- Client: `fetchActivity()` + `ActivityEvent` types added to
  `src/lib/analyticsApi.ts`.
- Tests: 2 added to `backend/tests/test_analytics.py` — merged feed
  ordering/kinds/dedup/limit, and hotel scoping + 401 unauthenticated
  + 403 for a role without `analytics.view`.

## Verification (run 2026-10-23)

- Backend: `pytest` (recipe: from `backend/`,
  `DATABASE_URL=sqlite:///./stayflow_e2e.db`) →
  **284 passed, 2 failed, 2 deselected**. The 2 failures are the
  pre-existing SQLite-environment ones
  (`test_hotel_crud_and_validation`,
  `test_ingest_document_creates_chunks_and_embeddings`) — baseline
  was 282 passed with the same 2 failures, so the +2 are the new
  activity tests and there are zero regressions.
- Dashboard: `npm run build` ✓ and `npm run build:demo` ✓ (only the
  pre-existing >500 kB chunk-size advisory).
- Responsive/no-overflow was verified by construction: fluid grids
  (`sm/lg/xl/2xl` breakpoints), SVGs scale via `viewBox`, the only
  fixed-min-width element (ranked table) sits inside an
  `overflow-x-auto` wrapper. Live visual verification at each
  breakpoint still needs a browser pass after deploy.

## Known limits

- The comparison series aligns by position (same behaviour as
  before); ranges with mismatched bucket counts show the comparison
  line only where points exist.
- Recent Activity is hotel-wide latest events (not range-filtered),
  matching the "latest real events" intent.
- The activity feed depends on audit-log coverage for cancellations;
  bookings created before audit logging existed still appear via the
  creation-event fallback (titled "Booking confirmed" / "New booking"
  from their current status).
