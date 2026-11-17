import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { genomeAtlas, type Atlas } from "../views";
import { sequential } from "../ramp";
import { token, useTheme } from "../theme";

// One assay in all tissues, across the locus: tissues down, the window
// across, the gene body marked above. All rows show the same assay, so they
// share one sequential scale. A darker cell in one tissue is a real
// difference.
//
// A cell is too small for its number. Each row thus shows its peak value at
// the right, the hover gives the value of any cell, and the scale is under
// the chart. The colour uses a log scale; the figures are the values.

const ROW = 13;
const LABEL = 190;
const PEAK = 64;
const FAMILIES: [string, string][] = [
  ["dnase", "Open chromatin (DNase)"],
  ["h3k27ac", "Active chromatin (H3K27ac)"],
  ["gtex_coverage", "RNA-seq coverage (GTEx)"],
];

export function AtlasHeatmap({ symbol, ensemblId }: { symbol: string; ensemblId: string }) {
  const [family, setFamily] = useState("dnase");
  const [data, setData] = useState<Atlas | null>(null);
  const [busy, setBusy] = useState(false);
  const [order, setOrder] = useState<"peak" | "name">("peak");
  const [hover, setHover] = useState<{ row: number; bin: number } | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const theme = useTheme(); // a canvas does not follow tokens: draw again

  async function draw(which = family) {
    setBusy(true);
    try {
      setData(await genomeAtlas(symbol, ensemblId, which));
    } finally {
      setBusy(false);
    }
  }

  const rows = data && !data.error
    ? [...data.rows].sort((a, b) =>
        order === "peak" ? (b.peak ?? -1) - (a.peak ?? -1) || a.tissue.localeCompare(b.tissue)
                         : a.tissue.localeCompare(b.tissue))
    : [];

  useEffect(() => {
    if (!data || data.error || !canvas.current || !box.current) return;
    const width = box.current.clientWidth - LABEL - PEAK;
    const ratio = window.devicePixelRatio || 1;
    const c = canvas.current;
    c.width = Math.max(1, width) * ratio;
    c.height = rows.length * ROW * ratio;
    c.style.width = `${width}px`;
    c.style.height = `${rows.length * ROW}px`;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    const cell = width / data.bins;
    const top = Math.log1p(Math.max(data.max, 1e-9));
    rows.forEach((row, r) => {
      row.values.forEach((value, b) => {
        // No data is drawn as the surface, not as the bottom of the scale.
        ctx.fillStyle = value === null ? token("surface") : sequential(Math.log1p(Math.max(value, 0)) / top);
        ctx.fillRect(b * cell, r * ROW, cell + 0.5, ROW - 2);
      });
    });
  }, [data, rows, theme]);

  const geneSpan = data && !data.error
    ? {
        left: ((data.gene.start - data.start) / (data.end - data.start)) * 100,
        width: ((data.gene.end - data.gene.start) / (data.end - data.start)) * 100,
      }
    : null;
  const hovered = hover && rows[hover.row] && data
    ? {
        tissue: rows[hover.row].tissue,
        value: rows[hover.row].values[hover.bin],
        position: Math.round(data.start + ((hover.bin + 0.5) / data.bins) * (data.end - data.start)),
      }
    : null;

  return (
    <section className="border-t border-line px-5 py-5">
      <h3 className="text-[13px] font-semibold text-ink">Regulation atlas</h3>
      <p className="mt-1 text-[12px] text-slate">
        One assay, all tissues, this window. One scale for all rows.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {FAMILIES.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={family === key}
            onClick={() => { setFamily(key); if (data) draw(key); }}
            className={`rounded-full px-3 py-1 text-[12px] transition-colors ${
              family === key ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"}`}>
            {label}
          </button>
        ))}
        <button type="button" onClick={() => draw()} disabled={busy}
          className="flex h-7 items-center gap-1 rounded-full bg-azure-deep px-3 text-[12px] font-semibold text-on-accent disabled:opacity-60">
          {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Draw
        </button>
        {data && !data.error && (
          <button type="button" onClick={() => setOrder(order === "peak" ? "name" : "peak")}
            className="ml-auto text-[12px] text-azure-deep hover:underline">
            {order === "peak" ? "Order by name" : "Order by peak"}
          </button>
        )}
      </div>
      {data?.error && <p className="mt-2 text-[12px] text-error">{data.error}</p>}
      {data && !data.error && geneSpan && (
        <div ref={box} className="relative mt-3">
          <div className="relative mb-1 h-5" style={{ marginLeft: LABEL, marginRight: PEAK }}>
            <span className="absolute top-2 h-[6px] rounded-[2px] bg-ink"
              style={{ left: `${geneSpan.left}%`, width: `${geneSpan.width}%` }} />
            <span className="absolute top-[-2px] font-mono text-[10px] text-ink"
              style={{ left: `${geneSpan.left}%` }}>
              {data.gene.symbol} ({data.gene.strand})
            </span>
          </div>
          <div className="flex">
            <ul style={{ width: LABEL }} className="shrink-0">
              {rows.map((row) => (
                <li key={row.key} className="truncate pr-2 text-right text-[11px] text-ink" style={{ height: ROW, lineHeight: `${ROW}px` }}
                  title={row.tissue}>{row.tissue}</li>
              ))}
            </ul>
            <canvas ref={canvas} className="block"
              onPointerMove={(event) => {
                const rect = event.currentTarget.getBoundingClientRect();
                const row = Math.floor((event.clientY - rect.top) / ROW);
                const bin = Math.floor(((event.clientX - rect.left) / rect.width) * data.bins);
                setHover(row >= 0 && row < rows.length && bin >= 0 && bin < data.bins ? { row, bin } : null);
              }}
              onPointerLeave={() => setHover(null)} />
            <ul style={{ width: PEAK }} className="shrink-0">
              {rows.map((row) => (
                <li key={row.key} className="pl-2 font-mono text-[11px] tabular-nums text-ink" style={{ height: ROW, lineHeight: `${ROW}px` }}>
                  {row.peak === null ? "none" : row.peak >= 100 ? row.peak.toFixed(0) : row.peak.toFixed(2)}
                </li>
              ))}
            </ul>
          </div>
          {hovered && (
            <p className="mt-2 font-mono text-[11px] text-ink">
              {hovered.tissue}, {data.chrom}:{hovered.position.toLocaleString("en-US")}:{" "}
              {hovered.value === null ? "no data" : hovered.value}
            </p>
          )}
          <div className="mt-2 flex items-center gap-2 text-[11px] text-slate">
            <span className="font-mono">0</span>
            <span className="h-[8px] w-40 rounded-full"
              style={{ background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map(sequential).join(", ")})` }} />
            <span className="font-mono">{data.max >= 100 ? data.max.toFixed(0) : data.max.toFixed(2)}</span>
            <span>{data.unit}, log colour scale. Right column: tissue peak in the window.</span>
          </div>
          {data.failed.length > 0 && (
            <p className="mt-1 text-[11px] text-error">
              Not read: {data.failed.map((f) => f.tissue).join(", ")}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
