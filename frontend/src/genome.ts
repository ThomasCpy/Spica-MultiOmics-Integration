// The genome view's side of the bridge. Every track arrives as plain
// features from Python; igv.js only ever draws what it is handed.

export type TrackSpec = {
  id: string;
  label: string;
  group: string;
  source: string;
  licence: string;
  verified: boolean;
  default: boolean;
  kind: "annotation" | "wig";
  description: string;
  tissues: string[];
};

export type LocusInfo = {
  symbol: string;
  ensembl_id: string;
  chrom: string;
  start: number;
  end: number;
  strand: string;
  assembly: string;
  window: { start: number; end: number };
  view: string;
};

export type LocusResult = {
  error?: string;
  locus: LocusInfo;
  reference: { id: string; name: string; fasta: string; chrom: string; length: number; source: string };
  catalog: TrackSpec[];
  hint: Partial<Record<"organ" | "dnase" | "h3k27ac" | "gtex_coverage" | "encode", string>>;
  labels: Record<string, string>; // GTEx track suffix -> the name GTEx prints
  organs: string[];
  assays: Record<string, string>;
  online: boolean;
};

export type TrackResult = {
  id: string;
  state: "ok" | "failed" | "offline";
  reason?: string;
  config?: Record<string, unknown> & { name: string };
  features?: Record<string, unknown>[];
  count?: number;
  source?: string;
  licence?: string;
};

export type Experiment = {
  id: string;
  experiment: string;
  file: string;
  assay: string;
  target: string;
  biosample: string;
  format: string;
  output: string;
  url: string;
};

export type ExperimentList = {
  state: "ok" | "failed";
  reason?: string;
  items: Experiment[];
  without_files?: number;
  with_chipseq?: string[];
  without_chipseq?: string[];
  regulators?: string[];
};

type GenomeApi = {
  genome_locus: (symbol: string, ensemblId: string, topTissue: string) => Promise<LocusResult>;
  genome_track: (symbol: string, ensemblId: string, trackId: string) => Promise<TrackResult>;
  genome_encode: (symbol: string, ensemblId: string, organ: string, assay: string, adult: boolean) => Promise<ExperimentList>;
  genome_regulators: (symbol: string, ensemblId: string) => Promise<ExperimentList>;
};

function api(): GenomeApi {
  const backend = window.pywebview?.api as unknown as GenomeApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const openLocus = (symbol: string, ensemblId: string, topTissue: string) =>
  api().genome_locus(symbol, ensemblId, topTissue);
export const fetchTrack = (symbol: string, ensemblId: string, trackId: string) =>
  api().genome_track(symbol, ensemblId, trackId);
export const findEncode = (symbol: string, ensemblId: string, organ: string, assay: string, adult: boolean) =>
  api().genome_encode(symbol, ensemblId, organ, assay, adult);
export const findRegulators = (symbol: string, ensemblId: string) =>
  api().genome_regulators(symbol, ensemblId);

/** `SmallIntestineTerminalIleum` -> `Small Intestine Terminal Ileum`. */
export function tissueLabel(name: string): string {
  return name.replace(/(?<=[a-z])(?=[A-Z])/g, " ");
}
