import { useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import {
  useMarkNotificationRead,
  useNotifications,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import { formatDateTime } from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { FormError } from "../components/Form";

export default function Notifications() {
  const { hotelId, user } = useAuth();
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const notificationsQuery = useNotifications(hotelId, showUnreadOnly);
  const markRead = useMarkNotificationRead(hotelId);
  const [actionError, setActionError] = useState<string | null>(null);

  const unreadCount = useMemo(
    () => (notificationsQuery.data ?? []).filter((n) => !n.is_read).length,
    [notificationsQuery.data],
  );

  async function onMarkRead(id: number) {
    setActionError(null);
    try {
      await markRead.mutateAsync(id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Notifications"
        description={
          user
            ? `Operational alerts for ${user.name}. Mark them read as you handle them.`
            : "Operational alerts."
        }
        actions={
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={showUnreadOnly}
              onChange={(e) => setShowUnreadOnly(e.target.checked)}
            />
            Unread only
          </label>
        }
      />
      <FormError error={actionError} />
      {unreadCount > 0 && !showUnreadOnly && (
        <p className="mb-4 text-sm text-ink/70" role="status">
          {unreadCount} unread notification{unreadCount === 1 ? "" : "s"}.
        </p>
      )}
      <ListState
        query={notificationsQuery}
        emptyTitle={showUnreadOnly ? "All caught up" : "No notifications"}
        emptyHint={
          showUnreadOnly
            ? "Every notification has been marked read."
            : "The backend raises notifications for operational events; they will appear here."
        }
        render={(items) => (
          <ul className="space-y-3">
            {items.map((n) => (
              <li
                key={n.id}
                className={`panel p-4 ${n.is_read ? "opacity-70" : "border-l-4 border-l-sun"}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{n.title}</p>
                    <p className="mt-1 text-sm text-ink/75 whitespace-pre-wrap">{n.message}</p>
                    <p className="mt-1 font-mono text-xs text-ink/50">
                      {n.type}
                      {n.reference_type ? ` · ${n.reference_type}${n.reference_id !== null ? ` #${n.reference_id}` : ""}` : ""}{" "}
                      · {formatDateTime(n.created_at)}
                    </p>
                  </div>
                  {!n.is_read && (
                    <button
                      type="button"
                      className="btn btn-secondary shrink-0 !py-1.5 !text-xs"
                      onClick={() => onMarkRead(n.id)}
                      disabled={markRead.isPending}
                    >
                      Mark read
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      />
    </div>
  );
}
