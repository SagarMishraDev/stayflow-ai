import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  useAvailabilityRows,
  useCreate,
  useHotel,
  useHotelRooms,
  useRates,
  useRemove,
  useRooms,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  bulkRateSchema,
  formatDate,
  formatMoney,
  hotelRoomSchema,
  rateSchema,
  roomSchema,
  type BulkRateForm,
  type HotelRoomForm,
  type RateForm,
  type RoomForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";

function isoOf(y: number, m: number, day: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return isoOf(d.getFullYear(), d.getMonth(), d.getDate());
}

export default function RoomsRates() {
  const { hotelId } = useAuth();
  const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);
  const [month, setMonth] = useState(() => new Date());
  const [showRoomModal, setShowRoomModal] = useState(false);
  const [showBulkModal, setShowBulkModal] = useState(false);
  const [showPhysicalModal, setShowPhysicalModal] = useState(false);
  const [editingRate, setEditingRate] = useState<{
    date: string;
    rateId: number | null;
    price: string;
  } | null>(null);

  const roomsQuery = useRooms(hotelId);
  const ratesQuery = useRates(selectedRoomId);
  const hotelRoomsQuery = useHotelRooms(hotelId);
  const availabilityQuery = useAvailabilityRows(selectedRoomId);
  const hotelQuery = useHotel(hotelId);

  const rooms = roomsQuery.data ?? [];
  const selectedRoom = rooms.find((r) => r.id === selectedRoomId) ?? null;

  const rateByDate = useMemo(() => {
    const map = new Map<string, { id: number; price: string }>();
    (ratesQuery.data ?? []).forEach((r) => {
      if (r.is_active) map.set(r.date, { id: r.id, price: r.price });
    });
    return map;
  }, [ratesQuery.data]);

  const availByDate = useMemo(() => {
    const map = new Map<string, number>();
    (availabilityQuery.data ?? []).forEach((a) => {
      if (a.is_active) map.set(a.date, a.available_rooms);
    });
    return map;
  }, [availabilityQuery.data]);

  const days = useMemo(() => {
    const y = month.getFullYear();
    const m = month.getMonth();
    const first = new Date(y, m, 1);
    const startPad = first.getDay(); // 0 = Sunday
    const total = new Date(y, m + 1, 0).getDate();
    const cells: (string | null)[] = [];
    for (let i = 0; i < startPad; i++) cells.push(null);
    for (let d = 1; d <= total; d++) cells.push(isoOf(y, m, d));
    return cells;
  }, [month]);

  return (
    <div>
      <PageHeader
        title="Rooms & rates"
        description="Room types, nightly rates on a calendar, and the physical rooms behind each type."
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setShowRoomModal(true)}>
              Add room type
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowPhysicalModal(true)}>
              Add physical room
            </button>
          </>
        }
      />

      {/* Room type selector */}
      <section aria-label="Room types" className="mb-6">
        <ListState
          query={roomsQuery}
          emptyTitle="No room types yet"
          emptyHint="Add a room type (e.g. Deluxe King) before you can set rates."
          emptyAction={
            <button type="button" className="btn btn-primary" onClick={() => setShowRoomModal(true)}>
              Add room type
            </button>
          }
          render={(list) => (
            <div className="flex flex-wrap gap-2" role="listbox" aria-label="Choose a room type">
              {list.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="option"
                  aria-selected={selectedRoomId === r.id}
                  onClick={() => setSelectedRoomId(r.id)}
                  className={`rounded-xl border px-4 py-2.5 text-left ${
                    selectedRoomId === r.id
                      ? "border-deep-teal bg-deep-teal text-white"
                      : "border-line bg-paper hover:border-teal"
                  }`}
                >
                  <span className="block text-sm font-semibold">{r.room_type}</span>
                  <span className={`block text-xs ${selectedRoomId === r.id ? "text-white/70" : "text-ink/60"}`}>
                    Sleeps {r.capacity} · {r.total_rooms} rooms
                    {!r.is_active && " · inactive"}
                  </span>
                </button>
              ))}
            </div>
          )}
        />
      </section>

      {selectedRoom && (
        <section aria-label={`Rates for ${selectedRoom.room_type}`} className="mb-6">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="panel-title">
              Nightly rates — {selectedRoom.room_type}
            </h2>
            <div className="flex items-center gap-2">
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
              <button type="button" className="btn btn-primary" onClick={() => setShowBulkModal(true)}>
                Bulk set rates
              </button>
            </div>
          </div>

          {ratesQuery.isLoading ? (
            <div aria-busy="true" className="grid grid-cols-7 gap-1.5" aria-label="Loading rates">
              {Array.from({ length: 35 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-mist" />
              ))}
              <span className="sr-only">Loading rates…</span>
            </div>
          ) : ratesQuery.isError ? (
            <div role="alert" className="panel p-6 text-center">
              <p className="font-semibold">Couldn't load rates</p>
              <p className="mt-1 text-sm text-ink/70">{apiErrorMessage(ratesQuery.error)}</p>
              <button type="button" className="btn btn-secondary mt-4" onClick={() => ratesQuery.refetch()}>
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
                {days.map((iso, i) =>
                  iso === null ? (
                    <div key={`pad-${i}`} className="min-h-16 bg-paper" />
                  ) : (
                    <RateCell
                      key={iso}
                      date={iso}
                      rate={rateByDate.get(iso)}
                      available={availByDate.get(iso)}
                      currency={hotelQuery.data?.currency ?? "INR"}
                      onEdit={() =>
                        setEditingRate({
                          date: iso,
                          rateId: rateByDate.get(iso)?.id ?? null,
                          price: rateByDate.get(iso)?.price ?? "",
                        })
                      }
                    />
                  ),
                )}
              </div>
              <p className="border-t border-line px-4 py-2 text-xs text-ink/60">
                Select a day to set or change its rate. Cells marked "no rate" are
                priced as missing when a booking is quoted.
              </p>
            </div>
          )}
        </section>
      )}

      {/* Physical rooms */}
      {selectedRoom && (
        <section aria-label="Physical rooms" className="mb-6">
          <h2 className="panel-title mb-3">
            Physical rooms — {selectedRoom.room_type}
          </h2>
          <ListState
            query={hotelRoomsQuery}
            emptyTitle="No physical rooms added"
            emptyHint="Add room numbers (e.g. 201) so the team knows which doors exist."
            skeletonRows={3}
            render={(list) => {
              const mine = list.filter((hr) => hr.room_id === selectedRoomId);
              if (mine.length === 0)
                return (
                  <p className="panel p-5 text-sm text-ink/60">
                    No physical rooms for this room type yet.
                  </p>
                );
              return (
                <ul className="flex flex-wrap gap-2">
                  {mine.map((hr) => (
                    <li
                      key={hr.id}
                      className={`rounded-lg border px-3 py-2 font-mono text-sm ${
                        hr.is_active
                          ? "border-line bg-paper"
                          : "border-line bg-mist text-ink/50 line-through"
                      }`}
                    >
                      {hr.room_number}
                    </li>
                  ))}
                </ul>
              );
            }}
          />
        </section>
      )}

      {/* Modals */}
      {showRoomModal && hotelId && (
        <RoomModal hotelId={hotelId} onClose={() => setShowRoomModal(false)} />
      )}
      {showBulkModal && selectedRoom && hotelId && (
        <BulkRateModal
          roomId={selectedRoom.id}
          roomType={selectedRoom.room_type}
          currency={hotelQuery.data?.currency ?? "INR"}
          onClose={() => setShowBulkModal(false)}
        />
      )}
      {showPhysicalModal && selectedRoomId && hotelId && (
        <PhysicalRoomModal
          roomId={selectedRoomId}
          hotelId={hotelId}
          onClose={() => setShowPhysicalModal(false)}
        />
      )}
      {editingRate && selectedRoom && hotelId && (
        <EditRateModal
          roomId={selectedRoom.id}
          currency={hotelQuery.data?.currency ?? "INR"}
          editing={editingRate}
          onClose={() => setEditingRate(null)}
        />
      )}
    </div>
  );
}

function RateCell({
  date,
  rate,
  available,
  currency,
  onEdit,
}: {
  date: string;
  rate: { id: number; price: string } | undefined;
  available: number | undefined;
  currency: string;
  onEdit: () => void;
}) {
  const dayNum = parseInt(date.slice(8, 10), 10);
  return (
    <button
      type="button"
      onClick={onEdit}
      aria-label={`${formatDate(date)}: ${rate ? formatMoney(rate.price, currency) : "no rate set"}`}
      className={`min-h-16 bg-paper p-1.5 text-left hover:bg-mist ${
        rate ? "" : "bg-sun/15"
      }`}
    >
      <span className="block text-xs font-semibold text-ink/60">{dayNum}</span>
      {rate ? (
        <span className="block font-mono text-xs font-semibold tabular-nums">
          {formatMoney(rate.price, currency).replace(/\.00$/, "")}
        </span>
      ) : (
        <span className="block text-xs text-ink/50">no rate</span>
      )}
      {available !== undefined && (
        <span className="block text-[11px] text-ink/50">{available} left</span>
      )}
    </button>
  );
}

function RoomModal({ hotelId, onClose }: { hotelId: number; onClose: () => void }) {
  const create = useCreate("/rooms", [[ "rooms", hotelId ]]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RoomForm>({ resolver: zodResolver(roomSchema) });

  async function onSubmit(values: RoomForm) {
    setServerError(null);
    try {
      await create.mutateAsync({
        hotel_id: hotelId,
        room_type: values.room_type,
        description: values.description || null,
        capacity: values.capacity,
        total_rooms: values.total_rooms,
        amenities: values.amenities || null,
        is_active: values.is_active,
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title="Add room type" onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Room type name" htmlFor="rm-type" error={errors.room_type?.message}>
          <TextInput id="rm-type" name="room_type" register={register} placeholder="Deluxe King" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Sleeps (capacity)" htmlFor="rm-cap" error={errors.capacity?.message}>
            <TextInput id="rm-cap" name="capacity" register={register} type="number" min={1} />
          </Field>
          <Field label="Number of rooms" htmlFor="rm-total" error={errors.total_rooms?.message}>
            <TextInput id="rm-total" name="total_rooms" register={register} type="number" min={1} />
          </Field>
        </div>
        <Field label="Description" htmlFor="rm-desc">
          <textarea id="rm-desc" className="input" rows={2} {...register("description")} />
        </Field>
        <Field label="Amenities" htmlFor="rm-amen">
          <TextInput id="rm-amen" name="amenities" register={register} placeholder="Wi-Fi, sea view…" />
        </Field>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Add room type"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function BulkRateModal({
  roomId,
  roomType,
  currency,
  onClose,
}: {
  roomId: number;
  roomType: string;
  currency: string;
  onClose: () => void;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const create = useCreate("/rates", [["rates", roomId]]);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<BulkRateForm>({ resolver: zodResolver(bulkRateSchema) });

  async function onSubmit(values: BulkRateForm) {
    setServerError(null);
    try {
      const dates: string[] = [];
      let d = values.start_date;
      while (d <= values.end_date) {
        dates.push(d);
        d = addDays(d, 1);
      }
      let done = 0;
      for (const date of dates) {
        setProgress(`Saving ${++done} of ${dates.length}…`);
        await create.mutateAsync({
          room_id: roomId,
          date,
          price: values.price,
          currency: values.currency,
          is_active: true,
        });
      }
      onClose();
    } catch (e) {
      setProgress(null);
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={`Bulk set rates — ${roomType}`} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="grid grid-cols-2 gap-4">
          <Field label="From" htmlFor="br-from" error={errors.start_date?.message}>
            <TextInput id="br-from" name="start_date" register={register} type="date" />
          </Field>
          <Field label="To" htmlFor="br-to" error={errors.end_date?.message}>
            <TextInput id="br-to" name="end_date" register={register} type="date" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label={`Nightly price (${currency})`} htmlFor="br-price" error={errors.price?.message}>
            <TextInput id="br-price" name="price" register={register} inputMode="decimal" />
          </Field>
          <Field label="Currency" htmlFor="br-cur">
            <TextInput id="br-cur" name="currency" register={register} defaultValue={currency} />
          </Field>
        </div>
        <p className="text-xs text-ink/60">
          One rate record is created per night in the range. If a night already
          has a rate, the server may reject the duplicate — narrow the range
          and retry.
        </p>
        {progress && <p className="text-sm text-ink/70" aria-live="polite">{progress}</p>}
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Set rates"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function EditRateModal({
  roomId,
  currency,
  editing,
  onClose,
}: {
  roomId: number;
  currency: string;
  editing: { date: string; rateId: number | null; price: string };
  onClose: () => void;
}) {
  const create = useCreate("/rates", [["rates", roomId]]);
  const update = useUpdate((id: number) => `/rates/${id}`, [["rates", roomId]]);
  const remove = useRemove((id: number) => `/rates/${id}`, [["rates", roomId]]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RateForm>({
    resolver: zodResolver(rateSchema),
    defaultValues: { room_id: roomId, date: editing.date, currency },
  });

  async function onSubmit(values: RateForm) {
    setServerError(null);
    try {
      if (editing.rateId) {
        await update.mutateAsync({
          id: editing.rateId,
          data: { price: values.price, currency: values.currency },
        });
      } else {
        await create.mutateAsync({
          room_id: roomId,
          date: editing.date,
          price: values.price,
          currency: values.currency,
          is_active: true,
        });
      }
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  async function onDelete() {
    if (!editing.rateId) return;
    setServerError(null);
    try {
      await remove.mutateAsync(editing.rateId);
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={`Rate — ${formatDate(editing.date)}`} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label={`Price (${currency})`} htmlFor="er-price" error={errors.price?.message}>
          <TextInput
            id="er-price"
            name="price"
            register={register}
            inputMode="decimal"
            defaultValue={editing.price}
          />
        </Field>
        <FormError error={serverError} />
        <div className="flex justify-between gap-2">
          <div>
            {editing.rateId && (
              <button type="button" className="btn btn-danger" onClick={onDelete} disabled={remove.isPending}>
                {remove.isPending ? "Removing…" : "Remove rate"}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={create.isPending || update.isPending}
            >
              {create.isPending || update.isPending ? "Saving…" : "Save rate"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function PhysicalRoomModal({
  hotelId,
  roomId,
  onClose,
}: {
  hotelId: number;
  roomId: number;
  onClose: () => void;
}) {
  const create = useCreate("/hotel-rooms", [["hotel-rooms", hotelId]]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<HotelRoomForm>({
    resolver: zodResolver(hotelRoomSchema),
    defaultValues: { room_id: roomId },
  });

  async function onSubmit(values: HotelRoomForm) {
    setServerError(null);
    try {
      await create.mutateAsync({
        hotel_id: hotelId,
        room_id: values.room_id,
        room_number: values.room_number,
        is_active: values.is_active,
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title="Add physical room" onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Room number" htmlFor="pr-num" error={errors.room_number?.message}>
          <TextInput id="pr-num" name="room_number" register={register} placeholder="201" />
        </Field>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Add room"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
