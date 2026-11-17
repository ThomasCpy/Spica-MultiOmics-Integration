import { useState } from "react";

// Genes on the two specificity measures at once: tau across, peak over
// the median tissue up. Both are comparable between genes (unlike a peak
// TPM), which is the only reason they can share a plot.
//
// One hue, because the genes are identified by their labels, not by a
// colour key: with up to eight genes every dot is direct-labelled, so no
// legend is needed and nothing depends on telling hues apart. The band
// limits that name tau's classes are drawn as hairlines, so a dot's class
// can be read off the plot. The table below carries every value too.

export type MapPoint = { symbol: string; tau: number | null; fold: number | null };

const W = 720;
const H = 330;
const M = { top: 34, right: 96, bottom: 44, left: 64 };

export function SpecificityMap({
  points,
  bands,
}: {
  points: MapPoint[];
  bands: { from: number; to: number; label: string }[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const plotted = points.filter(
    (p): p is { symbol: string; tau: number; fold: number } =>
      typeof p.tau === "number" && typeof p.fold === "number" && p.fold > 0,
  );
  const missing = points.filter((p) => !plotted.includes(p as never));
  if (plotted.length < 2) return null;

  const top = Math.max(2, Math.ceil(Math.log10(Math.max(...plotted.map((p) => p.fold))) + 0.2));
  const x = (tau: number) => M.left + Math.min(Math.max(tau, 0), 1) * (W - M.left - M.right);
  const y = (fold: number) =>
    H - M.bottom - (Math.log10(Math.max(fold, 1)) / top) * (H - M.top - M.bottom);

  // Direct labels to the right of each dot; a label that would sit on top
  // of an earlier one moves to the left, then down a line.
  const placed: { x: number; y: number; anchor: "start" | "end" }[] = [];
  const order = plotted
    .map((p, index) => ({ p, index }))
    .sort((a, b) => a.p.fold - b.p.fold);
  const labels: Record<number, { x: number; y: number; anchor: "start" | "end" }> = {};
  for (const { p, index } of order) {
    const cx = x(p.tau);
    const cy = y(p.fold);
    const width = p.symbol.length * 7.6 + 4;
    const collides = (lx: number, ly: number, anchor: "start" | "end") =>
      placed.some((q) => {
        const a0 = anchor === "start" ? lx : lx - width;
        const b0 = q.anchor === "start" ? q.x : q.x - width;
        return Math.abs(q.y - ly) < 14 && a0 < b0 + width && b0 < a0 + width;
      });
    let spot = { x: cx + 11, y: cy + 4, anchor: "start" as "start" | "end" };
    if (collides(spot.x, spot.y, spot.anchor)) spot = { x: cx - 11, y: cy + 4, anchor: "end" };
    if (collides(spot.x, spot.y, spot.anchor)) spot = { x: cx + 11, y: cy + 18, anchor: "start" };
    placed.push(spot);
    labels[index] = spot;
  }

  const focus = hover === null ? null : plotted[hover];

  return (
    <figure className="m-0">
      <figcaption className="mb-2 text-[12px] leading-relaxed text-slate">
        Across: tau. Up: peak over median tissue (log). Up and right: more tissue-restricted. Values in the
        table below.
      </figcaption>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
          aria-label="Specificity map of the compared genes">
          {/* Decades on the fold axis. */}
          {Array.from({ length: top + 1 }, (_, power) => {
            const fold = 10 ** power;
            return (
              <g key={power}>
                <line x1={M.left} x2={W - M.right} y1={y(fold)} y2={y(fold)}
                  stroke="var(--color-line)" strokeWidth={1} />
                <text x={M.left - 8} y={y(fold) + 4} textAnchor="end"
                  className="fill-slate font-mono text-[11px]">
                  {fold.toLocaleString("en-US")}×
                </text>
              </g>
            );
          })}
          {/* Tau's band limits, named along the top. */}
          {bands.map((band, index) => (
            <g key={band.label}>
              {index > 0 && (
                <line x1={x(band.from)} x2={x(band.from)} y1={M.top - 4} y2={H - M.bottom}
                  stroke="var(--color-line)" strokeWidth={1} />
              )}
              <text x={(x(band.from) + x(band.to)) / 2} y={M.top - 12} textAnchor="middle"
                className="fill-slate text-[11px]">
                {band.label}
              </text>
            </g>
          ))}
          <line x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom}
            stroke="var(--color-slate)" strokeWidth={1} opacity={0.5} />
          {[0, 0.15, 0.5, 0.85, 1].map((tick) => (
            <text key={tick} x={x(tick)} y={H - M.bottom + 16} textAnchor="middle"
              className="fill-slate font-mono text-[11px]">
              {tick}
            </text>
          ))}
          <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle"
            className="fill-slate text-[11px]">
            RNA specificity, tau
          </text>

          {plotted.map((p, index) => (
            <g key={p.symbol}
              onPointerEnter={() => setHover(index)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              tabIndex={0}
              aria-label={`${p.symbol}: tau ${p.tau}, ${p.fold} times the median tissue`}
              className="cursor-default outline-none">
              {/* The hit area is bigger than the dot. */}
              <circle cx={x(p.tau)} cy={y(p.fold)} r={14} fill="transparent" />
              <circle cx={x(p.tau)} cy={y(p.fold)} r={hover === index ? 7 : 6}
                fill="var(--color-azure)" stroke="var(--color-surface)" strokeWidth={2} />
              <text x={labels[index].x} y={labels[index].y} textAnchor={labels[index].anchor}
                className="fill-ink font-mono text-[12px] font-medium">
                {p.symbol}
              </text>
            </g>
          ))}
        </svg>

        {focus && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-[8px] border border-line bg-surface px-3 py-2 text-[12px]"
            style={{
              left: `${(x(focus.tau) / W) * 100}%`,
              top: `${((y(focus.fold) - 12) / H) * 100}%`,
            }}
          >
            <div className="font-mono font-semibold text-ink">{focus.symbol}</div>
            <div className="mt-0.5 whitespace-nowrap text-slate">
              tau <span className="font-mono text-ink">{focus.tau}</span>
              {" · "}
              <span className="font-mono text-ink">
                {focus.fold.toLocaleString("en-US", { maximumFractionDigits: 1 })}×
              </span>{" "}
              the median tissue
            </div>
          </div>
        )}
      </div>
      {missing.length > 0 && (
        <p className="mt-2 text-[11px] text-slate">
          Not plotted, no RNA profile:{" "}
          <span className="font-mono text-ink">{missing.map((p) => p.symbol).join(", ")}</span>.
        </p>
      )}
    </figure>
  );
}
