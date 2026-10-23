import { useMemo, useState } from "react";
import type { PopularityRow } from "../../lib/analyticsApi";
import { inr } from "./format";

/** Room popularity — deterministic packed bubbles.
 *
 * Placement follows the order rows arrive in (the page sorts them by
 * bookings / revenue / occupancy, so sorting visibly reorders the
 * layout); positions come from a golden-angle spiral scan with
 * collision checks — identical input always yields an identical,
 * overlap-free layout. Bubble SIZE is always proportional to booking
 * count (√ scale). Colours: teal shades = has bookings, soft amber =
 * zero bookings, muted gray = inactive room type. */

const BOOKED_FILLS = ["#087E78", "#0F9D94", "#18B8AC", "#075E5A"];
const W = 720;
const H = 400;

interface Placed {
  row: PopularityRow;
  x: number;
  y: number;
  r: number;
}

function packBubbles(rows: PopularityRow[]): Placed[] {
  const maxBookings = Math.max(1, ...rows.map((r) => r.bookings));
  const placed: Placed[] = [];
  for (const row of rows) {
    const r = row.bookings > 0 ? 22 + 46 * Math.sqrt(row.bookings / maxBookings) : 17;
    let done = false;
    for (let t = 0; t < 5000 && !done; t += 1) {
      const angle = t * 2.399963; // golden angle
      const dist = 4.2 * Math.sqrt(t) * 6;
      const x = W / 2 + dist * Math.cos(angle);
      const y = H / 2 + dist * Math.sin(angle) * 0.8;
      if (x - r < 4 || x + r > W - 4 || y - r < 4 || y + r > H - 4) continue;
      const collides = placed.some((p) => Math.hypot(p.x - x, p.y - y) < p.r + r + 3);
      if (!collides) {
        placed.push({ row, x, y, r });
        done = true;
      }
    }
    if (!done) placed.push({ row, x: r + 6, y: r + 6, r });
  }
  return placed;
}

function wrapType(name: string, r: number): string[] {
  const maxChars = Math.max(6, Math.floor(r / 4.2));
  if (name.length <= maxChars) return [name];
  const words = name.split(" ");
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > maxChars && line) {
      lines.push(line);
      line = w;
    } else {
      line = (line + " " + w).trim();
    }
    if (lines.length === 2) break;
  }
  if (line && lines.length < 2) lines.push(line);
  if (lines.length === 2 && words.join(" ").length > lines.join(" ").length) {
    lines[1] = lines[1].slice(0, Math.max(1, maxChars - 1)) + "…";
  }
  return lines;
}

export function RoomPopularityChart({ rows }: { rows: PopularityRow[] }) {
  const [active, setActive] = useState<PopularityRow | null>(null);
  const bubbles = useMemo(() => packBubbles(rows), [rows]);

  if (!rows.length) {
    return <p className="py-8 text-center text-sm text-ink-muted">No room types configured yet.</p>;
  }
  const shown = active ?? rows[0];
  let bookedIdx = -1;

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Room popularity bubble chart — circle size is proportional to booking count"
      >
        {bubbles.map(({ row, x, y, r }) => {
          const isBooked = row.is_active && row.bookings > 0;
          if (isBooked) bookedIdx += 1;
          const fill = !row.is_active
            ? "#E2E8F0"
            : row.bookings > 0
              ? BOOKED_FILLS[bookedIdx % BOOKED_FILLS.length]
              : "#FDEBC8";
          const stroke = !row.is_active ? "#B8CDD3" : row.bookings > 0 ? fill : "#F59E0B";
          const textFill = !row.is_active ? "#8293A5" : row.bookings > 0 ? "#FFFFFF" : "#92600A";
          const lines = wrapType(row.room_type, r);
          const showType = r >= 24;
          return (
            <g
              key={row.room_id}
              onMouseEnter={() => setActive(row)}
              onClick={() => setActive(row)}
              className="cursor-pointer"
            >
              <title>
                {`${row.room_type}: ${row.bookings} bookings, ${inr(row.revenue)} revenue, ${row.occupancy_rate}% occupancy, ${row.is_active ? "active" : "inactive"}`}
              </title>
              <circle
                cx={x}
                cy={y}
                r={r}
                fill={fill}
                stroke={stroke}
                strokeWidth={shown?.room_id === row.room_id ? 3 : 1.2}
              />
              {showType
                ? lines.map((line, i) => (
                    <text
                      key={i}
                      x={x}
                      y={y - (lines.length - 1) * 7 + i * 14 - 2}
                      textAnchor="middle"
                      fill={textFill}
                      className="text-[12px] font-semibold"
                    >
                      {line}
                    </text>
                  ))
                : null}
              <text
                x={x}
                y={y + (showType ? lines.length * 7 + 8 : 4)}
                textAnchor="middle"
                fill={textFill}
                className="text-[12px] font-bold tabular-nums"
              >
                {row.bookings}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 px-1 text-[11.5px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-dark-teal" /> Has bookings
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-sun" /> Zero bookings
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-[#E2E8F0] ring-1 ring-compare" /> Inactive
        </span>
        <span>Size = booking count</span>
      </div>

      {shown ? (
        <div aria-live="polite" className="mt-3 rounded-xl bg-pale px-4 py-3 text-[13px] text-ink">
          <strong>{shown.room_type}</strong> — {shown.bookings} bookings · {inr(shown.revenue)}{" "}
          revenue · {shown.occupancy_rate}% occupancy · {shown.occupied_room_nights}/
          {shown.available_room_nights} room-nights · {shown.is_active ? "Active" : "Inactive"}
        </div>
      ) : null}
    </div>
  );
}
