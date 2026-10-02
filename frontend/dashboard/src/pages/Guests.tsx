import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useBookings,
  useConversations,
  useCreate,
  useGuest,
  useGuests,
  useList,
  useServiceRequests,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  guestSchema,
  type GuestForm,
} from "../lib/schemas";
import {
  DetailState,
  ListState,
  PageHeader,
} from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import StatusBadge from "../components/StatusBadge";

export function Guests() {
  const { hotelId } = useAuth();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const guestsQuery = useGuests(hotelId);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const items = guestsQuery.data ?? [];
    if (!q) return items;
    return items.filter(
      (g) =>
        g.name.toLowerCase().includes(q) ||
        (g.phone ?? "").toLowerCase().includes(q) ||
        (g.email ?? "").toLowerCase().includes(q),
    );
  }, [guestsQuery.data, search]);

  return (
    <div>
      <PageHeader
        title="Guests"
        description="Everyone the hotel knows — profiles, stays, orders, requests, and chats."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Add guest
          </button>
        }
      />
      <label className="mb-4 block max-w-sm text-sm">
        <span className="sr-only">Search guests</span>
        <input
          type="search"
          className="input"
          placeholder="Search by name, phone, or email"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <ListState
        query={guestsQuery}
        emptyTitle="No guests yet"
        emptyHint="Guests are created automatically by the concierge, or add one manually."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Add guest
          </button>
        }
        render={() =>
          filtered.length === 0 ? (
            <div className="panel p-8 text-center">
              <p className="font-semibold">No guests match "{search}"</p>
              <p className="mt-1 text-sm text-ink/70">Try a different search.</p>
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Email</th>
                    <th>Nationality</th>
                    <th>Active</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((g) => (
                    <tr key={g.id} className={!g.is_active ? "opacity-60" : ""}>
                      <td className="font-medium">{g.name}</td>
                      <td className="font-mono">{g.phone ?? "—"}</td>
                      <td>{g.email ?? "—"}</td>
                      <td>{g.nationality ?? "—"}</td>
                      <td>{g.is_active ? "Yes" : "No"}</td>
                      <td>
                        <Link to={`/guests/${g.id}`} className="font-medium text-pine-700 underline">
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
        <GuestModal hotelId={hotelId} onClose={() => setShowCreate(false)} />
      )}
    </div>
  );
}

interface OrderSummary {
  id: number;
  order_type: string;
  status: string;
  total_amount: string;
  created_at: string;
}

export function GuestDetail() {
  const { id } = useParams<{ id: string }>();
  const guestId = id ? parseInt(id, 10) : null;
  const { hotelId } = useAuth();
  const [showEdit, setShowEdit] = useState(false);

  const guestQuery = useGuest(guestId);
  const bookingsQuery = useBookings(hotelId, guestId);
  const ordersQuery = useList<OrderSummary>(
    ["orders", "guest", guestId ?? "none"],
    "/orders",
    { guest_id: guestId ?? undefined },
    { enabled: guestId !== null },
  );
  const requestsQuery = useServiceRequests(hotelId);
  const conversationsQuery = useConversations(hotelId);

  const guestRequests = useMemo(
    () =>
      (requestsQuery.data ?? []).filter((r) => r.guest_id === guestId),
    [requestsQuery.data, guestId],
  );
  const guestChats = useMemo(
    () =>
      (conversationsQuery.data ?? []).filter((c) => c.guest_id === guestId),
    [conversationsQuery.data, guestId],
  );

  const guest = guestQuery.data;

  return (
    <div>
      <PageHeader
        title={guest ? guest.name : "Guest"}
        actions={
          <>
            <Link to="/guests" className="btn btn-secondary">
              Back to guests
            </Link>
            {guest && (
              <button type="button" className="btn btn-primary" onClick={() => setShowEdit(true)}>
                Edit profile
              </button>
            )}
          </>
        }
      />
      <DetailState
        isLoading={guestQuery.isLoading}
        isError={guestQuery.isError}
        error={guestQuery.error}
        onRetry={() => guestQuery.refetch()}
      >
        {guest && (
          <div className="space-y-6">
            <section className="panel p-5" aria-label="Profile">
              <h2 className="panel-title mb-3">Profile</h2>
              <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
                {(
                  [
                    ["Phone", guest.phone],
                    ["Email", guest.email],
                    ["Nationality", guest.nationality],
                    ["Telegram chat", guest.telegram_chat_id],
                    ["WhatsApp", guest.whatsapp_number],
                    ["Preferences", guest.preferences],
                    ["Notes", guest.notes],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-ink/60">{label}</dt>
                    <dd className="font-medium">{value || "—"}</dd>
                  </div>
                ))}
                <div>
                  <dt className="text-ink/60">Active</dt>
                  <dd className="font-medium">{guest.is_active ? "Yes" : "No"}</dd>
                </div>
                <div>
                  <dt className="text-ink/60">Since</dt>
                  <dd className="font-medium">{formatDateTime(guest.created_at)}</dd>
                </div>
              </dl>
            </section>

            <section aria-label="Bookings">
              <h2 className="panel-title mb-3">Bookings</h2>
              <ListState
                query={bookingsQuery}
                emptyTitle="No bookings"
                emptyHint="This guest has no bookings yet."
                skeletonRows={2}
                render={(bookings) => (
                  <div className="panel overflow-x-auto">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>Stay</th>
                          <th>Guests</th>
                          <th>Status</th>
                          <th>Amount</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {bookings.map((b) => (
                          <tr key={b.id}>
                            <td className="font-mono">#{b.id}</td>
                            <td className="whitespace-nowrap">
                              {formatDate(b.check_in)} → {formatDate(b.check_out)}
                            </td>
                            <td className="font-mono tabular-nums">{b.number_of_guests}</td>
                            <td><StatusBadge status={b.booking_status} /></td>
                            <td className="font-mono tabular-nums">{formatMoney(b.final_price)}</td>
                            <td>
                              <Link to={`/bookings/${b.id}`} className="font-medium text-pine-700 underline">
                                Open
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              />
            </section>

            <div className="grid gap-6 lg:grid-cols-3">
              <section aria-label="Orders" className="lg:col-span-1">
                <h2 className="panel-title mb-3">Orders</h2>
                <ListState
                  query={ordersQuery}
                  emptyTitle="No orders"
                  emptyHint="Food and service orders for this guest."
                  skeletonRows={2}
                  render={(orders) => (
                    <ul className="space-y-2">
                      {orders.map((o) => (
                        <li key={o.id} className="panel p-3 text-sm">
                          <p className="font-semibold">
                            Order #{o.id} · {o.order_type.replace(/_/g, " ")}
                          </p>
                          <p className="text-ink/60">
                            {formatDateTime(o.created_at)} · {o.status} ·{" "}
                            <span className="font-mono">{formatMoney(o.total_amount)}</span>
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                />
              </section>

              <section aria-label="Service requests" className="lg:col-span-1">
                <h2 className="panel-title mb-3">Service requests</h2>
                {requestsQuery.isLoading ? (
                  <div aria-busy="true" className="h-16 animate-pulse rounded-xl bg-parchment" aria-label="Loading requests" />
                ) : guestRequests.length === 0 ? (
                  <p className="panel p-4 text-sm text-ink/60">None yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {guestRequests.map((r) => (
                      <li key={r.id} className="panel p-3 text-sm">
                        <p className="font-semibold">#{r.id} · {r.status.replace(/_/g, " ")}</p>
                        <p className="text-ink/60">{r.request_text ?? "—"}</p>
                        <p className="font-mono text-xs text-ink/50">{formatDateTime(r.created_at)}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-label="Conversations" className="lg:col-span-1">
                <h2 className="panel-title mb-3">Conversations</h2>
                {conversationsQuery.isLoading ? (
                  <div aria-busy="true" className="h-16 animate-pulse rounded-xl bg-parchment" aria-label="Loading conversations" />
                ) : guestChats.length === 0 ? (
                  <p className="panel p-4 text-sm text-ink/60">None yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {guestChats.map((c) => (
                      <li key={c.id} className="panel p-3 text-sm">
                        <p className="font-semibold">
                          <Link to={`/conversations/${c.id}`} className="text-pine-700 underline">
                            Chat #{c.id}
                          </Link>
                        </p>
                        <p className="text-ink/60">
                          {c.channel} · {c.status} · {formatDateTime(c.created_at)}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>
        )}
      </DetailState>

      {showEdit && guest && hotelId && (
        <GuestModal
          hotelId={hotelId}
          existing={guest}
          onClose={() => setShowEdit(false)}
        />
      )}
    </div>
  );
}

function GuestModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing?: { id: number; name: string };
  onClose: () => void;
}) {
  const guestQuery = useGuest(existing?.id ?? null);
  const create = useCreate("/guests", [qk.guests(hotelId)]);
  const update = useUpdate((id) => `/guests/${id}`, [
    qk.guests(hotelId),
    ["guest", existing?.id ?? "none"],
  ]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<GuestForm>({
    resolver: zodResolver(guestSchema),
    defaultValues: { is_active: true },
  });

  // Guest data for editing may arrive after the form mounts; sync it in.
  const guestData = guestQuery.data;
  useEffect(() => {
    if (guestData) {
      reset({
        name: guestData.name,
        phone: guestData.phone ?? "",
        email: guestData.email ?? "",
        nationality: guestData.nationality ?? "",
        telegram_chat_id: guestData.telegram_chat_id ?? "",
        whatsapp_number: guestData.whatsapp_number ?? "",
        preferences: guestData.preferences ?? "",
        notes: guestData.notes ?? "",
        is_active: guestData.is_active,
      });
    }
  }, [guestData, reset]);

  function payload(values: GuestForm) {
    const clean = (v: string | undefined) => (v && v.trim() ? v.trim() : null);
    return {
      hotel_id: hotelId,
      name: values.name.trim(),
      phone: clean(values.phone),
      email: clean(values.email),
      nationality: clean(values.nationality),
      telegram_chat_id: clean(values.telegram_chat_id),
      whatsapp_number: clean(values.whatsapp_number),
      preferences: clean(values.preferences),
      notes: clean(values.notes),
      is_active: values.is_active,
    };
  }

  async function onSubmit(values: GuestForm) {
    setServerError(null);
    try {
      if (existing) await update.mutateAsync({ id: existing.id, data: payload(values) });
      else await create.mutateAsync(payload(values));
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={existing ? `Edit ${existing.name}` : "Add guest"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Full name" htmlFor="g-name" error={errors.name?.message}>
          <TextInput id="g-name" name="name" register={register} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Phone" htmlFor="g-phone" error={errors.phone?.message}>
            <TextInput id="g-phone" name="phone" register={register} />
          </Field>
          <Field label="Email" htmlFor="g-email" error={errors.email?.message}>
            <TextInput id="g-email" name="email" register={register} type="email" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Nationality" htmlFor="g-nat">
            <TextInput id="g-nat" name="nationality" register={register} />
          </Field>
          <Field label="WhatsApp number" htmlFor="g-wa">
            <TextInput id="g-wa" name="whatsapp_number" register={register} />
          </Field>
        </div>
        <Field label="Telegram chat ID" htmlFor="g-tg">
          <TextInput id="g-tg" name="telegram_chat_id" register={register} />
        </Field>
        <Field label="Preferences" htmlFor="g-pref">
          <textarea id="g-pref" className="input" rows={2} {...register("preferences")} />
        </Field>
        <Field label="Notes" htmlFor="g-notes">
          <textarea id="g-notes" className="input" rows={2} {...register("notes")} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Guest is active
        </label>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add guest"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
