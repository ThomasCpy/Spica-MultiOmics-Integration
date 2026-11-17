import { useMemo, useState } from "react";
import type { Dogma } from "../report";

// Agreement between sources on where the gene is expressed. Each pair of
// layers (two RNA atlases, single cell, antibody, mass spectrometry) gives
// one correlation: Pearson r of log(1 + value) over the organs that both
// measure. Python calculates it (`spica.dogma.agreement`), so the AI tools
// read the same figures. A click on a cell shows that pair organ by organ.
//
// The colour diverges around zero: azure when the two rise and fall
// together, orange when they move apart, grey when there is no relation.
// Each cell keeps its number, so the matrix reads in grayscale.

type Pair = { a: string; b: string; n: number; rho: number | null };

const SIZE = 300;
const PAD = { left: 52, right: 14, top: 24, bottom: 40 };
const LEVELS = ["Not detected", "Low", "Medium", "High"];

// Tokens, so the matrix follows the theme; each step brings the text that
// reads on it.
function fill(r: number | null): { bg: string; ink: string } {
  if (r === null) return { bg: "var(--color-surface)", ink: "var(--color-slate)" };
  if (r >= 0.8) return { bg: "var(--color-seq-4)", ink: "var(--color-on-seq-4)" };
  if (r >= 0.6) return { bg: "var(--color-seq-3)", ink: "var(--color-on-seq-3)" };
  if (r >= 0.4) return { bg: "var(--color-seq-2)", ink: "var(--color-on-seq-2)" };
  if (r >= 0.2) return { bg: "var(--color-seq-1)", ink: "var(--color-on-seq-1)" };
  if (r > -0.2) return { bg: "var(--color-neutral)", ink: "var(--color-ink)" };
  if (r > -0.5) return { bg: "var(--color-up-soft)", ink: "var(--color-ink)" };
  return { bg: "var(--color-up)", ink: "var(--color-ink)" };
}

export function SourceAgreement({ dogma }: { dogma: Dogma & { agreement?: Pair[] } }) {
  const pairs = dogma.agreement ?? [];
  const layers = dogma.layers;
  const label = (key: string) => layers.find((l) => l.key === key)?.label ?? key;
  const lookup = (a: string, b: string) =>
    pairs.find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a));
  const first = pairs.find((p) => p.rho !== null) ?? null;
  const [chosen, setChosen] = useState<Pair | null>(first);
  const [view, setView] = useState<"plot" | "list">("plot");

  if (layers.length < 2 || !pairs.length) return null;

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-3 text-[12px] text-slate">
        Source agreement: Pearson r of log(1 + value) over shared organs.
      </p>
      <div className="flex flex-wrap items-start gap-6">
        <table className="border-separate border-spacing-[2px] text-[12px]">
          <thead>
            <tr>
              <th />
              {layers.slice(1).map((layer) => (
                <th key={layer.key} className="max-w-[86px] px-1 pb-1 text-left align-bottom font-medium text-slate">
                  {layer.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {layers.slice(0, -1).map((row, i) => (
              <tr key={row.key}>
                <th className="pr-2 text-right font-medium text-slate">{row.label}</th>
                {layers.slice(1).map((column, j) => {
                  if (j < i) return <td key={column.key} />;
                  const pair = lookup(row.key, column.key);
                  const colours = fill(pair?.rho ?? null);
                  const active =
                    chosen && pair && chosen.a === pair.a && chosen.b === pair.b;
                  return (
                    <td key={column.key}>
                      <button
                        type="button"
                        disabled={!pair || pair.rho === null}
                        onClick={() => pair && setChosen(pair)}
                        title={
                          pair
                            ? pair.rho === null
                              ? `${pair.n} organs in common: too few, or one side flat`
                              : `r = ${pair.rho} over ${pair.n} organs`
                            : ""
                        }
                        className={`h-9 w-[86px] rounded-[6px] font-mono tabular-nums transition-[outline] ${
                          active ? "outline outline-2 outline-offset-1 outline-ink" : ""
                        }`}
                        style={{ background: colours.bg, color: colours.ink }}
                      >
                        {pair?.rho ?? "n/a"}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {chosen && (
          <div className="min-w-[300px] flex-1">
            <div className="mb-1 flex items-baseline gap-2 text-[12px] text-slate">
              <span className="text-ink">
                {label(chosen.a)} against {label(chosen.b)}
              </span>
              <span className="font-mono">
                r = {chosen.rho}, {chosen.n} organs
              </span>
              <span className="ml-auto flex gap-1">
                {(["plot", "list"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={view === v}
                    onClick={() => setView(v)}
                    className={`rounded-full px-2 py-0.5 text-[11px] ${
                      view === v ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </span>
            </div>
            <PairView dogma={dogma} pair={chosen} view={view} />
          </div>
        )}
      </div>
    </div>
  );
}

type Point = { organ: string; a: number; b: number; da: string; db: string };

function PairView({ dogma, pair, view }: { dogma: Dogma; pair: Pair; view: "plot" | "list" }) {
  const layerA = dogma.layers.find((l) => l.key === pair.a);
  const layerB = dogma.layers.find((l) => l.key === pair.b);
  const points: Point[] = useMemo(
    () =>
      dogma.rows
        .filter((row) => row.cells[pair.a]?.value != null && row.cells[pair.b]?.value != null)
        .map((row) => ({
          organ: row.organ,
          a: row.cells[pair.a]!.value as number,
          b: row.cells[pair.b]!.value as number,
          da: row.cells[pair.a]!.display,
          db: row.cells[pair.b]!.display,
        })),
    [dogma, pair],
  );
  const [hover, setHover] = useState<Point | null>(null);

  if (view === "list") {
    const sorted = [...points].sort((x, y) => y.a - x.a || x.organ.localeCompare(y.organ));
    return (
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-slate">
            <th className="py-1 font-medium">Organ</th>
            <th className="py-1 text-right font-medium">{layerA?.label}</th>
            <th className="py-1 text-right font-medium">{layerB?.label}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {sorted.map((p) => (
            <tr key={p.organ}>
              <td className="py-1 text-ink">{p.organ}</td>
              <td className="py-1 text-right font-mono tabular-nums text-ink">{p.da}</td>
              <td className="py-1 text-right font-mono tabular-nums text-ink">{p.db}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  const tx = (v: number) => Math.log1p(Math.max(0, v));
  const maxA = Math.max(...points.map((p) => tx(p.a)), 0.0001);
  const maxB = Math.max(...points.map((p) => tx(p.b)), 0.0001);
  const width = SIZE + PAD.left + PAD.right;
  const height = SIZE + PAD.top + PAD.bottom;
  const x = (v: number) => PAD.left + (tx(v) / maxA) * SIZE;
  const y = (v: number) => PAD.top + SIZE - (tx(v) / maxB) * SIZE;

  // Labels where they help: the organs that lead on either side, and the
  // ones the two sources disagree on most. Every point has its figures on hover.
  const share = (p: Point) => [tx(p.a) / maxA, tx(p.b) / maxB];
  const lead = [...points]
    .sort((p, q) => Math.max(...share(q)) - Math.max(...share(p)))
    .slice(0, 4);
  const apart = [...points]
    .sort((p, q) => {
      const [pa, pb] = share(p);
      const [qa, qb] = share(q);
      return Math.abs(qa - qb) - Math.abs(pa - pb);
    })
    .slice(0, 2);
  const labelled = new Set([...lead, ...apart].map((p) => p.organ));

  const ticks = (layer: typeof layerA, max: number) =>
    layer?.kind === "level"
      ? LEVELS.map((name, at) => ({ value: at, name }))
      : [0, 1, 10, 100, 1000, 10000, 100000, 1000000]
          .filter((v) => tx(v) <= max * 1.001)
          .map((v) => ({ value: v, name: v.toLocaleString("en-US") }));

  return (
    <div className="relative">
      <svg width={width} height={height} role="img" aria-label={`${layerA?.label} against ${layerB?.label}, by organ`}>
        {ticks(layerA, maxA).map((t) => (
          <g key={`x${t.value}`}>
            <line x1={x(t.value)} x2={x(t.value)} y1={PAD.top} y2={PAD.top + SIZE} className="stroke-line" />
            <text x={x(t.value)} y={PAD.top + SIZE + 14} textAnchor="middle" className="fill-slate text-[10px]">
              {t.name}
            </text>
          </g>
        ))}
        {ticks(layerB, maxB).map((t) => (
          <g key={`y${t.value}`}>
            <line x1={PAD.left} x2={PAD.left + SIZE} y1={y(t.value)} y2={y(t.value)} className="stroke-line" />
            <text x={PAD.left - 6} y={y(t.value) + 3} textAnchor="end" className="fill-slate text-[10px]">
              {t.name}
            </text>
          </g>
        ))}
        <text x={PAD.left + SIZE / 2} y={height - 6} textAnchor="middle" className="fill-slate text-[11px]">
          {layerA?.label} {layerA?.kind === "number" ? `(${layerA.unit}, log)` : ""}
        </text>
        {points.map((p) => (
          <g
            key={p.organ}
            onMouseEnter={() => setHover(p)}
            onMouseLeave={() => setHover(null)}
            className="cursor-default"
          >
            <circle cx={x(p.a)} cy={y(p.b)} r={10} className="fill-transparent" />
            <circle cx={x(p.a)} cy={y(p.b)} r={4.5} className="fill-azure stroke-surface" strokeWidth={2} />
            {labelled.has(p.organ) && (
              <text
                x={x(p.a) + (x(p.a) > PAD.left + SIZE * 0.7 ? -7 : 7)}
                y={Math.max(12, y(p.b) - 6)}
                textAnchor={x(p.a) > PAD.left + SIZE * 0.7 ? "end" : "start"}
                className="fill-ink text-[11px]"
              >
                {p.organ}
              </text>
            )}
          </g>
        ))}
      </svg>
      <p className="-mt-1 pl-[52px] text-[11px] text-slate">
        Up: {layerB?.label}
        {layerB?.kind === "number" ? ` (${layerB.unit}, log)` : ""}. Point: one organ.
      </p>
      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 whitespace-nowrap rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-[12px]"
          style={{ left: Math.min(x(hover.a) + 10, width - 200), top: Math.max(0, y(hover.b) - 44) }}
        >
          <span className="font-semibold text-ink">{hover.organ}</span>
          <span className="ml-2 text-slate">
            {layerA?.label} <span className="font-mono text-ink">{hover.da}</span>, {layerB?.label}{" "}
            <span className="font-mono text-ink">{hover.db}</span>
          </span>
        </div>
      )}
    </div>
  );
}
