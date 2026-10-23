/** Shared formatting for the analytics components. Money arrives from
 * the API as decimal strings; everything renders in INR (en-IN). */

export function num(value: string | number): number {
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isNaN(n) ? 0 : n;
}

export function inr(value: string | number): string {
  return `₹${num(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** Compact axis label: ₹950 · ₹12k · ₹1.2L (Indian numbering). */
export function inrShort(value: string | number): string {
  const n = Math.abs(num(value));
  if (n >= 100000) {
    const v = n / 100000;
    return `₹${v >= 100 ? Math.round(v) : trimZero(v.toFixed(1))}L`;
  }
  if (n >= 1000) {
    const v = n / 1000;
    return `₹${v >= 100 ? Math.round(v) : trimZero(v.toFixed(1))}k`;
  }
  return `₹${Math.round(n)}`;
}

function trimZero(s: string): string {
  return s.endsWith(".0") ? s.slice(0, -2) : s;
}

/** "Nice" Y-axis scale for a data maximum `v`: a step from the
 * 1 / 2 / 2.5 / 5 × 10^n family with 3–6 intervals, chosen so the
 * axis maximum (step × intervals) HUGS the data instead of jumping a
 * whole decade step — a ₹51k daily maximum used to get a ₹1L axis,
 * leaving the top half of the plot permanently empty; it now gets a
 * ₹60k axis (6 × ₹10k). The axis maximum is never below `v`, and
 * ticks land exactly on step multiples (₹26k, ₹34.6k…). */
export function niceAxisScale(v: number): { max: number; step: number; ticks: number[] } {
  if (!(v > 0) || !Number.isFinite(v)) {
    return { max: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] };
  }
  const decade = Math.floor(Math.log10(v));
  let best: { max: number; step: number; intervals: number } | null = null;
  for (let p = decade - 1; p <= decade + 1; p++) {
    for (const mult of [1, 2, 2.5, 5]) {
      const step = mult * Math.pow(10, p);
      const intervals = Math.ceil(v / step - 1e-9);
      if (intervals < 3 || intervals > 6) continue;
      const max = step * intervals;
      // Tightest axis wins; on a tie prefer the finer step (more
      // gridlines read better than fewer, coarser ones).
      if (!best || max < best.max || (max === best.max && intervals > best.intervals)) {
        best = { max, step, intervals };
      }
    }
  }
  if (!best) {
    // Unreachable for finite v > 0 (some family step always lands in
    // 3–6 intervals), but never return an axis below the data.
    const max = Math.pow(10, Math.ceil(Math.log10(v)));
    return { max, step: max / 4, ticks: [0, max / 4, max / 2, (3 * max) / 4, max] };
  }
  const ticks = Array.from({ length: best.intervals + 1 }, (_, i) => best.step * i);
  return { max: best.max, step: best.step, ticks };
}

/** Smallest "nice" axis maximum covering `v` (see niceAxisScale). */
export function niceAxisMax(v: number): number {
  return niceAxisScale(v).max;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Human label for a series bucket key:
 * "2026-10-23" → "23 Oct" · "2026-10-23 14:00" → "14:00" ·
 * "2026-10" → "Oct 26" · "2026" → "2026". */
export function periodLabel(period: string, style: "short" | "full" = "short"): string {
  const hour = period.match(/^\d{4}-\d{2}-\d{2} (\d{2}:\d{2})$/);
  if (hour) return style === "full" ? `${period.slice(8, 10)} ${MONTHS[Number(period.slice(5, 7)) - 1]}, ${hour[1]}` : hour[1];
  const day = period.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (day) {
    const base = `${Number(day[3])} ${MONTHS[Number(day[2]) - 1]}`;
    return style === "full" ? `${base} ${day[1]}` : base;
  }
  const month = period.match(/^(\d{4})-(\d{2})$/);
  if (month) return `${MONTHS[Number(month[2]) - 1]} ${month[1].slice(2)}`;
  return period;
}

/** The four trend-series colours, assigned chronologically to the
 * four displayed months (oldest → newest). Fixed by the design spec. */
export const MONTH_SERIES_COLORS = ["#0F9D94", "#3B82F6", "#8B5CF6", "#F59E0B"];

/** Canonical room-type colours (approved design): the three known
 * types are pinned by name; any additional room type takes the next
 * colour from the extended palette, in first-seen order. The same
 * mapping is used by the grouped bars, the category donut, legend
 * chips and table indicators so a type keeps one colour everywhere. */
export const ROOM_TYPE_COLORS: Record<string, string> = {
  "Heritage Suite": "#0F9D94",
  "Deluxe King Room": "#3B82F6",
  "Executive Twin Room": "#F59E0B",
};
export const ROOM_TYPE_FALLBACK = [
  "#8B5CF6",
  "#10B981",
  "#EF4444",
  "#087E78",
  "#18B8AC",
  "#8293A5",
];

export function roomTypeColor(roomType: string, fallbackIndex = 0): string {
  return (
    ROOM_TYPE_COLORS[roomType] ??
    ROOM_TYPE_FALLBACK[fallbackIndex % ROOM_TYPE_FALLBACK.length]
  );
}

/** Deterministic colour map for a set of room types: pinned colours
 * by name; unpinned types take the fallback palette in ALPHABETICAL
 * order, so every chart/table on the page assigns the same colour to
 * the same type regardless of sort order. */
export function buildRoomColorMap(roomTypes: string[]): Map<string, string> {
  const map = new Map<string, string>();
  const unpinned = roomTypes.filter((t) => !(t in ROOM_TYPE_COLORS)).sort();
  for (const t of roomTypes) if (t in ROOM_TYPE_COLORS) map.set(t, ROOM_TYPE_COLORS[t]);
  unpinned.forEach((t, i) => map.set(t, ROOM_TYPE_FALLBACK[i % ROOM_TYPE_FALLBACK.length]));
  return map;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-10" → "October 2026" (or "Oct 2026" when short). */
export function monthLabel(key: string, style: "long" | "short" = "long"): string {
  const m = key.match(/^(\d{4})-(\d{2})$/);
  if (!m) return key;
  const name = style === "long" ? MONTH_NAMES[Number(m[2]) - 1] : MONTHS[Number(m[2]) - 1];
  return `${name} ${m[1]}`;
}

/** Percent change of current vs baseline; null when baseline is 0
 * (a percentage against nothing would be misleading). */
export function pctChange(current: number, baseline: number): number | null {
  if (baseline === 0) return null;
  return ((current - baseline) / Math.abs(baseline)) * 100;
}

export function formatPct(pct: number): string {
  const rounded = Math.round(pct * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${trimZero(rounded.toFixed(1))}%`;
}
