const STYLES: Record<string, string> = {
  // bookings
  PENDING: "bg-sun text-ink border border-ink/15",
  CONFIRMED: "bg-mist text-deep-teal border border-teal/40",
  CHECKED_IN: "bg-deep-teal text-white",
  CHECKED_OUT: "bg-paper text-ink/60 border border-line",
  CANCELLED: "bg-coral-soft text-coral-deep border border-coral/50",
  // service requests
  ACKNOWLEDGED: "bg-mist text-deep-teal border border-teal/40",
  IN_PROGRESS: "bg-sun text-ink border border-ink/15",
  COMPLETED: "bg-deep-teal text-white",
  // food orders
  PREPARING: "bg-sun text-ink border border-ink/15",
  READY: "bg-mist text-deep-teal border border-teal/40",
  DELIVERED: "bg-deep-teal text-white",
  // documents
  processing: "bg-sun text-ink border border-ink/15",
  ready: "bg-deep-teal text-white",
  failed: "bg-coral-soft text-coral-deep border border-coral/50",
};

export default function StatusBadge({ status }: { status: string }) {
  const style =
    STYLES[status] ?? "bg-paper text-ink/60 border border-line";
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-bold ${style}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
