import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { follow, latestBenchmark, startBenchmark, type Benchmark, type CriteriaInfo } from "../candidates";

// The benchmark: the rank of known targets against undrugged genes under
// these weights. Approved targets of one modality go against decoys. The
// score uses the weights on screen, without the criteria that encode the
// label. The panel shows the ROC curve with its diagonal and the AUC. It
// also shows each criterion alone, as a bar from chance (0.5) to 1 or 0.

const SIZE = 220;
const STEP = 25;

export function BenchmarkPanel({
  weights,
  missing,
  info,
}: {
  weights: Record<string, number>;
  missing: "skip" | "zero";
  info: CriteriaInfo;
}) {
  const modalities = Object.entries(info.benchmarks);
  const [modality, setModality] = useState(modalities[0]?.[0] ?? "antibody");
  const [result, setResult] = useState<Benchmark | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [problem, setProblem] = useState("");
  const [count, setCount] = useState(STEP);

  useEffect(() => {
    setResult(null);
    latestBenchmark(modality)
      .then((found) => (found.error ? setResult(null) : setResult(found)))
      .catch(() => undefined);
  }, [modality]);

  const run = async () => {
    setProblem("");
    setProgress({ done: 0, total: 0 });
    const started = await startBenchmark(modality, weights, missing);
    if (started.error || !started.job) {
      setProblem(started.error ?? "Benchmark not started.");
      setProgress(null);
      return;
    }
    const job = await follow<Benchmark>(started.job, (state) => setProgress({ done: state.done, total: state.total }));
    setProgress(null);
    if (job.state === "done" && job.result) {
      setResult(job.result);
      setCount(STEP);
    } else setProblem(job.error ?? "Benchmark not finished.");
  };

  const same =
    result && Object.keys(weights).every((key) => (result.dropped.includes(key) ? true : (result.weights[key] ?? 0) === (weights[key] ?? 0)));
  const chance = result ? Math.round((result.top.size * result.positives) / (result.positives + result.decoys)) : 0;
  const positives = result ? result.rows.filter((row) => row.positive) : [];

  return (
    <section className="mt-8 rounded-[16px] border border-line bg-surface p-5">
      <h2 className="text-[15px] font-semibold text-ink">Benchmark</h2>
      <p className="mt-1 max-w-[80ch] text-[12px] text-slate">
        Known targets against decoys, with the current weights. Criteria that encode the label (clinical
        precedent; Open Targets association) are excluded. Local data only.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
        {modalities.map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={modality === key}
            onClick={() => setModality(key)}
            className={`rounded-full px-2.5 py-0.5 ${modality === key ? "bg-mist text-azure-deep" : "border border-line text-slate hover:text-azure-deep"}`}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          onClick={run}
          disabled={progress !== null}
          className="ml-2 flex items-center gap-2 rounded-full bg-azure-deep px-4 py-1 text-[12px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-70"
        >
          {progress && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
          {progress ? (progress.total ? `Scoring ${progress.done} of ${progress.total}` : "Selecting genes") : "Run"}
        </button>
        {result && !same && !progress && (
          <span className="text-[11px] text-slate">Result below: other weights.</span>
        )}
      </div>
      {problem && (
        <p role="alert" className="mt-3 text-[13px] text-error">
          {problem}
        </p>
      )}
      {!result && !progress && <p className="mt-3 text-[12px] text-slate">No run for this modality.</p>}
      {result && (
        <div className="mt-5 grid grid-cols-[auto_minmax(0,1fr)] gap-8">
          <div>
            <Roc points={result.roc} />
            <p className="mt-2 text-center text-[12px] text-slate">
              AUC <span className="font-mono text-[20px] font-semibold text-ink">{result.auc?.toFixed(3) ?? "none"}</span>
            </p>
          </div>
          <div className="min-w-0">
            <p className="text-[13px] text-ink">
              {result.positives} known targets, {result.decoys} decoys, run {result.when}. The top{" "}
              {result.top.size}: {result.top.positives} known targets (chance: about {chance}).
            </p>
            <p className="mt-1 text-[12px] text-slate">
              {result.sets} Data coverage: known targets {Math.round((result.coverage.positives ?? 0) * 100)}%,
              decoys {Math.round((result.coverage.decoys ?? 0) * 100)}%.
              {result.dropped.length > 0 && ` Excluded: ${result.dropped.join(", ")}.`}
            </p>
            <p className="mt-4 text-[12px] font-semibold text-ink">AUC per criterion (0.5: chance)</p>
            <ul className="mt-2 space-y-[4px]">
              {[...result.criteria]
                .filter((criterion) => criterion.auc !== null)
                .sort((a, b) => (b.auc ?? 0) - (a.auc ?? 0))
                .map((criterion) => (
                  <li
                    key={criterion.key}
                    className="grid grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)_44px] items-center gap-3 text-[12px]"
                    title={`${criterion.positives} known targets and ${criterion.decoys} decoys had data`}
                  >
                    <span className={`truncate ${criterion.weight ? "text-ink" : "text-slate"}`}>
                      {criterion.label}
                      {criterion.leaks && <span className="text-slate"> (encodes the label)</span>}
                    </span>
                    <Centered value={criterion.auc!} faint={criterion.leaks || !criterion.weight} />
                    <span className="text-right font-mono tabular-nums text-ink">{criterion.auc!.toFixed(2)}</span>
                  </li>
                ))}
            </ul>
            <p className="mt-1 text-[11px] text-slate">Pale: weight 0, or encodes the label.</p>
            <p className="mt-4 text-[12px] font-semibold text-ink">Known targets by rank</p>
            <ul className="mt-1 columns-3 gap-6 text-[12px]">
              {positives.slice(0, count).map((row) => (
                <li key={row.symbol} className="break-inside-avoid">
                  <span className="inline-block w-[40px] font-mono text-slate">{row.rank}</span>
                  <span className="font-mono text-ink">{row.symbol}</span>
                </li>
              ))}
            </ul>
            {positives.length > count && (
              <button type="button" onClick={() => setCount(positives.length)} className="mt-1 text-[12px] text-azure-deep hover:underline">
                Show all {positives.length}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function Roc({ points }: { points: [number, number][] }) {
  const pad = 26;
  const span = SIZE - pad - 8;
  const at = (x: number, y: number) => `${pad + x * span},${8 + (1 - y) * span}`;
  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} role="img" aria-label="ROC curve">
      <rect x={pad} y={8} width={span} height={span} fill="none" stroke="var(--color-line)" />
      <line x1={pad} y1={8 + span} x2={pad + span} y2={8} stroke="var(--color-edge)" strokeDasharray="4 4" />
      <polyline points={points.map(([x, y]) => at(x, y)).join(" ")} fill="none" stroke="var(--color-azure)" strokeWidth={2} />
      <text x={pad + span / 2} y={SIZE - 2} fontSize="10" textAnchor="middle" fill="var(--color-slate)">
        decoys passed (false positive rate)
      </text>
      <text x={10} y={8 + span / 2} fontSize="10" textAnchor="middle" fill="var(--color-slate)" transform={`rotate(-90 10 ${8 + span / 2})`}>
        known targets found
      </text>
    </svg>
  );
}

function Centered({ value, faint }: { value: number; faint: boolean }) {
  // From the middle (0.5, chance) to the value: right is better than chance.
  const left = Math.min(value, 0.5) * 100;
  const width = Math.abs(value - 0.5) * 100;
  return (
    <span className="relative block h-[10px] bg-mist">
      <span className="absolute left-1/2 top-[-2px] h-[14px] w-px bg-edge" />
      <span className={`absolute h-full ${faint ? "bg-edge" : "bg-azure"}`} style={{ left: `${left}%`, width: `${Math.max(width, 0.5)}%` }} />
    </span>
  );
}
