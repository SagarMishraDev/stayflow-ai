import { useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import { useRooms } from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import { formatDate } from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { api } from "../lib/api";
import { useQuery } from "@tanstack/react-query";
import type { AvailabilityNight } from "../lib/types";

function monthRange(month: Date): { start: string; end: string } {
  const y = month.getFullYear();
  const m = month.getMonth();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    start: `${y}-${pad(m + 1)}-01`,
    end: `${y}-${pad(m + 1)}-${new Date(y, m + 1, 0).getDate()}`,
  };
}

export default function AvailabilityCalendar() {
  const { hotelId } = useAuth();
  const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);
  const [month, setMonth] = useState(() => new Date());

  const roomsQuery = useRooms(hotelId);
  const { start, end } = monthRange(month);

  const checkQuery = useQuery<{ nights: AvailabilityNight[] }, Error>({
    queryKey: ["availability-check", selectedRoomId, start, end],
    queryFn: async () =>
      (
        await api.get("/bookings/availability-check", {
          params: { room_id: selectedRoomId, check_in: start, check_out: end },
        })
      ).data,
    enabled: selectedRoomId !== null,
  });

  const byDate = useMemo(() => {
    const map = new Map<string, AvailabilityNight>();
    (checkQuery.data?.nights ?? []).forEach((n) => map.set(n.date, n));
    return map;
  }, [checkQuery.data]);

  const days = useMemo(() => {
    const y = month.getFullYear();
    const m = month.getMonth();
    const first = new Date(y, m, 1);
    const cells: (string | null)[] = [];
    for (let i = 0; i < first.getDay(); i++) cells.push(null);
    for (let d = 1; d <= new Date(y, m + 1, 0).getDate(); d++)
      cells.push(
        `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
      );
    return cells;
  }, [month]);

  const soldOut = useMemo(
    () => [...byDate.values()].filter((n) => n.available <= 0).length,
    [byDate],
  );

  return (
    <div>
      <PageHeader
        title="Availability calendar"
        description="Per-night availability from the booking engine. Sold-out nights are flagged."
      />

      <section aria-label="Room types" className="mb-6">
        <ListState
          query={roomsQuery}
          emptyTitle="No room types yet"
          emptyHint="Add a room type under Rooms & rates first."
          skeletonRows={3}
          render={(list) => (
            <div className="flex flex-wrap gap-2" role="listbox" aria-label="Choose a room type">
              {list.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="option"
                  aria-selected={selectedRoomId === r.id}
                  onClick={() => setSelectedRoomId(r.id)}
                  className={`rounded-xl border px-4 py-2.5 text-left text-sm font-semibold ${
                    selectedRoomId === r.id
                      ? "border-deep-teal bg-deep-teal text-white"
                      : "border-line bg-paper hover:border-teal"
                  }`}
                >
                  {r.room_type}
                </button>
              ))}
            </div>
          )}
        />
      </section>

      {selectedRoomId && (
        <section aria-label="Availability grid">
          <div className="mb-3 flex items-center gap-2">
            <button
              type="button"
              className="btn btn-secondary !px-3"
              onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
              aria-label="Previous month"
            >
              ‹
            </button>
            <span className="min-w-36 text-center text-sm font-semibold" aria-live="polite">
              {month.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}
            </span>
            <button
              type="button"
              className="btn btn-secondary !px-3"
              onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
              aria-label="Next month"
            >
              ›
            </button>
            {checkQuery.data && (
              <span className="ml-2 text-sm text-ink/60">
                {soldOut} sold-out night{soldOut === 1 ? "" : "s"} this month
              </span>
            )}
          </div>

          {checkQuery.isLoading ? (
            <div aria-busy="true" className="grid grid-cols-7 gap-1.5" aria-label="Loading availability">
              {Array.from({ length: 35 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-mist" />
              ))}
              <span className="sr-only">Loading availability…</span>
            </div>
          ) : checkQuery.isError ? (
            <div role="alert" className="panel p-6 text-center">
              <p className="font-semibold">Couldn't load availability</p>
              <p className="mt-1 text-sm text-ink/70">{apiErrorMessage(checkQuery.error)}</p>
              <button type="button" className="btn btn-secondary mt-4" onClick={() => checkQuery.refetch()}>
                Try again
              </button>
            </div>
          ) : (
            <div className="panel overflow-hidden">
              <div className="grid grid-cols-7 border-b border-line bg-mist/60 text-center text-xs font-semibold text-ink/60">
                {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
                  <div key={d} className="py-2">{d}</div>
                ))}
              </div>
              <div className="grid grid-cols-7 gap-px bg-ink/10">
                {days.map((iso, i) => {
                  if (iso === null)
                    return <div key={`pad-${i}`} className="min-h-16 bg-paper" />;
                  const n = byDate.get(iso);
                  const isSoldOut = n !== undefined && n.available <= 0;
                  return (
                    <div
                      key={iso}
                      className={`min-h-16 p-1.5 ${
                        isSoldOut ? "bg-coral-deep text-white" : "bg-paper"
                      }`}
                      aria-label={`${formatDate(iso)}: ${
                        n === undefined
                          ? "no data"
                          : isSoldOut
                            ? "sold out"
                            : `${n.available} of ${n.capacity} available`
                      }`}
                    >
                      <span className={`block text-xs font-semibold ${isSoldOut ? "text-white/80" : "text-ink/60"}`}>
                        {parseInt(iso.slice(8, 10), 10)}
                      </span>
                      {n === undefined ? (
                        <span className="block text-xs text-ink/40">—</span>
                      ) : isSoldOut ? (
                        <span className="block text-xs font-bold">
                          Sold out
                        </span>
                      ) : (
                        <span className="block font-mono text-xs tabular-nums">
                          {n.available}/{n.capacity}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="border-t border-line px-4 py-2 text-xs text-ink/60">
                Read-only view from the booking engine. To change availability,
                set rates under Rooms &amp; rates.
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
