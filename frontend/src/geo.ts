// NCBI GEO through the bridge: search, a series in context, a gene's values.
// The interface never reaches GEO itself; Python reads it (spica/geo/).

export type GeoHit = {
  accession: string;
  title: string;
  summary: string;
  type: string;
  organisms: string;
  samples: number;
  date: string;
  files: string[];
  tracks: boolean;
  pubmed: string[];
};

export type GeoSearch = {
  error?: string;
  open?: string;
  query: string;
  terms: string[];
  expression: string;
  total: number;
  offset: number;
  results: GeoHit[];
  page: number;
};

export type GeoFile = {
  url: string;
  name: string;
  kind: string;
  sample: string;
  assembly: string;
  human: boolean;
  track: boolean;
};

export type GeoSample = {
  accession: string;
  title: string;
  source: string;
  organism: string;
  molecule: string;
  strategy: string;
  platform: string;
  characteristics: Record<string, string>;
  treatment: string;
  processing: string;
  assembly: string;
  files: GeoFile[];
  url: string;
  arm: string;
};

export type GeoFacet = { field: string; values: { value: string; samples: number }[] };

export type GeoSeries = {
  error?: string;
  accession: string;
  title: string;
  summary: string;
  design: string;
  types: string[];
  pubmed: string[];
  platforms: string[];
  samples: GeoSample[];
  submitted: string;
  updated: string;
  files: GeoFile[];
  url: string;
  facets: GeoFacet[];
  counts: { samples: number; human: number; files: number; tracks: number; matrices: number; sheets?: number };
  organisms: string[];
};

export type GeoColumn = {
  column: string;
  value: number;
  matched_by: "accession" | "title" | "abbreviation" | "order" | "";
  sample: string;
  title: string;
  context: Record<string, string>;
  arm: string;
};

export type GeoGene = {
  error?: string;
  gene?: string;
  state?: "ok" | "none" | "absent";
  message?: string;
  file?: string;
  url?: string;
  tables?: string[];
  table_urls?: string[];
  columns?: GeoColumn[];
  matched?: number;
  groups?: { field: string; groups: { value: string; samples: number; mean: number; values: number[] }[] }[];
  note?: string;
};

// Differential expression (spica/geo/de.py): published results as published,
// or DESeq2 on raw counts. Nothing else is tested.

export type DeColumn = {
  index: number;
  column: string;
  sample: string;
  title: string;
  matched_by: string;
  context: Record<string, string>;
};

export type DeContrast = { label: string; fold: string; p: string; adjusted: boolean };

export type DeTable = {
  sheet: string;
  kind: "results" | "counts" | "values" | "other";
  routes: ("published" | "deseq2")[];
  rows: number;
  gene_column: string;
  contrasts: DeContrast[];
  columns: DeColumn[];
  matched: number;
  other_numeric: string[];
  reason?: string;
};

export type DeInspect = {
  error?: string;
  tables_in_series?: { name: string; url: string }[];
  file?: string;
  url?: string;
  tables?: DeTable[];
};

/** [label, gene id, mean, log2 fold change, p (adjusted when stated), lfcSE, raw p] */
export type DePoint = [string, string, number | null, number, number | null, (number | null)?, (number | null)?];

export type DeResult = {
  route: "published" | "deseq2";
  points: DePoint[];
  method: string;
  p_label: string;
  mean_label: string;
  file: string;
  url: string;
  sheet: string;
  accession: string;
  skipped?: number;
  filtered?: number;
  dropped?: number;
  duplicates?: number;
  design?: string;
  groups?: {
    field: string;
    reference: { value: string; samples: [string, string][] };
    comparison: { value: string; samples: [string, string][] };
  };
};

export type DeRequest = {
  url: string;
  sheet: string;
  route: "published" | "deseq2";
  contrast?: string;
  field?: string;
  reference?: string;
  comparison?: string;
  covariate?: string;
  referenceColumns?: string[];
  comparisonColumns?: string[];
};

type GeoApi = {
  geo_search: (text: string, human: boolean, tracks: boolean, offset: number) => Promise<GeoSearch>;
  geo_series: (accession: string) => Promise<GeoSeries>;
  geo_gene: (accession: string, symbol: string, fileUrl: string) => Promise<GeoGene>;
  gene_locate: (text: string) => Promise<{ symbol?: string; ensembl_id?: string; error?: string }>;
  geo_de_inspect: (accession: string, fileUrl: string) => Promise<DeInspect>;
  geo_de_start: (
    accession: string,
    fileUrl: string,
    sheet: string,
    route: string,
    contrast: string,
    field: string,
    reference: string,
    comparison: string,
    covariate: string,
    referenceColumns: string[],
    comparisonColumns: string[],
  ) => Promise<{ job?: string; error?: string }>;
};

function api(): GeoApi {
  const backend = window.pywebview?.api as unknown as GeoApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const geoSearch = async (text: string, human = true, tracks = false, offset = 0) =>
  api().geo_search(text, human, tracks, offset);
export const geoSeries = async (accession: string) => api().geo_series(accession);
export const geoGene = async (accession: string, symbol: string, fileUrl = "") =>
  api().geo_gene(accession, symbol, fileUrl);
export const locateGene = async (text: string) => api().gene_locate(text);
export const geoDeInspect = async (accession: string, fileUrl = "") => api().geo_de_inspect(accession, fileUrl);
export const geoDeStart = async (accession: string, r: DeRequest) =>
  api().geo_de_start(
    accession,
    r.url,
    r.sheet,
    r.route,
    r.contrast ?? "",
    r.field ?? "",
    r.reference ?? "",
    r.comparison ?? "",
    r.covariate ?? "",
    r.referenceColumns ?? [],
    r.comparisonColumns ?? [],
  );

/** The genome view's id for one GEO file: sample, stated build, address. */
export const geoTrackId = (file: GeoFile, sample = "") =>
  `geo:${file.sample || sample}|${file.assembly}|${file.url}`;

/** Every file of a sample that can be drawn on the locus, its own and the series' files named after it. */
export function sampleTracks(series: GeoSeries, sample: GeoSample): GeoFile[] {
  return [...sample.files, ...series.files.filter((f) => f.sample === sample.accession)].filter((f) => f.track);
}

// Tracks chosen on the Datasets screen for a gene's locus, picked up by that
// gene's report when it opens: the report opens Genomics and draws them.
let pending: { symbol: string; ids: string[] } | null = null;
export function requestLocusTracks(symbol: string, ids: string[]) {
  pending = { symbol: symbol.toUpperCase(), ids };
}
export function takeLocusTracks(symbol: string): string[] {
  if (!pending || pending.symbol !== symbol.toUpperCase()) return [];
  const ids = pending.ids;
  pending = null;
  return ids;
}
