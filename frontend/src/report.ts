// The deterministic side, as the interface sees it: one record, or several
// side by side. No model is involved in either; that is the whole point of
// keeping them apart from `agents.ts`.

import type { GeneRecord, Schema } from "./bridge";

export type Cell = {
  display: string;
  value: unknown;
  state: "" | "not_found" | "not_covered" | "failed";
  reason: string;
  source: string;
  version: string;
  notable: boolean; // the highest, where highest means something
};

export type ComparisonRow = {
  field: string;
  label: string;
  section: string;
  unit: string;
  mono: boolean;
  type: string;
  derived: boolean;
  description: string;
  filled: number;
  cells: Cell[];
};

export type ComparisonSection = {
  key: string;
  label: string;
  rows: ComparisonRow[];
};

export type ComparedGene = {
  query: string;
  symbol: string;
  resolved: boolean;
  reason: string;
  matched_on: string;
  candidates: string[];
  filled: number;
  fingerprint: string;
};

export type Comparison = {
  genes: ComparedGene[];
  sections: ComparisonSection[];
  rows: ComparisonRow[];
  compared: number;
  schema?: Schema;
  error?: string;
  dogma?: DogmaCompare | null;
  bands?: { from: number; to: number; label: string }[];
};

export type ReportResult = {
  status: "ok" | "unresolved" | "error" | "preview";
  message: string;
  schema?: Schema;
  record?: GeneRecord | null;
  dogma?: Dogma | null;
  bands?: { from: number; to: number; label: string }[];
  glance?: Glance | null;
  locations?: Locations | null;
};

// The gene at a glance (spica/glance.py): the words its GO terms and its
// disease associations keep returning to. `from` lists GO terms, or
// [disease, score] pairs, heaviest first.
export type GlanceWord = {
  word: string;
  weight: number;
  count: number;
  from: (string | [string, number])[];
};

export type GlanceBlock = {
  words: GlanceWord[];
  terms: number;
  measurements?: number;
  source: string;
  reason: string;
};

export type Glance = { function: GlanceBlock; disease: GlanceBlock };

// Where the protein sits (spica/locations.py): each compartment with the
// terms each source used for it.
export type Locations = {
  compartments: {
    name: string;
    sources: Record<string, string[]>;
    main: boolean; // HPA's main location
    count: number;
  }[];
  sources: { key: string; label: string; reported: boolean; stamp: string }[];
  topology: string[];
  unplaced: { source: string; term: string }[];
};

export type AppStatus = {
  local: string[];
  sources: number;
  online: boolean;
  recent: { symbol: string; date: string }[];
};

type ReportApi = {
  app_status: () => Promise<AppStatus>;
  build_report: (target: string) => Promise<ReportResult>;
  build_comparison: (targets: string[]) => Promise<Comparison>;
};

function api(): ReportApi | null {
  return (window.pywebview?.api as unknown as ReportApi) ?? null;
}

export async function buildReport(target: string): Promise<ReportResult> {
  const backend = api();
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend.build_report(target);
}

export async function appStatus(): Promise<AppStatus | null> {
  const backend = api();
  return backend ? backend.app_status() : null;
}

export async function buildComparison(targets: string[]): Promise<Comparison> {
  const backend = api();
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend.build_comparison(targets);
}

/** Split what was typed into gene queries: commas, semicolons or whitespace. */
export function splitGenes(text: string): string[] {
  return text
    .split(/[,;\n]+|\s{2,}|\s+(?=[A-Za-z0-9])/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** How a null reads in a cell. Never blank: a blank is a silent gap. */
export const STATE_LABEL: Record<string, string> = {
  not_found: "not found",
  not_covered: "not covered",
  failed: "failed",
};


// The central dogma on one organ axis. Each layer keeps its own scale (TPM,
// nTPM and staining intensity have no common unit). The `share` of a cell
// is relative to the peak of its own layer, never across layers.

export type DogmaLayer = {
  key: string;
  field: string;
  label: string;
  unit: string;
  kind: "number" | "level";
  stage: "transcript" | "protein";
  organs: number; // how much of the axis this layer covers
  sparse: boolean; // too little of it for its own-peak scale to mean much
};

export type DogmaMember = { tissue: string; value: number; display: string };

export type DogmaCell = {
  value: number | null;
  display: string;
  members: DogmaMember[];
  merged: number;
  peak_tissue: string;
  share: number;
};

export type DogmaRow = {
  organ: string;
  cells: Record<string, DogmaCell>;
  reading: string;
};

export type Dogma = {
  layers: DogmaLayer[];
  missing: { key: string; label: string; reason: string }[];
  rows: DogmaRow[];
  unmatched: Record<string, string[]>;
  organs: number;
  summary: string;
  // Every two layers: Pearson r of log(1 + value) over the organs both measure.
  agreement?: { a: string; b: string; n: number; rho: number | null }[];
};

/** The same organ axis for several genes: shared axis, separate scales. */

export type DogmaStageCell = DogmaCell & {
  layer: string;
  unit: string;
  kind: "number" | "level";
};

export type DogmaPair = {
  transcript: DogmaStageCell | null;
  protein: DogmaStageCell | null;
  reading: string;
};

export type DogmaCompareRow = {
  organ: string;
  cells: DogmaPair[]; // one per gene, in the genes' order
  lead: number;
};

export type DogmaColumn = {
  label: string;
  unit: string;
  kind: "number" | "level";
  organs: number;
} | null;

export type DogmaCompare = {
  genes: {
    query: string;
    symbol: string;
    layers: Record<"transcript" | "protein", DogmaColumn>; // what each column draws from
  }[];
  stages: { key: "transcript" | "protein"; label: string }[];
  layers: DogmaLayer[];
  rows: DogmaCompareRow[];
  notes: string[];
  organs: number;
  summary: string;
};
