import { useMemo, useState } from "react";
import type { SeriesPoint } from "../../lib/analyticsApi";
import { inr, inrShort, num, periodLabel } from "./format";

/** Revenue trend — hand-rolled SVG (no chart dependency in this
 * project). Teal current series with a soft area fill, dashed
 * comparison series aligned by position, gridlines, ₹ axis, and an
 * HTML hover tooltip (date · revenue · comparison · bookings). */

const W = 720;
const H = 300;
const PAD = { l: 58, r: 14, t: 16, b: 30 };

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

export function RevenueTrendChart({
  current,
  previous,
  currentLabel,
  comparisonLabel,
}: {
  current: SeriesPoint[];
  previous?: SeriesPoint[];
  currentLabel: string;
  comparisonLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [showPrevious, setShowPrevious] = useState(true);

  const prev = showPrevious ? previous : undefined;
  const n = Math.max(current.length, prev?.length ?? 0);
  const max = Math.max(1, ...current.map((p) => num(p.revenue)), ...(prev ?? []).map((p) => num(p.revenue)));
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const stepX = n > 1 ? innerW / (n - 1) : 0;
  const x = (i: number) => PAD.l + i * stepX;
  const y = (v: number) => PAD.t + innerH - (v / max) * innerH;

  const curPts = useMemo(
    () => current.map((p, i): [number, number] => [x(i), y(num(p.revenue))]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [current, max, n],
  );
  const prevPts = useMemo(
    () => (prev ?? []).map((p, i): [number, number] => [x(i), y(num(p.revenue))]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [prev, max, n],
  );

  if (!current.length) {
    return <p className="py-10 text-center text-sm text-ink-muted">No revenue in this period yet.</p>;
  }

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => max * f);
  const labelEvery = Math.max(1, Math.ceil(n / 8));
  const hoverPoint = hover !== null ? current[hover] : undefined;
  const hoverPrev = hover !== null && prev ? prev[hover] : undefined;
  const total = current.reduce((s, p) => s + num(p.revenue), 0);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-ink-soft">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-[3px] w-5 rounded bg-teal" />
          {currentLabel}
        </span>
        {previous && comparisonLabel ? (
          <button
            type="button"
            onClick={() => setShowPrevious((v) => !v)}
            aria-pressed={showPrevious}
            className={`inline-flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-mist ${
              showPrevious ? "" : "opacity-50"
            }`}
          >
            <span
              aria-hidden
              className="h-0 w-5 border-t-2 border-dashed border-compare"
            />
            {comparisonLabel}
            <span className="text-ink-muted">({showPrevious ? "shown" : "hidden"})</span>
          </button>
        ) : null}
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={`Revenue trend: ${current.length} points, total ${inr(total)}, peak ${inr(max)}`}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const mx = ((e.clientX - rect.left) / rect.width) * W;
            if (n > 1) {
              const idx = Math.round((mx - PAD.l) / stepX);
              setHover(Math.max(0, Math.min(current.length - 1, idx)));
            } else {
              setHover(0);
            }
          }}
        >
          {/* gridlines + y axis */}
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#E7EDF2" strokeWidth={1} />
              <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="fill-ink-muted text-[11px] tabular-nums">
                {inrShort(t)}
              </text>
            </g>
          ))}
          {/* comparison series */}
          {prev && prev.length > 1 ? (
            <path d={smoothPath(prevPts)} fill="none" stroke="#B8CDD3" strokeWidth={2} strokeDasharray="6 4" />
          ) : null}
          {prev && prev.length === 1 ? (
            <circle cx={prevPts[0][0]} cy={prevPts[0][1]} r={3.5} fill="#fff" stroke="#B8CDD3" strokeWidth={2} />
          ) : null}
          {/* current area + line */}
          {curPts.length > 1 ? (
            <>
              <path
                d={`${smoothPath(curPts)}L${curPts[curPts.length - 1][0]},${PAD.t + innerH}L${curPts[0][0]},${PAD.t + innerH}Z`}
                fill="#0F9D94"
                fillOpacity={0.15}
                stroke="none"
              />
              <path d={smoothPath(curPts)} fill="none" stroke="#0F9D94" strokeWidth={2.5} strokeLinejoin="round" />
            </>
          ) : null}
          {/* hover guide */}
          {hover !== null && curPts[hover] ? (
            <line
              x1={curPts[hover][0]}
              x2={curPts[hover][0]}
              y1={PAD.t}
              y2={PAD.t + innerH}
              stroke="#8293A5"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          ) : null}
          {/* points */}
          {curPts.map(([cx, cy], i) => (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={i === curPts.length - 1 ? 4.5 : hover === i ? 4.5 : 3}
              fill="#fff"
              stroke="#0F9D94"
              strokeWidth={2}
            >
              <title>{`${periodLabel(current[i].period, "full")}: ${inr(current[i].revenue)} · ${current[i].bookings} bookings`}</title>
            </circle>
          ))}
          {/* x labels */}
          {current.map((p, i) =>
            i % labelEvery === 0 ? (
              <text
                key={p.period + i}
                x={x(i)}
                y={H - 8}
                textAnchor="middle"
                className="fill-ink-muted text-[11px]"
              >
                {periodLabel(p.period)}
              </text>
            ) : null,
          )}
        </svg>

        {hoverPoint && curPts[hover!] ? (
          <div
            role="status"
            className="pointer-events-none absolute top-0 z-10 min-w-[150px] -translate-x-1/2 rounded-[10px] border border-line bg-white px-3 py-2 text-xs shadow-lift"
            style={{ left: `${(curPts[hover!][0] / W) * 100}%` }}
          >
            <p className="font-semibold text-ink">{periodLabel(hoverPoint.period, "full")}</p>
            <p className="mt-1 tabular-nums text-ink-soft">
              Revenue <span className="font-semibold text-ink">{inr(hoverPoint.revenue)}</span>
            </p>
            {hoverPrev ? (
              <p className="tabular-nums text-ink-soft">
                {comparisonLabel ?? "Comparison"}{" "}
                <span className="font-semibold text-ink">{inr(hoverPrev.revenue)}</span>
              </p>
            ) : null}
            <p className="tabular-nums text-ink-soft">
              Bookings <span className="font-semibold text-ink">{hoverPoint.bookings}</span>
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
