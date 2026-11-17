// Candidates: gene lists, mapped and confirmed, then ranked on user weights.
// The benchmark checks the weights.
// Backend: spica/genelist.py, spica/ranking.py, spica/benchmark.py.

export type Criterion = {
  key: string;
  label: string;
  group: string;
  describe: string;
  reads: string[];
  leaks: string[];
  weight: number;
};

export type CriteriaInfo = {
  criteria: Criterion[];
  presets: Record<string, { label: string; weights: Record<string, number> }>;
  benchmarks: Record<string, string>;
};

export type MapStatus = "exact" | "alias" | "renamed" | "ambiguous" | "not_found" | "duplicate";

export type MappingRow = {
  input: string;
  position: number;
  status: MapStatus;
  symbol: string;
  hgnc_id: string;
  name: string;
  matched_on: string;
  candidates: { symbol: string; hgnc_id: string; name: string }[];
  note: string;
};

export type Mapping = {
  error?: string;
  entries: string[];
  rows: MappingRow[];
  counts: Partial<Record<MapStatus, number>>;
  genes: number;
  needs_review: number;
  message: string;
};

export type ListSummary = { slug: string; name: string; updated: string; genes: number; preset: string };

export type SavedList = {
  error?: string;
  name: string;
  created: string;
  updated: string;
  entries: string[];
  mapping: Mapping;
  choices: Record<string, string>;
  genes: { input: string; symbol: string; hgnc_id: string }[];
  weights: Record<string, number>;
  preset: string;
  indication: string;
};

export type Part = { score: number | null; value: string; weight: number; contribution: number };

export type RankedRow = {
  symbol: string;
  hgnc_id: string;
  ensembl_id: string;
  score: number | null;
  coverage: number | null;
  parts: Record<string, Part>;
  rank: number;
};

export type Ranked = {
  rows: RankedRow[];
  criteria: Criterion[];
  weights: Record<string, number>;
  indication: string;
  missing: "skip" | "zero";
  summary: string;
};

export type Job<T> = {
  job: string;
  kind: string;
  state: "running" | "done" | "failed" | "unknown";
  done: number;
  total: number;
  started?: number;
  stopping?: boolean;
  seconds?: number;
  result?: T;
  error?: string;
};

export type Benchmark = {
  error?: string;
  modality: string;
  label: string;
  when: string;
  seconds: number;
  weights: Record<string, number>;
  dropped: string[];
  missing: string;
  positives: number;
  decoys: number;
  auc: number | null;
  roc: [number, number][];
  top: { size: number; positives: number };
  coverage: { positives: number | null; decoys: number | null };
  criteria: {
    key: string;
    label: string;
    auc: number | null;
    positives: number;
    decoys: number;
    weight: number;
    dropped: boolean;
    leaks: boolean;
  }[];
  rows: { rank: number; symbol: string; score: number; coverage: number; positive: boolean }[];
  sets: string;
};

type CandidatesApi = {
  candidates_criteria: () => Promise<CriteriaInfo>;
  genelist_map: (text: string) => Promise<Mapping>;
  genelist_read_file: () => Promise<{ text?: string; name?: string; error?: string; cancelled?: boolean }>;
  genelist_save: (
    name: string,
    entries: string[],
    mapping: Mapping,
    choices: Record<string, string>,
    weights: Record<string, number>,
    preset: string,
    indication: string,
  ) => Promise<{ error?: string; slug?: string; name?: string; genes?: SavedList["genes"] }>;
  genelists: () => Promise<{ lists: ListSummary[] }>;
  genelist_open: (slug: string) => Promise<SavedList>;
  genelist_delete: (slug: string) => Promise<{ deleted: boolean }>;
  rank_start: (genes: string[], weights: Record<string, number>, indication: string, missing: string) => Promise<{ job?: string; error?: string }>;
  benchmark_start: (modality: string, weights: Record<string, number>, missing: string) => Promise<{ job?: string; error?: string }>;
  benchmark_latest: (modality: string) => Promise<Benchmark>;
  export_ranked_start: (
    genes: string[],
    weights: Record<string, number>,
    indication: string,
    missing: string,
    project: string,
    profiles: number,
  ) => Promise<{ job?: string; error?: string }>;
  export_save: (job: string) => Promise<{ path?: string; error?: string; cancelled?: boolean }>;
  job_status: <T>(job: string) => Promise<Job<T>>;
};

function api(): CandidatesApi {
  const backend = window.pywebview?.api as unknown as CandidatesApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const candidatesCriteria = async () => api().candidates_criteria();
export const mapList = async (text: string) => api().genelist_map(text);
export const readListFile = async () => api().genelist_read_file();
export const saveList = async (...args: Parameters<CandidatesApi["genelist_save"]>) => api().genelist_save(...args);
export const savedLists = async () => api().genelists();
export const openList = async (slug: string) => api().genelist_open(slug);
export const deleteList = async (slug: string) => api().genelist_delete(slug);
export const startRank = async (...args: Parameters<CandidatesApi["rank_start"]>) => api().rank_start(...args);
export const startBenchmark = async (...args: Parameters<CandidatesApi["benchmark_start"]>) =>
  api().benchmark_start(...args);
export const latestBenchmark = async (modality: string) => api().benchmark_latest(modality);
export const startRankedExport = async (...args: Parameters<CandidatesApi["export_ranked_start"]>) =>
  api().export_ranked_start(...args);
export const saveRankedExport = async (job: string) => api().export_save(job);
export const jobStatus = async <T>(job: string) => api().job_status<T>(job);

/** Poll a job until it ends, reporting progress; resolves with the job. */
export async function follow<T>(job: string, onProgress: (state: Job<T>) => void): Promise<Job<T>> {
  for (;;) {
    const state = await jobStatus<T>(job);
    onProgress(state);
    if (state.state !== "running") return state;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

/** The ranked table again under new weights, with no call to Python. Each
 * row holds the score of every criterion, whatever its weight. The totals
 * are thus the same weighted mean as in spica/ranking.py. */
export function rerank(rows: RankedRow[], weights: Record<string, number>, missing: "skip" | "zero"): RankedRow[] {
  const next = rows.map((row) => {
    let total = 0;
    let weighed = 0;
    let available = 0;
    for (const [key, part] of Object.entries(row.parts)) {
      const weight = Math.max(0, weights[key] ?? 0);
      if (!weight) continue;
      weighed += weight;
      if (part.score === null) continue;
      available += weight;
      total += weight * part.score;
    }
    const denominator = missing === "zero" ? weighed : available;
    const parts: Record<string, Part> = {};
    for (const [key, part] of Object.entries(row.parts)) {
      const weight = Math.max(0, weights[key] ?? 0);
      parts[key] = {
        ...part,
        weight,
        contribution: denominator && part.score !== null && weight ? (weight * part.score) / denominator : 0,
      };
    }
    return {
      ...row,
      parts,
      score: denominator ? total / denominator : null,
      coverage: weighed ? available / weighed : null,
    };
  });
  next.sort(
    (a, b) =>
      (b.score ?? -1) - (a.score ?? -1) || (b.coverage ?? 0) - (a.coverage ?? 0) || a.symbol.localeCompare(b.symbol),
  );
  return next.map((row, index) => ({ ...row, rank: index + 1 }));
}
