import { useEffect, useState } from "react";
import { diseaseGenetics, type DiseaseGenetics as Data } from "../views";

// Three kinds of disease evidence, side by side:
// - the Open Targets association score,
// - the ClinVar variants in the gene that labs classify as pathogenic (rare),
// - the strongest GWAS association (common).
// The three measures have three scales. They use three bars in three
// columns, each with its own figure, never one shared axis. A disease with
// both kinds of genetic evidence is the strongest case.

const STEP = 25;
const GENOME_WIDE = 7.3;

type Filter = "all" | "pathogenic" | "gwas";

export function DiseaseGenetics({ symbol, ensemblId }: { symbol: string; ensemblId: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [count, setCount] = useState(STEP);
  const [filter, setFilter] = useState<Filter>("all");
  const [traits, setTraits] = useState(STEP);

  useEffect(() => {
    let live = true;
    diseaseGenetics(symbol, ensemblId)
      .then((found) => live && setData(found))
      .catch((error) => live && setData({ error: String(error) } as Data));
    return () => {
      live = false;
    };
  }, [symbol, ensemblId]);

  if (!data) {
    return <div className="border-t border-line px-5 py-4 text-[12px] text-slate">Joining diseases and variants.</div>;
  }
  if (data.error) {
    return <div className="border-t border-line px-5 py-4 text-[12px] text-slate">{data.error}</div>;
  }

  const rows = data.rows.filter((row) =>
    filter === "pathogenic" ? row.pathogenic > 0 : filter === "gwas" ? row.gwas > 0 : true,
  );
  const shown = rows.slice(0, count);
  const topScore = Math.max(...data.rows.map((row) => row.score), 0.0001);
  const topPathogenic = Math.max(...data.rows.map((row) => row.pathogenic), 1);
  // Each list on its own scale: a measurement at 1e-1364 would flatten
  // every disease's bar beside it.
  const topGwas = Math.max(...data.rows.map((row) => row.gwas), 1);
  const topTrait = Math.max(...data.gwas_only.map((t) => t.mlog10p), 1);
  const s = data.summary;
  const columns = data.gwas
    ? "grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]"
    : "grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]";
  const filters: [Filter, string][] = [
    ["all", "every disease"],
    ["pathogenic", "with pathogenic variants"],
    ...(data.gwas ? ([["gwas", "with GWAS associations"]] as [Filter, string][]) : []),
  ];

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-1 text-[12px] text-slate">
        Disease association (Open Targets) and pathogenic or likely pathogenic ClinVar variants in {data.symbol}
        {data.gwas ? ", with the strongest GWAS Catalog association" : ""}; matched on disease identifiers. <span className="opacity-70">{data.sources}</span>
      </p>
      <p className="mb-3 text-[13px] text-ink">
        Associated diseases: {s.associations.toLocaleString("en-US")}. With pathogenic variants: {s.with_pathogenic}
        {data.gwas ? `. With GWAS associations: ${s.with_gwas}` : ""}
        {s.top_supported ? `. Strongest with pathogenic variants: ${s.top_supported}` : ""}.
      </p>
      <div className="mb-2 flex flex-wrap items-center gap-1 text-[11px]">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => {
              setFilter(value);
              setCount(STEP);
            }}
            className={`rounded-full px-2 py-0.5 ${
              filter === value ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={`grid ${columns} gap-x-4 border-b border-line pb-1 text-[11px] text-slate`}>
        <span>Disease</span>
        <span>Association (Open Targets, 0 to 1)</span>
        <span>Pathogenic variants (ClinVar)</span>
        {data.gwas && <span>GWAS, strongest (-log10 p)</span>}
      </div>
      <ul className="mt-1 space-y-[5px]">
        {shown.map((row) => (
          <li
            key={row.id || row.disease}
            className={`grid ${columns} items-center gap-x-4 text-[12px]`}
            title={[
              row.conditions.length ? `ClinVar: ${row.conditions.join("; ")}` : "No ClinVar condition matches",
              data.gwas ? (row.gwas_traits.length ? `GWAS: ${row.gwas_traits.join("; ")}` : "No GWAS trait matches") : "",
            ]
              .filter(Boolean)
              .join("\n")}
          >
            <span className="truncate text-ink">{row.disease}</span>
            <Bar value={row.score} max={topScore} label={row.score.toFixed(3)} />
            {row.records ? (
              <Bar value={row.pathogenic} max={topPathogenic} label={`${row.pathogenic} of ${row.records}`} />
            ) : (
              <span className="text-[11px] text-slate">no ClinVar condition</span>
            )}
            {data.gwas &&
              (row.gwas ? (
                <Bar value={row.gwas} max={topGwas} label={row.gwas.toFixed(1)} faint={row.gwas < GENOME_WIDE} />
              ) : (
                <span className="text-[11px] text-slate">no GWAS trait</span>
              ))}
          </li>
        ))}
      </ul>
      <More total={rows.length} count={count} setCount={setCount} />
      {data.clinvar_only.length > 0 && (
        <div className="mt-4">
          <p className="text-[12px] text-slate">
            ClinVar conditions without a matched association ({data.clinvar_only.length}):
          </p>
          <ul className="mt-1 columns-2 gap-6 text-[12px]">
            {data.clinvar_only.map((condition) => (
              <li key={condition.condition} className="break-inside-avoid text-ink">
                {condition.condition}{" "}
                <span className="font-mono text-slate">
                  {condition.pathogenic} of {condition.records}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.gwas_only.length > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-[12px] text-slate">
            GWAS traits without a matched association ({data.gwas_only.length}), mostly measurements.
            Strongest association, -log10 p; pale below 7.3 (genome-wide significance).
          </p>
          <ul className="space-y-[4px]">
            {data.gwas_only.slice(0, traits).map((trait) => (
              <li
                key={trait.trait}
                className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1.4fr)_minmax(0,1fr)] items-center gap-x-4 text-[12px]"
                title={`${trait.associations} associations; lead variant ${trait.variant}`}
              >
                <span className="truncate text-ink">{trait.trait}</span>
                <Bar value={trait.mlog10p} max={topTrait} label={trait.mlog10p.toFixed(1)} faint={trait.mlog10p < GENOME_WIDE} />
                <span className="truncate text-[11px] text-slate">{trait.relation}</span>
              </li>
            ))}
          </ul>
          <More total={data.gwas_only.length} count={traits} setCount={setTraits} />
        </div>
      )}
    </div>
  );
}

function More({
  total,
  count,
  setCount,
}: {
  total: number;
  count: number;
  setCount: (n: number) => void;
}) {
  return (
    <div className="mt-2 flex gap-4 text-[12px]">
      {total > count && (
        <>
          <button type="button" onClick={() => setCount(count + STEP)} className="text-azure-deep hover:underline">
            Show {Math.min(STEP, total - count)} more ({(total - count).toLocaleString("en-US")} left)
          </button>
          <button type="button" onClick={() => setCount(total)} className="text-azure-deep hover:underline">
            Show all {total.toLocaleString("en-US")}
          </button>
        </>
      )}
      {count > STEP && (
        <button type="button" onClick={() => setCount(STEP)} className="text-azure-deep hover:underline">
          Show the first {STEP}
        </button>
      )}
    </div>
  );
}

function Bar({ value, max, label, faint = false }: { value: number; max: number; label: string; faint?: boolean }) {
  return (
    <span className="grid grid-cols-[1fr_auto] items-center gap-2">
      <span className="block h-[7px] rounded-full bg-mist">
        <span
          className={`block h-full rounded-r-[4px] ${faint ? "bg-edge" : "bg-azure"}`}
          style={{ width: `${Math.max(value > 0 ? 2 : 0, (100 * value) / max)}%` }}
        />
      </span>
      <span className={`min-w-[64px] whitespace-nowrap text-right font-mono tabular-nums ${faint ? "text-slate" : "text-ink"}`}>{label}</span>
    </span>
  );
}
