// The client report: built in Python from the records (spica/export.py) and
// saved where the user picks. The interface only asks and says where it went.

export type Exported = {
  error?: string;
  cancelled?: boolean;
  path?: string;
  genes?: string[];
};

export type ExportedFile = { name: string; path: string; modified: string; megabytes: number };

type ExportApi = {
  exported_reports: () => Promise<{ folder: string; reports: ExportedFile[] }>;
  export_report: (symbols: string[], project: string) => Promise<Exported>;
  open_exported: (path: string) => Promise<{ error?: string; opened?: string }>;
};

function api(): ExportApi {
  const backend = window.pywebview?.api as unknown as ExportApi | undefined;
  if (!backend) throw new Error("Spica's backend is not attached to this window.");
  return backend;
}

export const exportReport = async (symbols: string[], project: string) => api().export_report(symbols, project);
export const openExported = async (path: string) => api().open_exported(path);
export const exportedReports = async () => api().exported_reports();
