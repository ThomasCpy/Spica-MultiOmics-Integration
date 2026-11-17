import { useState } from "react";

// Expression across tissues, as bars.
//
// Design decisions:
//
// *One azure, not the azure ramp.* There is one series, and bar length
// already carries the magnitude. A shade by value encodes it twice. Also,
// the pale end of the ramp is 1.44:1 on white, so such a bar is not visible.
// Length carries the number; the fill shows that data exists.
//
// *A number at each tip.* The art direction requires it, so the chart reads
// in grayscale and on a printed report. The contrast check also requires it:
// azure on white is 2.32:1, below the 3:1 limit for meaning without text.
// The numbers also make the log view safe: the bar is a shape, and the
// figure beside it is the fact.
//
// *Linear by default, log on request.* A bar means its length, so a log bar
// must say so. The chart labels it and puts the scale note below. But
// expression spans 0.1 to 684 in one profile, and without the log view the
// tail does not show at all.
//
// *No cut.* The default view is a slice, not a limit. The full list is one
// click away, and the record holds all values.

const DEFAULT_SHOWN = 12;
//: Below this, a chart is worse than the row of text above it: one bar at
//: full width says only "this is the largest of one".
const MIN_BARS = 3;
const BAR = 14; // px thick, well under the 24px cap; the rest of the row is air

export type TissueChartProps = {
  values: Record<string, number>;
  unit?: string;
  caption?: string;
  highlight?: string; // a tissue to mark, e.g. the peak
  noun?: string; // what a bar is, for "Show all 481 diseases"
  scales?: boolean; // offer the log view; off for bounded scores
};

export function TissueChart({
  values,
  unit = "",
  caption,
  highlight,
  noun = "tissues",
  scales = true,
}: TissueChartProps) {
  const [all, setAll] = useState(false);
  const [log, setLog] = useState(false);

  const ordered = Object.entries(values)
    .filter(([, value]) => typeof value === "number" && isFinite(value))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

  if (ordered.length < MIN_BARS) return null;

  const peak = ordered[0][1];
  const shown = all ? ordered : ordered.slice(0, DEFAULT_SHOWN);
  const hidden = ordered.length - shown.length;

  // log1p keeps zero at zero, which matters: a tissue where nothing was
  // detected must not vanish off the left edge or run to minus infinity.
  const extent = log ? Math.log1p(Math.max(peak, 0)) : peak;
  const length = (value: number) => {
    const raw = log ? Math.log1p(Math.max(value, 0)) : Math.max(value, 0);
    return extent > 0 ? Math.max(0.6, (raw / extent) * 100) : 0;
  };

  return (
    <figure className="m-0">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-2 text-[12px] text-slate">
        {caption}
        {unit && <span className="opacity-70">({unit})</span>}
        {scales && (
          <span className="ml-auto flex items-center gap-1">
            <ScaleButton active={!log} onClick={() => setLog(false)}>
              linear
            </ScaleButton>
            <ScaleButton active={log} onClick={() => setLog(true)}>
              log
            </ScaleButton>
          </span>
        )}
      </figcaption>

      <ul className="space-y-[6px]">
        {shown.map(([tissue, value]) => {
          const marked = highlight && tissue === highlight;
          return (
            <li
              key={tissue}
              className="grid grid-cols-[minmax(0,220px)_1fr_auto] items-center gap-3"
            >
              <span
                className={`truncate text-[12px] ${marked ? "text-ink" : "text-slate"}`}
                title={tissue}
              >
                {tissue}
              </span>
              {/* The track is a pale step of the same hue, so an empty bar
                  still reads as "measured and low" rather than as missing. */}
              <span className="block rounded-full bg-mist" style={{ height: BAR }}>
                <span
                  className="block h-full rounded-l-none rounded-r-[4px] bg-azure transition-[width]"
                  style={{ width: `${length(value)}%` }}
                  title={`${tissue}: ${value}${unit ? ` ${unit}` : ""}`}
                />
              </span>
              <span
                className={`w-[68px] text-right font-mono text-[12px] tabular-nums ${
                  marked ? "font-medium text-ink" : "text-ink"
                }`}
              >
                {format(value)}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1">
        {hidden > 0 && (
          <button
            type="button"
            onClick={() => setAll(true)}
            className="text-[12px] text-azure-deep transition-colors hover:underline"
          >
            Show all {ordered.length} {noun}
          </button>
        )}
        {all && ordered.length > DEFAULT_SHOWN && (
          <button
            type="button"
            onClick={() => setAll(false)}
            className="text-[12px] text-azure-deep transition-colors hover:underline"
          >
            Show the top {DEFAULT_SHOWN}
          </button>
        )}
        {log && (
          <span className="text-[11px] text-slate">
            Log scale: bar length not proportional; figures exact.
          </span>
        )}
      </div>
    </figure>
  );
}

function ScaleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-2 py-0.5 text-[11px] transition-colors ${
        active
          ? "bg-mist text-azure-deep"
          : "text-slate hover:text-azure-deep"
      }`}
    >
      {children}
    </button>
  );
}

/** Compact, but never so compact that two different values look the same. */
function format(value: number): string {
  // Counts are counts: 88 records, not 88.0.
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  if (value >= 100) return value.toFixed(0);
  if (value >= 1) return value.toFixed(1);
  return value.toFixed(2);
}
