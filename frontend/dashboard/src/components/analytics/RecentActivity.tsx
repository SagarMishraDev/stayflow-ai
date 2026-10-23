import type { ReactNode } from "react";
import type { ActivityEvent, ActivityKind } from "../../lib/analyticsApi";
import { inr } from "./format";
import { EmptyState } from "./ChartCard";

/** Latest real booking/payment events (GET /analytics/activity),
 * newest first. Guest names appear only in the summary the backend
 * returns for analytics roles — nothing extra is exposed here. */

const KIND_STYLE: Record<ActivityKind, { chip: string; icon: ReactNode }> = {
  booking_created: {
    chip: "bg-info/10 text-info",
    icon: (
      <>
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <line x1="12" y1="14" x2="12" y2="18" />
        <line x1="10" y1="16" x2="14" y2="16" />
      </>
    ),
  },
  booking_confirmed: {
    chip: "bg-emerald/10 text-emerald",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m8.5 12.2 2.4 2.4 4.6-4.9" />
      </>
    ),
  },
  booking_cancelled: {
    chip: "bg-coral-soft text-coral-deep",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <line x1="9" y1="9" x2="15" y2="15" />
        <line x1="15" y1="9" x2="9" y2="15" />
      </>
    ),
  },
  payment_received: {
    chip: "bg-emerald/10 text-emerald",
    icon: (
      <>
        <rect x="2" y="6" width="20" height="12" rx="2" />
        <circle cx="12" cy="12" r="2.6" />
        <path d="M6 12h.01M18 12h.01" />
      </>
    ),
  },
  payment_pending: {
    chip: "bg-warn/10 text-[#B45309]",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3.2 2" />
      </>
    ),
  },
  refund_processed: {
    chip: "bg-grape/10 text-grape",
    icon: (
      <>
        <path d="M3 12a9 9 0 1 0 2.6-6.3" />
        <path d="M3 4v5h5" />
      </>
    ),
  },
};

function when(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function RecentActivity({
  events,
  isLoading,
  isError,
}: {
  events?: ActivityEvent[];
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) {
    return (
      <div aria-busy="true" aria-label="Loading activity" className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-xl bg-mist" />
        ))}
      </div>
    );
  }
  if (isError) {
    return (
      <p className="py-6 text-center text-[13px] text-coral-deep">
        Activity could not be loaded. Try refreshing the page.
      </p>
    );
  }
  if (!events || events.length === 0) {
    return <EmptyState message="No recent activity yet — new bookings and payments will appear here." />;
  }
  return (
    <ul className="divide-y divide-divider">
      {events.map((e, i) => {
        const style = KIND_STYLE[e.kind] ?? KIND_STYLE.booking_created;
        return (
          <li key={`${e.kind}-${e.reference}-${e.timestamp}-${i}`} className="flex items-center gap-3 py-3">
            <span
              aria-hidden
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${style.chip}`}
            >
              <svg
                width="17"
                height="17"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {style.icon}
              </svg>
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13.5px] font-semibold text-ink">
                {e.title} <span className="font-medium text-ink-muted">{e.reference}</span>
              </p>
              <p className="truncate text-xs text-ink-muted">
                {e.summary ? `${e.summary} · ` : ""}
                {when(e.timestamp)}
              </p>
            </div>
            <span className="shrink-0 text-[13.5px] font-semibold tabular-nums text-ink">
              {inr(e.amount)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
