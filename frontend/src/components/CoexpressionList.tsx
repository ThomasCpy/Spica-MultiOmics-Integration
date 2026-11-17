import { useState } from "react";
import { Loader2 } from "lucide-react";
import { coexpressed, type Coexpression } from "../views";
import { diverging } from "../ramp";
import { useTheme } from "../theme";

// Genes whose tissue profile moves with this one, strongest first, every
// gene ranked. A diverging bar per gene: orange as r rises towards 1, azure
// as it falls towards -1, grey at zero, with the figure beside it.

const SHOWN = 25;

export function CoexpressionList({ symbol, ensemblId }: { symbol: string; ensemblId: string }) {
  useTheme(); // colours computed in code: render again when the theme changes
  const [data, setData] = useState<Coexpression | null>(null);
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState(SHOWN);
  const [ascending, setAscending] = useState(false);

  async function run() {
    setBusy(true);
    try {
      setData(await coexpressed(symbol, ensemblId));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-t border-line px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-ink">Co-expressed genes</span>
        <span className="text-[12px] text-slate">
          Correlation with the {symbol} GTEx tissue profile. Indicates shared regulation or cell type; not a mechanism.
        </span>
        {!data && (
          <button type="button" onClick={run} disabled={busy}
            className="flex h-7 items-center gap-1 rounded-full bg-azure-deep px-3 text-[12px] font-semibold text-on-accent disabled:opacity-60">
            {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Compute
          </button>
        )}
      </div>
      {data?.error && <p className="mt-2 text-[12px] text-slate">{data.error}</p>}
      {data && !data.error && (
        <>
          <p className="mt-2 text-[11px] text-slate">
            {data.method}, {data.tissues} tissues, {data.source}. {data.genes.length.toLocaleString("en-US")} genes
            ranked; {data.left_out.toLocaleString("en-US")} below {data.min_peak} TPM in all tissues excluded.
            <button type="button" onClick={() => setAscending(!ascending)} className="ml-2 text-azure-deep hover:underline">
              {ascending ? "Strongest positive first" : "Strongest negative first"}
            </button>
          </p>
          <ul className="mt-2 space-y-[3px]">
            {(ascending ? [...data.genes].reverse() : data.genes).slice(0, count).map((gene) => (
              <li key={gene.ensembl_id} className="grid grid-cols-[110px_1fr_52px] items-center gap-3 text-[12px]">
                <span className="truncate font-mono text-ink" title={gene.ensembl_id}>{gene.symbol}</span>
                <span className="relative block h-[8px] rounded-full bg-mist">
                  <span className="absolute top-0 h-full rounded-[3px]"
                    style={{
                      left: gene.r >= 0 ? "50%" : `${50 + gene.r * 50}%`,
                      width: `${Math.abs(gene.r) * 50}%`,
                      background: diverging(gene.r),
                    }} />
                  <span className="absolute left-1/2 top-[-2px] h-[12px] w-px bg-slate opacity-40" />
                </span>
                <span className="text-right font-mono tabular-nums text-ink">{gene.r.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex gap-4 text-[12px]">
            {/* Every gene is reachable; it arrives 500 at a time so a
                20,000-row list never freezes the window. */}
            {data.genes.length > count && (
              <button type="button" onClick={() => setCount(count + 500)} className="text-azure-deep hover:underline">
                Show {Math.min(500, data.genes.length - count)} more ({(data.genes.length - count).toLocaleString("en-US")} left)
              </button>
            )}
            {count > SHOWN && (
              <button type="button" onClick={() => setCount(SHOWN)} className="text-azure-deep hover:underline">
                Show the first {SHOWN}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
