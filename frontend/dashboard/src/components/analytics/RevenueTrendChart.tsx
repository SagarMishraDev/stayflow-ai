import { useMemo, useState } from "react";
import type { SeriesPoint } from "../../lib/analyticsApi";
import { formatPct, inr, inrShort, num, pctChange, periodLabel } from "./format";

/** Revenue trend — FOUR MONTHS IN ONE CHART (hand-rolled SVG; the
 * project has no chart dependency).
 *
 * The page fetches each displayed month separately through the
 * existing series API (custom range = that calendar month) and this
 * component aligns the four series on a shared bucket axis:
 *  - group_by "day"   → day-of-month axis (1–31)
 *  - group_by "week"  → week-of-month index (Week 1–5)
 *  - group_by "month" / "year" → one aggregate point per month
 * A bucket the API did not return for a month is a GAP (null): the
 * line breaks there and the tooltip says "No data" — missing data is
 * never silently plotted as ₹0. A returned bucket with revenue 0 is a
 * genuine zero and IS plotted.
 *
 * Series colours are fixed by the design spec and assigned
 * chronologically: teal, blue, purple, orange (MONTH_SERIES_COLORS).
 * The month summary cards above the chart double as the legend
 * (colour, month name, total, growth vs the previous displayed month
 * — only when that baseline is non-zero).
 */

const W = 720;
const H = 300;
const PAD = { l: 58, r: 14, t: 16, b: 30 };

export interface AlignedPoint {
  /** Raw bucket key from the series API ("2026-10-05", "2026-10", …). */
  period: string;
  revenue: number;
  bookings: number;
}

export interface MonthSeries {
  /** Calendar month key "YYYY-MM". */
  key: string;
  label: string;
  color: string;
  total: number;
  bookings: number;
  points: (AlignedPoint | null)[];
}

/** Number of aligned buckets for a grouping. */
export function bucketCount(groupBy: string): number {
  if (groupBy === "day") return 31;
  if (groupBy === "week") return 5;
  return 1; // month / year: one aggregate point per month window
}

/** Align one month's API points onto the shared bucket axis. */
export function alignMonthPoints(
  points: SeriesPoint[],
  groupBy: string,
): (AlignedPoint | null)[] {
  const out: (AlignedPoint | null)[] = Array.from(
    { length: bucketCount(groupBy) },
    () => null,
  );
  for (const p of points) {
    let idx = 0;
    if (groupBy === "day" || groupBy === "week") {
      const day = Number(p.period.slice(8, 10));
      if (!Number.isFinite(day)) continue;
      idx = groupBy === "day" ? day - 1 : Math.floor((day - 1) / 7);
    }
    if (idx >= 0 && idx < out.length) {
      out[idx] = { period: p.period, revenue: num(p.revenue), bookings: p.bookings };
    }
  }
  return out;
}

export function bucketAxisLabel(groupBy: string, idx: number): string {
  if (groupBy === "day") return `Day ${idx + 1}`;
  if (groupBy === "week") return `Week ${idx + 1}`;
  return "Month total";
}

/** Gentle Catmull-Rom → Bézier smoothing; restrained, keeps every
 * data point on the curve (no invented peaks). */
function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return pts.length ? `M${pts[0][0]},${pts[0][1]}` : "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0]},${p2[1]}`;
  }
  return d;
}

/** Split aligned points into contiguous non-null runs so gaps break
 * the line instead of being bridged or zero-filled. */
function runs(points: (AlignedPoint | null)[]): { idx: number; point: AlignedPoint }[][] {
  const out: { idx: number; point: AlignedPoint }[][] = [];
  let current: { idx: number; point: AlignedPoint }[] = [];
  points.forEach((point, idx) => {
    if (point) {
      current.push({ idx, point });
    } else if (current.length) {
      out.push(current);
      current = [];
    }
  });
  if (current.length) out.push(current);
  return out;
}

export function RevenueTrendChart({
  months,
  groupBy,
}: {
  months: MonthSeries[];
  groupBy: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = bucketCount(groupBy);
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const max = Math.max(
    1,
    ...months.flatMap((m) => m.points.map((p) => p?.revenue ?? 0)),
  );
  const x = (i: number) => (n > 1 ? PAD.l + (i / (n - 1)) * innerW : PAD.l + innerW / 2);
  const y = (v: number) => PAD.t + innerH - (v / max) * innerH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => max * f);
  const labelEvery = groupBy === "day" ? 5 : 1;

  const monthRuns = useMemo(
    () => months.map((m) => runs(m.points)),
    [months],
  );

  const grandTotal = months.reduce((s, m) => s + m.total, 0);

  return (
    <div>
      {/* Month summary cards = legend (colour, month, total, growth). */}
      <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {months.map((m, i) => {
          const growth =
            i > 0 ? pctChange(m.total, months[i - 1].total) : null;
          return (
            <div key={m.key} className="rounded-xl bg-[#F8FAFC] px-3 py-2.5">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#52677D]">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ background: m.color }}
                />
                {m.label}
              </p>
              <p className="mt-1 text-[17px] font-bold leading-none tabular-nums text-[#102A43]">
                {inr(m.total)}
              </p>
              <p className="mt-1 text-[11px] tabular-nums text-[#8293A5]">
                {i === 0
                  ? `${m.bookings} bookings`
                  : growth === null
                    ? "No baseline"
                    : `${formatPct(growth)} vs ${months[i - 1].label.split(" ")[0]}`}
              </p>
            </div>
          );
        })}
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={`Revenue trend across four months: ${months
            .map((m) => `${m.label} ${inr(m.total)}`)
            .join(", ")}. Four-month total ${inr(grandTotal)}.`}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const mx = ((e.clientX - rect.left) / rect.width) * W;
            if (n > 1) {
              const idx = Math.round(((mx - PAD.l) / innerW) * (n - 1));
              setHover(Math.max(0, Math.min(n - 1, idx)));
            } else {
              setHover(0);
            }
          }}
        >
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#E7EDF2" strokeWidth={1} />
              <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + innerH} stroke="#E7EDF2" strokeWidth={1} />
              <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="fill-[#8293A5] text-[11px] tabular-nums">
                {inrShort(t)}
              </text>
            </g>
          ))}

          {months.map((m, mi) =>
            monthRuns[mi].map((run, ri) => {
              const pts = run.map(
                ({ idx, point }): [number, number] => [x(idx), y(point.revenue)],
              );
              return (
                <g key={`${m.key}-${ri}`}>
                  {pts.length > 1 ? (
                    <>
                      <path
                        d={`${smoothPath(pts)}L${pts[pts.length - 1][0]},${PAD.t + innerH}L${pts[0][0]},${PAD.t + innerH}Z`}
                        fill={m.color}
                        fillOpacity={0.1}
                        stroke="none"
                      />
                      <path
                        d={smoothPath(pts)}
                        fill="none"
                        stroke={m.color}
                        strokeWidth={2.5}
                        strokeLinejoin="round"
                      />
                    </>
                  ) : null}
                  {pts.map(([cx, cy], pi) => (
                    <circle key={pi} cx={cx} cy={cy} r={3.2} fill="#fff" stroke={m.color} strokeWidth={2}>
                      <title>{`${m.label} · ${periodLabel(run[pi].point.period, "full")}: ${inr(run[pi].point.revenue)} · ${run[pi].point.bookings} bookings`}</title>
                    </circle>
                  ))}
                </g>
              );
            }),
          )}

          {hover !== null ? (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.t}
              y2={PAD.t + innerH}
              stroke="#8293A5"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          ) : null}

          {Array.from({ length: n }, (_, i) =>
            i % labelEvery === 0 || i === n - 1 ? (
              <text
                key={i}
                x={x(i)}
                y={H - 8}
                textAnchor="middle"
                className="fill-[#8293A5] text-[11px]"
              >
                {groupBy === "day" ? String(i + 1) : bucketAxisLabel(groupBy, i)}
              </text>
            ) : null,
          )}
        </svg>

        {hover !== null ? (
          <div
            role="status"
            className="pointer-events-none absolute top-0 z-10 min-w-[190px] -translate-x-1/2 rounded-[10px] border border-[#E3EAF0] bg-white px-3 py-2 text-xs shadow-[0_4px_8px_rgba(16,42,67,0.06),0_12px_28px_rgba(16,42,67,0.10)]"
            style={{
              left: `${Math.min(88, Math.max(12, (x(hover) / W) * 100))}%`,
            }}
          >
            <p className="font-semibold text-[#102A43]">{bucketAxisLabel(groupBy, hover)}</p>
            <ul className="mt-1 space-y-1">
              {months.map((m) => {
                const point = m.points[hover];
                return (
                  <li key={m.key} className="flex items-baseline gap-1.5 tabular-nums text-[#52677D]">
                    <span
                      aria-hidden
                      className="h-2 w-2 shrink-0 translate-y-[-1px] rounded-full"
                      style={{ background: m.color }}
                    />
                    <span className="font-medium text-[#102A43]">{m.label}</span>
                    {point ? (
                      <span>
                        {inr(point.revenue)} · {point.bookings} bookings
                      </span>
                    ) : (
                      <span className="text-[#8293A5]">No data</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>
      <p className="mt-1 text-[11px] text-[#8293A5]">
        {groupBy === "day"
          ? "Aligned by day of month. Days a month does not have (or with no recorded activity) are gaps, not zeros."
          : groupBy === "week"
            ? "Aligned by week within the month (weeks start Monday, matching the API buckets)."
            : "Each month is aggregated to a single point."}
      </p>
    </div>
  );
}

/** Hourly fallback: the series API's hourly grouping always describes
 * TODAY's hours, so a four-month overlay would plot the same day four
 * times. Instead the card shows the single hourly series honestly. */
export function HourlyTrendChart({ points }: { points: SeriesPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = points.length;
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const max = Math.max(1, ...points.map((p) => num(p.revenue)));
  const x = (i: number) => (n > 1 ? PAD.l + (i / (n - 1)) * innerW : PAD.l + innerW / 2);
  const y = (v: number) => PAD.t + innerH - (v / max) * innerH;
  const ticks = [0, 0.5, 1].map((f) => max * f);
  const pts = points.map((p, i): [number, number] => [x(i), y(num(p.revenue))]);
  const hoverPoint = hover !== null ? points[hover] : undefined;

  if (!points.length) {
    return <p className="py-10 text-center text-sm text-[#8293A5]">No revenue in this period yet.</p>;
  }
  return (
    <div>
      <p className="mb-2 text-xs text-[#52677D]">
        Hourly grouping shows <strong>today's</strong> hours (the API's hourly buckets always
        describe today) — the four-month comparison applies to Daily grouping and coarser.
      </p>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label="Hourly revenue for today"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const mx = ((e.clientX - rect.left) / rect.width) * W;
            const idx = Math.round(((mx - PAD.l) / innerW) * (n - 1));
            setHover(Math.max(0, Math.min(n - 1, idx)));
          }}
        >
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#E7EDF2" strokeWidth={1} />
              <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="fill-[#8293A5] text-[11px] tabular-nums">
                {inrShort(t)}
              </text>
            </g>
          ))}
          {pts.length > 1 ? (
            <>
              <path
                d={`${smoothPath(pts)}L${pts[pts.length - 1][0]},${PAD.t + innerH}L${pts[0][0]},${PAD.t + innerH}Z`}
                fill="#0F9D94"
                fillOpacity={0.12}
                stroke="none"
              />
              <path d={smoothPath(pts)} fill="none" stroke="#0F9D94" strokeWidth={2.5} strokeLinejoin="round" />
            </>
          ) : null}
          {pts.map(([cx, cy], i) => (
            <circle key={i} cx={cx} cy={cy} r={3} fill="#fff" stroke="#0F9D94" strokeWidth={2}>
              <title>{`${periodLabel(points[i].period, "full")}: ${inr(points[i].revenue)} · ${points[i].bookings} bookings`}</title>
            </circle>
          ))}
          {points.map((p, i) =>
            i % 3 === 0 ? (
              <text key={p.period} x={x(i)} y={H - 8} textAnchor="middle" className="fill-[#8293A5] text-[11px]">
                {periodLabel(p.period)}
              </text>
            ) : null,
          )}
        </svg>
        {hoverPoint && hover !== null ? (
          <div
            role="status"
            className="pointer-events-none absolute top-0 z-10 min-w-[150px] -translate-x-1/2 rounded-[10px] border border-[#E3EAF0] bg-white px-3 py-2 text-xs shadow-[0_4px_8px_rgba(16,42,67,0.06),0_12px_28px_rgba(16,42,67,0.10)]"
            style={{ left: `${Math.min(88, Math.max(12, (x(hover) / W) * 100))}%` }}
          >
            <p className="font-semibold text-[#102A43]">{periodLabel(hoverPoint.period, "full")}</p>
            <p className="mt-1 tabular-nums text-[#52677D]">
              Revenue <span className="font-semibold text-[#102A43]">{inr(hoverPoint.revenue)}</span>
            </p>
            <p className="tabular-nums text-[#52677D]">
              Bookings <span className="font-semibold text-[#102A43]">{hoverPoint.bookings}</span>
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
