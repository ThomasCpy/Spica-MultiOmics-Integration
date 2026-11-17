import { Fragment, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  CircleSlash,
  Loader2,
  Play,
  RotateCcw,
  Square,
} from "lucide-react";
import {
  cancelRun,
  pollRun,
  resumeRun,
  rollbackRun,
  type Run,
  type Step,
  type Verdict,
} from "../agents";
import { Schematic } from "./Schematic";

const POLL_MS = 250;

export function AgentRun({ run: initial, onBack }: { run: Run; onBack: () => void }) {
  const [run, setRun] = useState<Run>(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  // One poll in flight at a time; `version` means an unchanged run costs a
  // round trip rather than the whole run.
  useEffect(() => {
    if (run.status !== "running") return;
    let live = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await pollRun(run.id, run.version);
        if (!live || !next || "unchanged" in next || "missing" in next) return;
        setRun(next);
      } catch {
        /* the window is closing, or the backend went away */
      }
    }, POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [run.id, run.status, run.version]);

  async function act(fn: () => Promise<Run & { problem?: string }>) {
    setBusy(true);
    setProblem("");
    try {
      const next = await fn();
      if (next.problem) setProblem(next.problem);
      setRun(next);
    } finally {
      setBusy(false);
    }
  }

  const running = run.status === "running";
  const verdict = run.state.verdict;

  return (
    <div className="mx-auto w-full max-w-[860px] px-8 py-10">
      <button
        type="button"
        onClick={onBack}
        className="mb-6 flex items-center gap-1.5 text-[13px] text-slate transition-colors hover:text-azure-deep"
      >
        <ArrowLeft size={15} aria-hidden="true" />
        New question
      </button>

      <header className="mb-6">
        <h1 className="text-[22px] font-semibold leading-snug tracking-[-0.01em] text-ink">
          {run.question}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Status run={run} />
          <span className="rounded-full border border-line bg-surface px-3 py-1 font-mono text-[12px] text-slate">
            {run.backend}
          </span>
          {run.thinking !== undefined && (
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-slate">
              Thinking {run.thinking ? "on" : "off"}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {running && (
              <Control onClick={() => act(() => cancelRun(run.id))} busy={busy}>
                <Square size={14} aria-hidden="true" />
                Stop
              </Control>
            )}
            {!running && run.status !== "done" && (
              <Control onClick={() => act(() => resumeRun(run.id))} busy={busy} filled>
                <Play size={14} aria-hidden="true" />
                Resume
              </Control>
            )}
          </div>
        </div>
      </header>

      <section className="mb-5 rounded-[14px] border border-line bg-surface p-4">
        <Schematic run={run} />
      </section>

      {run.state.plan.length > 0 && (
        <section className="mb-6 rounded-[14px] border border-line bg-surface px-4 py-3">
          <h2 className="text-[12px] font-medium text-slate">Open points</h2>
          <ul className="mt-1.5 space-y-1">
            {run.state.plan.map((goal, index) => (
              <li key={index} className="flex gap-2 text-[13px] text-ink">
                <span className="text-slate">&middot;</span>
                {goal}
              </li>
            ))}
          </ul>
        </section>
      )}

      {run.error && (
        <Callout tone="error">
          {run.error}
        </Callout>
      )}
      {problem && <Callout tone="warning">{problem}</Callout>}

      <ol className="space-y-3">
        {run.steps.map((step) => (
          <StepCard
            key={`${step.index}-${step.seed}`}
            step={step}
            live={running && step.index === run.steps.length - 1}
            verdict={step.stage === "verify" ? verdict : null}
            onRewind={busy ? undefined : () => act(() => rollbackRun(run.id, step.index))}
          />
        ))}
      </ol>

      {run.history.length > 0 && (
        <p className="mt-5 flex items-center gap-1.5 text-[12px] text-slate">
          <RotateCcw size={13} aria-hidden="true" />
          {run.history.length} rolled-back {run.history.length === 1 ? "step" : "steps"} kept in the run file.
        </p>
      )}

      {run.state.draft && <Answer draft={run.state.draft} verdict={verdict} />}
    </div>
  );
}

function Status({ run }: { run: Run }) {
  const map: Record<Run["status"], { text: string; skin: string }> = {
    running: { text: "Running", skin: "border-azure bg-mist text-azure-deep" },
    paused: { text: "Paused", skin: "border-line bg-surface text-slate" },
    done: { text: "Finished", skin: "border-azure/40 bg-mist text-azure-deep" },
    failed: { text: "Stopped", skin: "border-warn-line bg-warn-bg text-warn-ink" },
    cancelled: { text: "Stopped", skin: "border-line bg-surface text-slate" },
  };
  const { text, skin } = map[run.status];
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium ${skin}`}>
      {run.status === "running" && <Loader2 size={12} className="animate-spin" aria-hidden="true" />}
      {text}
    </span>
  );
}

function Control({
  children,
  onClick,
  busy,
  filled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  busy: boolean;
  filled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-60 ${
        filled
          ? "bg-azure-deep text-on-accent hover:bg-azure-hover"
          : "border border-line bg-surface text-ink hover:border-azure hover:text-azure-deep"
      }`}
    >
      {children}
    </button>
  );
}

function StepCard({
  step,
  live,
  verdict,
  onRewind,
}: {
  step: Step;
  live: boolean;
  verdict: Verdict | null;
  onRewind?: () => void;
}) {
  // The step in flight shows its thinking; finished ones keep it folded away,
  // because the decision is what matters once it has been made.
  const [open, setOpen] = useState(live);
  useEffect(() => {
    if (live) setOpen(true);
  }, [live]);

  return (
    <li className="rounded-[14px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <span className="rounded-full bg-mist px-2.5 py-0.5 text-[11px] font-medium text-azure-deep">
          {step.stage_label}
        </span>
        {step.cycle > 0 && (
          <span className="shrink-0 font-mono text-[11px] text-slate">
            cycle {step.cycle}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-[14px] text-ink" title={step.title}>
          {step.title}
        </span>
        {step.tool &&
          // One move can call several tools at once: a chip for each.
          step.tool.split(",").map((name) => (
            <span key={name} className="shrink-0 rounded-[6px] bg-frost px-1.5 py-0.5 font-mono text-[11px] text-azure-deep">
              {name}
            </span>
          ))}
        <StepStatus step={step} live={live} />
        {onRewind && (
          <button
            type="button"
            onClick={onRewind}
            title="Discard this step and later steps"
            className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-slate transition-colors hover:border-azure hover:text-azure-deep"
          >
            <RotateCcw size={12} aria-hidden="true" />
            Rewind
          </button>
        )}
      </div>

      {step.thought && (
        <div className="border-t border-line">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex w-full items-center gap-1.5 px-4 py-2 text-left text-[12px] text-slate transition-colors hover:text-azure-deep"
          >
            <ChevronRight
              size={13}
              aria-hidden="true"
              className={`transition-transform ${open ? "rotate-90" : ""}`}
            />
            Thinking
            <span className="font-mono text-[11px] opacity-70">
              {step.thought.length.toLocaleString()} characters
            </span>
          </button>
          {open && <Thought text={step.thought} live={live} />}
        </div>
      )}

      {step.output && (
        <div className="border-t border-line px-4 py-3">
          {verdict ? (
            <VerdictBody verdict={verdict} />
          ) : (
            <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
              <Cited text={step.output} />
            </div>
          )}
        </div>
      )}

      {step.error && (
        <p className="border-t border-line px-4 py-3 text-[13px] text-error">{step.error}</p>
      )}
    </li>
  );
}

function StepStatus({ step, live }: { step: Step; live: boolean }) {
  if (step.status === "running" || live) {
    return <Loader2 size={14} className="animate-spin text-azure-deep" aria-label="running" />;
  }
  if (step.status === "done") {
    return <Check size={14} className="text-azure-deep" aria-label="done" />;
  }
  if (step.status === "cancelled") {
    return <CircleSlash size={14} className="text-slate" aria-label="stopped" />;
  }
  return <AlertTriangle size={14} className="text-warn-ink" aria-label="failed" />;
}

function Thought({ text, live }: { text: string; live: boolean }) {
  const box = useRef<HTMLPreElement>(null);
  const pinned = useRef(true);

  // Follow the stream, unless the reader has scrolled up to read something.
  useEffect(() => {
    const node = box.current;
    if (!node || !live || !pinned.current) return;
    node.scrollTop = node.scrollHeight;
  }, [text, live]);

  return (
    <pre
      ref={box}
      onScroll={(e) => {
        const node = e.currentTarget;
        pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
      }}
      className="max-h-56 overflow-y-auto whitespace-pre-wrap break-words bg-frost px-4 py-3 font-mono text-[12px] leading-relaxed text-slate"
    >
      {text}
    </pre>
  );
}

/** Renders `[field_name]` citations as chips, so a claim shows its source. */
function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[[a-z0-9_]+\])/g);
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\[([a-z0-9_]+)\]$/.exec(part);
        if (!match) return <Fragment key={index}>{part}</Fragment>;
        return (
          <span
            key={index}
            className="mx-0.5 rounded-[6px] bg-mist px-1.5 py-0.5 font-mono text-[11px] text-azure-deep"
          >
            {match[1]}
          </span>
        );
      })}
    </>
  );
}

function VerdictBody({ verdict }: { verdict: Verdict }) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-[13px] text-ink">
        {verdict.ok ? (
          <Check size={14} className="text-azure-deep" aria-hidden="true" />
        ) : (
          <AlertTriangle size={14} className="text-warn-ink" aria-hidden="true" />
        )}
        {verdict.summary}
      </p>
      {verdict.problems.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {verdict.problems.map((problem, index) => (
            <li
              key={index}
              className={`rounded-[8px] px-2.5 py-1.5 text-[12px] ${
                problem.severity === "error"
                  ? "bg-warn-bg text-warn-ink"
                  : "bg-frost text-slate"
              }`}
            >
              <span className="font-medium">
                {problem.severity === "error" ? "Fails" : "Check"}:
              </span>{" "}
              {problem.detail}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Answer({ draft, verdict }: { draft: string; verdict: Verdict | null }) {
  return (
    <section className="mt-7 rounded-[14px] border border-line bg-surface p-6">
      <h2 className="mb-3 text-[18px] font-semibold text-ink">Answer</h2>
      <div className="space-y-2 text-[14px] leading-relaxed text-ink">
        {draft.split("\n").map((line, index) => {
          const heading = /^#{1,6}\s+(.*)$/.exec(line.trim());
          if (heading) {
            return (
              <h3 key={index} className="pt-2 text-[15px] font-semibold text-ink">
                {heading[1]}
              </h3>
            );
          }
          if (!line.trim()) return null;
          const bullet = /^[-*]\s+(.*)$/.exec(line.trim());
          return (
            <p key={index} className={bullet ? "pl-4 -indent-4" : ""}>
              {bullet ? "• " : ""}
              <Cited text={bullet ? bullet[1] : line} />
            </p>
          );
        })}
      </div>
      {verdict && !verdict.ok && (
        <Callout tone="warning">
          Claims not supported by the notes.
        </Callout>
      )}
    </section>
  );
}

function Callout({ tone, children }: { tone: "warning" | "error"; children: React.ReactNode }) {
  return (
    <p
      className={`mb-5 flex items-start gap-2 rounded-[10px] px-3.5 py-2.5 text-[13px] ${
        tone === "error" ? "bg-warn-bg text-warn-ink" : "bg-warn-bg text-warn-ink"
      }`}
      role={tone === "error" ? "alert" : "status"}
    >
      <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}
