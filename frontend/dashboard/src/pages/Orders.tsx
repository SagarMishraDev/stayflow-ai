import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  qk,
  useGuests,
  useHotelRooms,
  useMenuItems,
  useOrderItems,
  useOrders,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import { formatDateTime, formatMoney } from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { FormError } from "../components/Form";
import StatusBadge from "../components/StatusBadge";
import type { Order, OrderStatus } from "../lib/types";

/* Mirrors ORDER_STATUSES in backend/app/schemas/order.py. */
const STATUSES: OrderStatus[] = [
  "PENDING",
  "CONFIRMED",
  "PREPARING",
  "READY",
  "DELIVERED",
  "CANCELLED",
];

const STATUS_FILTERS: (OrderStatus | "ALL")[] = ["ALL", ...STATUSES];

/** Sensible forward moves per status; the full list stays available in the select. */
const NEXT_STATUS: Partial<Record<OrderStatus, OrderStatus[]>> = {
  PENDING: ["CONFIRMED", "CANCELLED"],
  CONFIRMED: ["PREPARING", "CANCELLED"],
  PREPARING: ["READY", "CANCELLED"],
  READY: ["DELIVERED"],
};

export default function Orders() {
  const { hotelId } = useAuth();
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "ALL">("ALL");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const ordersQuery = useOrders(hotelId);
  const guestsQuery = useGuests(hotelId);
  const roomsQuery = useHotelRooms(hotelId);

  const update = useUpdate((id) => `/orders/${id}`, [qk.orders(hotelId)]);

  const guestName = useMemo(() => {
    const map = new Map<number, string>();
    (guestsQuery.data ?? []).forEach((g) => map.set(g.id, g.name));
    return (id: number) => map.get(id) ?? `Guest #${id}`;
  }, [guestsQuery.data]);

  const roomNumber = useMemo(() => {
    const map = new Map<number, string>();
    (roomsQuery.data ?? []).forEach((r) => map.set(r.id, r.room_number));
    return (id: number | null) =>
      id === null ? "—" : (map.get(id) ?? `Room record #${id}`);
  }, [roomsQuery.data]);

  const filtered = useMemo(() => {
    let items = ordersQuery.data ?? [];
    if (statusFilter !== "ALL")
      items = items.filter((o) => o.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      items = items.filter(
        (o) =>
          guestName(o.guest_id).toLowerCase().includes(q) ||
          String(o.id).includes(q) ||
          o.order_type.toLowerCase().includes(q),
      );
    }
    return [...items].sort((a, b) => b.id - a.id);
  }, [ordersQuery.data, statusFilter, search, guestName]);

  async function setStatus(order: Order, status: OrderStatus) {
    setActionError(null);
    try {
      await update.mutateAsync({ id: order.id, data: { status } });
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Food orders"
        description="Guest food and room-service orders. Totals are calculated by the server from menu prices — update the status as each order moves through the kitchen."
      />
      <FormError error={actionError} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div
          role="group"
          aria-label="Filter by status"
          className="flex flex-wrap gap-1.5"
        >
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              aria-pressed={statusFilter === s}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                statusFilter === s
                  ? "bg-deep-teal text-white"
                  : "border border-line bg-paper hover:bg-mist"
              }`}
            >
              {s === "ALL" ? "All" : s.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">Search by guest, order number, or type</span>
          <input
            type="search"
            className="input !w-56"
            placeholder="Guest, #order, or type"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>

      <ListState
        query={ordersQuery}
        emptyTitle="No food orders yet"
        emptyHint="Orders placed by guests through the concierge will appear here."
        render={() =>
          filtered.length === 0 ? (
            <div className="panel p-8 text-center">
              <p className="font-semibold">No orders match this filter</p>
              <p className="mt-1 text-sm text-ink/70">
                Try another status or search term.
              </p>
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Guest</th>
                    <th>Type</th>
                    <th>Room / table</th>
                    <th>Total</th>
                    <th>Status</th>
                    <th>Placed</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((order) => (
                    <OrderRow
                      key={order.id}
                      order={order}
                      guest={guestName(order.guest_id)}
                      roomLabel={roomNumber(order.room_id)}
                      expanded={expandedId === order.id}
                      onToggle={() =>
                        setExpandedId(expandedId === order.id ? null : order.id)
                      }
                      onStatus={(s) => setStatus(order, s)}
                      saving={update.isPending}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      />
    </div>
  );
}

function OrderRow({
  order,
  guest,
  roomLabel,
  expanded,
  onToggle,
  onStatus,
  saving,
}: {
  order: Order;
  guest: string;
  roomLabel: string;
  expanded: boolean;
  onToggle: () => void;
  onStatus: (status: OrderStatus) => void;
  saving: boolean;
}) {
  const quickMoves = NEXT_STATUS[order.status] ?? [];
  return (
    <>
      <tr className={!order.is_active ? "opacity-60" : ""}>
        <td className="font-mono tabular-nums">#{order.id}</td>
        <td>
          <Link
            to={`/guests/${order.guest_id}`}
            className="font-medium text-deep-teal underline"
          >
            {guest}
          </Link>
        </td>
        <td>{order.order_type.replace(/_/g, " ")}</td>
        <td>
          {order.room_id !== null
            ? roomLabel
            : order.table_number !== null
              ? `Table ${order.table_number}`
              : "—"}
        </td>
        <td className="font-mono tabular-nums">
          {formatMoney(order.total_amount)}
        </td>
        <td>
          <StatusBadge status={order.status} />
        </td>
        <td className="whitespace-nowrap">{formatDateTime(order.created_at)}</td>
        <td className="whitespace-nowrap">
          <button
            type="button"
            className="mr-3 font-medium text-deep-teal underline"
            onClick={onToggle}
            aria-expanded={expanded}
          >
            {expanded ? "Hide items" : "Items"}
          </button>
          <label className="sr-only" htmlFor={`order-status-${order.id}`}>
            Update status for order {order.id}
          </label>
          <select
            id={`order-status-${order.id}`}
            className="input !w-auto !py-1.5 !text-xs"
            value={order.status}
            disabled={saving}
            onChange={(e) => onStatus(e.target.value as OrderStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          {quickMoves.length > 0 && (
            <span className="ml-2 inline-flex gap-1.5">
              {quickMoves.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="btn btn-secondary !py-1 !text-xs"
                  disabled={saving}
                  onClick={() => onStatus(s)}
                >
                  {s === "CANCELLED"
                    ? "Cancel"
                    : `Mark ${s.replace(/_/g, " ").toLowerCase()}`}
                </button>
              ))}
            </span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} className="bg-mist/50">
            <OrderItems orderId={order.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function OrderItems({ orderId }: { orderId: number }) {
  const { hotelId } = useAuth();
  const itemsQuery = useOrderItems(orderId);
  const menuQuery = useMenuItems(hotelId);

  const itemName = useMemo(() => {
    const map = new Map<number, string>();
    (menuQuery.data ?? []).forEach((m) => map.set(m.id, m.name));
    return (id: number) => map.get(id) ?? `Menu item #${id}`;
  }, [menuQuery.data]);

  if (itemsQuery.isLoading) {
    return (
      <div aria-busy="true" className="space-y-2 p-2">
        <div className="h-8 animate-pulse rounded bg-ink/10" />
        <span className="sr-only">Loading order items…</span>
      </div>
    );
  }
  if (itemsQuery.isError) {
    return (
      <div role="alert" className="p-2 text-sm">
        <p className="font-semibold">Couldn't load the items for this order</p>
        <p className="mt-1 text-ink/70">{apiErrorMessage(itemsQuery.error)}</p>
        <button
          type="button"
          className="btn btn-secondary mt-2 !py-1.5 !text-xs"
          onClick={() => itemsQuery.refetch()}
        >
          Try again
        </button>
      </div>
    );
  }
  const items = itemsQuery.data ?? [];
  if (items.length === 0) {
    return <p className="p-2 text-sm text-ink/70">No items recorded for this order.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Item</th>
          <th>Qty</th>
          <th>Unit price</th>
          <th>Notes</th>
          <th>Subtotal</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td className="font-medium">{itemName(item.menu_item_id)}</td>
            <td className="font-mono tabular-nums">{item.quantity}</td>
            <td className="font-mono tabular-nums">
              {formatMoney(item.unit_price)}
            </td>
            <td>{item.customization ?? "—"}</td>
            <td className="font-mono tabular-nums">
              {formatMoney(item.subtotal)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
