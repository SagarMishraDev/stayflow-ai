import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../components/DataStates";
import { useAuth } from "../lib/auth";
import {
  downloadCsv,
  fetchActivity,
  fetchBreakdowns,
  fetchCompare,
  fetchOverview,
  fetchPopularity,
  fetchSeries,
  RANGE_OPTIONS,
  type RangeParams,
} from "../lib/analyticsApi";
import { ChartCard, ChartSkeleton, EmptyState } from "../components/analytics/ChartCard";
import { KpiCard, KpiIcon, Sparkline, type KpiDelta } from "../components/analytics/KpiCard";
import { RevenueTrendChart } from "../components/analytics/RevenueTrendChart";
import { RoomPopularityChart } from "../components/analytics/RoomPopularityChart";
import {
  DonutChart,
  HorizontalBars,
  VerticalBars,
  type ChartRow,
} from "../components/analytics/BreakdownCharts";
import { RecentActivity } from "../components/analytics/RecentActivity";
import { inr, num, pctChange } from "../components/analytics/format";

type SortKey = "bookings" | "revenue" | "occupancy";

const GROUP_OPTIONS: { key: string; label: string }[] = [
  { key: "hour", label: "Hourly" },
  { key: "day", label: "Daily" },
  { key: "week", label: "Weekly" },
  { key: "month", label: "Monthly" },
  { key: "year", label: "Yearly" },
];

const CATEGORY_COLORS = ["#087E78", "#18B8AC", "#FBBF24", "#0F9D94", "#8B5CF6", "#3B82F6", "#075E5A"];

const PAYMENT_STYLE: Record<string, { label: string; color: string }> = {
  upi: { label: "UPI", color: "#0F9D94" },
  card: { label: "Card", color: "#3B82F6" },
  cash: { label: "Cash", color: "#8B5CF6" },
  bank_transfer: { label: "Bank transfer", color: "#F59E0B" },
  other: { label: "Other", color: "#8293A5" },
};

/** Friendly labels for the booking sources the backend actually
 * stamps. Anything unrecognised falls back to "Unknown" only when the
 * backend itself reports it as unknown; other keys are shown prettified
 * rather than invented. */
const SOURCE_LABELS: Record<string, string> = {
  agent_chat: "AI concierge",
  widget: "Website widget",
  dashboard: "Front desk",
  walk_in: "Walk-in",
  integration: "Integration",
  unknown: "Unknown",
};

const DEPARTMENT_STYLE: Record<string, { label: string; color: string }> = {
  rooms: { label: "Rooms", color: "#0F9D94" },
  food_and_beverage: { label: "Food & beverage", color: "#087E78" },
};

function prettify(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key;
}

const selectCls =
  "rounded-[10px] border border-line bg-white px-3 py-2 text-[13.5px] font-medium text-ink";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-ink-muted";

export default function Analytics() {
  const { hotelId } = useAuth();
  const [range, setRange] = useState<string>("month");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [groupBy, setGroupBy] = useState("day");
  const [compareKey, setCompareKey] = useState<string>("last_month");
  const [sortKey, setSortKey] = useState<SortKey>("bookings");

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
  const popularityQ = useQuery({
    queryKey: ["analytics", "popularity", hotelId, rangeParams],
    queryFn: () => fetchPopularity(hotelId!, rangeParams!),
    enabled: ready,
  });
  const activityQ = useQuery({
    queryKey: ["analytics", "activity", hotelId],
    queryFn: () => fetchActivity(hotelId!, 10),
    enabled: Boolean(hotelId),
  });

  const kpi = overviewQ.data;
  const breakdowns = breakdownsQ.data;
  const compareLabel =
    compareEnabled && compareKey !== "none"
      ? (RANGE_OPTIONS.find((o) => o.key === compareKey)?.label ?? compareKey)
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

  const sortedRooms = useMemo(() => {
    const rooms = popularityQ.data?.rooms ?? [];
    return [...rooms].sort((a, b) => {
      if (sortKey === "revenue") return num(b.revenue) - num(a.revenue);
      if (sortKey === "occupancy") return b.occupancy_rate - a.occupancy_rate;
      return b.bookings - a.bookings;
    });
  }, [popularityQ.data, sortKey]);

  const categoryRows: ChartRow[] = (breakdowns?.by_room_category ?? []).map((r, i) => ({
    label: r.key,
    value: num(r.revenue),
    bookings: r.bookings,
    color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
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
      color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
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
    <div>
      <PageHeader
        title="Analytics"
        description="Track your hotel performance and revenue insights."
      />

      {/* Filters */}
      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-white p-4 shadow-card">
        <label className={labelCls}>
          Date range
          <select
            aria-label="Date range"
            className={selectCls}
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
            <label className={labelCls}>
              From
              <input
                type="date"
                aria-label="From date"
                className={selectCls}
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label className={labelCls}>
              To
              <input
                type="date"
                aria-label="To date"
                className={selectCls}
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
          </>
        )}
        <label className={labelCls}>
          Compare with
          <select
            aria-label="Comparison period"
            className={selectCls}
            value={compareKey}
            onChange={(e) => setCompareKey(e.target.value)}
          >
            <option value="none">No comparison</option>
            {RANGE_OPTIONS.filter((o) => o.key !== "custom").map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex flex-wrap gap-2">
          <button
            className="btn-secondary"
            disabled={!ready}
            onClick={() => void exportCsv("series")}
          >
            Export revenue CSV
          </button>
          <button
            className="btn-secondary"
            disabled={!ready}
            onClick={() => void exportCsv("room-popularity")}
          >
            Export rooms CSV
          </button>
        </div>
      </div>

      {overviewQ.isError && (
        <div className="mb-4 rounded-xl border border-coral/40 bg-coral-soft px-4 py-3 text-sm text-coral-deep">
          Analytics failed to load. Try changing the range or refreshing.
        </div>
      )}

      {!ready && hotelId ? (
        <p className="mb-4 rounded-xl border border-line bg-white px-4 py-3 text-sm text-ink-soft">
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
            iconClass="bg-pale text-dark-teal"
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
            iconClass="bg-emerald/10 text-emerald"
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
            iconClass="bg-warn/10 text-[#B45309]"
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
            iconClass="bg-coral-soft text-coral-deep"
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
            iconClass="bg-info/10 text-info"
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
            iconClass="bg-teal/10 text-teal"
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
            iconClass="bg-grape/10 text-grape"
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
            iconClass="bg-dark-teal/10 text-dark-teal"
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
            iconClass="bg-sun/15 text-[#B45309]"
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
            iconClass="bg-pale text-deep-teal"
          />
        </div>
      ) : null}

      {/* Row 1: revenue trend + room popularity */}
      <div className="mb-5 grid gap-5 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <ChartCard
            title="Revenue trend"
            subtitle="Bookings revenue over the selected period"
            actions={
              <div
                role="group"
                aria-label="Group series by"
                className="flex rounded-[10px] bg-mist p-0.5"
              >
                {GROUP_OPTIONS.map((o) => (
                  <button
                    key={o.key}
                    type="button"
                    aria-pressed={groupBy === o.key}
                    onClick={() => setGroupBy(o.key)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
                      groupBy === o.key
                        ? "bg-white font-semibold text-ink shadow-sm"
                        : "text-ink-soft hover:text-ink"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            }
          >
            {seriesQ.isLoading ? (
              <ChartSkeleton height={300} />
            ) : seriesQ.isError ? (
              <p className="py-10 text-center text-sm text-coral-deep">
                The revenue series could not be loaded.
              </p>
            ) : (
              <RevenueTrendChart
                current={seriesQ.data ?? []}
                previous={compareEnabled ? compareQ.data?.series.previous : undefined}
                currentLabel={rangeLabel}
                comparisonLabel={compareLabel ?? undefined}
              />
            )}
          </ChartCard>
        </div>

        <div className="xl:col-span-5">
          <ChartCard
            title="Room popularity"
            subtitle="Bubble size = bookings in period"
            actions={
              <select
                aria-label="Sort room popularity by"
                className={selectCls}
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
              >
                <option value="bookings">Bookings</option>
                <option value="revenue">Revenue</option>
                <option value="occupancy">Occupancy</option>
              </select>
            }
          >
            {popularityQ.isLoading ? (
              <ChartSkeleton height={320} />
            ) : popularityQ.isError ? (
              <p className="py-10 text-center text-sm text-coral-deep">
                Room popularity could not be loaded.
              </p>
            ) : (
              <>
                {popularityQ.data && popularityQ.data.rooms.length > 0 ? (
                  <div className="mb-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl bg-pale px-3 py-2 text-xs leading-relaxed text-ink">
                      <span className="font-semibold text-deep-teal">Most booked:</span>{" "}
                      {(popularityQ.data.most_booked ?? []).length
                        ? popularityQ.data.most_booked
                            .map((r) => `${r.room_type} (${r.bookings})`)
                            .join(", ")
                        : "—"}
                    </div>
                    <div className="rounded-xl bg-sun/10 px-3 py-2 text-xs leading-relaxed text-ink">
                      <span className="font-semibold text-[#92600A]">Least booked:</span>{" "}
                      {(popularityQ.data.least_booked ?? []).length
                        ? popularityQ.data.least_booked
                            .map((r) => `${r.room_type} (${r.bookings})`)
                            .join(", ")
                        : "—"}
                    </div>
                  </div>
                ) : null}
                <RoomPopularityChart rows={sortedRooms} />
                {sortedRooms.length > 0 ? (
                  <div className="mt-4 overflow-x-auto">
                    <table className="table min-w-[430px]">
                      <thead>
                        <tr>
                          <th>Room type</th>
                          <th>Bookings</th>
                          <th>Revenue</th>
                          <th>Occupancy</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedRooms.map((r) => (
                          <tr key={r.room_id}>
                            <td className="font-medium text-ink">{r.room_type}</td>
                            <td>{r.bookings}</td>
                            <td>{inr(r.revenue)}</td>
                            <td>{r.occupancy_rate}%</td>
                            <td>{r.is_active ? "Active" : "Inactive"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </>
            )}
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
