import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Columns3, Loader2, Search } from "lucide-react";
import { ExpandableValue } from "./Expandable";
import { DogmaCompare } from "./DogmaCompare";
import { SpecificityMap, type MapPoint } from "./SpecificityMap";
import { SharedRegulation } from "./SharedRegulation";
import { ExportReport } from "./ExportReport";
import {
  buildComparison,
  splitGenes,
  STATE_LABEL,
  type Comparison as Table,
  type ComparisonRow,
} from "../report";

// Genes side by side, the comparable measures first. Six database pages
// show what each gene is. This screen shows which gene stands out, and on
// which measure.
//
// As the art direction requires, a bar never carries the number alone. Each
// value keeps its figure beside it, so the table reads the same in
// grayscale and on a printed report.

export function Comparison({ initial }: { initial?: string }) {
  const [text, setText] = useState(initial ?? "");
  const [table, setTable] = useState<Table | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const genes = splitGenes(text);
    if (genes.length < 2) {
      setProblem("Two genes minimum, comma-separated.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const result = await buildComparison(genes);
      if (result.error) setProblem(result.error);
      else setTable(result);
    } catch (error) {
      setProblem(
        error instanceof Error && error.message
          ? error.message
          : "The backend didn't respond.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1100px] px-8 py-10">
      {table && (
        <button
          type="button"
          onClick={() => setTable(null)}
          className="mb-6 flex items-center gap-1.5 text-[13px] text-slate transition-colors hover:text-azure-deep"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          New comparison
        </button>
      )}

      {!table && (
        <>
          <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">
            Gene comparison
          </h1>
          <p className="mt-3 max-w-[58ch] text-[15px] leading-relaxed text-slate">
            Two to six genes, side by side. Specificity measures first: peak values do not compare across genes.
          </p>
        </>
      )}

      <form onSubmit={submit} noValidate className={table ? "mb-7" : "mt-8"}>
        <label htmlFor="compare-genes" className="mb-1.5 block px-1 text-[12px] font-medium text-slate">
          Genes, separated by commas
        </label>
        <div className="flex h-14 items-center gap-3 rounded-full border border-line bg-surface pl-5 pr-1.5 transition-[border-color,box-shadow] focus-within:border-azure focus-within:shadow-[0_0_0_4px_rgb(0_178_255/0.18)]">
          <Search size={20} strokeWidth={1.75} className="shrink-0 text-slate" aria-hidden="true" />
          <input
            ref={input}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (problem) setProblem("");
            }}
            id="compare-genes"
            autoComplete="off"
            spellCheck={false}
            aria-label="Genes to compare"
            className="h-full min-w-0 flex-1 bg-transparent font-mono text-[15px] text-ink outline-none placeholder:font-sans placeholder:text-[14px] placeholder:text-slate/70"
          />
          <button
            type="submit"
            disabled={busy}
            className="flex h-11 shrink-0 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
          >
            {busy ? (
              <Loader2 size={17} className="animate-spin" aria-hidden="true" />
            ) : (
              <Columns3 size={17} strokeWidth={2} aria-hidden="true" />
            )}
            Compare
          </button>
        </div>
        {problem && (
          <p role="alert" className="mt-3 px-5 text-[13px] text-error">
            {problem}
          </p>
        )}
      </form>

      {table && <Table table={table} />}
    </div>
  );
}

function Table({ table }: { table: Table }) {
  const genes = table.genes;
  const numberAt = (field: string, index: number) => {
    const value = table.rows.find((row) => row.field === field)?.cells[index]?.value;
    return typeof value === "number" ? value : null;
  };
  const points: MapPoint[] = genes
    .map((gene, index) => ({ gene, index }))
    .filter(({ gene }) => gene.resolved)
    .map(({ gene, index }) => ({
      symbol: gene.symbol,
      tau: numberAt("rna_specificity_tau", index),
      fold: numberAt("rna_fold_over_median", index),
    }));
  return (
    <div className="space-y-7">
      {genes.some((gene) => gene.resolved) && (
        // The genes that resolved, in the order typed; the others are named in
        // the table with what went wrong.
        <div className="-mb-3 flex justify-end">
          <ExportReport genes={genes.filter((gene) => gene.resolved).map((gene) => gene.symbol)} />
        </div>
      )}
      {points.filter((p) => p.tau !== null && p.fold !== null).length >= 2 && (
        <section className="rounded-[14px] border border-line bg-surface">
          <h2 className="border-b border-line px-5 py-3 text-[15px] font-semibold text-ink">
            Specificity map
          </h2>
          <div className="px-5 py-4">
            <SpecificityMap points={points} bands={table.bands ?? []} />
          </div>
        </section>
      )}

      <section className="overflow-x-auto rounded-[14px] border border-line bg-surface">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line">
              <th
                scope="col"
                className="sticky left-0 z-10 bg-surface px-4 py-3 text-left text-[12px] font-medium text-slate"
              >
                Field
              </th>
              {genes.map((gene) => (
                <th key={gene.query} scope="col" className="px-4 py-3 text-left">
                  <span className="font-mono text-[14px] font-semibold text-ink">
                    {gene.symbol}
                  </span>
                  <span className="mt-0.5 block text-[11px] font-normal text-slate">
                    {gene.resolved
                      ? `${gene.filled} fields`
                      : gene.reason || "did not resolve"}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          {table.sections.map((section) => {
            const rows = section.rows.filter((row) => row.filled > 0);
            if (!rows.length) return null;
            return (
              <tbody key={section.key}>
                <tr>
                  <th
                    scope="rowgroup"
                    colSpan={genes.length + 1}
                    className="bg-frost px-4 py-2 text-left text-[12px] font-semibold text-azure-deep"
                  >
                    {section.label}
                  </th>
                </tr>
                {rows.map((row) => (
                  <Line key={row.field} row={row} />
                ))}
              </tbody>
            );
          })}
        </table>
      </section>

      {table.dogma && table.dogma.rows.length > 0 && (
        <section className="rounded-[14px] border border-line bg-surface">
          <h2 className="border-b border-line px-5 py-3 text-[15px] font-semibold text-ink">
            RNA and protein by organ
          </h2>
          <div className="px-5 py-4">
            <DogmaCompare data={table.dogma} />
          </div>
        </section>
      )}

      {genes.filter((gene) => gene.resolved).length >= 2 && (
        <section className="rounded-[14px] border border-line bg-surface">
          <h2 className="border-b border-line px-5 py-3 text-[15px] font-semibold text-ink">
            Shared regulation
          </h2>
          <SharedRegulation symbols={genes.filter((gene) => gene.resolved).map((gene) => gene.symbol)} />
        </section>
      )}

      <p className="text-[12px] leading-relaxed text-slate">
        No ranking: target choice depends on modality, indication and acceptable safety signal. Marked
        value: highest, where a high value has meaning.
      </p>
    </div>
  );
}

function Line({ row }: { row: ComparisonRow }) {
  // Bars only for the measures where a magnitude is comparable across genes.
  const numbers = row.cells.map((cell) =>
    typeof cell.value === "number" ? cell.value : null,
  );
  const peak = Math.max(...numbers.map((n) => (n === null ? 0 : Math.abs(n))), 0);
  const scale = row.type === "number" && peak > 0 && numbers.some((n) => n !== null);

  return (
    <tr className="border-b border-line last:border-0">
      <th
        scope="row"
        className="sticky left-0 z-10 bg-surface px-4 py-2.5 text-left align-top font-normal"
      >
        <span className="text-ink" title={row.description}>
          {row.label}
        </span>
        {row.unit && <span className="ml-1 text-[11px] text-slate">{row.unit}</span>}
        {row.derived && (
          <span className="ml-1.5 rounded-[5px] bg-mist px-1.5 py-0.5 text-[10px] text-azure-deep">
            derived
          </span>
        )}
      </th>
      {row.cells.map((cell, index) => (
        <td key={index} className="px-4 py-2.5 align-top">
          {cell.state ? (
            <span className="text-[12px] text-slate" title={cell.reason}>
              {STATE_LABEL[cell.state] ?? cell.state}
            </span>
          ) : (
            <>
              <span
                className={cell.notable ? "font-semibold text-ink" : "text-ink"}
                title={cell.source ? `${cell.source} ${cell.version}` : undefined}
              >
                {/* The table abbreviates; it never truncates. Anything with
                    more in it than fits opens in place. */}
                {cell.value && typeof cell.value === "object" ? (
                  <ExpandableValue value={cell.value} limit={3} mono={row.mono} />
                ) : (
                  <span className={row.mono ? "font-mono" : ""}>{cell.display}</span>
                )}
                {cell.notable && (
                  <span className="ml-1.5 text-[11px] font-normal text-azure-deep">
                    highest
                  </span>
                )}
              </span>
              {scale && typeof cell.value === "number" && (
                <span
                  aria-hidden="true"
                  className="mt-1 block h-[7px] overflow-hidden rounded-full bg-mist"
                >
                  <span
                    className="block h-full rounded-full bg-azure"
                    style={{ width: `${Math.max(2, (Math.abs(cell.value) / peak) * 100)}%` }}
                  />
                </span>
              )}
            </>
          )}
        </td>
      ))}
    </tr>
  );
}

export function ComparisonProblem({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-2 rounded-[10px] bg-warn-bg px-3.5 py-2.5 text-[13px] text-warn-ink">
      <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      {text}
    </p>
  );
}
