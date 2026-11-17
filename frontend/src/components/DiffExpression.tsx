import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { follow } from "../candidates";
import { geoDeInspect, geoDeStart, type DeInspect, type DePoint, type DeRequest, type DeResult, type GeoSeries } from "../geo";
import { Volcano, callOf } from "./Volcano";

// Differential expression in one series, by validated routes only: the
// results table of the authors, as published, or DESeq2 on a raw count table
// with two groups of samples. Spica does not test tables of normalised
// values (spica/geo/de.py gives the reason). The panel shows the reason.

const ALPHAS = [0.1, 0.05, 0.01];
const FOLDS: [number, string][] = [
  [0, "any"],
  [0.585, "1.5x"],
  [1, "2x"],
  [2, "4x"],
];
/** Values that name a control arm, for the default reference group. */
const CONTROL = /control|ctrl|vehicle|dmso|untreated|mock|wild.?type|\bwt\b|sham|scrambl|non.?target|\bnc\b|pbs|baseline|normal/i;
const STEP = 25;

const KIND_LABEL: Record<string, string> = {
  results: "published results",
  counts: "raw counts",
  values: "normalised values",
  other: "other table",
};

export function DiffExpression({ series, onGene }: { series: GeoSeries; onGene?: (symbol: string) => void }) {
  const [files, setFiles] = useState<{ name: string; url: string }[]>([]);
  const [fileUrl, setFileUrl] = useState("");
  const [inspected, setInspected] = useState<DeInspect | null>(null);
  const [reading, setReading] = useState(false);
  const [sheet, setSheet] = useState(0);
  const [route, setRoute] = useState<"published" | "deseq2">("published");
  const [contrast, setContrast] = useState("");
  const [mode, setMode] = useState<"variable" | "columns">("variable");
  const [field, setField] = useState("");
  const [reference, setReference] = useState("");
  const [comparison, setComparison] = useState("");
  const [covariate, setCovariate] = useState("");
  const [refCols, setRefCols] = useState<string[]>([]);
  const [compCols, setCompCols] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [problem, setProblem] = useState("");
  const [result, setResult] = useState<DeResult | null>(null);
  const [alpha, setAlpha] = useState(0.05);
  const [fold, setFold] = useState(1);
  const [highlight, setHighlight] = useState("");
  const [count, setCount] = useState(STEP);

  const tableCount = series.counts.matrices + (series.counts.sheets ?? 0);

  useEffect(() => {
    if (!tableCount) return;
    geoDeInspect(series.accession)
      .then((found) => {
        setFiles(found.tables_in_series ?? []);
        setFileUrl(found.tables_in_series?.[0]?.url ?? "");
      })
      .catch(() => undefined);
  }, [series.accession, tableCount]);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const table = inspected?.tables?.[sheet];

  // Sample variables that split the count columns into groups of two or more.
  const fields = useMemo(() => {
    if (!table) return [];
    const out: { field: string; values: { value: string; n: number }[] }[] = [];
    const keys = new Set(table.columns.flatMap((c) => Object.keys(c.context)));
    for (const key of keys) {
      const tally = new Map<string, number>();
      for (const c of table.columns) {
        const v = c.context[key];
        if (v) tally.set(v, (tally.get(v) ?? 0) + 1);
      }
      const values = [...tally.entries()].filter(([, n]) => n >= 2).map(([value, n]) => ({ value, n }));
      if (values.length >= 2) out.push({ field: key, values });
    }
    return out;
  }, [table]);

  const chooseTable = (index: number, found: DeInspect | null = inspected) => {
    const t = found?.tables?.[index];
    setSheet(index);
    setResult(null);
    setProblem("");
    if (!t) return;
    setRoute(t.routes.includes("published") ? "published" : "deseq2");
    setContrast(t.contrasts[0]?.fold ?? "");
    setRefCols([]);
    setCompCols([]);
  };

  useEffect(() => {
    // Defaults for the grouping when the table or its variables change.
    const first = fields[0];
    setMode(first ? "variable" : "columns");
    setField(first?.field ?? "");
    const ref = first?.values.find((v) => CONTROL.test(v.value)) ?? first?.values[0];
    setReference(ref?.value ?? "");
    setComparison(first?.values.find((v) => v.value !== ref?.value)?.value ?? "");
    setCovariate("");
  }, [fields]);

  const read = async () => {
    if (!fileUrl) return;
    setReading(true);
    setInspected(null);
    setResult(null);
    setProblem("");
    try {
      const found = await geoDeInspect(series.accession, fileUrl);
      setInspected(found);
      if (found.error) setProblem(found.error);
      else chooseTable(0, found);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "No backend response.");
    } finally {
      setReading(false);
    }
  };

  const groupsOf = (name: string) => fields.find((f) => f.field === name)?.values ?? [];
  const chosenColumns = useMemo(() => {
    if (!table) return [];
    if (mode === "columns") return table.columns.filter((c) => refCols.includes(c.column) || compCols.includes(c.column));
    return table.columns.filter((c) => c.context[field] === reference || c.context[field] === comparison);
  }, [table, mode, refCols, compCols, field, reference, comparison]);
  const covariates = useMemo(() => {
    if (mode !== "variable") return [];
    return fields
      .map((f) => f.field)
      .filter((f) => f !== field && new Set(chosenColumns.map((c) => c.context[f] ?? "")).size > 1);
  }, [fields, field, chosenColumns, mode]);
  const nRef = mode === "columns" ? refCols.length : groupsOf(field).find((v) => v.value === reference)?.n ?? 0;
  const nComp = mode === "columns" ? compCols.length : groupsOf(field).find((v) => v.value === comparison)?.n ?? 0;
  const ready =
    route === "published"
      ? !!contrast
      : nRef >= 2 && nComp >= 2 && (mode === "columns" || (reference !== comparison && !!reference && !!comparison));

  const run = async () => {
    if (!table || !inspected?.url) return;
    const request: DeRequest =
      route === "published"
        ? { url: inspected.url, sheet: table.sheet, route, contrast }
        : mode === "columns"
          ? { url: inspected.url, sheet: table.sheet, route, referenceColumns: refCols, comparisonColumns: compCols }
          : { url: inspected.url, sheet: table.sheet, route, field, reference, comparison, covariate };
    setRunning(true);
    setElapsed(0);
    setProblem("");
    setResult(null);
    try {
      const started = await geoDeStart(series.accession, request);
      if (!started.job) {
        setProblem(started.error ?? "Analysis not started.");
        return;
      }
      const done = await follow<DeResult>(started.job, () => undefined);
      if (done.state === "done" && done.result) {
        setResult(done.result);
        setCount(STEP);
      } else setProblem(done.error ?? "Analysis not finished.");
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "No backend response.");
    } finally {
      setRunning(false);
    }
  };

  /** A column joins one group and leaves the other; a second click takes it out. */
  const toggle = (side: "reference" | "comparison", column: string) => {
    const [set, setOther] = side === "reference" ? [setRefCols, setCompCols] : [setCompCols, setRefCols];
    set((list) => (list.includes(column) ? list.filter((c) => c !== column) : [...list, column]));
    setOther((list) => list.filter((c) => c !== column));
  };

  if (!tableCount) return null;

  return (
    <section className="mt-6 rounded-[14px] border border-line bg-surface p-4">
      <h3 className="text-[14px] font-semibold text-ink">Differential expression</h3>
      <p className="mt-1 text-[12px] text-slate">
        Published results as published, or DESeq2 on raw read counts. Normalised values (TPM, FPKM): no test.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-slate">Table</span>
        <select
          value={fileUrl}
          onChange={(e) => {
            setFileUrl(e.target.value);
            setInspected(null);
            setResult(null);
          }}
          aria-label="Table file"
          className="h-9 max-w-[420px] rounded-full border border-line bg-surface px-3 font-mono text-[11px] text-ink"
        >
          {files.map((f) => (
            <option key={f.url} value={f.url}>
              {f.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={read}
          disabled={!fileUrl || reading}
          className="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-[13px] text-azure-deep hover:border-azure disabled:opacity-60"
        >
          {reading && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
          {reading ? "Reading" : "Read"}
        </button>
        {inspected?.tables && inspected.tables.length > 1 && (
          <select
            value={sheet}
            onChange={(e) => chooseTable(Number(e.target.value))}
            aria-label="Sheet"
            className="h-9 rounded-full border border-line bg-surface px-3 text-[12px] text-ink"
          >
            {inspected.tables.map((t, i) => (
              <option key={`${t.sheet}${i}`} value={i}>
                {t.sheet || `table ${i + 1}`}: {KIND_LABEL[t.kind]}
              </option>
            ))}
          </select>
        )}
      </div>

      {table && (
        <div className="mt-3 rounded-[10px] bg-frost px-3 py-2.5 text-[12px]">
          <p className="text-slate">
            <span className="text-ink">{KIND_LABEL[table.kind]}</span> · {table.rows.toLocaleString("en-US")} rows · gene column{" "}
            <span className="font-mono text-ink">{table.gene_column}</span>
            {table.columns.length > 0 && (
              <>
                {" "}
                · {table.columns.length} count columns, {table.matched} matched to samples
              </>
            )}
          </p>
          {table.reason && <p className="mt-1 text-slate">{table.reason}</p>}

          {table.routes.length > 1 && (
            <div role="radiogroup" aria-label="Analysis" className="mt-2 flex w-fit rounded-full border border-line bg-surface p-0.5">
              {table.routes.map((r) => (
                <button
                  key={r}
                  type="button"
                  role="radio"
                  aria-checked={route === r}
                  onClick={() => setRoute(r)}
                  className={`rounded-full px-3 py-0.5 text-[12px] ${route === r ? "bg-mist text-azure-deep" : "text-slate hover:text-ink"}`}
                >
                  {r === "published" ? "Published results" : "DESeq2 on counts"}
                </button>
              ))}
            </div>
          )}

          {route === "published" && table.contrasts.length > 0 && (
            <label className="mt-2 flex flex-wrap items-center gap-2 text-slate">
              Fold-change column
              <select value={contrast} onChange={(e) => setContrast(e.target.value)} className="rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink">
                {table.contrasts.map((c) => (
                  <option key={c.fold} value={c.fold}>
                    {c.fold} / {c.p}
                  </option>
                ))}
              </select>
            </label>
          )}

          {route === "deseq2" && table.routes.includes("deseq2") && (
            <div className="mt-2 space-y-2">
              <div role="radiogroup" aria-label="Groups" className="flex w-fit rounded-full border border-line bg-surface p-0.5">
                {(["variable", "columns"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="radio"
                    aria-checked={mode === m}
                    disabled={m === "variable" && !fields.length}
                    onClick={() => setMode(m)}
                    className={`rounded-full px-3 py-0.5 text-[12px] disabled:opacity-40 ${mode === m ? "bg-mist text-azure-deep" : "text-slate hover:text-ink"}`}
                  >
                    {m === "variable" ? "By sample variable" : "By column"}
                  </button>
                ))}
              </div>
              {mode === "variable" ? (
                <div className="flex flex-wrap items-center gap-2 text-slate">
                  <select value={field} onChange={(e) => {
                    const next = e.target.value;
                    setField(next);
                    const values = groupsOf(next);
                    const ref = values.find((v) => CONTROL.test(v.value)) ?? values[0];
                    setReference(ref?.value ?? "");
                    setComparison(values.find((v) => v.value !== ref?.value)?.value ?? "");
                    setCovariate("");
                  }} aria-label="Sample variable" className="rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] text-ink">
                    {fields.map((f) => (
                      <option key={f.field} value={f.field}>
                        {f.field}
                      </option>
                    ))}
                  </select>
                  <span>Reference</span>
                  <select value={reference} onChange={(e) => setReference(e.target.value)} aria-label="Reference group" className="rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] text-ink">
                    {groupsOf(field).map((v) => (
                      <option key={v.value} value={v.value}>
                        {v.value} ({v.n})
                      </option>
                    ))}
                  </select>
                  <span>Comparison</span>
                  <select value={comparison} onChange={(e) => setComparison(e.target.value)} aria-label="Comparison group" className="rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] text-ink">
                    {groupsOf(field).map((v) => (
                      <option key={v.value} value={v.value}>
                        {v.value} ({v.n})
                      </option>
                    ))}
                  </select>
                  {covariates.length > 0 && (
                    <>
                      <span>Covariate</span>
                      <select value={covariate} onChange={(e) => setCovariate(e.target.value)} aria-label="Covariate" className="rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] text-ink">
                        <option value="">none</option>
                        {covariates.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {(
                    [
                      ["Reference columns", refCols, "reference"],
                      ["Comparison columns", compCols, "comparison"],
                    ] as const
                  ).map(([label, list, side]) => (
                    <fieldset key={label}>
                      <legend className="text-slate">
                        {label} <span className="font-mono text-ink">{list.length}</span>
                      </legend>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {table.columns.map((c) => (
                          <button
                            key={c.column}
                            type="button"
                            aria-pressed={list.includes(c.column)}
                            onClick={() => toggle(side, c.column)}
                            title={c.title || c.column}
                            className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${
                              list.includes(c.column) ? "border-azure bg-mist text-azure-deep" : "border-line bg-surface text-ink hover:border-azure"
                            }`}
                          >
                            {c.column}
                          </button>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-slate">
                Reference <span className="font-mono text-ink">{nRef}</span>, comparison <span className="font-mono text-ink">{nComp}</span>{" "}
                samples; 2 minimum per group. Duration: about 1 min per 60,000 genes.
              </p>
            </div>
          )}

          {table.routes.length > 0 && (
            <button
              type="button"
              onClick={run}
              disabled={!ready || running}
              className="mt-3 flex items-center gap-1.5 rounded-full bg-azure-deep px-4 py-1.5 text-[13px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-50"
            >
              {running && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
              {running ? `Running, ${elapsed} s` : route === "published" ? "Plot" : "Run DESeq2"}
            </button>
          )}
        </div>
      )}

      {problem && <p role="alert" className="mt-2 text-[12px] text-error">{problem}</p>}
      {result && <DeView result={result} alpha={alpha} setAlpha={setAlpha} fold={fold} setFold={setFold}
        highlight={highlight} setHighlight={setHighlight} count={count} setCount={setCount} onGene={onGene} />}
    </section>
  );
}

function DeView({
  result,
  alpha,
  setAlpha,
  fold,
  setFold,
  highlight,
  setHighlight,
  count,
  setCount,
  onGene,
}: {
  result: DeResult;
  alpha: number;
  setAlpha: (v: number) => void;
  fold: number;
  setFold: (v: number) => void;
  highlight: string;
  setHighlight: (v: string) => void;
  count: number;
  setCount: (v: number) => void;
  onGene?: (symbol: string) => void;
}) {
  const tally = useMemo(() => {
    const t = { up: 0, down: 0, ns: 0 };
    for (const p of result.points) t[callOf(p, alpha, fold)] += 1;
    return t;
  }, [result, alpha, fold]);
  const hits = useMemo(
    () =>
      result.points
        .filter((p) => callOf(p, alpha, fold) !== "ns")
        .sort((a, b) => (a[4] ?? 1) - (b[4] ?? 1) || Math.abs(b[3]) - Math.abs(a[3])),
    [result, alpha, fold],
  );
  const g = result.groups;

  return (
    <div className="mt-4">
      <p className="text-[12px] text-slate">
        <span className="font-mono text-ink">{result.file}</span>
        {result.sheet && <> · sheet {result.sheet}</>}. {result.method}
      </p>
      {g && (
        <p className="mt-1 text-[12px] text-slate">
          Reference {g.field === "columns" ? "" : `${g.field} `}
          <span className="text-ink">{g.reference.value}</span>
          {samplesOf(g.reference.samples)}; comparison <span className="text-ink">{g.comparison.value}</span>
          {samplesOf(g.comparison.samples)}.
        </p>
      )}
      <p className="mt-1 text-[12px] text-slate">
        Genes plotted <span className="font-mono text-ink">{result.points.length.toLocaleString("en-US")}</span>
        {result.filtered ? (
          <>
            ; without adjusted p (low counts, outliers) <span className="font-mono text-ink">{result.filtered.toLocaleString("en-US")}</span>
          </>
        ) : null}
        {result.skipped ? (
          <>
            ; rows without values <span className="font-mono text-ink">{result.skipped.toLocaleString("en-US")}</span>
          </>
        ) : null}
        {result.duplicates ? (
          <>
            ; duplicate gene IDs <span className="font-mono text-ink">{result.duplicates}</span>
          </>
        ) : null}
        .
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px] text-slate">
        <label className="flex items-center gap-1.5">
          {result.p_label} at most
          <select value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} className="rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-[12px] text-ink">
            {ALPHAS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5">
          Fold change at least
          <select value={fold} onChange={(e) => setFold(Number(e.target.value))} className="rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-[12px] text-ink">
            {FOLDS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5">
          Gene
          <input
            value={highlight}
            onChange={(e) => setHighlight(e.target.value.toUpperCase())}
            aria-label="Gene to mark"
            className="h-7 w-[110px] rounded-full border border-line bg-frost px-2.5 font-mono text-[12px] text-ink outline-none focus:border-azure"
          />
        </label>
        <span className="ml-auto flex items-center gap-3" aria-label="Legend">
          <Swatch colour="var(--color-up)" label="Up" n={tally.up} />
          <Swatch colour="var(--color-down)" label="Down" n={tally.down} />
          <Swatch colour="var(--color-slate)" label="Not significant" n={tally.ns} faint />
        </span>
      </div>

      <div className="mt-2">
        <Volcano points={result.points} alpha={alpha} fold={fold} highlight={highlight} pLabel={result.p_label} onPick={onGene} />
      </div>

      <table className="mt-3 w-full text-[12px]">
        <thead>
          <tr className="border-b border-line text-left text-slate">
            <th className="py-1.5 pr-3 font-medium">Gene</th>
            <th className="py-1.5 pr-3 text-right font-medium">log2 fold change</th>
            <th className="py-1.5 pr-3 text-right font-medium">{result.p_label}</th>
            <th className="py-1.5 text-right font-medium">{result.mean_label || "mean"}</th>
          </tr>
        </thead>
        <tbody>
          {hits.slice(0, count).map((p: DePoint) => (
            <tr key={`${p[1]}${p[0]}`} className="border-b border-line">
              <td className="py-1 pr-3">
                <button
                  type="button"
                  onClick={() => onGene?.(p[0])}
                  className="font-mono text-azure-deep hover:underline"
                  title={p[1] !== p[0] ? p[1] : undefined}
                >
                  {p[0]}
                </button>
              </td>
              <td className="py-1 pr-3 text-right font-mono text-ink">
                {p[3] > 0 ? "+" : ""}
                {p[3]}
              </td>
              <td className="py-1 pr-3 text-right font-mono text-ink">{p[4] === 0 ? "< 1e-300" : p[4]}</td>
              <td className="py-1 text-right font-mono text-slate">{p[2] ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hits.length === 0 && <p className="mt-2 text-[12px] text-slate">No gene passes both thresholds.</p>}
      {hits.length > count && (
        <button type="button" onClick={() => setCount(count + STEP)} className="mt-2 text-[12px] text-azure-deep hover:underline">
          Show {Math.min(STEP, hits.length - count)} more of {(hits.length - count).toLocaleString("en-US")}
        </button>
      )}
    </div>
  );
}

/** " (GSM1, GSM2)" when the group's columns name samples; nothing otherwise. */
function samplesOf(samples: [string, string][]): string {
  const named = samples.filter((s) => s[0]);
  return named.length ? ` (${named.map((s) => s[0]).join(", ")})` : "";
}

function Swatch({ colour, label, n, faint }: { colour: string; label: string; n: number; faint?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block size-[9px] rounded-full" style={{ background: colour, opacity: faint ? 0.45 : 1 }} />
      {label} <span className="font-mono text-ink">{n.toLocaleString("en-US")}</span>
    </span>
  );
}
