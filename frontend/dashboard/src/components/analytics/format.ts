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
