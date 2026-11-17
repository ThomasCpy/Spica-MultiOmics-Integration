import { ArrowUp, Check, ChevronRight, Loader2 } from "lucide-react";
import type { Run, Stage } from "../agents";

// The loop, drawn as a loop. The orchestrator picks one move. The tool agent
// runs it against one source and writes a note. The orchestrator reads that
// note before the next move. The loop continues until the orchestrator says
// DONE. Then the writer and the verifier close the run.
//
// The chips below are the available tools. They show the tool of this cycle
// and the tools already used.
//
// Colour never carries state alone. A used tool keeps its tick and the
// active one keeps its spinner, so the schematic reads in grayscale.

type NodeState = "done" | "active" | "ahead";

export function Schematic({ run }: { run: Run }) {
  const current = run.status === "running" ? run.steps.at(-1) : undefined;
  const stage = current?.stage;
  const read = new Set(run.read ?? []);
  const notes = run.state.notes.length;

  const nodeState = (which: Stage): NodeState => {
    if (stage === which) return "active";
    if (which === "orchestrate") return run.steps.length ? "done" : "ahead";
    if (which === "tool") return notes ? "done" : "ahead";
    if (which === "write") return run.state.draft ? "done" : "ahead";
    return run.state.verdict ? "done" : "ahead";
  };

  const looping = stage === "orchestrate" || stage === "tool";

  return (
    <div className="space-y-3">
      <div className="rounded-[12px] border border-line bg-frost/60 p-3">
        <div className="flex items-center gap-2">
          <Node
            label="Orchestrator"
            caption={stage === "orchestrate" ? "selecting calls" : "selects calls"}
            state={nodeState("orchestrate")}
          />
          <ChevronRight size={16} className="shrink-0 text-slate" aria-hidden="true" />
          <Node
            label="Tool agent"
            caption={
              stage === "tool" && current?.tool_label
                ? `reading ${current.tool_label}`
                : "reads, writes a note"
            }
            state={nodeState("tool")}
          />
          <span className="ml-auto shrink-0 pl-2 font-mono text-[11px] text-slate">
            {notes ? `cycle ${current?.cycle ?? notes}` : "cycle 1"}
          </span>
        </div>

        {/* the way back */}
        <div className="relative ml-6 mr-20 mt-1 h-5" aria-hidden="true">
          <div
            className={`absolute inset-x-0 top-0 h-4 rounded-b-[8px] border-b border-l border-r ${
              looping ? "border-azure" : "border-line"
            }`}
          />
          <ArrowUp
            size={12}
            strokeWidth={2.5}
            className={`absolute -top-1.5 -left-[6px] ${
              looping ? "text-azure" : "text-line"
            }`}
          />
          <span className="absolute left-1/2 top-[7px] -translate-x-1/2 bg-frost px-2 text-[10px] text-slate">
            until DONE
          </span>
        </div>

        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Moves available">
          {(run.tools ?? []).map((tool) => {
            const firing = stage === "tool" && current?.tool === tool.key;
            const spent = read.has(tool.key);
            return (
              <li
                key={tool.key}
                className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] ${
                  firing
                    ? "border-azure bg-azure text-ink"
                    : spent
                      ? "border-azure/40 bg-mist text-azure-deep"
                      : "border-line bg-surface text-slate"
                }`}
                title={`${tool.usage}
${tool.status}`}
              >
                {firing && <Loader2 size={11} className="animate-spin" aria-hidden="true" />}
                {spent && !firing && <Check size={11} aria-hidden="true" />}
                <span className="font-mono">{tool.key}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="flex items-center gap-2">
        <span className="shrink-0 text-[11px] text-slate">then</span>
        <Node
          label="Writer"
          caption="each claim cites a field"
          state={nodeState("write")}
        />
        <ChevronRight size={16} className="shrink-0 text-slate" aria-hidden="true" />
        <Node
          label="Verifier"
          caption="code check, no model"
          state={nodeState("verify")}
        />
      </div>
    </div>
  );
}

function Node({
  label,
  caption,
  state,
}: {
  label: string;
  caption: string;
  state: NodeState;
}) {
  const skin =
    state === "active"
      ? "border-azure bg-azure text-ink"
      : state === "done"
        ? "border-azure/40 bg-mist text-azure-deep"
        : "border-line bg-surface text-slate";

  return (
    <div
      className={`min-w-0 flex-1 rounded-[10px] border px-3 py-2 transition-colors ${skin}`}
      aria-current={state === "active" ? "step" : undefined}
    >
      <div className="flex items-center gap-1.5">
        {state === "done" && <Check size={13} strokeWidth={2.5} aria-hidden="true" />}
        {state === "active" && (
          <Loader2 size={13} strokeWidth={2.5} className="animate-spin" aria-hidden="true" />
        )}
        <span className="truncate text-[13px] font-medium">{label}</span>
      </div>
      <p
        className={`mt-0.5 truncate text-[11px] ${
          state === "active" ? "text-ink/70" : "text-slate"
        }`}
        title={caption}
      >
        {caption}
      </p>
    </div>
  );
}
