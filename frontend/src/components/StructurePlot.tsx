import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { structureProfile, type StructureProfile } from "../views";

// The protein along its sequence, in three lanes that share one residue
// axis and one crosshair: how confidently AlphaFold predicts each residue,
// how damaging AlphaMissense expects changing it to be, and how many PDB
// entries resolve it.
//
// Three lanes, three scales, never one axis for two measures: each lane is
// its own small chart, stacked so the residue lines up. The thresholds that
// give each scale its meaning (pLDDT 50, 70, 90; AlphaMissense 0.34 and
// 0.564) are drawn as hairlines and named.

const W = 900;
const LEFT = 44;
const RIGHT = 12;
const LANES = [
  { key: "plddt", label: "AlphaFold confidence (pLDDT)", height: 84 },
  { key: "missense", label: "Missense pathogenicity (AlphaMissense, mean)", height: 64 },
  { key: "pdb", label: "PDB entries covering the residue", height: 44 },
] as const;
const GAP = 26;
const SHOWN = 10;

export function StructurePlot({ accession }: { accession: string }) {
  const [data, setData] = useState<StructureProfile | null>(null);
  const [problem, setProblem] = useState("");
  const [hover, setHover] = useState<number | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    let alive = true;
    structureProfile(accession)
      .then((result) => {
        if (!alive) return;
        if (result.error) setProblem(result.error);
        else setData(result);
      })
      .catch((error) => alive && setProblem(error instanceof Error ? error.message : "no answer"));
    return () => {
      alive = false;
    };
  }, [accession]);

  const lanes = useMemo(() => {
    if (!data) return null;
    const n = data.length;
    const plddt = new Array<number | null>(n + 1).fill(null);
    for (const [r, v] of data.plddt) plddt[r] = v;
    const missense = new Array<number | null>(n + 1).fill(null);
    for (const [r, v] of data.missense) missense[r] = v;
    const pdb = new Array<number>(n + 1).fill(0);
    for (const entry of data.pdb)
      for (const [a, b] of entry.ranges)
        for (let r = Math.max(1, a); r <= Math.min(n, b); r++) pdb[r] += 1;
    return { n, plddt, missense, pdb, pdbMax: Math.max(1, ...pdb) };
  }, [data]);

  if (problem) return <p className="px-5 py-4 text-[13px] text-slate">Structure view not opened: {problem}</p>;
  if (!data || !lanes)
    return (
      <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-slate">
        <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Reading AlphaFold DB and UniProt
      </p>
    );

  const { n } = lanes;
  const x = (residue: number) => LEFT + ((residue - 0.5) / n) * (W - LEFT - RIGHT);
  const tops: number[] = [];
  let y = 18;
  for (const lane of LANES) {
    tops.push(y);
    y += lane.height + GAP;
  }
  const H = y - GAP + 22;

  // A line for a lane, broken where a residue has no value.
  const path = (values: (number | null)[], top: number, height: number, max: number) => {
    let d = "";
    let open = false;
    for (let r = 1; r <= n; r++) {
      const v = values[r];
      if (v === null || v === undefined) {
        open = false;
        continue;
      }
      const py = top + height - (v / max) * height;
      d += `${open ? "L" : "M"}${x(r).toFixed(1)},${py.toFixed(1)}`;
      open = true;
    }
    return d;
  };

  const ticks = Array.from({ length: 6 }, (_, i) => Math.max(1, Math.round((n * i) / 5)));
  const residue = hover;
  const readout =
    residue !== null
      ? {
          plddt: lanes.plddt[residue],
          missense: lanes.missense[residue],
          pdb: lanes.pdb[residue],
        }
      : null;
  const entries = [...data.pdb].sort(
    (a, b) => (a.resolution ?? 99) - (b.resolution ?? 99) || a.id.localeCompare(b.id),
  );

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-2 text-[12px] text-slate">
        Residues 1 to {n.toLocaleString("en-US")}
        {data.model_version ? `, AlphaFold model v${data.model_version}` : ""}.
      </p>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          role="img"
          aria-label="Structure confidence, missense pathogenicity and PDB coverage along the sequence"
          onPointerMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const px = ((event.clientX - box.left) / box.width) * W;
            const r = Math.round(((px - LEFT) / (W - LEFT - RIGHT)) * n + 0.5);
            setHover(r >= 1 && r <= n ? r : null);
          }}
          onPointerLeave={() => setHover(null)}
        >
          {LANES.map((lane, i) => {
            const top = tops[i];
            return (
              <g key={lane.key}>
                <text x={LEFT} y={top - 6} className="fill-ink text-[11px]">{lane.label}</text>
                <line x1={LEFT} x2={W - RIGHT} y1={top + lane.height} y2={top + lane.height}
                  stroke="var(--color-slate)" strokeWidth={1} opacity={0.4} />
                {lane.key === "plddt" && (
                  <>
                    {[50, 70, 90].map((t) => (
                      <g key={t}>
                        <line x1={LEFT} x2={W - RIGHT} y1={top + lane.height - (t / 100) * lane.height}
                          y2={top + lane.height - (t / 100) * lane.height} stroke="var(--color-line)" />
                        <text x={LEFT - 6} y={top + lane.height - (t / 100) * lane.height + 3}
                          textAnchor="end" className="fill-slate font-mono text-[10px]">{t}</text>
                      </g>
                    ))}
                    <path d={path(lanes.plddt, top, lane.height, 100)} fill="none"
                      stroke="var(--color-azure-deep)" strokeWidth={2} strokeLinejoin="round" />
                  </>
                )}
                {lane.key === "missense" && (
                  <>
                    {[0.34, 0.564].map((t) => (
                      <g key={t}>
                        <line x1={LEFT} x2={W - RIGHT} y1={top + lane.height - t * lane.height}
                          y2={top + lane.height - t * lane.height} stroke="var(--color-line)" />
                        <text x={LEFT - 6} y={top + lane.height - t * lane.height + 3}
                          textAnchor="end" className="fill-slate font-mono text-[10px]">{t}</text>
                      </g>
                    ))}
                    <path d={path(lanes.missense, top, lane.height, 1)} fill="none"
                      stroke="var(--color-up)" strokeWidth={2} strokeLinejoin="round" />
                    {lanes.missense.every((v) => v === null) && (
                      <text x={LEFT + 8} y={top + lane.height / 2} className="fill-slate text-[11px]">
                        No AlphaMissense table for this model
                      </text>
                    )}
                  </>
                )}
                {lane.key === "pdb" && (
                  <>
                    {/* One stepped area, not a rectangle per residue: hundreds
                        of hairline rectangles leave seams where they meet. */}
                    <path
                      fill="var(--color-azure)"
                      d={(() => {
                        const step = (W - LEFT - RIGHT) / n;
                        const base = top + lane.height;
                        let d = `M${LEFT},${base}`;
                        for (let r = 1; r <= n; r++) {
                          const py = base - (lanes.pdb[r] / lanes.pdbMax) * lane.height;
                          const x0 = LEFT + (r - 1) * step;
                          d += `L${x0.toFixed(2)},${py.toFixed(2)}L${(x0 + step).toFixed(2)},${py.toFixed(2)}`;
                        }
                        return `${d}L${W - RIGHT},${base}Z`;
                      })()}
                    />
                    <text x={LEFT - 6} y={top + 8} textAnchor="end" className="fill-slate font-mono text-[10px]">
                      {lanes.pdbMax}
                    </text>
                    {data.pdb.length === 0 && (
                      <text x={LEFT + 8} y={top + lane.height / 2} className="fill-slate text-[11px]">
                        No experimental structure in UniProt's cross-references
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}
          {ticks.map((t) => (
            <text key={t} x={x(t)} y={H - 6} textAnchor="middle" className="fill-slate font-mono text-[10px]">{t}</text>
          ))}
          {residue !== null && (
            <line x1={x(residue)} x2={x(residue)} y1={10} y2={H - 18} stroke="var(--color-ink)" strokeWidth={1} opacity={0.35} />
          )}
        </svg>
        {residue !== null && readout && (
          <div
            className="pointer-events-none absolute top-0 z-10 rounded-[8px] border border-line bg-surface px-3 py-1.5 text-[12px] whitespace-nowrap"
            style={{ left: `${Math.min(80, Math.max(0, (x(residue) / W) * 100))}%` }}
          >
            <span className="font-mono font-semibold text-ink">residue {residue}</span>
            <span className="ml-2 text-slate">pLDDT</span>{" "}
            <span className="font-mono text-ink">{readout.plddt ?? "n/a"}</span>
            <span className="ml-2 text-slate">AlphaMissense</span>{" "}
            <span className="font-mono text-ink">{readout.missense ?? "n/a"}</span>
            <span className="ml-2 text-slate">PDB</span>{" "}
            <span className="font-mono text-ink">{readout.pdb}</span>
          </div>
        )}
      </div>
      {data.notes.length > 0 && (
        <p className="mt-2 text-[11px] text-slate">{data.notes.join(" ")}</p>
      )}
      {entries.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-[12px] text-slate">PDB entries, sharpest first</p>
          <ul className="grid gap-x-6 gap-y-1 text-[12px] sm:grid-cols-2">
            {(all ? entries : entries.slice(0, SHOWN)).map((entry) => (
              <li key={entry.id} className="flex gap-3">
                <span className="w-[44px] shrink-0 font-mono text-ink">{entry.id}</span>
                <span className="w-[92px] shrink-0 text-slate">{entry.method}</span>
                <span className="w-[54px] shrink-0 text-right font-mono text-ink">
                  {entry.resolution !== null ? `${entry.resolution} Å` : "n/a"}
                </span>
                <span className="truncate font-mono text-slate">
                  {entry.ranges.map(([a, b]) => `${a}-${b}`).join(", ")}
                </span>
              </li>
            ))}
          </ul>
          {entries.length > SHOWN && (
            <button type="button" onClick={() => setAll(!all)} className="mt-1.5 text-[12px] text-azure-deep hover:underline">
              {all ? `Show the sharpest ${SHOWN}` : `Show all ${entries.length} entries`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
