import { useState } from "react";
import { useAuth } from "../lib/auth";
import { useAuditLogs } from "../lib/queries";
import { formatDateTime } from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";

export default function AuditLog() {
  const { hotelId } = useAuth();
  const [actionFilter, setActionFilter] = useState("");
  const [appliedAction, setAppliedAction] = useState<string | undefined>(undefined);

  const logsQuery = useAuditLogs(hotelId, appliedAction);

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Who changed what, and when. Read-only; entries are written by the backend."
      />
      <form
        className="mb-4 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setAppliedAction(actionFilter.trim() || undefined);
        }}
      >
        <label className="text-sm">
          <span className="label">Filter by action</span>
          <input
            type="search"
            className="input !w-64"
            placeholder="e.g. booking.modified"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          />
        </label>
        <button type="submit" className="btn btn-secondary">
          Apply
        </button>
        {appliedAction && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setActionFilter("");
              setAppliedAction(undefined);
            }}
          >
            Clear
          </button>
        )}
      </form>
      <ListState
        query={logsQuery}
        emptyTitle="No audit entries"
        emptyHint="Staff actions (logins, booking changes, user management) are recorded here."
        skeletonRows={8}
        render={(logs) => (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id}>
                    <td className="whitespace-nowrap font-mono text-xs">
                      {formatDateTime(l.created_at)}
                    </td>
                    <td className="font-mono text-xs">
                      {l.actor_type}
                      {l.actor_id !== null ? ` #${l.actor_id}` : ""}
                    </td>
                    <td className="font-mono text-xs">{l.action}</td>
                    <td className="font-mono text-xs">
                      {l.entity_type ?? "—"}
                      {l.entity_id !== null ? ` #${l.entity_id}` : ""}
                    </td>
                    <td className="max-w-xs truncate font-mono text-xs text-ink/70" title={l.details ?? ""}>
                      {l.details ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      />
    </div>
  );
}
