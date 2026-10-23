# Analytics Chart Fixes — Report (2026-10-23)

Bug-fix pass over the StayFlow Grand Hotel Analytics charts (Revenue
Trend + Room Popularity), driven by the owner's screen-recording bug
report and three live-reproduction items observed on the production
demo after the 180-booking demo fill. **Nothing was committed,
pushed or deployed** — the parent agent releases.

Context established in Phase 1: there is **no chart library** in this
project — every chart is hand-rolled SVG (`RevenueTrendChart.tsx`,
`RoomPopularityChart.tsx`, `BreakdownCharts.tsx`), fed by
`app/services/analytics.py` through `app/api/analytics.py`. All
reproduction below was done against the isolated demo database
(`backend/analytics_demo.db`, seeded with
`python -m scripts.seed_analytics_demo`: 520 bookings, 485
non-CANCELLED, ₹1,00,64,750 earned revenue) by driving the service
functions directly and comparing against raw SQL aggregates.

---

## 1. Root causes (verified in code or data BEFORE fixing)

### Live repro 1 → Bug 9/10 — popularity totals silently truncated (BACKEND BUG, confirmed)
`popularity_series` capped the bucket-start list at 366 entries
(payload safety) and then computed the `room_types` **totals by
summing those capped buckets**. On any range wider than the cap
(day-grouped "All time" ≈ 760 days) every booking past bucket 366
vanished from the totals, the Most/Least summaries and the
performance table.
*Evidence (demo DB, range=all, group_by=day): buckets returned =
366 (2025-01-03 → 2026-01-03); totals = 226 bookings / ₹46,48,350 vs
SQL ground truth 485 / ₹1,00,64,750 and vs the popularity endpoint's
485 / ₹1,00,64,750. Exactly the owner's live symptom (78 of 168).*
Month/year groupings stayed under the cap, which is why they matched.

### Live repro 2 → Bug 10 — "all" range zeroes every denominator (BACKEND BUG, confirmed)
For the open-ended `all` range, `resolve_range` returns (None, None),
`_days()` returns 0, and `kpi_overview` therefore computed
available room-nights = rooms × 0 = 0 → occupancy 0%, RevPAR ₹0,
average daily revenue ₹0, period_days 0 — while earned revenue and
occupied nights were real.
*Evidence (demo DB): revenue ₹1,00,64,750, occupied 1,405 nights,
available 0, occupancy 0.0, revpar "0". The same zero-denominator
flowed into `room_popularity` and `popularity_series` room-type
occupancy/available figures.*

### Live repro 3 → Bug 7 — four-month trend served stale values (FRONTEND, confirmed mechanism; API exonerated)
The series API returns correct per-month data (verified on the demo
DB — Jul 2026 ₹2,86,650 · Aug ₹3,33,700 · Sep ₹3,38,050 · Oct
₹6,61,800, each exactly matching SQL by check-in month). The chart's
month windows for range=all are also derived correctly (month of
today + 3 preceding = Jul–Oct 2026, as displayed). The values were
stale because the four month queries were keyed **only** by the
month's custom range + groupBy: different page ranges ending in the
same month (This month → This year → All time) produce identical
windows and identical keys, so no new fetch was ever keyed, and the
app-wide React Query config (`staleTime: 30_000`,
`refetchOnWindowFocus: false` in `src/lib/queries.ts`) kept serving
the pre-fill response in-session. The owner saw exactly pre-fill
numbers (Oct ₹73,050, Jul–Sep ₹0).

### Bug 1 — "unnatural spikes" (FRONTEND, confirmed numerically)
The trend path used Catmull-Rom → Bézier smoothing, which overshoots
sparse data. Verified with the chart's own math: a segment 0→10 with
next point 100 dips to **−0.64** (negative revenue drawn below the
axis); a segment 90→100 with next point 0 peaks at **105.0** — 5%
ABOVE the real data maximum. Daily hotel revenue is exactly the
adversarial shape (isolated booking days among gaps/zeros), so the
line invented spikes and sub-zero dips. The weekly misalignment
(Bug 3) further distorted the weekly shape.
*Refuted for Bug 1: the backend aggregations themselves — series,
overview, breakdowns and popularity totals were compared against
raw SQL for multiple windows and matched (after the two backend
fixes above); no double-counting, no date-parsing or sorting defect
was found. Revenue-by-check-in vs bookings-by-creation inside one
series bucket is the endpoint's documented definition and was
preserved.*

### Bug 3 — week misalignment in the four-month chart (FRONTEND, confirmed)
`alignMonthPoints` mapped a week bucket to a slot by
`floor((mondayDayOfMonth − 1) / 7)`. API week buckets are keyed by
their Monday, which for the week containing the 1st falls in the
**previous** month: Sep 2026's first bucket is `2026-08-31` → old
index 4 ("Week 5", actually Week 1); Oct 2026's first bucket
`2026-09-28` → index 3, **colliding** with the genuine `2026-10-26`
bucket (also index 3), which overwrote it — revenue silently dropped
from the plot while the month card (summed from raw points) kept it.
Months spanning six Monday-weeks (e.g. Aug 2026) also exceeded the
5 available slots.

### Bug 2/3 — Monthly/Yearly modes collapse to one x (FRONTEND, confirmed)
For group_by month/year each month window yields one point, and the
chart placed **all four series at the same centre x** — a vertical
stack of four dots under the label "Month total". Not a trend in any
reading. (Hourly mode is the documented single-day fallback and was
otherwise sound; Daily mode was sound apart from Bug 1 smoothing.)

### Bug 4 — Room Popularity grows extremely tall (FRONTEND, confirmed by construction)
`RoomPopularityBars` set the SVG style to `width: "100%"` with **no
height** whenever the viewBox width W ≤ 560, so the rendered height
scaled as containerWidth × 300/W. Few-bucket views explode: Month or
Year over a month = 1 bucket → W = 105 → ≈1,830px tall at a 640px
card; Week over a month (5 buckets, W = 325) → ≈590px. Day views
(W > 560) render at exactly 300px — matching the live observation
that All-time + Day looked normal.

### Bug 5 — period controls (hypothesis REFUTED as a data bug)
The Day/Week/Month/Year toggle does re-query with the matching
`group_by`, and the query key includes the period. The visible
failures in those views were the Bug 4 layout explosion, the Bug 9
truncated totals, and the missing all-zero empty state (below) —
not stale or mis-aggregated data.

### Bug 6 — axes/labels (minor, confirmed)
Trend Y ticks were raw-max quartiles (axis did start at 0 — that
part was correct); popularity Y ticks `[0, round(max/2), max]`
duplicate when max = 1 (two gridlines at the same height). Tooltip
clamping to the card already existed and was retained.

### Bug 8 — states (confirmed)
Trend had **no all-empty state** (empty axes + ₹0 cards). Popularity:
the API zero-fills buckets for bounded ranges, so an all-zero range
rendered a field of invisible bars instead of an empty state, and
the fallback message differed from spec. Neither chart offered a
Retry on error. Loading skeletons already preserved card height.

### Bug 9 — consistency (confirmed with nuance)
Summaries, chart and table all derive from the **same**
popularity-series response (no divergent fetches) and sorting copies
the array before sorting (the cache-mutation hypothesis is refuted).
The inconsistency the owner saw was the truncated totals themselves
(Live repro 1). One pre-existing definitional note: the
room-popularity **endpoint** counts bookings by creation date while
popularity-series counts by check-in date; they legitimately differ
on bounded ranges and coincide on range=all (485 = 485 after fix).
The page uses only popularity-series, so the page is internally
consistent; the CSV room export uses the endpoint (unchanged
contract).

### Bug 11 — responsive/performance
Bug 4 was the responsive breaker. The trend SVG (fixed 720×300
viewBox, width 100%) scales proportionally and stays bounded. No
unbounded heights or resize loops were found elsewhere.

---

## 2. Fixes and files changed

### Backend — `backend/app/services/analytics.py`
- **New `_effective_window()`**: fills open range bounds from the
  hotel's own non-cancelled stays (first check-in → later of last
  check-out and tomorrow); bounded ranges pass through unchanged; a
  hotel with no stays keeps open bounds (honest zeros).
- `kpi_overview`, `room_popularity`, `popularity_series` now take
  their denominator days from the effective window (available
  room-nights, occupancy, RevPAR, daily average, period_days).
- `popularity_series` **totals are aggregated from the full stay
  set**, never from the bucket list. The 366-bucket cap now bounds
  only the rendered bucket list and is documented as such in code.
- No accounting definitions changed; no API contract changed.

### Backend tests — `backend/tests/test_analytics.py` (+4 tests)
- `test_popularity_series_totals_cover_full_range_beyond_bucket_cap`
  — stays past bucket 366 are in the totals; totals equal the
  popularity endpoint's for range=all.
- `test_kpi_overview_all_range_computes_real_denominators` —
  available > 0, occupancy > 0, RevPAR > 0, period_days > 0 with
  real revenue present.
- `test_kpi_overview_all_range_empty_hotel_stays_zero` — no data,
  honest zeros, no crash.
- `test_popularity_series_month_buckets_keep_years_distinct` —
  2025-10 and 2026-10 are separate buckets; month and week bucket
  keys chronological; week keys are Mondays.

### Frontend — `src/components/analytics/format.ts`
- `niceAxisMax()` (1/2/2.5/5×10ⁿ ceiling) for readable Y axes.

### Frontend — `src/components/analytics/RevenueTrendChart.tsx`
- `smoothPath` (Catmull-Rom) → **`monotonePath`** (Fritsch–Carlson
  monotone cubic): never leaves a segment's endpoint range, so no
  invented peaks and no sub-zero dips. (First version of the port
  still overshot at local extrema — caught by the property test
  below and fixed with the extremum flat-tangent rule.)
- **Week alignment** anchored on the Monday of the week containing
  the 1st of each month; slots increased 5 → 6. Sep/Oct/Aug-2026
  bucket keys now map to indices [0..4] / [0..4] / [0..5] with no
  collisions or drops.
- **Month/Year totals mode**: one labelled point per month on a
  month-name axis (value label + exact tooltip), instead of four
  dots stacked at one x.
- Y axis scaled to `niceAxisMax` with quartile ticks; hourly chart
  got the same monotone path + nice axis.
- All-four-months-empty → `EmptyState` "No revenue data is available
  for the selected period." (hourly empty message aligned to the
  same wording). Gaps still break the line; per-month empty series
  keep their ₹0 legend card and draw no line.

### Frontend — `src/components/analytics/RoomPopularityChart.tsx`
- **Bounded 1:1 geometry**: the SVG renders at exactly W×H px
  (H = 300) with `minWidth: W`; slots widen to a 520px minimum plot
  width on few-bucket views (bar width cap raised to 28px there);
  dense views keep scrolling horizontally inside the card. Height
  can no longer depend on bucket count or container width.
- All-zero responses (zero-filled buckets) now show the spec empty
  state: "No room bookings are available for the selected period."
- Y ticks de-duplicated.

### Frontend — `src/pages/Analytics.tsx`
- Month query keys now carry the selected range identity (range key
  + custom from/to) under a dedicated `series-month` namespace, with
  `staleTime: 0` — a range switch always refetches current data
  (Live repro 3).
- `alignMonthPoints` call passes the month key (new signature).
- Error states for the trend (both modes) and popularity now include
  a working **Retry** button wired to `refetch()`.

---

## 3. Validation

**Backend suite** (recipe: `DATABASE_URL=sqlite:///./stayflow_e2e.db`,
pytest from `backend/`): **303 passed / 2 failed / 2 deselected** —
the 2 failures are exactly the pre-existing SQLite-env pair
(`test_hotel_crud_and_validation`,
`test_ingest_document_creates_chunks_and_embeddings`); baseline was
299, so +4 new tests, zero regressions. **Ruff** (`app tests
scripts`): all checks passed. **Dashboard**: `npm run build` ✓ and
`npm run build:demo` ✓ (only the pre-existing >500 kB chunk warning).

**Monotone property test** (Node, algorithm ported verbatim):
115,464 curve samples across adversarial shapes ([0,10,100],
[90,100,0], sparse live-like daily revenue) and 300 random sparse
series → **0 samples outside their segment's endpoint range**. The
old Catmull-Rom on the same shapes: −0.64 dip and +5.0% overshoot.

**Verification table — service output vs raw SQL (demo DB, 520
bookings, post-fix):**

| Combo | SQL ground truth | API output | Verdict |
|---|---|---|---|
| A. range=all × popularity-series, group_by=day | 485 bookings · ₹1,00,64,750 | totals 485 · ₹1,00,64,750 (buckets rendered: 366, capped) | MATCH |
| B. range=year 2026 × popularity-series, group_by=month | per-month revenue Jan–Dec 2026 (e.g. Oct ₹6,61,800, Dec ₹7,50,550); 261 bookings | identical for all 12 months; totals 261 | MATCH |
| C. Four-month trend inputs: custom Jul/Aug/Sep/Oct 2026 × series, group_by=day | ₹2,86,650 / ₹3,33,700 / ₹3,38,050 / ₹6,61,800 | identical | MATCH |
| D. overview, range=all | 1,405 occupied nights; 41 rooms × 708-day activity window = 29,028 available | available 29,028 · occupancy 4.84% · RevPAR ₹346.73 · period_days 708 | MATCH |
| Pre-fix reference (same DB) | 485 · ₹1,00,64,750; available — | totals 226 · ₹46,48,350; available 0, occupancy 0%, RevPAR ₹0 | was BROKEN, now fixed |

**Pre-existing behaviour deliberately preserved:** accounting
definitions (revenue earned by check-in, non-CANCELLED; bookings in
series/KPI counted by creation date; payments separate), all API
contracts, Analytics-scoped styling only (no global theme/token
changes), CSV exports, role gating (popularity-series hotel-scope
403/401/422 test still passes).

---

## 4. Not reproduced / known limits / open items

- The screen recording itself was not available to this agent; root
  causes were verified in code and data instead of by re-watching
  it. Every claimed root cause above has a code location or a
  numeric/data proof.
- The live Neon dataset (184 bookings) cannot be queried from here;
  the local demo DB exhibits the identical three live defects and
  now matches SQL truth after the fixes. Production picks the fixes
  up on the next deploy (none was made in this task).
- The popularity **bucket list** is still capped at 366 rendered
  buckets (payload safety): on a day-grouped range wider than ~1
  year the chart displays the first 366 buckets, while totals,
  summaries and the table cover the full range. Paging or
  downsampling the bucket list is a possible future step; it is no
  longer a silent data loss.
- Responsive behaviour at the seven spec widths was fixed by
  construction (fixed 300px plot height, 1:1 SVG sizing, in-card
  horizontal scroll, adaptive slot widths) but was **not**
  browser-verified in this environment — no live-browser pass was
  run for this task.
- The trend month cards' booking counts sum the series endpoint's
  creation-date booking counts (its documented semantics) while its
  revenue is check-in based — unchanged pre-existing definition.
- `backend/analytics_demo.db` (the seeded reproduction database)
  remains as a local artifact; it is not application code.
