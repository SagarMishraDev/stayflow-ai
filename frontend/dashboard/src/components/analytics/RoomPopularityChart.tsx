import { useState } from "react";
import type { PopularityRow, PopularitySeries } from "../../lib/analyticsApi";
import { EmptyState } from "./ChartCard";
import { inr, periodLabel } from "./format";

/** Room popularity — GROUPED VERTICAL BARS (replaced the bubble chart
 * in the 2026-10-23 master revision).
 *
 * X axis = time buckets from GET /analytics/popularity-series
 * (Day/Week/Month/Year within the selected range); one bar per room
 * type per bucket, height = booking count (check-in based, matching
 * the analytics accounting rules). Category order follows the page's
 * sorting control (bookings / revenue / occupancy). Colours come from
 * the shared room-type colour map — the same colours used by the
 * legend, the category donut and the performance table.
 *
 * Sizing is BOUNDED and 1:1 with the viewBox: the SVG renders at
 * exactly W×H px (H = 300) and dense day views scroll horizontally
 * inside the card. The old code set width:"100%" with no height for
 * narrow viewBoxes, so few-bucket views (Month/Year = 1 bucket,
 * W ≈ 105) were stretched to the card width and grew to 1000px+
 * tall through aspect-ratio scaling.
 */

const H = 300;
const PAD = { l: 40, r: 10, t: 16, b: 30 };
/** Minimum rendered plot width: slots widen to reach it on
 * few-bucket views so bars stay readable at the fixed height. */
const MIN_CHART_W = 520;

interface ActiveCell {
  bucket: string;
  roomType: string;
  bookings: number;
  revenue: number;
}

export function RoomPopularityBars({
  data,
  orderedTypes,
  colorFor,
  totalsByType,
}: {
  data: PopularitySeries;
  /** Room types in display order (the page's sort already applied). */
  orderedTypes: string[];
  colorFor: (roomType: string) => string;
  totalsByType: Map<string, PopularityRow>;
}) {
  const [active, setActive] = useState<ActiveCell | null>(null);
  const buckets = data.buckets;
  const totalBookings = buckets.reduce(
    (s, b) => s + b.rooms.reduce((t, c) => t + c.bookings, 0),
    0,
  );
  if (!buckets.length || !orderedTypes.length || totalBookings === 0) {
    // The API zero-fills buckets for bounded ranges, so an all-zero
    // response arrives WITH buckets — it is still "no bookings" and
    // gets the empty state rather than a field of invisible bars.
    return <EmptyState message="No room bookings are available for the selected period." />;
  }
  const typeCount = orderedTypes.length;
  const maxBookings = Math.max(
    1,
    ...buckets.flatMap((b) => b.rooms.map((c) => c.bookings)),
  );
  const slotW = Math.max(
    typeCount * 15 + 10,
    Math.ceil((MIN_CHART_W - PAD.l - PAD.r) / buckets.length),
    30,
  );
  const W = PAD.l + PAD.r + slotW * buckets.length;
  const innerH = H - PAD.t - PAD.b;
  const innerW = W - PAD.l - PAD.r;
  const barW = Math.min(28, Math.max(4, (slotW - 8) / typeCount));
  const ticks = Array.from(
    new Set([0, 0.5, 1].map((f) => Math.round(maxBookings * f))),
  );
  const labelEvery = buckets.length > 40 ? Math.ceil(buckets.length / 24) : 1;

  const shown =
    active ??
    (() => {
      const first = buckets[0]?.rooms.find((c) => c.room_type === orderedTypes[0]);
      return first
        ? {
            bucket: buckets[0].period,
            roomType: first.room_type,
            bookings: first.bookings,
            revenue: Number(first.revenue),
          }
        : null;
    })();

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-[#52677D]">
        {orderedTypes.map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-[3px]"
              style={{ background: colorFor(t) }}
            />
            {t}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: W, height: H, minWidth: W }}
          className="block"
          role="img"
          aria-label={`Room popularity grouped bar chart: bookings per ${data.group_by} bucket by room type`}
          onMouseLeave={() => setActive(null)}
        >
          {ticks.map((t, i) => {
            const yy = PAD.t + innerH - (t / maxBookings) * innerH;
            return (
              <g key={i}>
                <line x1={PAD.l} x2={W - PAD.r} y1={yy} y2={yy} stroke="#E7EDF2" strokeWidth={1} />
                <text x={PAD.l - 7} y={yy + 4} textAnchor="end" className="fill-[#8293A5] text-[11px] tabular-nums">
                  {t}
                </text>
              </g>
            );
          })}
          {buckets.map((bucket, bi) => {
            const slotX = PAD.l + bi * slotW;
            const groupW = barW * typeCount;
            const startX = slotX + (slotW - groupW) / 2;
            return (
              <g key={bucket.period}>
                {orderedTypes.map((type, ti) => {
                  const cell = bucket.rooms.find((c) => c.room_type === type);
                  const bookings = cell?.bookings ?? 0;
                  const h = (bookings / maxBookings) * innerH;
                  const bx = startX + ti * barW;
                  const isActive =
                    active?.bucket === bucket.period && active?.roomType === type;
                  return (
                    <rect
                      key={type}
                      x={bx + 0.75}
                      y={PAD.t + innerH - h}
                      width={Math.max(1, barW - 1.5)}
                      height={Math.max(0, h)}
                      rx={2}
                      fill={colorFor(type)}
                      opacity={active && !isActive ? 0.45 : 1}
                      onMouseEnter={() =>
                        setActive({
                          bucket: bucket.period,
                          roomType: type,
                          bookings,
                          revenue: Number(cell?.revenue ?? 0),
                        })
                      }
                    >
                      <title>{`${periodLabel(bucket.period, "full")} · ${type}: ${bookings} bookings · ${inr(cell?.revenue ?? 0)} revenue`}</title>
                    </rect>
                  );
                })}
                {bi % labelEvery === 0 ? (
                  <text
                    x={slotX + slotW / 2}
                    y={H - 8}
                    textAnchor="middle"
                    className="fill-[#8293A5] text-[10.5px]"
                  >
                    {periodLabel(bucket.period)}
                  </text>
                ) : null}
              </g>
            );
          })}
          <line
            x1={PAD.l}
            x2={PAD.l + innerW}
            y1={PAD.t + innerH}
            y2={PAD.t + innerH}
            stroke="#E7EDF2"
            strokeWidth={1}
          />
        </svg>
      </div>

      {shown ? (
        <div aria-live="polite" className="mt-3 rounded-xl bg-[#E7F7F4] px-4 py-3 text-[13px] text-[#102A43]">
          <strong>{shown.roomType}</strong> · {periodLabel(shown.bucket, "full")} —{" "}
          {shown.bookings} bookings · {inr(shown.revenue)} revenue
          {totalsByType.get(shown.roomType)
            ? ` · ${totalsByType.get(shown.roomType)!.occupancy_rate}% occupancy in range`
            : ""}
        </div>
      ) : null}
    </div>
  );
}
