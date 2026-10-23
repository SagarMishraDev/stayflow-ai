import { api } from "./api";

/** Analytics API client (HMS Phase 4). All values come from the backend
 * aggregations — the dashboard never computes or invents figures. Money
 * arrives as decimal strings. */

export interface KpiOverview {
  total_revenue: string;
  revenue_collected: string;
  pending_payments: string;
  refunds: string;
  total_bookings: number;
  confirmed_bookings: number;
  cancelled_bookings: number;
  average_daily_revenue: string;
  adr: string;
  revpar: string;
  occupancy_rate: number;
  average_booking_value: string;
  occupied_room_nights: number;
  available_room_nights: number;
  rooms_occupied_tonight: number;
  rooms_available_tonight: number;
  period_days: number;
}

export interface SeriesPoint {
  period: string;
  revenue: string;
  bookings: number;
}

export interface CompareResult {
  current: KpiOverview;
  previous: KpiOverview;
  series: { current: SeriesPoint[]; previous: SeriesPoint[] };
  deltas: {
    revenue_diff: string;
    revenue_pct: number | null;
    bookings_diff: number;
    bookings_pct: number | null;
    avg_booking_value_diff: string;
    avg_booking_value_pct: number | null;
    occupancy_diff_points: number;
  };
}

export interface BreakdownRow {
  key: string;
  revenue: string;
  bookings: number;
}

export interface Breakdowns {
  by_room_category: BreakdownRow[];
  by_room: BreakdownRow[];
  by_booking_source: BreakdownRow[];
  by_payment_method: BreakdownRow[];
  by_booking_status: BreakdownRow[];
  by_department: BreakdownRow[];
}

export interface PopularityRow {
  room_id: number;
  room_type: string;
  is_active: boolean;
  total_rooms: number;
  bookings: number;
  revenue: string;
  occupied_room_nights: number;
  available_room_nights: number;
  occupancy_rate: number;
}

export interface Popularity {
  rooms: PopularityRow[];
  most_booked: PopularityRow[];
  least_booked: PopularityRow[];
}

export type ActivityKind =
  | "booking_created"
  | "booking_confirmed"
  | "booking_cancelled"
  | "payment_received"
  | "payment_pending"
  | "refund_processed";

export interface ActivityEvent {
  kind: ActivityKind;
  title: string;
  /** Booking reference, e.g. "#42". */
  reference: string;
  /** Guest · room type, or payment method · booking. */
  summary: string;
  /** Decimal string, INR. */
  amount: string;
  /** ISO timestamp. */
  timestamp: string;
}

export const RANGE_OPTIONS: { key: string; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last_7_days", label: "Last 7 days" },
  { key: "last_30_days", label: "Last 30 days" },
  { key: "week", label: "This week" },
  { key: "last_week", label: "Last week" },
  { key: "month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "quarter", label: "This quarter" },
  { key: "last_quarter", label: "Last quarter" },
  { key: "year", label: "This year" },
  { key: "last_year", label: "Last year" },
  { key: "all", label: "All time" },
  { key: "custom", label: "Custom range" },
];

/** Comparison-period options for the compare endpoint. Range keys
 * resolve independently; "previous_period" is resolved BY THE BACKEND
 * from range A (the equal-length window immediately before it);
 * "none" disables comparison client-side. */
export const COMPARE_OPTIONS: { key: string; label: string }[] = [
  { key: "previous_period", label: "Previous period" },
  ...RANGE_OPTIONS.filter((o) => o.key !== "custom").map((o) => ({
    key: o.key,
    label: o.label,
  })),
  { key: "none", label: "No comparison" },
];

export interface RangeParams {
  range: string;
  start?: string;
  end?: string;
}

function params(hotelId: number, r: RangeParams): Record<string, string | number> {
  const p: Record<string, string | number> = { hotel_id: hotelId, range: r.range };
  if (r.range === "custom") {
    if (r.start) p.start = r.start;
    if (r.end) p.end = r.end;
  }
  return p;
}

export async function fetchOverview(hotelId: number, r: RangeParams): Promise<KpiOverview> {
  const { data } = await api.get("/analytics/overview", { params: params(hotelId, r) });
  return data as KpiOverview;
}

export async function fetchSeries(
  hotelId: number,
  r: RangeParams,
  groupBy: string,
): Promise<SeriesPoint[]> {
  const { data } = await api.get("/analytics/series", {
    params: { ...params(hotelId, r), group_by: groupBy },
  });
  return (data as { series: SeriesPoint[] }).series;
}

export async function fetchCompare(
  hotelId: number,
  a: RangeParams,
  b: RangeParams,
): Promise<CompareResult> {
  const p: Record<string, string | number> = {
    hotel_id: hotelId,
    range_a: a.range,
    range_b: b.range,
  };
  if (a.range === "custom") {
    if (a.start) p.a_start = a.start;
    if (a.end) p.a_end = a.end;
  }
  if (b.range === "custom") {
    if (b.start) p.b_start = b.start;
    if (b.end) p.b_end = b.end;
  }
  const { data } = await api.get("/analytics/compare", { params: p });
  return data as CompareResult;
}

export async function fetchBreakdowns(hotelId: number, r: RangeParams): Promise<Breakdowns> {
  const { data } = await api.get("/analytics/breakdowns", { params: params(hotelId, r) });
  return data as Breakdowns;
}

export async function fetchPopularity(hotelId: number, r: RangeParams): Promise<Popularity> {
  const { data } = await api.get("/analytics/room-popularity", {
    params: params(hotelId, r),
  });
  return data as Popularity;
}

export interface PopularityBucketCell {
  room_type: string;
  bookings: number;
  revenue: string;
}

export interface PopularityBucket {
  period: string;
  rooms: PopularityBucketCell[];
}

export interface PopularitySeries {
  group_by: string;
  period_days: number;
  buckets: PopularityBucket[];
  room_types: PopularityRow[];
}

export async function fetchPopularitySeries(
  hotelId: number,
  r: RangeParams,
  groupBy: string,
): Promise<PopularitySeries> {
  const { data } = await api.get("/analytics/popularity-series", {
    params: { ...params(hotelId, r), group_by: groupBy },
  });
  return data as PopularitySeries;
}

export async function fetchActivity(
  hotelId: number,
  limit = 10,
): Promise<ActivityEvent[]> {
  const { data } = await api.get("/analytics/activity", {
    params: { hotel_id: hotelId, limit },
  });
  return (data as { events: ActivityEvent[] }).events;
}

export async function downloadCsv(
  hotelId: number,
  r: RangeParams,
  dataset: "series" | "room-popularity",
): Promise<void> {
  const { data } = await api.get("/analytics/export", {
    params: { ...params(hotelId, r), dataset, group_by: "day" },
    responseType: "blob",
  });
  const url = URL.createObjectURL(data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${dataset}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
