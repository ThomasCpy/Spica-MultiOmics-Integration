// Bridge to the Python side. Inside the desktop window, pywebview exposes the
// methods of the Python `Api` class (app.py) as window.pywebview.api.
// In a plain browser (npm run dev) it falls back to a local placeholder.
//
// The types below mirror `spica/record.py` and `spica/schema.py`. A field is
// either a value with the provenance of where it came from, or a null state
// saying why there is none. There is no third case, so rendering a field
// means reading `state` first.

export type NullState = "not_found" | "not_covered" | "failed";

export type Provenance = {
  source: string;
  version: string;
  retrieved: string;
  locator: string;
};

export type FieldValue = {
  value: unknown;
  state: NullState | null;
  reason: string;
  provenance: Provenance | null;
};

export type FieldSpec = {
  name: string;
  section: string;
  label: string;
  type:
    | "text"
    | "text_list"
    | "integer"
    | "number"
    | "sequence"
    | "number_map"
    | "text_map";
  source: string;
  unit: string;
  mono: boolean; // render in JetBrains Mono, per the art direction
  derived_from: string[];
  description: string;
};

export type Schema = {
  schema_version: string;
  sections: Record<string, string>;
  fields: FieldSpec[];
};

export type Resolution = {
  query: string;
  resolved: boolean;
  matched_on: string;
  hgnc_id: string;
  symbol: string;
  ensembl_gene_id: string;
  uniprot_accession: string;
  reason: string;
  candidates: string[];
};

export type SourceStamp = {
  key: string;
  label: string;
  // read: from the local mirror. fetched / cached: from the source's public
  // API, fetched now or read from an earlier fetch on disk.
  status: "read" | "fetched" | "cached" | "unavailable" | "failed" | "skipped";
  version: string;
  retrieved: string;
  note: string;
};

export type GeneRecord = {
  query: string;
  schema_version: string;
  resolution: Resolution;
  sources: SourceStamp[];
  fields: Record<string, FieldValue>;
  fingerprint: string;
};

export type ReportRequestResult = {
  status: "ok" | "unresolved" | "error" | "preview";
  message: string;
  schema?: Schema;
  record?: GeneRecord | null;
};

type SpicaApi = {
  build_report: (target: string) => Promise<ReportRequestResult>;
};

declare global {
  interface Window {
    pywebview?: { api: SpicaApi };
  }
}

export async function requestReport(target: string): Promise<ReportRequestResult> {
  const api = window.pywebview?.api;
  if (api) return api.build_report(target);
  return {
    status: "preview",
    message: `${target} received. Records are built by Python, so run the app with \`python app.py\` to see one.`,
  };
}
