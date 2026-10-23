import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useAuth } from "../lib/auth";
import {
  COMPARE_OPTIONS,
  downloadCsv,
  fetchActivity,
  fetchBreakdowns,
  fetchCompare,
  fetchOverview,
  fetchPopularitySeries,
  fetchSeries,
  RANGE_OPTIONS,
  type PopularityRow,
  type RangeParams,
} from "../lib/analyticsApi";
import { ChartCard, ChartSkeleton, EmptyState } from "../components/analytics/ChartCard";
import { KpiCard, KpiIcon, Sparkline, type KpiDelta } from "../components/analytics/KpiCard";
import {
  HourlyTrendChart,
  RevenueTrendChart,
  alignMonthPoints,
  type MonthSeries,
} from "../components/analytics/RevenueTrendChart";
import { RoomPopularityBars } from "../components/analytics/RoomPopularityChart";
import {
  DonutChart,
  HorizontalBars,
  VerticalBars,
  type ChartRow,
} from "../components/analytics/BreakdownCharts";
import { RecentActivity } from "../components/analytics/RecentActivity";
import {
  MONTH_SERIES_COLORS,
  buildRoomColorMap,
  inr,
  monthLabel,
  num,
  pctChange,
} from "../components/analytics/format";
import "./analytics.css";

type SortKey = "bookings" | "revenue" | "occupancy";
type PopPeriod = "day" | "week" | "month" | "year";

const GROUP_OPTIONS: { key: string; label: string }[] = [
  { key: "hour", label: "Hourly" },
  { key: "day", label: "Daily" },
  { key: "week", label: "Weekly" },
  { key: "month", label: "Monthly" },
  { key: "year", label: "Yearly" },
];

const POP_PERIOD_OPTIONS: { key: PopPeriod; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "year", label: "Year" },
];

const PAYMENT_STYLE: Record<string, { label: string; color: string }> = {
  upi: { label: "UPI", color: "#0F9D94" },
  card: { label: "Card", color: "#3B82F6" },
  cash: { label: "Cash", color: "#8B5CF6" },
  bank_transfer: { label: "Bank transfer", color: "#F59E0B" },
  other: { label: "Other", color: "#8293A5" },
};

/** Friendly labels for the booking sources the backend actually
 * stamps. Anything unrecognised is shown prettified rather than
 * invented; the backend's own fallback key renders as "Unknown". */
const SOURCE_LABELS: Record<string, string> = {
  agent_chat: "AI concierge",
  widget: "Website widget",
  dashboard: "Front desk",
  direct: "Direct",
  website: "Website",
  walk_in: "Walk-in",
  integration: "Integration",
  unknown: "Unknown",
};

const DEPARTMENT_STYLE: Record<string, { label: string; color: string }> = {
  rooms: { label: "Rooms", color: "#0F9D94" },
  food_and_beverage: { label: "Food & beverage", color: "#087E78" },
};

const PAYMENT_FALLBACK = ["#0F9D94", "#3B82F6", "#8B5CF6", "#F59E0B", "#10B981"];

function prettify(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key;
}

/* ------------------------------------------------------------------ */
/* Four-month windows for the Revenue Trend                            */
/*                                                                     */
/* Rule (approved master revision): the chart shows the month that     */
/* contains the selected range's END date plus the three preceding     */
/* calendar months, in chronological order. Each month is fetched      */
/* separately as a custom range through the existing series API.       */
/* ------------------------------------------------------------------ */

function iso(d: Date): string {
  const pad = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Last day of the selected period (local date), mirroring the
 * backend's resolve_range bounds for each preset key. */
function resolvePeriodEnd(rangeKey: string, customEnd: string): Date {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  switch (rangeKey) {
    case "yesterday":
      return new Date(today.getTime() - 86400000);
    case "last_week": {
      // Backend weeks start Monday: this week's Monday minus one day
      // is last week's Sunday (the last day of the last-week period).
      const dow = (today.getDay() + 6) % 7; // days since Monday
      const monday = new Date(today.getTime() - dow * 86400000);
      return new Date(monday.getTime() - 86400000);
    }
    case "last_month":
      return new Date(today.getFullYear(), today.getMonth(), 0);
    case "last_quarter": {
      const qStartMonth = Math.floor(today.getMonth() / 3) * 3;
      return new Date(today.getFullYear(), qStartMonth, 0);
    }
    case "last_year":
      return new Date(today.getFullYear() - 1, 11, 31);
    case "custom": {
      const parsed = new Date(`${customEnd}T00:00:00`);
      return Number.isNaN(parsed.getTime()) ? today : parsed;
    }
    default:
      return today;
  }
}

interface MonthWindow {
  key: string;
  start: string;
  end: string;
}

function fourMonthWindows(rangeKey: string, customEnd: string): MonthWindow[] {
  const end = resolvePeriodEnd(rangeKey, customEnd);
  const windows: MonthWindow[] = [];
  for (let back = 3; back >= 0; back--) {
    const first = new Date(end.getFullYear(), end.getMonth() - back, 1);
    const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
    windows.push({ key: iso(first).slice(0, 7), start: iso(first), end: iso(last) });
  }
  return windows;
}

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className="flex rounded-[10px] bg-[#F8FAFC] p-0.5">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
          className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
            value === o.key
              ? "bg-white font-semibold text-[#102A43] shadow-sm"
              : "text-[#52677D] hover:text-[#102A43]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function Analytics() {
  const { hotelId } = useAuth();
  const [range, setRange] = useState<string>("month");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [groupBy, setGroupBy] = useState("day");
  const [compareKey, setCompareKey] = useState<string>("previous_period");
  const [sortKey, setSortKey] = useState<SortKey>("bookings");
  const [popPeriod, setPopPeriod] = useState<PopPeriod>("day");

  const rangeParams: RangeParams | null = useMemo(() => {
    if (!hotelId) return null;
    if (range === "custom") {
      if (!from || !to) return null;
      return { range: "custom", start: from, end: to };
    }
    return { range };
  }, [hotelId, range, from, to]);

  const compareEnabled = compareKey !== "none";
  const compareParams: RangeParams | null = useMemo(() => {
    if (!rangeParams || !compareEnabled) return null;
    return { range: compareKey };
  }, [rangeParams, compareEnabled, compareKey]);

  const ready = Boolean(rangeParams);

  const overviewQ = useQuery({
    queryKey: ["analytics", "overview", hotelId, rangeParams],
    queryFn: () => fetchOverview(hotelId!, rangeParams!),
    enabled: ready,
  });
  const seriesQ = useQuery({
    queryKey: ["analytics", "series", hotelId, rangeParams, groupBy],
    queryFn: () => fetchSeries(hotelId!, rangeParams!, groupBy),
    enabled: ready,
  });
  const compareQ = useQuery({
    queryKey: ["analytics", "compare", hotelId, rangeParams, compareParams],
    queryFn: () => fetchCompare(hotelId!, rangeParams!, compareParams!),
    enabled: ready && Boolean(compareParams),
  });
  const breakdownsQ = useQuery({
    queryKey: ["analytics", "breakdowns", hotelId, rangeParams],
    queryFn: () => fetchBreakdowns(hotelId!, rangeParams!),
    enabled: ready,
  });
  const popularitySeriesQ = useQuery({
    queryKey: ["analytics", "popularity-series", hotelId, rangeParams, popPeriod],
    queryFn: () => fetchPopularitySeries(hotelId!, rangeParams!, popPeriod),
    enabled: ready,
  });
  const activityQ = useQuery({
    queryKey: ["analytics", "activity", hotelId],
    queryFn: () => fetchActivity(hotelId!, 10),
    enabled: Boolean(hotelId),
  });

  /* Four-month trend: one series query per displayed month. */
  const monthWindows = useMemo(
    () => (rangeParams ? fourMonthWindows(range, to) : []),
    [rangeParams, range, to],
  );
  const monthQueries = useQueries({
    queries: monthWindows.map((w) => ({
      // The key MUST carry the selected page range: different ranges
      // ending in the same month (This month / This year / All time)
      // resolve to identical month windows, so a key built only from
      // the window + groupBy kept serving the earlier fetch — with
      // the app-wide staleTime that rendered pre-change data (e.g.
      // values from before a data import) under the new range label.
      // staleTime 0 makes a range switch always refetch current data.
      queryKey: [
        "analytics",
        "series-month",
        hotelId,
        range,
        range === "custom" ? from : "",
        range === "custom" ? to : "",
        w.start,
        w.end,
        groupBy,
      ],
      queryFn: () =>
        fetchSeries(hotelId!, { range: "custom", start: w.start, end: w.end }, groupBy),
      enabled: ready && groupBy !== "hour",
      staleTime: 0,
    })),
  });
  const monthSeries: MonthSeries[] = useMemo(
    () =>
      monthWindows.map((w, i) => {
        const points = monthQueries[i]?.data ?? [];
        return {
          key: w.key,
          label: monthLabel(w.key),
          color: MONTH_SERIES_COLORS[i % MONTH_SERIES_COLORS.length],
          total: points.reduce((s, p) => s + num(p.revenue), 0),
          bookings: points.reduce((s, p) => s + p.bookings, 0),
          points: alignMonthPoints(points, groupBy, w.key),
        };
      }),
    [monthWindows, monthQueries, groupBy],
  );
  const monthsLoading = monthQueries.some((q) => q.isLoading);
  const monthsError = monthQueries.some((q) => q.isError);

  const kpi = overviewQ.data;
  const breakdowns = breakdownsQ.data;
  const compareLabel = compareEnabled
    ? (COMPARE_OPTIONS.find((o) => o.key === compareKey)?.label ?? compareKey)
    : null;
  const rangeLabel = RANGE_OPTIONS.find((o) => o.key === range)?.label ?? range;

  /** Direction-aware delta vs the comparison period's overview. */
  const delta = (
    current: number,
    previous: number | undefined,
    goodWhenUp: boolean,
  ): KpiDelta | undefined => {
    if (!compareEnabled || !compareLabel || previous === undefined) return undefined;
    const pct = pctChange(current, previous);
    return {
      value: pct,
      favorable: pct === null || pct === 0 ? null : pct > 0 === goodWhenUp,
      caption: `vs ${compareLabel}`,
    };
  };

  const occupancyDelta = (): KpiDelta | undefined => {
    const prev = compareQ.data?.previous.occupancy_rate;
    if (!compareEnabled || !compareLabel || !kpi || prev === undefined) return undefined;
    const diff = Math.round((kpi.occupancy_rate - prev) * 100) / 100;
    return {
      value: diff,
      favorable: diff === 0 ? null : diff > 0,
      points: true,
      caption: `vs ${compareLabel}`,
    };
  };

  /* Room popularity (grouped bars): order + colours are shared with
   * the table and the category donut. */
  const popData = popularitySeriesQ.data;
  const sortedTypes = useMemo(() => {
    const rows = [...(popData?.room_types ?? [])];
    rows.sort((a, b) => {
      if (sortKey === "revenue") return num(b.revenue) - num(a.revenue);
      if (sortKey === "occupancy") return b.occupancy_rate - a.occupancy_rate;
      return b.bookings - a.bookings;
    });
    return rows;
  }, [popData, sortKey]);
  const totalsByType = useMemo(
    () => new Map(sortedTypes.map((r) => [r.room_type, r])),
    [sortedTypes],
  );
  const colorMap = useMemo(
    () =>
      buildRoomColorMap([
        ...sortedTypes.map((r) => r.room_type),
        ...(breakdowns?.by_room_category ?? []).map((r) => r.key),
      ]),
    [sortedTypes, breakdowns],
  );
  const colorFor = (roomType: string) => colorMap.get(roomType) ?? "#8293A5";
  const mostBooked = useMemo(() => {
    if (!sortedTypes.length) return [];
    const max = Math.max(...sortedTypes.map((r) => r.bookings));
    return sortedTypes.filter((r) => r.bookings === max);
  }, [sortedTypes]);
  const leastBooked = useMemo(() => {
    if (!sortedTypes.length) return [];
    const min = Math.min(...sortedTypes.map((r) => r.bookings));
    return sortedTypes.filter((r) => r.bookings === min);
  }, [sortedTypes]);
  const sparkFor = (roomType: string): number[] =>
    (popData?.buckets ?? []).map(
      (b) => b.rooms.find((c) => c.room_type === roomType)?.bookings ?? 0,
    );
  const periodDays = popData?.period_days ?? 0;
  const maxTypeBookings = Math.max(1, ...sortedTypes.map((r) => r.bookings));
  const maxTypeRevenue = Math.max(1, ...sortedTypes.map((r) => num(r.revenue)));

  const categoryRows: ChartRow[] = (breakdowns?.by_room_category ?? []).map((r) => ({
    label: r.key,
    value: num(r.revenue),
    bookings: r.bookings,
    color: colorFor(r.key),
  }));
  const sourceRows: ChartRow[] = (breakdowns?.by_booking_source ?? []).map((r) => ({
    label: SOURCE_LABELS[r.key] ?? prettify(r.key),
    value: num(r.revenue),
    bookings: r.bookings,
    color: "#0F9D94",
  }));
  const paymentRows: ChartRow[] = (breakdowns?.by_payment_method ?? []).map((r, i) => {
    const style = PAYMENT_STYLE[r.key] ?? {
      label: prettify(r.key),
      color: PAYMENT_FALLBACK[i % PAYMENT_FALLBACK.length],
    };
    return { label: style.label, value: num(r.revenue), bookings: r.bookings, color: style.color };
  });
  const paymentEmpty =
    !breakdownsQ.isLoading &&
    (paymentRows.length === 0 || paymentRows.every((r) => r.value <= 0));
  const departmentRows: ChartRow[] = (breakdowns?.by_department ?? []).map((r) => {
    const style = DEPARTMENT_STYLE[r.key] ?? { label: prettify(r.key), color: "#18B8AC" };
    return { label: style.label, value: num(r.revenue), bookings: r.bookings, color: style.color };
  });

  const exportCsv = async (dataset: "series" | "room-popularity") => {
    if (!rangeParams || !hotelId) return;
    await downloadCsv(hotelId, rangeParams, dataset);
  };

  const prev = compareQ.data?.previous;
  const seriesRevenue = (seriesQ.data ?? []).map((p) => num(p.revenue));
  const seriesBookings = (seriesQ.data ?? []).map((p) => p.bookings);

  return (
    <div className="analytics-root">
      {/* Page header (scoped replacement for the shared PageHeader so
          the global Barlow heading style stays untouched elsewhere). */}
      <div className="mb-6">
        <h1 className="text-[28px] font-bold leading-tight">Analytics</h1>
        <p className="mt-1 text-sm text-[#52677D]">
          Track your hotel performance and revenue insights.
        </p>
      </div>

      {/* Filters */}
      <div className="ax-card mb-5 flex flex-wrap items-end gap-3 p-4">
        <label className="ax-label">
          Date range
          <select
            aria-label="Date range"
            className="ax-select"
            value={range}
            onChange={(e) => setRange(e.target.value)}
          >
            {RANGE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        {range === "custom" && (
          <>
            <label className="ax-label">
              From
              <input
                type="date"
                aria-label="From date"
                className="ax-select"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label className="ax-label">
              To
              <input
                type="date"
                aria-label="To date"
                className="ax-select"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
          </>
        )}
        <label className="ax-label">
          Compare with
          <select
            aria-label="Comparison period"
            className="ax-select"
            value={compareKey}
            onChange={(e) => setCompareKey(e.target.value)}
          >
            {COMPARE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <span className="pb-2 text-xs text-[#8293A5]">Showing: {rangeLabel}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <button
            className="ax-btn"
            disabled={!ready}
            onClick={() => void exportCsv("series")}
          >
            Export revenue CSV
          </button>
          <button
            className="ax-btn"
            disabled={!ready}
            onClick={() => void exportCsv("room-popularity")}
          >
            Export rooms CSV
          </button>
        </div>
      </div>

      {overviewQ.isError && (
        <div className="mb-4 rounded-xl border border-[#EF4444]/40 bg-[#FDECEC] px-4 py-3 text-sm text-[#C22F2F]">
          Analytics failed to load. Try changing the range or refreshing.
        </div>
      )}

      {!ready && hotelId ? (
        <p className="mb-4 rounded-xl border border-[#E3EAF0] bg-white px-4 py-3 text-sm text-[#52677D]">
          Pick a start and end date to see analytics for the custom range.
        </p>
      ) : null}

      {/* KPI grid */}
      {overviewQ.isLoading ? (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="h-[128px] animate-pulse rounded-2xl bg-white" aria-hidden />
          ))}
        </div>
      ) : kpi ? (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          <KpiCard
            label="Total revenue"
            value={inr(kpi.total_revenue)}
            sub={kpi.period_days ? `${kpi.period_days} days in period` : undefined}
            icon={
              <KpiIcon>
                <rect x="2" y="6" width="20" height="12" rx="2" />
                <circle cx="12" cy="12" r="2.6" />
                <path d="M6 12h.01M18 12h.01" />
              </KpiIcon>
            }
            iconClass="bg-[#E7F7F4] text-[#087E78]"
            delta={delta(num(kpi.total_revenue), prev ? num(prev.total_revenue) : undefined, true)}
            spark={
              <Sparkline data={seriesRevenue} label={`Revenue sparkline, peak ${inr(Math.max(0, ...seriesRevenue))}`} />
            }
          />
          <KpiCard
            label="Collected payments"
            value={inr(kpi.revenue_collected)}
            sub="Captured payments"
            icon={
              <KpiIcon>
                <path d="M20 6 9 17l-5-5" />
              </KpiIcon>
            }
            iconClass="bg-[#10B981]/10 text-[#10B981]"
            delta={delta(num(kpi.revenue_collected), prev ? num(prev.revenue_collected) : undefined, true)}
          />
          <KpiCard
            label="Pending payments"
            value={inr(kpi.pending_payments)}
            sub="Earned, not yet collected"
            icon={
              <KpiIcon>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3.2 2" />
              </KpiIcon>
            }
            iconClass="bg-[#F59E0B]/10 text-[#B45309]"
            delta={delta(num(kpi.pending_payments), prev ? num(prev.pending_payments) : undefined, false)}
          />
          <KpiCard
            label="Refunds"
            value={inr(kpi.refunds)}
            sub="Processed refunds"
            icon={
              <KpiIcon>
                <path d="M3 12a9 9 0 1 0 2.6-6.3" />
                <path d="M3 4v5h5" />
              </KpiIcon>
            }
            iconClass="bg-[#FDECEC] text-[#C22F2F]"
            delta={delta(num(kpi.refunds), prev ? num(prev.refunds) : undefined, false)}
          />
          <KpiCard
            label="Total bookings"
            value={String(kpi.total_bookings)}
            sub={`${kpi.confirmed_bookings} confirmed · ${kpi.cancelled_bookings} cancelled`}
            icon={
              <KpiIcon>
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </KpiIcon>
            }
            iconClass="bg-[#3B82F6]/10 text-[#3B82F6]"
            delta={delta(kpi.total_bookings, prev?.total_bookings, true)}
            spark={
              <Sparkline
                data={seriesBookings}
                stroke="#3B82F6"
                label={`Bookings sparkline, peak ${Math.max(0, ...seriesBookings)}`}
              />
            }
          />
          <KpiCard
            label="Occupancy rate"
            value={`${kpi.occupancy_rate}%`}
            sub={`${kpi.occupied_room_nights} of ${kpi.available_room_nights} room-nights`}
            icon={
              <KpiIcon>
                <path d="M21.2 15.9A10 10 0 1 1 8 2.8" />
                <path d="M22 12A10 10 0 0 0 12 2v10z" />
              </KpiIcon>
            }
            iconClass="bg-[#0F9D94]/10 text-[#0F9D94]"
            delta={occupancyDelta()}
          />
          <KpiCard
            label="ADR"
            value={inr(kpi.adr)}
            sub="Average daily rate"
            icon={
              <KpiIcon>
                <path d="M12.6 2.9 21 11.3a2 2 0 0 1 0 2.8l-6.9 6.9a2 2 0 0 1-2.8 0L2.9 12.6A2 2 0 0 1 2.9 11.2V4a1.4 1.4 0 0 1 1.4-1.4h7.2a2 2 0 0 1 1.1.3z" />
                <circle cx="7.5" cy="7.5" r="1.2" />
              </KpiIcon>
            }
            iconClass="bg-[#8B5CF6]/10 text-[#8B5CF6]"
            delta={delta(num(kpi.adr), prev ? num(prev.adr) : undefined, true)}
          />
          <KpiCard
            label="RevPAR"
            value={inr(kpi.revpar)}
            sub="Per available room-night"
            icon={
              <KpiIcon>
                <line x1="12" y1="20" x2="12" y2="10" />
                <line x1="18" y1="20" x2="18" y2="4" />
                <line x1="6" y1="20" x2="6" y2="16" />
              </KpiIcon>
            }
            iconClass="bg-[#087E78]/10 text-[#087E78]"
            delta={delta(num(kpi.revpar), prev ? num(prev.revpar) : undefined, true)}
          />
          <KpiCard
            label="Avg booking value"
            value={inr(kpi.average_booking_value)}
            sub={`Daily average ${inr(kpi.average_daily_revenue)}`}
            icon={
              <KpiIcon>
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
                <polyline points="16 7 22 7 22 13" />
              </KpiIcon>
            }
            iconClass="bg-[#FBBF24]/15 text-[#B45309]"
            delta={delta(
              num(kpi.average_booking_value),
              prev ? num(prev.average_booking_value) : undefined,
              true,
            )}
          />
          <KpiCard
            label="Rooms tonight"
            value={`${kpi.rooms_occupied_tonight} occupied`}
            sub={`${kpi.rooms_available_tonight} available tonight`}
            icon={
              <KpiIcon>
                <path d="M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8" />
                <path d="M4 10V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4" />
                <path d="M2 17h20" />
              </KpiIcon>
            }
            iconClass="bg-[#E7F7F4] text-[#075E5A]"
          />
        </div>
      ) : null}

      {/* Row 1: four-month revenue trend + room popularity bars */}
      <div className="mb-5 grid gap-5 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <ChartCard
            title="Revenue trend"
            subtitle="Compare revenue across four months"
            actions={
              <SegmentedControl
                options={GROUP_OPTIONS}
                value={groupBy}
                onChange={setGroupBy}
                ariaLabel="Group series by"
              />
            }
          >
            {groupBy === "hour" ? (
              seriesQ.isLoading ? (
                <ChartSkeleton height={300} />
              ) : seriesQ.isError ? (
                <div className="py-10 text-center">
                  <p className="text-sm text-[#C22F2F]">
                    The revenue series could not be loaded.
                  </p>
                  <button
                    type="button"
                    className="ax-btn mt-3"
                    onClick={() => void seriesQ.refetch()}
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <HourlyTrendChart points={seriesQ.data ?? []} />
              )
            ) : monthsLoading ? (
              <ChartSkeleton height={300} />
            ) : monthsError ? (
              <div className="py-10 text-center">
                <p className="text-sm text-[#C22F2F]">
                  The revenue series could not be loaded.
                </p>
                <button
                  type="button"
                  className="ax-btn mt-3"
                  onClick={() => monthQueries.forEach((q) => void q.refetch())}
                >
                  Retry
                </button>
              </div>
            ) : (
              <RevenueTrendChart months={monthSeries} groupBy={groupBy} />
            )}
          </ChartCard>
        </div>

        <div className="xl:col-span-5">
          <ChartCard
            title="Room popularity"
            subtitle="Bookings per period, grouped by room type"
            actions={
              <>
                <SegmentedControl
                  options={POP_PERIOD_OPTIONS}
                  value={popPeriod}
                  onChange={setPopPeriod}
                  ariaLabel="Room popularity period"
                />
                <select
                  aria-label="Sort room popularity by"
                  className="ax-select"
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                >
                  <option value="bookings">Bookings</option>
                  <option value="revenue">Revenue</option>
                  <option value="occupancy">Occupancy</option>
                </select>
              </>
            }
          >
            {popularitySeriesQ.isLoading ? (
              <ChartSkeleton height={320} />
            ) : popularitySeriesQ.isError ? (
              <div className="py-10 text-center">
                <p className="text-sm text-[#C22F2F]">
                  Room popularity could not be loaded.
                </p>
                <button
                  type="button"
                  className="ax-btn mt-3"
                  onClick={() => void popularitySeriesQ.refetch()}
                >
                  Retry
                </button>
              </div>
            ) : popData ? (
              <>
                {sortedTypes.length > 0 ? (
                  <div className="mb-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl bg-[#E7F7F4] px-3 py-2 text-xs leading-relaxed text-[#102A43]">
                      <span className="font-semibold text-[#075E5A]">Most booked:</span>{" "}
                      {mostBooked.length
                        ? mostBooked.map((r) => `${r.room_type} (${r.bookings})`).join(", ")
                        : "—"}
                    </div>
                    <div className="rounded-xl bg-[#FBBF24]/10 px-3 py-2 text-xs leading-relaxed text-[#102A43]">
                      <span className="font-semibold text-[#92600A]">Least booked:</span>{" "}
                      {leastBooked.length
                        ? leastBooked.map((r) => `${r.room_type} (${r.bookings})`).join(", ")
                        : "—"}
                    </div>
                  </div>
                ) : null}
                <RoomPopularityBars
                  data={popData}
                  orderedTypes={sortedTypes.map((r) => r.room_type)}
                  colorFor={colorFor}
                  totalsByType={totalsByType}
                />
                {sortedTypes.length > 0 ? (
                  <div className="mt-4 overflow-x-auto">
                    <table className="ax-table min-w-[560px]">
                      <thead>
                        <tr>
                          <th>Room type</th>
                          <th>Bookings</th>
                          <th>Revenue</th>
                          <th>Avg / day</th>
                          <th>Occupancy</th>
                          <th>Trend</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedTypes.map((r: PopularityRow) => (
                          <tr key={r.room_id}>
                            <td className="font-medium text-[#102A43]">
                              <span className="inline-flex items-center gap-2">
                                <span
                                  aria-hidden
                                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                                  style={{ background: colorFor(r.room_type) }}
                                />
                                {r.room_type}
                              </span>
                            </td>
                            <td>
                              <span className="tabular-nums">{r.bookings}</span>
                              <span className="mt-1 block h-1.5 w-16 rounded-full bg-[#EDF1F5]">
                                <span
                                  className="block h-1.5 rounded-full"
                                  style={{
                                    width: `${(r.bookings / maxTypeBookings) * 100}%`,
                                    background: colorFor(r.room_type),
                                  }}
                                />
                              </span>
                            </td>
                            <td>
                              <span className="tabular-nums">{inr(r.revenue)}</span>
                              <span className="mt-1 block h-1.5 w-16 rounded-full bg-[#EDF1F5]">
                                <span
                                  className="block h-1.5 rounded-full"
                                  style={{
                                    width: `${(num(r.revenue) / maxTypeRevenue) * 100}%`,
                                    background: colorFor(r.room_type),
                                  }}
                                />
                              </span>
                            </td>
                            <td className="tabular-nums">
                              {periodDays > 0 ? (r.bookings / periodDays).toFixed(2) : "—"}
                            </td>
                            <td>
                              <span className="tabular-nums">{r.occupancy_rate}%</span>
                              <span className="block text-[11px] text-[#8293A5]">
                                {r.occupied_room_nights}/{r.available_room_nights} room-nights
                              </span>
                              <span className="mt-1 block h-1.5 w-16 rounded-full bg-[#EDF1F5]">
                                <span
                                  className="block h-1.5 rounded-full"
                                  style={{
                                    width: `${Math.min(100, r.occupancy_rate)}%`,
                                    background: colorFor(r.room_type),
                                  }}
                                />
                              </span>
                            </td>
                            <td>
                              <Sparkline
                                data={sparkFor(r.room_type)}
                                stroke={colorFor(r.room_type)}
                                label={`${r.room_type} bookings trend`}
                              />
                            </td>
                            <td>{r.is_active ? "Active" : "Inactive"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </>
            ) : null}
          </ChartCard>
        </div>
      </div>

      {/* Row 2: breakdowns + activity */}
      <div className="mb-5 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        <ChartCard title="Revenue by room category" subtitle="Share of room revenue">
          {breakdownsQ.isLoading ? (
            <ChartSkeleton height={180} />
          ) : categoryRows.length && categoryRows.some((r) => r.value > 0) ? (
            <DonutChart
              rows={categoryRows}
              centerLabel="Total"
              ariaLabel="Revenue by room category donut chart"
            />
          ) : (
            <EmptyState message="No room revenue in this period." />
          )}
        </ChartCard>

        <ChartCard title="Revenue by booking source" subtitle="Where bookings came from">
          {breakdownsQ.isLoading ? (
            <ChartSkeleton height={180} />
          ) : sourceRows.length && sourceRows.some((r) => r.value > 0) ? (
            <VerticalBars rows={sourceRows} ariaLabel="Revenue by booking source bar chart" />
          ) : (
            <EmptyState message="No booking revenue in this period." />
          )}
        </ChartCard>

        <ChartCard title="Revenue by payment method" subtitle="Captured payments only">
          {breakdownsQ.isLoading ? (
            <ChartSkeleton height={180} />
          ) : paymentEmpty ? (
            <EmptyState message="No payment-method data available for this period." />
          ) : (
            <DonutChart
              rows={paymentRows}
              centerLabel="Collected"
              ariaLabel="Revenue by payment method donut chart"
            />
          )}
        </ChartCard>

        <ChartCard title="Recent activity" subtitle="Latest bookings and payments">
          <RecentActivity
            events={activityQ.data}
            isLoading={activityQ.isLoading}
            isError={activityQ.isError}
          />
        </ChartCard>
      </div>

      {/* Department revenue */}
      <ChartCard title="Revenue by department" subtitle="Rooms vs food & beverage, with share of total">
        {breakdownsQ.isLoading ? (
          <ChartSkeleton height={120} />
        ) : departmentRows.length && departmentRows.some((r) => r.value > 0) ? (
          <HorizontalBars rows={departmentRows} />
        ) : (
          <EmptyState message="No department revenue in this period." />
        )}
      </ChartCard>
    </div>
  );
}
