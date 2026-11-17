// The local data and Spica's own use of the network, as the interface sees
// them. Updating the mirror runs in Python, in a process of its own; the
// interface only asks how it is going.

export type MirrorRow = {
  key: string;
  label: string;
  version: string; // "" when not built
  retrieved: string;
  bytes: number;
  missing: string[];
  latest: string; // newest upstream, as of the last check
  error: string; // why the check could not ask this source
  newer: boolean;
};

export type MirrorJob = {
  running?: boolean;
  interrupted?: boolean;
  started?: string;
  finished?: string;
  sources?: string[];
  current?: string;
  done?: string[];
  failed?: Record<string, string>;
  file?: { name: string; done: number; total: number } | null;
  log?: string[];
};

export type MirrorStatus = {
  rows: MirrorRow[];
  checked: string;
  job: MirrorJob;
  folder: string;
  online: boolean;
  parquet: boolean; // can this copy build Open Targets
  error?: string;
};

export type NetworkSettings = {
  online: boolean; // the saved choice
  online_effective: boolean; // what applies, after the environment
  forced_by: string; // "SPICA_OFFLINE" | "SPICA_ONLINE" | ""
  theme: "light" | "dark" | "system";
  menu?: "sidebar" | "cards";
};

type MirrorApi = {
  mirror_status: () => Promise<MirrorStatus>;
  mirror_check: () => Promise<MirrorStatus>;
  mirror_update: (sources: string[], rebuild: boolean) => Promise<MirrorStatus>;
  mirror_stop: () => Promise<MirrorStatus>;
  settings_status: () => Promise<NetworkSettings>;
  set_online: (on: boolean) => Promise<NetworkSettings>;
  set_theme: (theme: string) => Promise<NetworkSettings>;
  set_menu: (style: string) => Promise<NetworkSettings>;
};

function api(): MirrorApi {
  const backend = window.pywebview?.api as unknown as MirrorApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

// Async. The bridge can be absent in the first moments after the window
// opens. The caller then gets a rejected promise to catch, not an exception
// through React.
export const mirrorStatus = async () => api().mirror_status();
export const mirrorCheck = async () => api().mirror_check();
export const mirrorUpdate = async (sources: string[], rebuild = true) =>
  api().mirror_update(sources, rebuild);
export const mirrorStop = async () => api().mirror_stop();
export const networkSettings = async () => api().settings_status();
export const setOnline = async (on: boolean) => api().set_online(on);
export const setThemeChoice = async (theme: string) => api().set_theme(theme);
export const setMenuStyle = async (style: "sidebar" | "cards") => api().set_menu(style);

/** Bytes as people read them: 1.8 GB, 49 MB, 760 KB. */
export function size(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}
