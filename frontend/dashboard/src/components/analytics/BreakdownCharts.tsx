import { inr, inrShort } from "./format";

export interface ChartRow {
  label: string;
  value: number;
  bookings?: number;
  color: string;
}

/** Donut with a centre total and a legend carrying amounts + share.
 * Segments are real values only; a zero-total dataset renders nothing
 * (the caller shows an empty state instead). */
export function DonutChart({
  rows,
  centerLabel,
  ariaLabel,
}: {
  rows: ChartRow[];
  centerLabel: string;
  ariaLabel: string;
}) {
  const total = rows.reduce((s, r) => s + r.value, 0);
  if (total <= 0) return null;
  const R = 54;
  const C = 2 * Math.PI * R;
  let acc = 0;
  const segments = rows
    .filter((r) => r.value > 0)
    .map((r) => {
      const frac = r.value / total;
      const seg = { ...r, frac, offset: acc };
      acc += frac;
      return seg;
    });
  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg viewBox="0 0 140 140" className="h-[140px] w-[140px] shrink-0" role="img" aria-label={ariaLabel}>
        <circle cx="70" cy="70" r={R} fill="none" stroke="#EDF1F5" strokeWidth="20" />
        {segments.map((s) => (
          <circle
            key={s.label}
            cx="70"
            cy="70"
            r={R}
            fill="none"
            stroke={s.color}
            strokeWidth="20"
            strokeDasharray={`${Math.max(0, s.frac * C - (segments.length > 1 ? 2 : 0))} ${C}`}
            strokeDashoffset={-s.offset * C}
            transform="rotate(-90 70 70)"
          >
            <title>{`${s.label}: ${inr(s.value)} (${Math.round(s.frac * 100)}%)`}</title>
          </circle>
        ))}
        <text x="70" y="66" textAnchor="middle" className="fill-ink text-[15px] font-bold tabular-nums">
          {inrShort(total)}
        </text>
        <text x="70" y="82" textAnchor="middle" className="fill-ink-muted text-[9.5px]">
          {centerLabel}
        </text>
      </svg>
      <ul className="min-w-[170px] flex-1 space-y-2">
        {rows.map((r) => (
          <li key={r.label} className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="inline-flex min-w-0 items-center gap-2">
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: r.color }} />
              <span className="truncate font-medium text-ink">{r.label}</span>
            </span>
            <span className="shrink-0 tabular-nums text-ink-soft">
              {inr(r.value)} · {total > 0 ? Math.round((r.value / total) * 100) : 0}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Vertical bars (booking source). Teal bars, ₹ axis, gridlines,
 * native tooltips with revenue + bookings. */
export function VerticalBars({ rows, ariaLabel }: { rows: ChartRow[]; ariaLabel: string }) {
  const W = 560;
  const H = 230;
  const PAD = { l: 52, r: 8, t: 18, b: 30 };
  const max = Math.max(1, ...rows.map((r) => r.value));
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const slot = innerW / Math.max(1, rows.length);
  const barW = Math.min(64, slot * 0.55);
  const ticks = [0, 0.5, 1].map((f) => max * f);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={ariaLabel}>
      {ticks.map((t, i) => {
        const y = PAD.t + innerH - (t / max) * innerH;
        return (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="#E7EDF2" strokeWidth={1} />
            <text x={PAD.l - 8} y={y + 4} textAnchor="end" className="fill-ink-muted text-[11px] tabular-nums">
              {inrShort(t)}
            </text>
          </g>
        );
      })}
      {rows.map((r, i) => {
        const h = (r.value / max) * innerH;
        const cx = PAD.l + slot * i + slot / 2;
        return (
          <g key={r.label}>
            <rect
              x={cx - barW / 2}
              y={PAD.t + innerH - h}
              width={barW}
              height={Math.max(0, h)}
              rx={4}
              fill={r.color}
            >
              <title>{`${r.label}: ${inr(r.value)}${r.bookings !== undefined ? ` · ${r.bookings} bookings` : ""}`}</title>
            </rect>
            <text x={cx} y={PAD.t + innerH - h - 6} textAnchor="middle" className="fill-ink text-[11px] font-semibold tabular-nums">
              {inrShort(r.value)}
            </text>
            <text x={cx} y={H - 8} textAnchor="middle" className="fill-ink-muted text-[11px]">
              {r.label.length > 14 ? r.label.slice(0, 13) + "…" : r.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Horizontal bars with share-of-total (department revenue). */
export function HorizontalBars({ rows }: { rows: ChartRow[] }) {
  const total = rows.reduce((s, r) => s + r.value, 0);
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-4">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="font-medium text-ink">{r.label}</span>
            <span className="tabular-nums text-ink-soft">
              {inr(r.value)}
              {total > 0 ? ` · ${Math.round((r.value / total) * 100)}%` : ""}
              {r.bookings !== undefined ? ` · ${r.bookings} bookings` : ""}
            </span>
          </div>
          <div className="mt-1.5 h-2.5 rounded-full bg-mist">
            <div
              className="h-2.5 rounded-full"
              style={{ width: `${(r.value / max) * 100}%`, background: r.color }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
