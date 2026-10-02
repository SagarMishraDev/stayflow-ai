import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useBookings,
  useCreate,
  useGuests,
  useHotel,
  useRooms,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  bookingCreateSchema,
  formatDate,
  formatMoney,
  todayISO,
  type BookingCreateForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import StatusBadge from "../components/StatusBadge";
import type { BookingStatus } from "../lib/types";

const STATUS_FILTERS: (BookingStatus | "ALL")[] = [
  "ALL",
  "PENDING",
  "CONFIRMED",
  "CHECKED_IN",
  "CHECKED_OUT",
  "CANCELLED",
];

export default function Bookings() {
  const { hotelId } = useAuth();
  const [statusFilter, setStatusFilter] = useState<BookingStatus | "ALL">("ALL");
  const [guestFilter, setGuestFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const bookingsQuery = useBookings(hotelId);
  const guestsQuery = useGuests(hotelId);
  const roomsQuery = useRooms(hotelId);
  const hotelQuery = useHotel(hotelId);

  const guestName = useMemo(() => {
    const map = new Map<number, string>();
    (guestsQuery.data ?? []).forEach((g) => map.set(g.id, g.name));
    return (id: number) => map.get(id) ?? `Guest #${id}`;
  }, [guestsQuery.data]);
  const roomName = useMemo(() => {
    const map = new Map<number, string>();
    (roomsQuery.data ?? []).forEach((r) => map.set(r.id, r.room_type));
    return (id: number) => map.get(id) ?? `Room #${id}`;
  }, [roomsQuery.data]);

  const filtered = useMemo(() => {
    let items = bookingsQuery.data ?? [];
    if (statusFilter !== "ALL")
      items = items.filter((b) => b.booking_status === statusFilter);
    if (guestFilter.trim()) {
      const q = guestFilter.trim().toLowerCase();
      items = items.filter(
        (b) =>
          guestName(b.guest_id).toLowerCase().includes(q) ||
          String(b.id).includes(q),
      );
    }
    return [...items].sort((a, b) => b.id - a.id);
  }, [bookingsQuery.data, statusFilter, guestFilter, guestName]);

  return (
    <div>
      <PageHeader
        title="Bookings"
        description="Filter by status or guest, then open a booking for its price breakdown and status actions."
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowCreate(true)}
          >
            New booking
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              aria-pressed={statusFilter === s}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                statusFilter === s
                  ? "bg-pine-950 text-white"
                  : "border border-pine-950/25 bg-parchment hover:bg-pine-50"
              }`}
            >
              {s === "ALL" ? "All" : s.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">Search by guest or booking number</span>
          <input
            type="search"
            className="input !w-56"
            placeholder="Guest or #booking"
            value={guestFilter}
            onChange={(e) => setGuestFilter(e.target.value)}
          />
        </label>
      </div>

      <ListState
        query={bookingsQuery}
        emptyTitle="No bookings yet"
        emptyHint="Create the first booking for this hotel to get started."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            New booking
          </button>
        }
        render={() =>
          filtered.length === 0 ? (
            <div className="panel p-8 text-center">
              <p className="font-semibold">No bookings match these filters</p>
              <p className="mt-1 text-sm text-ink/70">
                Try a different status or clear the search.
              </p>
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Booking</th>
                    <th>Guest</th>
                    <th>Room type</th>
                    <th>Stay</th>
                    <th>Guests</th>
                    <th>Status</th>
                    <th>Amount</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((b) => (
                    <tr key={b.id}>
                      <td className="font-mono">#{b.id}</td>
                      <td>{guestName(b.guest_id)}</td>
                      <td>{roomName(b.room_id)}</td>
                      <td className="whitespace-nowrap">
                        {formatDate(b.check_in)} → {formatDate(b.check_out)}
                      </td>
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
          )
        }
      />

      {showCreate && hotelId && (
        <CreateBookingModal
          hotelId={hotelId}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}

function CreateBookingModal({
  hotelId,
  onClose,
}: {
  hotelId: number;
  onClose: () => void;
}) {
  const guestsQuery = useGuests(hotelId);
  const roomsQuery = useRooms(hotelId);
  const create = useCreate("/bookings", [qk.bookings(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<BookingCreateForm>({
    resolver: zodResolver(bookingCreateSchema),
    defaultValues: {
      check_in: todayISO(),
      booking_status: "PENDING",
      number_of_guests: 1,
    },
  });

  async function onSubmit(values: BookingCreateForm) {
    setServerError(null);
    try {
      await create.mutateAsync({
        hotel_id: hotelId,
        guest_id: values.guest_id,
        room_id: values.room_id,
        check_in: values.check_in,
        check_out: values.check_out,
        number_of_guests: values.number_of_guests,
        final_price: values.final_price || null,
        booking_status: values.booking_status,
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title="New booking" onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Guest" htmlFor="bk-guest" error={errors.guest_id?.message}>
          <select id="bk-guest" className="input" {...register("guest_id")}>
            <option value="">Select a guest…</option>
            {(guestsQuery.data ?? []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Room type" htmlFor="bk-room" error={errors.room_id?.message}>
          <select id="bk-room" className="input" {...register("room_id")}>
            <option value="">Select a room type…</option>
            {(roomsQuery.data ?? [])
              .filter((r) => r.is_active)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.room_type} (sleeps {r.capacity})
                </option>
              ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Check-in" htmlFor="bk-in" error={errors.check_in?.message}>
            <TextInput id="bk-in" name="check_in" register={register} type="date" />
          </Field>
          <Field label="Check-out" htmlFor="bk-out" error={errors.check_out?.message}>
            <TextInput id="bk-out" name="check_out" register={register} type="date" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field
            label="Guests"
            htmlFor="bk-guests"
            error={errors.number_of_guests?.message}
          >
            <TextInput
              id="bk-guests"
              name="number_of_guests"
              register={register}
              type="number"
              min={1}
            />
          </Field>
          <Field
            label="Final price (optional)"
            htmlFor="bk-price"
            error={errors.final_price?.message}
          >
            <TextInput
              id="bk-price"
              name="final_price"
              register={register}
              inputMode="decimal"
              placeholder="Leave blank to price from rates"
            />
          </Field>
        </div>
        <p className="text-xs text-ink/60">
          Leave the price blank and the server computes it from configured
          rates. A supplied price that disagrees with the computed total is
          rejected.
        </p>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create booking"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
