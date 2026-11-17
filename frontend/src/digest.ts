// The digest: scientific podcasts transcribed on this computer, clinical
// trials and papers from the watches, searchable (spica/digest/). The
// backend does every fetch; links open in the browser.

import type { Job } from "./candidates";

export type DigestKind = "podcast" | "notes" | "title" | "trial" | "paper";

export type DigestFeed = {
  key: string;
  name: string;
  publisher: string;
  url: string;
  site: string;
  about: string;
  added: boolean;
  on: boolean;
  episodes: number;
  transcribed: number;
  reserved: string;
  latest: string;
};

export type SpeechStatus = {
  engine: boolean;
  problem: string;
  model: string;
  models: { name: string; file: string; megabytes: number; about: string; present: boolean }[];
  ready: boolean;
};

export type DigestStatus = {
  error?: string;
  feeds: DigestFeed[];
  speech: SpeechStatus;
  per_feed: number;
  last_update: { at: string; feeds: number; new: number; transcribed: number; problems: string[] } | null;
  episodes: number;
  transcribed: number;
  online: boolean;
  /** What "Process all" faces: episodes waiting, their audio, how long at this computer's pace. */
  backlog?: { episodes: number; audio_hours: number; unknown_length: number; pace: number | null; estimate_hours: number | null };
  added?: string;
  reserved?: string;
};

export type DigestPassage = {
  id: string;
  kind: DigestKind;
  source: string;
  title: string;
  date: string;
  text: string;
  link: string;
  start: number | null;
  episode: string;
  genes: string[];
  at?: string;
  snippet: string;
  score?: number;
};

export type DigestResults = {
  error?: string;
  query?: string;
  terms?: string[];
  genes?: string[];
  total: number;
  offset: number;
  results: DigestPassage[];
  passages?: number;
  meaning?: boolean; // ranked by meaning too, with the local embedding model
  naming?: number; // results that name the gene the query names
};

export type Transcript = {
  error?: string;
  id: string;
  title: string;
  date: string;
  link: string;
  feed: string;
  engine: string;
  note?: string;
  segments: [number, number, string][];
};

type DigestApi = {
  digest_status: () => Promise<DigestStatus>;
  digest_latest: (kinds: string[], since: string, offset: number) => Promise<DigestResults>;
  digest_search: (query: string, kinds: string[], gene: string, since: string, offset: number) => Promise<DigestResults>;
  digest_transcript: (episode: string) => Promise<Transcript>;
  digest_set_feed: (key: string, on: boolean) => Promise<DigestStatus>;
  digest_set_per_feed: (count: number) => Promise<DigestStatus>;
  digest_add_feed: (url: string) => Promise<DigestStatus>;
  digest_remove_feed: (key: string) => Promise<DigestStatus>;
  digest_update_start: (everything: boolean) => Promise<{ job?: string; error?: string; already?: boolean }>;
  digest_running: () => Promise<{ job?: string; state?: string }>;
  job_stop: (job: string) => Promise<Job<unknown>>;
  speech_download_start: (name: string) => Promise<{ job?: string; error?: string }>;
  job_status: <T>(job: string) => Promise<Job<T>>;
};

function api(): DigestApi {
  const backend = window.pywebview?.api as unknown as DigestApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const digestStatus = async () => api().digest_status();
export const digestLatest = async (kinds: string[], since: string, offset = 0) => api().digest_latest(kinds, since, offset);
export const digestSearch = async (query: string, kinds: string[], gene: string, since: string, offset = 0) =>
  api().digest_search(query, kinds, gene, since, offset);
export const digestTranscript = async (episode: string) => api().digest_transcript(episode);
export const setFeed = async (key: string, on: boolean) => api().digest_set_feed(key, on);
export const setPerFeed = async (count: number) => api().digest_set_per_feed(count);
export const addFeed = async (url: string) => api().digest_add_feed(url);
export const removeFeed = async (key: string) => api().digest_remove_feed(key);
export const startDigestUpdate = async (everything = false) => api().digest_update_start(everything);
export const digestRunning = async () => api().digest_running();
export const stopJob = async (job: string) => api().job_stop(job);
export const startSpeechDownload = async (name: string) => api().speech_download_start(name);

export const KIND_LABEL: Record<DigestKind, string> = {
  podcast: "talk",
  notes: "show notes",
  title: "title only",
  trial: "trial",
  paper: "paper",
};
