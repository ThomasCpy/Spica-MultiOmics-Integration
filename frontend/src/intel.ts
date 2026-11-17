// Competitive intelligence, as the interface sees it: a topic, checked
// against Europe PMC and the EPO, every check kept by the backend.
// No model is involved. The interface itself still never calls the
// network: the backend does the fetching, and links open in the browser.

export type Term = { text: string; origin: string };

export type Paper = {
  id: string;
  source: string;
  kind: string; // "paper" | "preprint"
  title: string;
  authors: string;
  venue: string;
  date: string;
  pmid: string;
  doi: string;
  types: string[];
  link: string;
  new: boolean;
};

export type PatentFamily = {
  id: string;
  family: string;
  title: string;
  applicants: string[];
  countries: string[];
  cpc: string[];
  publications: { number: string; date: string }[];
  date: string; // latest publication inside the window
  first: string; // earliest publication inside the window
  link: string;
  new: boolean;
};

export type Trial = {
  id: string;
  nct: string;
  title: string;
  status: string;
  phase: string;
  sponsor: string;
  conditions: string[];
  interventions: string[];
  start: string;
  first_posted: string;
  date: string; // last update
  url: string;
  new: boolean;
};

type Block<T, F> = {
  state: "ok" | "not_configured" | "failed" | "offline";
  reason: string;
  total: number;
  fetched: number;
  items: T[];
  search_url: string;
  label: string;
  facets: F;
};

export type Check = {
  slug: string;
  at: string;
  topic: string;
  terms: Term[];
  window: { days: number; from: string; to: string };
  papers: Block<Paper, { kind: [string, number][]; venue: [string, number][] }>;
  patents: Block<
    PatentFamily,
    { applicant: [string, number][]; cpc: [string, number, string][] }
  >;
  // Absent from checks made before trials were added.
  trials?: Block<Trial, { phase: [string, number][]; status: [string, number][]; sponsor: [string, number][] }> & {
    credit: string;
  };
  first_check: boolean;
  new: { papers: number; patents: number; trials?: number };
  checks: number;
  previous: string;
  search_changed: boolean;
  error?: string;
};

export type WatchSummary = {
  slug: string;
  topic: string;
  checked: string;
  checks: number;
  papers: number;
  patents: number;
  patents_state: string;
  trials?: number;
  new: { papers: number; patents: number; trials?: number };
};

export type IntelStatus = {
  patents_configured: boolean;
  online: boolean;
  watches: WatchSummary[];
};

type IntelApi = {
  intel_status: () => Promise<IntelStatus>;
  intel_watch: (topic: string, days: number, expand: boolean) => Promise<Check>;
  intel_open: (slug: string) => Promise<Check>;
  intel_configure: (
    key: string,
    secret: string,
  ) => Promise<{ ok: boolean; patents_configured?: boolean; error?: string }>;
};

function api(): IntelApi {
  const backend = window.pywebview?.api as unknown as IntelApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const intelStatus = () => api().intel_status();
export const runCheck = (topic: string, days: number, expand: boolean) =>
  api().intel_watch(topic, days, expand);
export const openWatch = (slug: string) => api().intel_open(slug);
export const configurePatents = (key: string, secret: string) =>
  api().intel_configure(key, secret);

export const WINDOWS: { days: number; label: string }[] = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
  { days: 1825, label: "5 years" },
];
