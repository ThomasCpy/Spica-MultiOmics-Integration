import { useEffect, useState } from "react";
import { exportedReports, openExported, type ExportedFile } from "../exporting";

// Reports: the genes looked at on this computer, and the client reports
// exported from it. A gene's report is rebuilt from the mirror when it is
// opened, so it is never stale; an exported file is what was sent.

export function Reports({
  recent,
  onOpenReport,
}: {
  recent: { symbol: string; date: string }[];
  onOpenReport: (symbol: string) => void;
}) {
  const [files, setFiles] = useState<ExportedFile[]>([]);
  const [folder, setFolder] = useState("");
  const [problem, setProblem] = useState("");

  useEffect(() => {
    exportedReports()
      .then((found) => {
        setFiles(found.reports);
        setFolder(found.folder);
      })
      .catch(() => undefined);
  }, []);

  return (
    <div className="mx-auto w-full max-w-[880px] px-8 py-10">
      <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Reports</h1>
      <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-slate">
        Built gene reports and exported client reports. A gene report is rebuilt from local data on
        opening; an exported file does not change.
      </p>

      <h2 className="mt-8 text-[15px] font-semibold text-ink">Exported</h2>
      <p className="mt-1 text-[12px] text-slate">
        Folder: <span className="font-mono">{folder || "Documents/Spica reports"}</span>, and other
        locations used in this session.
      </p>
      {files.length === 0 ? (
        <p className="mt-3 text-[13px] text-slate">No exported report.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line rounded-[14px] border border-line bg-surface">
          {files.map((file) => (
            <li key={file.path} className="flex items-center gap-4 px-5 py-3 text-[13px]">
              <span className="min-w-0 flex-1 truncate text-ink" title={file.path}>
                {file.name.replace(/\.html?$/i, "")}
              </span>
              <span className="font-mono text-slate">{file.megabytes} MB</span>
              <span className="text-slate">{file.modified}</span>
              <button
                type="button"
                onClick={async () => {
                  const result = await openExported(file.path).catch((error) => ({ error: String(error) }));
                  setProblem("error" in result && result.error ? result.error : "");
                }}
                className="text-azure-deep hover:underline"
              >
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
      {problem && (
        <p role="alert" className="mt-2 text-[13px] text-error">
          {problem}
        </p>
      )}

      <h2 className="mt-10 text-[15px] font-semibold text-ink">Built reports</h2>
      {recent.length === 0 ? (
        <p className="mt-2 text-[13px] text-slate">None yet.</p>
      ) : (
        <ul className="mt-3 grid grid-cols-3 gap-2">
          {recent.map((item) => (
            <li key={item.symbol}>
              <button
                type="button"
                onClick={() => onOpenReport(item.symbol)}
                className="flex w-full items-center justify-between rounded-[10px] border border-line bg-surface px-3 py-2 text-[13px] hover:border-azure"
              >
                <span className="font-mono font-semibold text-ink">{item.symbol}</span>
                <span className="text-[12px] text-slate">{item.date}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
