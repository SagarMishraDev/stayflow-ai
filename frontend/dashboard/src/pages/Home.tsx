import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  useBookings,
  useConversations,
  useHotel,
  useRooms,
  useServiceRequests,
} from "../lib/queries";
import { formatMoney, todayISO } from "../lib/schemas";
import { PageHeader } from "../components/DataStates";
import StatusBadge from "../components/StatusBadge";

/**
 * Dashboard home. The bold visual moment is today's arrivals and
 * departures; everything else is a quiet, real-data metric.
 */
export default function Home() {
  const { hotelId } = useAuth();
  const today = todayISO();
  const hotelQuery = useHotel(hotelId);
  const bookingsQuery = useBookings(hotelId);
  const roomsQuery = useRooms(hotelId);
  const requestsQuery = useServiceRequests(hotelId);
  const conversationsQuery = useConversations(hotelId);

  const arrivals = useMemo(
    () =>
      (bookingsQuery.data ?? []).filter(
        (b) =>
          b.check_in === today &&
          (b.booking_status === "CONFIRMED" || b.booking_status === "PENDING"),
      ),
    [bookingsQuery.data, today],
  );
  const departures = useMemo(
    () =>
      (bookingsQuery.data ?? []).filter(
        (b) => b.check_out === today && b.booking_status === "CHECKED_IN",
      ),
    [bookingsQuery.data, today],
  );
  const openRequests = useMemo(
    () =>
      (requestsQuery.data ?? []).filter((r) =>
        ["PENDING", "ACKNOWLEDGED", "IN_PROGRESS"].includes(r.status),
      ),
    [requestsQuery.data],
  );
  const activeConversations = useMemo(
    () =>
      (conversationsQuery.data ?? []).filter(
        (c) => c.status === "ACTIVE" && c.is_active,
      ),
    [conversationsQuery.data],
  );
  const occupancy = useMemo(() => {
    const rooms = roomsQuery.data ?? [];
    const capacity = rooms.reduce((s, r) => s + r.total_rooms, 0);
    const inHouse = (bookingsQuery.data ?? []).filter(
      (b) =>
        b.booking_status === "CHECKED_IN" &&
        b.check_in <= today &&
        b.check_out > today,
    ).length;
    return { capacity, inHouse, pct: capacity ? Math.round((inHouse / capacity) * 100) : 0 };
  }, [roomsQuery.data, bookingsQuery.data, today]);

  const movement = useMemo(
    () =>
      [...arrivals.map((b) => ({ ...b, kind: "Arrival" as const })),
        ...departures.map((b) => ({ ...b, kind: "Departure" as const })),
      ].sort((a, b) => a.id - b.id),
    [arrivals, departures],
  );

  return (
    <div>
      <PageHeader
        title={
          hotelQuery.data ? `${hotelQuery.data.name} — today` : "Today"
        }
        description={new Date().toLocaleDateString("en-IN", {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        })}
      />

      {/* The bold moment: today's movement, brass numerals on deep pine. */}
      <section
        aria-label="Today's arrivals and departures"
        className="mb-6 rounded-xl bg-pine-950 p-6 text-white md:p-8"
      >
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="border-l-4 border-brass-500 pl-5">
            <p className="text-sm font-medium text-white/70">Arrivals</p>
            <p className="font-mono text-6xl font-semibold text-brass-500 tabular-nums">
              {arrivals.length}
            </p>
            <p className="mt-1 text-sm text-white/60">
              checking in today
            </p>
          </div>
          <div className="border-l-4 border-brass-500 pl-5">
            <p className="text-sm font-medium text-white/70">Departures</p>
            <p className="font-mono text-6xl font-semibold text-brass-500 tabular-nums">
              {departures.length}
            </p>
            <p className="mt-1 text-sm text-white/60">checking out today</p>
          </div>
        </div>
      </section>

      {/* Quiet metrics — real data only. */}
      <section aria-label="Key figures" className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="panel p-5">
          <p className="text-sm text-ink/60">Occupancy tonight</p>
          <p className="mt-1 font-mono text-3xl font-semibold tabular-nums">
            {occupancy.pct}%
          </p>
          <p className="text-sm text-ink/60">
            {occupancy.inHouse} of {occupancy.capacity} rooms
          </p>
        </div>
        <div className="panel p-5">
          <p className="text-sm text-ink/60">Open service requests</p>
          <p className="mt-1 font-mono text-3xl font-semibold tabular-nums">
            {openRequests.length}
          </p>
          <Link to="/service-requests" className="text-sm font-medium text-pine-700 underline">
            Open the board
          </Link>
        </div>
        <div className="panel p-5">
          <p className="text-sm text-ink/60">Active guest chats</p>
          <p className="mt-1 font-mono text-3xl font-semibold tabular-nums">
            {activeConversations.length}
          </p>
          <Link to="/conversations" className="text-sm font-medium text-pine-700 underline">
            Read transcripts
          </Link>
        </div>
      </section>

      <section aria-label="Today's movement" className="panel overflow-hidden">
        <h2 className="panel-title border-b border-pine-950/10 px-5 py-4">
          Today's movement
        </h2>
        {movement.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink/60">
            No arrivals or departures scheduled for today.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Booking</th>
                  <th>Movement</th>
                  <th>Room type</th>
                  <th>Guests</th>
                  <th>Status</th>
                  <th>Amount</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {movement.map((b) => (
                  <tr key={`${b.kind}-${b.id}`}>
                    <td className="font-mono">#{b.id}</td>
                    <td>{b.kind}</td>
                    <td>Room #{b.room_id}</td>
                    <td className="font-mono tabular-nums">{b.number_of_guests}</td>
                    <td>
                      <StatusBadge status={b.booking_status} />
                    </td>
                    <td className="font-mono tabular-nums">
                      {formatMoney(b.final_price, hotelQuery.data?.currency)}
                    </td>
                    <td>
                      <Link
                        to={`/bookings/${b.id}`}
                        className="font-medium text-pine-700 underline"
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Hidden preload note: ListState not needed here; keep page honest about
          which queries back each number (bookings, rooms, requests, chats). */}
      <span className="sr-only">
        {bookingsQuery.isLoading || roomsQuery.isLoading ? "Loading figures…" : ""}
      </span>
    </div>
  );
}
