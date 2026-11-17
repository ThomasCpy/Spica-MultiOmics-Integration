// Views beside the record: computed from the same sources, on request.

export type StructureProfile = {
  error?: string;
  accession: string;
  length: number;
  plddt: [number, number][];
  missense: [number, number][];
  pdb: { id: string; method: string; resolution: number | null; ranges: [number, number][] }[];
  notes: string[];
  model_version?: number;
};

export type IsoformTable = {
  error?: string;
  symbol: string;
  dataset: string;
  unit: string;
  transcripts: { id: string; name: string; biotype: string; canonical: boolean; expressed_in: number; total: number }[];
  tissues: string[];
  values: Record<string, Record<string, number>>;
  dominant: Record<string, { transcript: string; share: number }>;
};

export type Coexpression = {
  error?: string;
  symbol: string;
  source: string;
  tissues: number;
  genes: { symbol: string; ensembl_id: string; r: number }[];
  left_out: number;
  min_peak: number;
  method: string;
};

// Open Targets' associations beside ClinVar's variants, joined on disease
// identifiers (spica/genetics.py).
export type DiseaseGenetics = {
  error?: string;
  symbol: string;
  rows: {
    disease: string;
    id: string;
    score: number;
    pathogenic: number;
    records: number;
    conditions: string[];
    gwas: number;
    gwas_traits: string[];
  }[];
  clinvar_only: { condition: string; ids: string[]; pathogenic: number; records: number }[];
  gwas: boolean;
  gwas_only: { trait: string; ids: string[]; mlog10p: number; associations: number; relation: string; variant: string }[];
  summary: {
    associations: number;
    with_pathogenic: number;
    conditions: number;
    unmatched: number;
    top_supported: string;
    with_gwas: number;
    gwas_traits: number;
  };
  sources: string;
};

// HPA's experimental partners beside OmniPath's curated ones, joined on
// identifiers (spica/interactions.py).
export type PartnerLink = {
  direction: "out" | "in" | "none";
  sign: "stimulates" | "inhibits" | "both" | "unsigned";
  from: string;
  to: string;
};

export type Network = "hpa" | "omnipath" | "string";

export type InteractionPartners = {
  error?: string;
  symbol: string;
  partners: {
    symbol: string;
    ensembl_id: string;
    hpa: string[] | null;
    omnipath: {
      references: number;
      links: PartnerLink[];
      databases: string;
      direct: boolean;
      complexes: string[];
    } | null;
    // STRING's physical subnetwork, 0 to 1; in STRING only from `medium`.
    string: { score: number; experimental: number; database: number; textmining: number; medium: boolean } | null;
    networks: Network[];
  }[];
  datasets: string[];
  summary: {
    hpa: number;
    omnipath: number;
    both: number;
    union: number;
    jaccard: number | null;
    omnipath_in_hpa: number | null;
    hpa_in_omnipath: number | null;
    via_complex_only: number;
    string: number | null;
    networks: Network[];
    combinations: { networks: Network[]; count: number }[];
    confirmed: Partial<Record<Network, number | null>>;
    string_threshold: number;
  };
  sources: string;
};

export type Atlas = {
  error?: string;
  family: string;
  label: string;
  unit: string;
  chrom: string;
  start: number;
  end: number;
  bins: number;
  gene: { symbol: string; start: number; end: number; strand: string };
  rows: { tissue: string; key: string; values: (number | null)[]; peak: number | null }[];
  failed: { tissue: string; reason: string }[];
  max: number;
};

export type SharedRegulation = {
  error?: string;
  state?: string;
  genes: string[];
  regulators: Record<string, string[]>;
  shared: { tf: string; targets: number; genes: Record<string, string> }[];
  links: { source: string; target: string; effect: string; type: string; references: number; databases: string }[];
  source: string;
};

export type TfHit = {
  start: number;
  end: number;
  strand: "+" | "-";
  score: number;
  p: number;
  site: string;
  offset: number;
  in_peak: boolean;
  cells: number;
};

export type TfPeak = { start: number; end: number; cells: number; score: number; from: number; to: number };

export type TfRow = {
  tf: string;
  members: string[];
  complex: boolean;
  effect: "activates" | "represses" | "both" | "unsigned";
  level: string;
  references: number;
  motif: { id: string; name: string; length: number; consensus: string; frequencies: number[][]; url: string } | null;
  motif_note: string;
  hits: TfHit[];
  supported: number;
  chip: { assayed: boolean | null; experiments: number; peaks: TfPeak[] };
};

export type TfAnalysis = {
  state: "ok" | "offline" | "failed";
  error?: string;
  gene: string;
  chrom: string;
  strand: "+" | "-";
  tss: number;
  tss_from: string;
  region: { start: number; end: number; upstream: number; downstream: number };
  p_value: number;
  background: string;
  regulators: TfRow[];
  summary: {
    regulators: number;
    complexes: number;
    with_motif: number;
    with_sites: number;
    sites: number;
    assayed: number;
    bound_here: number;
    supported: number;
    supported_sites: number;
    bound_without_motif: number;
  };
  chip_state: string;
  sources: Record<string, string>;
};

type ViewsApi = {
  tf_analysis: (symbol: string, ensemblId: string, upstream: number, downstream: number) => Promise<TfAnalysis>;
  structure_profile: (accession: string) => Promise<StructureProfile>;
  isoform_table: (symbol: string, ensemblId: string) => Promise<IsoformTable>;
  coexpressed: (symbol: string, ensemblId: string) => Promise<Coexpression>;
  disease_genetics: (symbol: string, ensemblId: string) => Promise<DiseaseGenetics>;
  interaction_partners: (symbol: string, ensemblId: string) => Promise<InteractionPartners>;
  genome_atlas: (symbol: string, ensemblId: string, family: string) => Promise<Atlas>;
  compare_regulators: (symbols: string[]) => Promise<SharedRegulation>;
};

function api(): ViewsApi {
  const backend = window.pywebview?.api as unknown as ViewsApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const structureProfile = async (accession: string) => api().structure_profile(accession);
export const isoformTable = async (symbol: string, ensemblId: string) => api().isoform_table(symbol, ensemblId);
export const coexpressed = async (symbol: string, ensemblId: string) => api().coexpressed(symbol, ensemblId);
export const diseaseGenetics = async (symbol: string, ensemblId: string) =>
  api().disease_genetics(symbol, ensemblId);
export const interactionPartners = async (symbol: string, ensemblId: string) =>
  api().interaction_partners(symbol, ensemblId);
export const genomeAtlas = async (symbol: string, ensemblId: string, family: string) =>
  api().genome_atlas(symbol, ensemblId, family);
export const tfAnalysis = async (symbol: string, ensemblId: string, upstream: number, downstream: number) =>
  api().tf_analysis(symbol, ensemblId, upstream, downstream);
export const compareRegulators = async (symbols: string[]) => api().compare_regulators(symbols);
