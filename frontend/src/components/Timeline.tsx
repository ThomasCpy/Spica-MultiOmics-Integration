import { useState } from "react";

// Counts over time, as columns: how much appeared, and when.
//
// The bucket follows the window so a chart never has more than about
// twenty columns: weeks for 30 and 90 days, months for a year, quarters
// for five. With twenty columns at most, every column keeps its figure on the cap, as
// the art direction asks, without the figures colliding. Empty periods
// are drawn as zero, not skipped: a quiet quarter is part of the answer.

type Bucket = { start: Date; end: Date; label: string; long: string; count: number };

const DAY = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parse(text: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text);
  return match ? new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])) : null;
}

function day(date: Date): string {
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

function buckets(from: Date, to: Date, days: number): Bucket[] {
  const out: Bucket[] = [];
  if (days <= 120) {
    // Weeks starting on Monday.
    let start = new Date(from.getTime() - ((from.getUTCDay() + 6) % 7) * DAY);
    while (start <= to) {
      const end = new Date(start.getTime() + 6 * DAY);
      out.push({ start, end, label: day(start), long: `Week of ${day(start)} ${start.getUTCFullYear()}`, count: 0 });
      start = new Date(start.getTime() + 7 * DAY);
    }
  } else if (days <= 400) {
    let year = from.getUTCFullYear();
    let month = from.getUTCMonth();
    while (Date.UTC(year, month, 1) <= to.getTime()) {
      const start = new Date(Date.UTC(year, month, 1));
      const end = new Date(Date.UTC(year, month + 1, 0));
      const label = month === 0 || out.length === 0 ? `${MONTHS[month]} ${year}` : MONTHS[month];
      out.push({ start, end, label, long: `${MONTHS[month]} ${year}`, count: 0 });
      month += 1;
      if (month === 12) { month = 0; year += 1; }
    }
  } else {
    let year = from.getUTCFullYear();
    let quarter = Math.floor(from.getUTCMonth() / 3);
    while (Date.UTC(year, quarter * 3, 1) <= to.getTime()) {
      const start = new Date(Date.UTC(year, quarter * 3, 1));
      const end = new Date(Date.UTC(year, quarter * 3 + 3, 0));
      const label = quarter === 0 || out.length === 0 ? `Q${quarter + 1} ${year}` : `Q${quarter + 1}`;
      out.push({ start, end, label, long: `Q${quarter + 1} ${year}`, count: 0 });
      quarter += 1;
      if (quarter === 4) { quarter = 0; year += 1; }
    }
  }
  return out;
}

export function Timeline({
  dates,
  window,
  caption,
  noun,
}: {
  dates: string[];
  window: { days: number; from: string; to: string };
  caption: string;
  noun: string; // "articles", "families"
}) {
  const [hover, setHover] = useState<number | null>(null);
  const from = parse(window.from);
  const to = parse(window.to);
  if (!from || !to || !dates.length) return null;

  const columns = buckets(from, to, window.days);
  let undated = 0;
  for (const text of dates) {
    const date = parse(text);
    const bucket = date && columns.find((b) => date >= b.start && date <= b.end);
    if (bucket) bucket.count += 1;
    else undated += 1;
  }
  const peak = Math.max(1, ...columns.map((b) => b.count));
  // The window rarely starts on a period boundary, so the end columns are
  // usually part-periods. A short column there is the calendar, not a lull.
  const partial = columns.filter((b) => b.start < from || b.end > to).map((b) => b.long);
  const PLOT = 96; // px of column height at the peak

  return (
    <figure className="m-0">
      <figcaption className="mb-3 text-[12px] text-slate">{caption}</figcaption>
      <div className="relative">
        <div className="flex items-end gap-[2px] border-b border-line" style={{ height: PLOT + 22 }}>
          {columns.map((bucket, index) => (
            <div
              key={bucket.long}
              className="flex min-w-0 flex-1 flex-col items-center justify-end"
              style={{ height: "100%" }}
              onPointerEnter={() => setHover(index)}
              onPointerLeave={() => setHover(null)}
              tabIndex={0}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              aria-label={`${bucket.long}: ${bucket.count} ${noun}`}
            >
              <span
                className={`mb-1 font-mono text-[11px] tabular-nums ${
                  bucket.count ? "text-ink" : "text-slate"
                }`}
              >
                {bucket.count}
              </span>
              <span
                className={`block w-full max-w-[24px] rounded-t-[4px] transition-colors ${
                  hover === index ? "bg-azure-deep" : "bg-azure"
                }`}
                // Zero stays zero: no stub pretending something is there.
                style={{ height: bucket.count ? Math.max(3, (bucket.count / peak) * PLOT) : 0 }}
              />
            </div>
          ))}
        </div>
        <div className="mt-1.5 flex gap-[2px]">
          {columns.map((bucket) => {
            // Every label when they fit. When they would crowd, the year
            // alone at its first quarter or month, so each bar can still be
            // placed in time; the hover gives every bar its own label.
            const crowded = columns.length > 14;
            const yearStart = /^(Q1|Jan) /.test(bucket.long);
            return (
              <span
                key={bucket.long}
                className={`min-w-0 flex-1 text-center text-[10px] text-slate ${crowded ? "overflow-visible whitespace-nowrap" : "truncate"}`}
              >
                {crowded ? (yearStart ? bucket.long.split(" ")[1] : "") : bucket.label}
              </span>
            );
          })}
        </div>
        {hover !== null && (
          <div
            className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-[8px] border border-line bg-surface px-3 py-1.5 text-[12px] whitespace-nowrap"
            style={{ left: `${((hover + 0.5) / columns.length) * 100}%` }}
          >
            <span className="font-mono font-semibold text-ink">{columns[hover].count}</span>{" "}
            <span className="text-slate">
              {noun}, {columns[hover].long}
            </span>
          </div>
        )}
      </div>
      {partial.length > 0 && (
        <p className="mt-2 text-[11px] text-slate">
          {partial.join(" and ")}: partly inside the window; {partial.length === 1 ? "count" : "counts"} not comparable.
        </p>
      )}
      {undated > 0 && (
        <p className="mt-2 text-[11px] text-slate">
          {undated} {noun} without a full date, not charted.
        </p>
      )}
    </figure>
  );
}
