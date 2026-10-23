import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/DataStates";
import {
  RANGE_OPTIONS,
  downloadCsv,
  fetchBreakdowns,
  fetchCompare,
  fetchOverview,
  fetchPopularity,
  fetchSeries,
  type PopularityRow,
  type RangeParams,
  type SeriesPoint,
} from "../lib/analyticsApi";

/** HMS Phase 4 — analytics dashboard. Every number comes from the
 * backend aggregation APIs (real bookings/payments); charts are
 * hand-rolled SVG (no chart dependency in this project). */

function inr(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "₹0";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-card">
      <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">{label}</p>
      <p className="mt-1 font-mono text-3xl font-semibold tabular-nums text-ink">{value}</p>
      {sub ? <p className="mt-1 text-sm text-ink/60">{sub}</p> : null}
    </div>
  );
}

/** Deterministic circle packing: largest first, golden-angle spiral
 * scan with collision checks — no overlaps, stable layout. */
function packBubbles(
  rows: PopularityRow[],
  width: number,
  height: number,
): { row: PopularityRow; x: number; y: number; r: number }[] {
  const maxBookings = Math.max(1, ...rows.map((r) => r.bookings));
  const sorted = [...rows].sort((a, b) => b.bookings - a.bookings);
  const placed: { row: PopularityRow; x: number; y: number; r: number }[] = [];
  for (const row of sorted) {
    const r =
      row.bookings > 0 ? 16 + 40 * Math.sqrt(row.bookings / maxBookings) : 13;
    let done = false;
    for (let t = 0; t < 4000 && !done; t += 1) {
      const angle = t * 2.399963; // golden angle
      const dist = 4 * Math.sqrt(t) * 6;
      const x = width / 2 + dist * Math.cos(angle);
      const y = height / 2 + dist * Math.sin(angle) * 0.78;
      if (x - r < 4 || x + r > width - 4 || y - r < 4 || y + r > height - 4) continue;
      const collides = placed.some(
        (p) => Math.hypot(p.x - x, p.y - y) < p.r + r + 3,
      );
      if (!collides) {
        placed.push({ row, x, y, r });
        done = true;
      }
    }
    if (!done) placed.push({ row, x: r + 6, y: r + 6, r });
  }
  return placed;
}

function BubbleChart({ rows }: { rows: PopularityRow[] }) {
  const [selected, setSelected] = useState<PopularityRow | null>(null);
  const width = 720;
  const height = 380;
  const bubbles = useMemo(() => packBubbles(rows, width, height), [rows]);
  if (!rows.length) {
    return <p className="p-6 text-sm text-ink/60">No room types configured yet.</p>;
  }
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label="Room popularity bubble chart — circle size is proportional to booking count"
      >
        {bubbles.map(({ row, x, y, r }) => (
          <g
            key={row.room_id}
            onClick={() => setSelected(row)}
            className="cursor-pointer"
          >
            <title>
              {`${row.room_type}: ${row.bookings} bookings, ${inr(row.revenue)} revenue, ${row.occupancy_rate}% occupancy`}
            </title>
            <circle
              cx={x}
              cy={y}
              r={r}
              className={
                !row.is_active
                  ? "fill-ink/20 stroke-ink/30"
                  : row.bookings > 0
                    ? "fill-teal/70 stroke-deep-teal"
                    : "fill-sun/50 stroke-sun"
              }
              strokeWidth={selected?.room_id === row.room_id ? 3 : 1}
            />
            <text
              x={x}
              y={y - 2}
              textAnchor="middle"
              className="fill-ink text-[11px] font-semibold"
            >
              {row.room_type}
            </text>
            <text
              x={x}
              y={y + 12}
              textAnchor="middle"
              className="fill-ink/70 text-[11px]"
            >
              {row.bookings} bookings
            </text>
          </g>
        ))}
      </svg>
      <div className="flex flex-wrap gap-4 px-2 pb-2 text-xs text-ink/60">
        <span>● Sized by booking count</span>
        <span>● Teal = has bookings</span>
        <span>● Yellow = zero bookings</span>
        <span>● Grey = inactive room type</span>
      </div>
      {selected ? (
        <div className="mx-2 mb-2 rounded-xl bg-mist p-4 text-sm">
          <strong>{selected.room_type}</strong> — {selected.bookings} bookings ·{" "}
          {inr(selected.revenue)} revenue · {selected.occupancy_rate}% occupancy ·{" "}
          {selected.occupied_room_nights}/{selected.available_room_nights} room-nights ·{" "}
          {selected.is_active ? "active" : "inactive"}
        </div>
      ) : null}
    </div>
  );
}

function SeriesChart({
  current,
  previous,
}: {
  current: SeriesPoint[];
  previous?: SeriesPoint[];
}) {
  const width = 720;
  const height = 240;
  const pad = 34;
  const values = [
    ...current.map((p) => parseFloat(p.revenue)),
    ...(previous ?? []).map((p) => parseFloat(p.revenue)),
  ];
  const max = Math.max(1, ...values);
  const n = Math.max(current.length, previous?.length ?? 0);
  const stepX = n > 1 ? (width - pad * 2) / (n - 1) : 0;
  const xy = (series: SeriesPoint[]) =>
    series.map((p, i) => [
      pad + i * stepX,
      height - pad - (parseFloat(p.revenue) / max) * (height - pad * 2),
    ]);
  const line = (series: SeriesPoint[]) =>
    xy(series)
      .map(([x, y]) => `${x},${y}`)
      .join(" ");
  const area = (series: SeriesPoint[]) =>
    `${pad},${height - pad} ${line(series)} ${pad + (series.length - 1) * stepX},${height - pad}`;
  if (!current.length) {
    return <p className="p-6 text-sm text-ink/60">No revenue in this period yet.</p>;
  }
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      aria-label="Revenue trend chart"
    >
      <polygon points={area(current)} className="fill-teal/25" />
      <polyline points={line(current)} fill="none" className="stroke-deep-teal" strokeWidth={2.5} />
      {previous && previous.length ? (
        <polyline
          points={line(previous)}
          fill="none"
          className="stroke-coral"
          strokeWidth={2}
          strokeDasharray="6 4"
        />
      ) : null}
      {current.map((p, i) => {
        const [x, y] = xy(current)[i];
        return (
          <g key={p.period}>
            <circle cx={x} cy={y} r={3.5} className="fill-deep-teal">
              <title>{`${p.period}: ${inr(p.revenue)} · ${p.bookings} bookings`}</title>
            </circle>
            {i % Math.ceil(current.length / 8 || 1) === 0 ? (
              <text x={x} y={height - 8} textAnchor="middle" className="fill-ink/50 text-[10px]">
                {p.period.slice(5)}
              </text>
            ) : null}
          </g>
        );
      })}
      <text x={pad} y={16} className="fill-ink/50 text-[11px]">
        max {inr(max)}
      </text>
    </svg>
  );
}

function BreakdownBars({
  title,
  rows,
}: {
  title: string;
  rows: { key: string; revenue: string; bookings: number }[];
}) {
  const max = Math.max(1, ...rows.map((r) => parseFloat(r.revenue)));
  return (
    <div className="rounded-2xl bg-white p-5 shadow-card">
      <h3 className="font-display text-lg uppercase tracking-wide">{title}</h3>
      {!rows.length ? (
        <p className="mt-3 text-sm text-ink/60">No data in this period.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {rows.map((row) => (
            <li key={row.key}>
              <div className="flex justify-between text-sm">
                <span className="font-medium">{row.key}</span>
                <span className="font-mono tabular-nums">
                  {inr(row.revenue)} · {row.bookings}
                </span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-mist">
                <div
                  className="h-2 rounded-full bg-teal"
                  style={{ width: `${(parseFloat(row.revenue) / max) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Analytics() {
  const { hotelId } = useAuth();
  const [range, setRange] = useState("month");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [groupBy, setGroupBy] = useState("day");
  const [compareKey, setCompareKey] = useState("last_month");
  const [sortBy, setSortBy] = useState<"bookings" | "revenue" | "occupancy">("bookings");

  const rangeParams: RangeParams = {
    range,
    start: customStart || undefined,
    end: customEnd || undefined,
  };
  const ready =
    Boolean(hotelId) && (range !== "custom" || Boolean(customStart && customEnd));

  const overviewQ = useQuery({
    queryKey: ["analytics", "overview", hotelId, rangeParams],
    queryFn: () => fetchOverview(hotelId!, rangeParams),
    enabled: ready,
  });
  const seriesQ = useQuery({
    queryKey: ["analytics", "series", hotelId, rangeParams, groupBy],
    queryFn: () => fetchSeries(hotelId!, rangeParams, groupBy),
    enabled: ready,
  });
  const compareQ = useQuery({
    queryKey: ["analytics", "compare", hotelId, rangeParams, compareKey],
    queryFn: () => fetchCompare(hotelId!, rangeParams, { range: compareKey }),
    enabled: ready,
  });
  const breakdownsQ = useQuery({
    queryKey: ["analytics", "breakdowns", hotelId, rangeParams],
    queryFn: () => fetchBreakdowns(hotelId!, rangeParams),
    enabled: ready,
  });
  const popularityQ = useQuery({
    queryKey: ["analytics", "popularity", hotelId, rangeParams],
    queryFn: () => fetchPopularity(hotelId!, rangeParams),
    enabled: ready,
  });

  const kpi = overviewQ.data;
  const popularity = popularityQ.data;
  const sortedRooms = useMemo(() => {
    const rows = [...(popularity?.rooms ?? [])];
    if (sortBy === "revenue")
      rows.sort((a, b) => parseFloat(b.revenue) - parseFloat(a.revenue));
    else if (sortBy === "occupancy") rows.sort((a, b) => b.occupancy_rate - a.occupancy_rate);
    else rows.sort((a, b) => b.bookings - a.bookings);
    return rows;
  }, [popularity, sortBy]);

  const selectCls =
    "rounded-full border border-ink/15 bg-white px-3 py-2 text-sm font-medium";
  const delta = compareQ.data?.deltas;

  return (
    <div>
      <PageHeader
        title="Analytics"
        description="Revenue, occupancy and room performance — computed live from bookings and payments."
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <select
          aria-label="Date range"
          className={selectCls}
          value={range}
          onChange={(e) => setRange(e.target.value)}
        >
          {RANGE_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
        {range === "custom" ? (
          <>
            <input
              type="date"
              aria-label="Start date"
              className={selectCls}
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
            />
            <input
              type="date"
              aria-label="End date"
              className={selectCls}
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
            />
          </>
        ) : null}
        <select
          aria-label="Group by"
          className={selectCls}
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value)}
        >
          <option value="hour">By hour (today)</option>
          <option value="day">By day</option>
          <option value="week">By week</option>
          <option value="month">By month</option>
          <option value="year">By year</option>
        </select>
        <label className="flex items-center gap-2 text-sm">
          Compare with
          <select
            aria-label="Comparison period"
            className={selectCls}
            value={compareKey}
            onChange={(e) => setCompareKey(e.target.value)}
          >
            {RANGE_OPTIONS.filter((o) => o.key !== "custom").map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="rounded-full bg-deep-teal px-4 py-2 text-sm font-semibold text-white"
          onClick={() => hotelId && downloadCsv(hotelId, rangeParams, "series")}
        >
          Export revenue CSV
        </button>
        <button
          type="button"
          className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white"
          onClick={() => hotelId && downloadCsv(hotelId, rangeParams, "room-popularity")}
        >
          Export rooms CSV
        </button>
      </div>

      {overviewQ.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse rounded-2xl bg-ink/5" />
      ) : overviewQ.isError ? (
        <p className="rounded-2xl bg-coral/15 p-5 text-sm">
          Analytics could not be loaded. Check your connection and try again.
        </p>
      ) : kpi ? (
        <>
          <section aria-label="Key metrics" className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard label="Total revenue" value={inr(kpi.total_revenue)} sub={`${kpi.period_days} days`} />
            <KpiCard label="Collected" value={inr(kpi.revenue_collected)} sub="captured payments" />
            <KpiCard label="Pending payments" value={inr(kpi.pending_payments)} sub="earned, not yet collected" />
            <KpiCard label="Refunds" value={inr(kpi.refunds)} />
            <KpiCard label="Bookings" value={String(kpi.total_bookings)} sub={`${kpi.confirmed_bookings} confirmed · ${kpi.cancelled_bookings} cancelled`} />
            <KpiCard label="Occupancy" value={`${kpi.occupancy_rate}%`} sub={`${kpi.occupied_room_nights} of ${kpi.available_room_nights} room-nights`} />
            <KpiCard label="ADR" value={inr(kpi.adr)} sub={`RevPAR ${inr(kpi.revpar)}`} />
            <KpiCard label="Avg booking value" value={inr(kpi.average_booking_value)} sub={`Daily avg ${inr(kpi.average_daily_revenue)}`} />
            <KpiCard
              label="Rooms tonight"
              value={`${kpi.rooms_occupied_tonight} occupied`}
              sub={`${kpi.rooms_available_tonight} available`}
            />
          </section>

          <section aria-label="Revenue trend" className="mb-6 rounded-2xl bg-white p-5 shadow-card">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-xl uppercase tracking-wide">Revenue trend</h2>
              {delta ? (
                <p className="text-sm text-ink/60">
                  vs comparison: {inr(delta.revenue_diff)} (
                  {delta.revenue_pct === null ? "no baseline" : `${delta.revenue_pct}%`}) · bookings{" "}
                  {delta.bookings_diff >= 0 ? "+" : ""}
                  {delta.bookings_diff} · occupancy {delta.occupancy_diff_points >= 0 ? "+" : ""}
                  {delta.occupancy_diff_points} pts
                </p>
              ) : null}
            </div>
            {seriesQ.isLoading ? (
              <div aria-busy="true" className="h-40 animate-pulse rounded-xl bg-ink/5" />
            ) : (
              <SeriesChart
                current={seriesQ.data ?? []}
                previous={compareQ.data?.series.previous}
              />
            )}
            <p className="text-xs text-ink/50">
              Teal = selected period · dashed coral = comparison period (aligned by position).
            </p>
          </section>

          <section aria-label="Room popularity" className="mb-6 rounded-2xl bg-white p-5 shadow-card">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-xl uppercase tracking-wide">
                Room popularity — booking bubbles
              </h2>
              <label className="flex items-center gap-2 text-sm">
                Sort by
                <select
                  aria-label="Sort rooms"
                  className={selectCls}
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                >
                  <option value="bookings">Bookings</option>
                  <option value="revenue">Revenue</option>
                  <option value="occupancy">Occupancy</option>
                </select>
              </label>
            </div>
            {popularityQ.isLoading ? (
              <div aria-busy="true" className="h-40 animate-pulse rounded-xl bg-ink/5" />
            ) : popularity ? (
              <>
                <div className="mb-4 grid gap-4 md:grid-cols-2">
                  <div className="rounded-xl bg-mist p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">
                      Most booked
                    </p>
                    {popularity.most_booked.map((r) => (
                      <p key={r.room_id} className="mt-1 text-sm">
                        <strong>{r.room_type}</strong> — {r.bookings} bookings · {inr(r.revenue)} ·{" "}
                        {r.occupancy_rate}% occupancy
                      </p>
                    ))}
                  </div>
                  <div className="rounded-xl bg-sun/20 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">
                      Least booked
                    </p>
                    {popularity.least_booked.map((r) => (
                      <p key={r.room_id} className="mt-1 text-sm">
                        <strong>{r.room_type}</strong> — {r.bookings} bookings · {inr(r.revenue)} ·{" "}
                        {r.occupancy_rate}% occupancy
                      </p>
                    ))}
                  </div>
                </div>
                <BubbleChart rows={sortedRooms} />
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-ink/10 text-ink/50">
                        <th className="py-2 pr-3">Room type</th>
                        <th className="py-2 pr-3">Bookings</th>
                        <th className="py-2 pr-3">Revenue</th>
                        <th className="py-2 pr-3">Occupancy</th>
                        <th className="py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedRooms.map((r) => (
                        <tr key={r.room_id} className="border-b border-ink/5">
                          <td className="py-2 pr-3 font-medium">{r.room_type}</td>
                          <td className="py-2 pr-3 font-mono tabular-nums">{r.bookings}</td>
                          <td className="py-2 pr-3 font-mono tabular-nums">{inr(r.revenue)}</td>
                          <td className="py-2 pr-3 font-mono tabular-nums">{r.occupancy_rate}%</td>
                          <td className="py-2">{r.is_active ? "Active" : "Inactive"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}
          </section>

          {breakdownsQ.data ? (
            <section aria-label="Revenue breakdowns" className="grid gap-4 md:grid-cols-2">
              <BreakdownBars title="Revenue by room category" rows={breakdownsQ.data.by_room_category} />
              <BreakdownBars title="Revenue by booking source" rows={breakdownsQ.data.by_booking_source} />
              <BreakdownBars title="Collected by payment method" rows={breakdownsQ.data.by_payment_method} />
              <BreakdownBars title="Revenue by department" rows={breakdownsQ.data.by_department} />
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
