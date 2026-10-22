import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  qk,
  useBooking,
  useBookingQuote,
  useCancelBooking,
  useGuest,
  useHotel,
  useRemove,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatDate,
  formatDateTime,
  formatMoney,
} from "../lib/schemas";
import { DetailState, PageHeader } from "../components/DataStates";
import { FormError } from "../components/Form";
import StatusBadge from "../components/StatusBadge";
import type { BookingStatus } from "../lib/types";

/**
 * Legal status moves, copied from backend/app/services/booking_service.py
 * STATUS_TRANSITIONS. The backend re-validates on every PATCH; this map only
 * decides which buttons to show.
 */
const STATUS_TRANSITIONS: Record<BookingStatus, BookingStatus[]> = {
  PENDING: ["CONFIRMED", "CANCELLED"],
  CONFIRMED: ["CHECKED_IN", "CANCELLED"],
  CHECKED_IN: ["CHECKED_OUT"],
  CHECKED_OUT: [],
  CANCELLED: [],
};

const STATUS_LABEL: Record<BookingStatus, string> = {
  PENDING: "Confirm",
  CONFIRMED: "Check in",
  CHECKED_IN: "Check out",
  CHECKED_OUT: "Checked out",
  CANCELLED: "Cancel booking",
};

export default function BookingDetail() {
  const { id } = useParams<{ id: string }>();
  const bookingId = id ? parseInt(id, 10) : null;
  const { hotelId } = useAuth();
  const navigate = useNavigate();

  const bookingQuery = useBooking(bookingId);
  const booking = bookingQuery.data;
  const guestQuery = useGuest(booking?.guest_id ?? null);
  const hotelQuery = useHotel(hotelId);

  const quoteArgs = booking
    ? {
        hotel_id: booking.hotel_id,
        room_id: booking.room_id,
        check_in: booking.check_in,
        check_out: booking.check_out,
        number_of_guests: booking.number_of_guests,
      }
    : null;
  const quoteQuery = useBookingQuote(quoteArgs);

  const update = useUpdate((id: number) => `/bookings/${id}`, [
    qk.bookings(hotelId),
    ["booking", bookingId ?? "none"],
  ]);
  const cancel = useCancelBooking(hotelId);
  const remove = useRemove((bid) => `/bookings/${bid}`, [qk.bookings(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<BookingStatus | null>(null);

  async function moveTo(status: BookingStatus) {
    if (!bookingId || !booking) return;
    setActionError(null);
    setConfirming(null);
    try {
      if (status === "CANCELLED") {
        await cancel.mutateAsync({ id: bookingId });
      } else {
        await update.mutateAsync({
          id: bookingId,
          data: { booking_status: status },
        });
      }
      await bookingQuery.refetch();
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  async function onDelete() {
    if (!bookingId) return;
    if (
      !window.confirm(
        `Delete booking #${bookingId}? This removes it permanently.`,
      )
    )
      return;
    try {
      await remove.mutateAsync(bookingId);
      navigate("/bookings");
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  const pending = update.isPending || cancel.isPending || remove.isPending;
  const nextStatuses = booking
    ? STATUS_TRANSITIONS[booking.booking_status] ?? []
    : [];

  return (
    <div>
      <PageHeader
        title={booking ? `Booking #${booking.id}` : "Booking"}
        actions={
          <Link to="/bookings" className="btn btn-secondary">
            Back to bookings
          </Link>
        }
      />
      <DetailState
        isLoading={bookingQuery.isLoading}
        isError={bookingQuery.isError}
        error={bookingQuery.error}
        onRetry={() => bookingQuery.refetch()}
      >
        {booking && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <section className="panel p-5" aria-label="Stay summary">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="panel-title">
                    {guestQuery.data?.name ?? `Guest #${booking.guest_id}`}
                  </h2>
                  <StatusBadge status={booking.booking_status} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                  <div>
                    <dt className="text-ink/60">Check-in</dt>
                    <dd className="font-medium">{formatDate(booking.check_in)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink/60">Check-out</dt>
                    <dd className="font-medium">{formatDate(booking.check_out)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink/60">Guests</dt>
                    <dd className="font-medium font-mono tabular-nums">
                      {booking.number_of_guests}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink/60">Created</dt>
                    <dd className="font-medium">
                      {formatDateTime(booking.created_at)}
                    </dd>
                  </div>
                </dl>
              </section>

              <section className="panel p-5" aria-label="Price breakdown">
                <h2 className="panel-title mb-3">Price breakdown</h2>
                {quoteQuery.isLoading ? (
                  <div aria-busy="true" className="space-y-2">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="h-8 animate-pulse rounded bg-ink/10" />
                    ))}
                    <span className="sr-only">Loading price breakdown…</span>
                  </div>
                ) : quoteQuery.isError ? (
                  <div role="alert">
                    <p className="text-sm text-ink/70">
                      Couldn't compute the breakdown from current rates:{" "}
                      {apiErrorMessage(quoteQuery.error)}
                    </p>
                    <button
                      type="button"
                      className="btn btn-secondary mt-2"
                      onClick={() => quoteQuery.refetch()}
                    >
                      Try again
                    </button>
                  </div>
                ) : quoteQuery.data ? (
                  <div>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Night</th>
                          <th className="text-right">Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {quoteQuery.data.nights.map((n) => (
                          <tr key={n.date}>
                            <td>{formatDate(n.date)}</td>
                            <td className="text-right font-mono tabular-nums">
                              {n.price === null ? (
                                <span className="text-coral-deep">no rate set</span>
                              ) : (
                                formatMoney(n.price, quoteQuery.data.currency)
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr>
                          <td className="font-semibold">Total</td>
                          <td className="text-right font-mono font-semibold tabular-nums">
                            {formatMoney(
                              quoteQuery.data.total,
                              quoteQuery.data.currency,
                            )}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                    {!quoteQuery.data.fully_priced && (
                      <p className="mt-2 text-sm text-coral-deep">
                        {quoteQuery.data.missing_dates.length} night(s) have no
                        configured rate; the total is partial.
                      </p>
                    )}
                    <p className="mt-2 text-sm text-ink/60">
                      Booked amount:{" "}
                      <span className="font-mono font-semibold text-ink tabular-nums">
                        {formatMoney(booking.final_price, hotelQuery.data?.currency)}
                      </span>{" "}
                      (from rates{quoteQuery.data.fully_priced ? "" : ", partial"})
                    </p>
                  </div>
                ) : null}
              </section>
            </div>

            <div className="space-y-6">
              <section className="panel p-5" aria-label="Status actions">
                <h2 className="panel-title mb-3">Status</h2>
                <FormError error={actionError} />
                {nextStatuses.length === 0 ? (
                  <p className="text-sm text-ink/60">
                    This booking is {booking.booking_status.replace(/_/g, " ").toLowerCase()}; no
                    further status changes are allowed.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {nextStatuses.map((s) =>
                      confirming === s ? (
                        <div key={s} className="rounded-lg border border-sun bg-sun/15 p-3">
                          <p className="text-sm font-medium">
                            {s === "CANCELLED"
                              ? `Cancel booking #${booking.id}?`
                              : `Move booking #${booking.id} to ${s.replace(/_/g, " ")}?`}
                          </p>
                          <div className="mt-2 flex gap-2">
                            <button
                              type="button"
                              className={s === "CANCELLED" ? "btn btn-danger" : "btn btn-primary"}
                              disabled={pending}
                              onClick={() => moveTo(s)}
                            >
                              {s === "CANCELLED" ? "Yes, cancel" : `Yes, ${STATUS_LABEL[s].toLowerCase()}`}
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={() => setConfirming(null)}
                            >
                              Keep as is
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          key={s}
                          type="button"
                          className={s === "CANCELLED" ? "btn btn-danger" : "btn btn-primary"}
                          disabled={pending}
                          onClick={() => setConfirming(s)}
                        >
                          {s === "CANCELLED"
                            ? "Cancel booking"
                            : STATUS_LABEL[s]}
                        </button>
                      ),
                    )}
                  </div>
                )}
                <button
                  type="button"
                  className="btn btn-secondary mt-4 w-full"
                  disabled={pending}
                  onClick={onDelete}
                >
                  Delete booking
                </button>
              </section>

              <section className="panel p-5" aria-label="Guest">
                <h2 className="panel-title mb-3">Guest</h2>
                {guestQuery.data ? (
                  <dl className="space-y-2 text-sm">
                    <div>
                      <dt className="text-ink/60">Name</dt>
                      <dd>
                        <Link
                          to={`/guests/${guestQuery.data.id}`}
                          className="font-medium text-deep-teal underline"
                        >
                          {guestQuery.data.name}
                        </Link>
                      </dd>
                    </div>
                    {guestQuery.data.phone && (
                      <div>
                        <dt className="text-ink/60">Phone</dt>
                        <dd className="font-mono">{guestQuery.data.phone}</dd>
                      </div>
                    )}
                    {guestQuery.data.email && (
                      <div>
                        <dt className="text-ink/60">Email</dt>
                        <dd>{guestQuery.data.email}</dd>
                      </div>
                    )}
                  </dl>
                ) : (
                  <p className="text-sm text-ink/60">Guest #{booking.guest_id}</p>
                )}
              </section>
            </div>
          </div>
        )}
      </DetailState>
    </div>
  );
}
