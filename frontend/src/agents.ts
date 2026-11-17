// The agent pipeline, as the interface sees it. Mirrors spica/agents/run.py.
//
// The interface polls; the backend does not push. A model streams for
// minutes. A snapshot that the interface can ask for again survives a
// reload, a stall and a crash. `version` increases on each change, so an
// unchanged run costs one small round trip, not the full run.

// The four roles. The first two are a loop; the last two close it.
export type Stage = "orchestrate" | "tool" | "write" | "verify";

export type Tool = {
  key: string; // "documents"
  label: string; // "Documents"
  usage: string; // how the orchestrator calls it
  status: string; // what it currently holds
};

export type Step = {
  index: number;
  stage: Stage;
  stage_label: string;
  title: string;
  status: "running" | "done" | "failed" | "cancelled";
  cycle: number; // which turn of the loop this belongs to
  tool: string; // the source a tool step read, e.g. "gtex"
  tool_label: string;
  thought: string; // the reasoning trace, as it arrives
  output: string; // what the agent decided
  seed: number;
  started: string;
  finished: string;
  error: string;
};

export type Problem = {
  kind:
    | "unknown_field"
    | "empty_field"
    | "uncited_number"
    | "nothing_cited"
    | "unsupported_number";
  severity: "error" | "warning";
  field: string;
  detail: string;
  claim: string;
};

export type Verdict = {
  ok: boolean;
  claims: number;
  sentences: number;
  sourced: number;
  citations: string[];
  problems: Problem[];
  errors: number;
  warnings: number;
  summary: string;
};

export type RunState = {
  plan: string[];
  notes: {
    tool: string;
    tool_label: string;
    text: string;
    argument: string;
    fields: string[];
  }[];
  pending: string; // a move chosen and not yet run
  closed: boolean; // the orchestrator has said DONE
  draft: string;
  verdict: Verdict | null;
};

export type Run = {
  id: string;
  question: string;
  status: "running" | "paused" | "done" | "failed" | "cancelled";
  backend: string;
  thinking?: boolean;
  created: string;
  error: string;
  version: number;
  stages: Stage[];
  stage_labels: Record<Stage, string>;
  current_stage: Stage | "";
  cycle: number;
  looping: Stage[];
  tools: Tool[];
  read: string[]; // tools already used, in order
  steps: Step[];
  history: Step[];
  state: RunState;
};

export type AgentStatus = {
  model: string;
  models_dir: string;
  loaded: boolean;
  backend: string;
  note: string;
  runs: string[];
};

type AgentApi = {
  agents_status: () => Promise<AgentStatus>;
  agents_ask: (question: string, thinking: boolean | null) => Promise<Run & { error?: string }>;
  settings_status: () => Promise<{ thinking: boolean }>;
  set_thinking: (on: boolean) => Promise<{ thinking: boolean }>;
  agents_poll: (
    runId: string,
    version: number,
  ) => Promise<Run | { unchanged: true; version: number } | { missing: true }>;
  agents_cancel: (runId: string) => Promise<Run>;
  agents_rollback: (runId: string, index: number) => Promise<Run & { problem?: string }>;
  agents_resume: (runId: string) => Promise<Run>;
};

function api(): AgentApi | null {
  return (window.pywebview?.api as unknown as AgentApi) ?? null;
}

export function agentsAvailable(): boolean {
  return api() !== null;
}

export async function agentStatus(): Promise<AgentStatus | null> {
  return api()?.agents_status() ?? null;
}

export async function askQuestion(question: string, thinking: boolean | null = null) {
  const backend = api();
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend.agents_ask(question, thinking);
}

/** Whether the model reasons before planning and writing: the saved choice. */
export async function thinkingChoice(): Promise<boolean> {
  const backend = api();
  if (!backend) return true;
  return (await backend.settings_status()).thinking ?? true;
}

export async function saveThinking(on: boolean): Promise<boolean> {
  return (await api()!.set_thinking(on)).thinking;
}

export async function pollRun(runId: string, version: number) {
  return api()!.agents_poll(runId, version);
}

export async function cancelRun(runId: string) {
  return api()!.agents_cancel(runId);
}

export async function rollbackRun(runId: string, index: number) {
  return api()!.agents_rollback(runId, index);
}

export async function resumeRun(runId: string) {
  return api()!.agents_resume(runId);
}
