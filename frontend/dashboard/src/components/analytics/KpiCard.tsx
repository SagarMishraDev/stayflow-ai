import type { ReactNode } from "react";
import { formatPct } from "./format";

/** Miniature line chart drawn ONLY from series data already fetched
 * for the page — never synthetic values. */
export function Sparkline({
  data,
  stroke = "#0F9D94",
  label,
}: {
  data: number[];
  stroke?: string;
  label: string;
}) {
  if (data.length < 2) return null;
  const w = 76;
  const h = 28;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * (w - 4) + 2,
    h - 3 - ((v - min) / span) * (h - 6),
  ]);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="h-7 w-[76px] shrink-0"
      role="img"
      aria-label={label}
    >
      <polygon
        points={`2,${h - 1} ${line} ${w - 2},${h - 1}`}
        fill={stroke}
        fillOpacity={0.12}
        stroke="none"
      />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.8} strokeLinejoin="round" />
    </svg>
  );
}

export interface KpiDelta {
  /** Percent change vs the comparison period, or point difference when
   * `points` is set (occupancy). Null = baseline was zero. */
  value: number | null;
  /** Whether the movement is favourable (decides the colour — a rise
   * in refunds or pending payments is NOT good news). */
  favorable: boolean | null;
  points?: boolean;
  caption: string;
}

export function KpiCard({
  label,
  value,
  sub,
  icon,
  iconClass,
  delta,
  spark,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: ReactNode;
  /** Tailwind classes for the circular icon chip (bg + text colour). */
  iconClass: string;
  delta?: KpiDelta | null;
  spark?: ReactNode;
}) {
  return (
    <div className="ax-card flex min-h-[128px] flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <span
          aria-hidden
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${iconClass}`}
        >
          {icon}
        </span>
        {spark}
      </div>
      <p className="mt-3 text-[26px] font-bold leading-none tabular-nums text-[#102A43]">{value}</p>
      <p className="mt-1.5 text-[12.5px] font-medium text-[#52677D]">{label}</p>
      {sub ? <p className="mt-1 text-[11.5px] text-[#8293A5]">{sub}</p> : null}
      {delta ? (
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px]">
          {delta.value === null ? (
            <span className="font-medium text-[#8293A5]">No baseline</span>
          ) : (
            <span
              className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold tabular-nums ${
                delta.favorable === null
                  ? "bg-[#F8FAFC] text-[#52677D]"
                  : delta.favorable
                    ? "bg-[#10B981]/10 text-[#10B981]"
                    : "bg-[#FDECEC] text-[#C22F2F]"
              }`}
            >
              <svg
                aria-hidden
                width="9"
                height="9"
                viewBox="0 0 10 10"
                className={delta.value < 0 ? "rotate-180" : ""}
              >
                <path d="M5 1.5 9 8H1z" fill="currentColor" />
              </svg>
              {delta.points
                ? `${delta.value > 0 ? "+" : ""}${delta.value} pts`
                : formatPct(delta.value)}
            </span>
          )}
          <span className="text-[#8293A5]">{delta.caption}</span>
        </p>
      ) : null}
    </div>
  );
}

/** Small 18px stroke icon helper for KPI chips. */
export function KpiIcon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
