import { useEffect, useMemo, useState } from "react";
import { FileDown, Loader2 } from "lucide-react";
import {
  follow,
  rerank,
  saveList,
  saveRankedExport,
  startRank,
  startRankedExport,
  type CriteriaInfo,
  type Ranked,
  type SavedList,
} from "../candidates";
import { openExported } from "../exporting";
import { BenchmarkPanel } from "./BenchmarkPanel";

// The ranked table. Python returns the score of each criterion, whatever its
// weight. A weight change thus re-ranks at once, with the same weighted mean
// as spica/ranking.py. Only a new indication calls Python again, because it
// changes what two criteria read.

const STEP = 50;
const PROFILES = [
  [10, "the top 10"],
  [25, "the top 25"],
  [0, "every gene"],
] as const;

export function RankedView({
  slug,
  list,
  info,
  onBack,
  onOpenReport,
}: {
  slug: string;
  list: SavedList;
  info: CriteriaInfo;
  onBack: () => void;
  onOpenReport: (symbol: string) => void;
}) {
  const startPreset = list.preset && info.presets[list.preset] ? list.preset : "antibody";
  const [preset, setPreset] = useState(Object.keys(list.weights ?? {}).length ? list.preset || "custom" : startPreset);
  const [weights, setWeights] = useState<Record<string, number>>(
    Object.keys(list.weights ?? {}).length ? list.weights : info.presets[startPreset].weights,
  );
  const [indication, setIndication] = useState(list.indication ?? "");
  const [applied, setApplied] = useState(list.indication ?? "");
  const [missing, setMissing] = useState<"skip" | "zero">("skip");
  const [ranked, setRanked] = useState<Ranked | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [problem, setProblem] = useState("");
  const [count, setCount] = useState(STEP);
  const [saved, setSaved] = useState("");

  const genes = list.genes.map((gene) => gene.hgnc_id);

  useEffect(() => {
    let live = true;
    (async () => {
      setProblem("");
      setProgress({ done: 0, total: genes.length });
      // The job reads every criterion; the weights only matter for the order.
      const started = await startRank(genes, weights, applied, "skip").catch((error) => ({ error: String(error) }));
      if (!live) return;
      if ("error" in started && started.error) {
        setProblem(started.error);
        return;
      }
      const job = await follow<Ranked>((started as { job: string }).job, (state) => {
        if (live) setProgress({ done: state.done, total: state.total });
      });
      if (!live) return;
      setProgress(null);
      if (job.state === "done" && job.result) setRanked(job.result);
      else setProblem(job.error ?? "Ranking not finished.");
    })();
    return () => {
      live = false;
    };
    // Weights are applied in the page; only the genes and the indication need Python.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, applied]);

  const rows = useMemo(() => (ranked ? rerank(ranked.rows, weights, missing) : []), [ranked, weights, missing]);
  const used = info.criteria.filter((criterion) => (weights[criterion.key] ?? 0) > 0);
  const groups = [...new Set(info.criteria.map((criterion) => criterion.group))];

  const setWeight = (key: string, value: number) => {
    setWeights({ ...weights, [key]: value });
    setPreset("custom");
    setSaved("");
  };

  const keep = async () => {
    const result = await saveList(list.name, list.entries, list.mapping, list.choices, weights, preset, applied);
    setSaved(result.error ? result.error : "Weights saved.");
  };

  return (
    <>
      <button type="button" onClick={onBack} className="text-[13px] text-slate hover:text-azure-deep">
        All lists
      </button>
      <div className="mt-3 flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-[28px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">{list.name}</h1>
          <p className="mt-2 text-[14px] text-slate">
            {list.genes.length} genes ranked on {used.length} weighted criteria
            {applied ? ` for ${applied}` : ""}. Scores depend on each gene record only.
          </p>
        </div>
        <ExportRanked genes={genes} weights={weights} indication={applied} missing={missing} name={list.name} />
      </div>

      <div className="mt-6 grid grid-cols-[280px_minmax(0,1fr)] gap-6">
        <aside className="space-y-5 self-start rounded-[16px] border border-line bg-surface p-4">
          <div>
            <p className="text-[12px] font-semibold text-ink">Start from</p>
            <div className="mt-2 flex flex-wrap gap-1 text-[12px]">
              {Object.entries(info.presets).map(([key, value]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={preset === key}
                  onClick={() => {
                    setPreset(key);
                    setWeights(value.weights);
                    setSaved("");
                  }}
                  className={`rounded-full px-2.5 py-0.5 ${preset === key ? "bg-mist text-azure-deep" : "border border-line text-slate hover:text-azure-deep"}`}
                >
                  {value.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label htmlFor="indication" className="text-[12px] font-semibold text-ink">
              Indication
            </label>
            <div className="mt-1 flex gap-2">
              <input
                id="indication"
                value={indication}
                onChange={(event) => setIndication(event.target.value)}
                title="Disease (empty: all)"
                className="h-8 min-w-0 flex-1 rounded-[8px] border border-line bg-frost px-2 text-[12px] text-ink outline-none focus:border-azure"
              />
              <button
                type="button"
                onClick={() => setApplied(indication.trim())}
                disabled={indication.trim() === applied}
                className="rounded-full border border-line px-3 text-[12px] text-azure-deep disabled:opacity-50"
              >
                Apply
              </button>
            </div>
            <p className="mt-1 text-[11px] text-slate">
              Matched on disease names. Applies to disease association and human genetics.
            </p>
          </div>
          <div>
            <p className="text-[12px] font-semibold text-ink">Missing data</p>
            <div className="mt-1 flex gap-1 text-[12px]">
              {(
                [
                  ["skip", "left out"],
                  ["zero", "counts as zero"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={missing === value}
                  onClick={() => setMissing(value)}
                  className={`rounded-full px-2.5 py-0.5 ${missing === value ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {groups.map((group) => (
            <div key={group}>
              <p className="text-[12px] font-semibold text-ink">{group}</p>
              <ul className="mt-1 space-y-1.5">
                {info.criteria
                  .filter((criterion) => criterion.group === group)
                  .map((criterion) => (
                    <li key={criterion.key} title={criterion.describe}>
                      <div className="flex items-center justify-between text-[12px]">
                        <span className={(weights[criterion.key] ?? 0) > 0 ? "text-ink" : "text-slate"}>
                          {criterion.label}
                        </span>
                        <span className="font-mono text-ink">
                          {(weights[criterion.key] ?? 0).toString()}
                          <span className="text-slate">/10</span>
                        </span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={10}
                        step={1}
                        value={weights[criterion.key] ?? 0}
                        onChange={(event) => setWeight(criterion.key, Number(event.target.value))}
                        aria-label={`Weight of ${criterion.label}`}
                        className="w-full accent-[var(--color-azure-deep)]"
                      />
                    </li>
                  ))}
              </ul>
            </div>
          ))}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={keep}
              className="rounded-full border border-line px-3 py-1 text-[12px] text-azure-deep hover:border-azure"
            >
              Save weights
            </button>
            {saved && <span className="text-[11px] text-slate">{saved}</span>}
          </div>
        </aside>

        <section className="min-w-0">
          {progress && (
            <p className="flex items-center gap-2 text-[13px] text-slate">
              <Loader2 size={15} className="animate-spin" aria-hidden="true" />
              Reading {progress.done} of {progress.total} records.
            </p>
          )}
          {problem && (
            <p role="alert" className="text-[13px] text-error">
              {problem}
            </p>
          )}
          {ranked && (
            <div className="overflow-x-auto rounded-[14px] border border-line bg-surface">
              <table className="w-full border-collapse text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left align-bottom text-[11px] text-slate">
                    <th className="px-3 py-2 font-medium">Rank</th>
                    <th className="px-3 py-2 font-medium">Gene</th>
                    <th className="min-w-[150px] px-3 py-2 font-medium">Score</th>
                    <th className="px-3 py-2 font-medium" title="Share of the weight the gene had data for">
                      Data
                    </th>
                    {used.map((criterion) => (
                      <th key={criterion.key} className="min-w-[96px] px-3 py-2 font-medium" title={criterion.describe}>
                        {criterion.label}
                        <span className="block font-mono font-normal">weight {weights[criterion.key]}/10</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, count).map((row) => (
                    <tr key={row.hgnc_id} className="border-b border-line last:border-0">
                      <td className="px-3 py-1.5 font-mono text-slate">{row.rank}</td>
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => onOpenReport(row.symbol)}
                          className="font-mono font-semibold text-ink hover:text-azure-deep"
                          title="Open the report"
                        >
                          {row.symbol}
                        </button>
                      </td>
                      <td className="px-3 py-1.5">
                        <Meter value={row.score} wide />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-slate">
                        {row.coverage === null ? "" : `${Math.round(row.coverage * 100)}%`}
                      </td>
                      {used.map((criterion) => {
                        const part = row.parts[criterion.key];
                        return (
                          <td key={criterion.key} className="px-3 py-1.5" title={`${criterion.label}: ${part.value}`}>
                            {part.score === null ? (
                              <span className="text-[11px] text-slate">no data</span>
                            ) : (
                              <Meter value={part.score} />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rows.length > count && (
            <div className="mt-2 flex gap-4 text-[12px]">
              <button type="button" onClick={() => setCount(count + STEP)} className="text-azure-deep hover:underline">
                Show {Math.min(STEP, rows.length - count)} more ({rows.length - count} left)
              </button>
              <button type="button" onClick={() => setCount(rows.length)} className="text-azure-deep hover:underline">
                Show all {rows.length}
              </button>
            </div>
          )}
          {ranked && <p className="mt-2 text-[11px] text-slate">Cell tooltip: source value.</p>}
          {ranked && (
            <BenchmarkPanel weights={weights} missing={missing} info={info} />
          )}
        </section>
      </div>
    </>
  );
}

function Meter({ value, wide = false }: { value: number | null; wide?: boolean }) {
  if (value === null) return <span className="text-[11px] text-slate">no data</span>;
  return (
    <span className="grid grid-cols-[1fr_auto] items-center gap-2">
      <span className={`block ${wide ? "h-[10px]" : "h-[7px]"} bg-mist`}>
        <span className="block h-full rounded-r-[4px] bg-azure" style={{ width: `${Math.max(value > 0 ? 2 : 0, value * 100)}%` }} />
      </span>
      <span className={`font-mono tabular-nums text-ink ${wide ? "w-[40px]" : "w-[30px]"} text-right`}>
        {value.toFixed(wide ? 3 : 2)}
      </span>
    </span>
  );
}

function ExportRanked({
  genes,
  weights,
  indication,
  missing,
  name,
}: {
  genes: string[];
  weights: Record<string, number>;
  indication: string;
  missing: string;
  name: string;
}) {
  const [open, setOpen] = useState(false);
  const [project, setProject] = useState(name);
  const [profiles, setProfiles] = useState<number>(10);
  const [state, setState] = useState<{ kind: "idle" | "busy" | "saved" | "problem"; text?: string; done?: number; total?: number }>({
    kind: "idle",
  });

  const run = async () => {
    setState({ kind: "busy", done: 0, total: genes.length });
    const started = await startRankedExport(genes, weights, indication, missing, project, profiles);
    if (started.error || !started.job) {
      setState({ kind: "problem", text: started.error ?? "Report not started." });
      return;
    }
    const job = await follow(started.job, (s) => setState({ kind: "busy", done: s.done, total: s.total }));
    if (job.state !== "done") {
      setState({ kind: "problem", text: job.error ?? "Report not finished." });
      return;
    }
    const saved = await saveRankedExport(started.job);
    if (saved.error) setState({ kind: "problem", text: saved.error });
    else if (saved.cancelled) setState({ kind: "idle" });
    else setState({ kind: "saved", text: saved.path });
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-ink hover:border-azure hover:text-azure-deep"
      >
        <FileDown size={15} aria-hidden="true" />
        Export report
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-[360px] rounded-[14px] border border-line bg-surface p-4 text-[13px]">
          <label className="block text-[12px] text-slate" htmlFor="ranked-project">
            Project name (cover)
          </label>
          <input
            id="ranked-project"
            value={project}
            onChange={(event) => setProject(event.target.value)}
            className="mt-1 h-9 w-full rounded-[8px] border border-line bg-frost px-3 text-ink outline-none focus:border-azure"
          />
          <p className="mt-3 text-[12px] text-slate">Ranked table and weights, then profiles of</p>
          <div className="mt-1 flex gap-1 text-[12px]">
            {PROFILES.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={profiles === value}
                onClick={() => setProfiles(value)}
                className={`rounded-full px-2.5 py-0.5 ${profiles === value ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={run}
            disabled={state.kind === "busy"}
            className="mt-3 flex items-center gap-2 rounded-full bg-azure-deep px-4 py-1.5 font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-70"
          >
            {state.kind === "busy" && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            {state.kind === "busy" ? `Reading ${state.done ?? 0} of ${state.total ?? genes.length}` : "Save report"}
          </button>
          {state.kind === "saved" && state.text && (
            <p className="mt-3 text-[12px] text-ink">
              Saved to <span className="break-all font-mono text-[11.5px]">{state.text}</span>.{" "}
              <button type="button" onClick={() => openExported(state.text!)} className="text-azure-deep hover:underline">
                Open it
              </button>
            </p>
          )}
          {state.kind === "problem" && (
            <p role="alert" className="mt-3 text-[12px] text-error">
              {state.text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
