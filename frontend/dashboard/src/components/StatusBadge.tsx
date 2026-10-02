const STYLES: Record<string, string> = {
  // bookings
  PENDING: "bg-brass-100 text-ink border border-brass-500/40",
  CONFIRMED: "bg-pine-100 text-pine-950 border border-pine-700/30",
  CHECKED_IN: "bg-pine-700 text-white",
  CHECKED_OUT: "bg-pine-950/10 text-ink/70 border border-pine-950/20",
  CANCELLED: "bg-brick-100 text-brick-700 border border-brick-600/30",
  // service requests
  ACKNOWLEDGED: "bg-pine-100 text-pine-950 border border-pine-700/30",
  IN_PROGRESS: "bg-brass-100 text-ink border border-brass-500/40",
  COMPLETED: "bg-pine-700 text-white",
  // documents
  processing: "bg-brass-100 text-ink border border-brass-500/40",
  ready: "bg-pine-700 text-white",
  failed: "bg-brick-100 text-brick-700 border border-brick-600/30",
};

export default function StatusBadge({ status }: { status: string }) {
  const style =
    STYLES[status] ?? "bg-pine-950/10 text-ink/70 border border-pine-950/20";
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
