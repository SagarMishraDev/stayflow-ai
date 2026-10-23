import type { ReactNode } from "react";

/** White analytics card: title, optional subtitle, optional header
 * actions, and the chart/list body. View 2 card system: 16px radius,
 * 1px #E6ECF1 border, very light shadow. */
export function ChartCard({
  title,
  subtitle,
  actions,
  children,
  labelledBy,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  labelledBy?: string;
}) {
  return (
    <section
      aria-label={labelledBy ?? title}
      className="rounded-2xl border border-line bg-white p-5 shadow-card"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-bold leading-snug text-ink">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** Neutral empty state with a simple icon — used where a dataset is
 * legitimately empty (never filled with fake segments). */
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <span
        aria-hidden
        className="grid h-11 w-11 place-items-center rounded-full bg-mist text-ink-muted"
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <line x1="12" y1="20" x2="12" y2="10" />
          <line x1="18" y1="20" x2="18" y2="4" />
          <line x1="6" y1="20" x2="6" y2="16" />
        </svg>
      </span>
      <p className="mt-3 max-w-[260px] text-[13px] leading-relaxed text-ink-soft">{message}</p>
    </div>
  );
}

export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading chart"
      className="animate-pulse rounded-xl bg-mist"
      style={{ height }}
    />
  );
}
