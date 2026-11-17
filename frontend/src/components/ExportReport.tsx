import { useState } from "react";
import { FileDown, Loader2 } from "lucide-react";
import { exportReport, openExported } from "../exporting";

// "Export report": the client report for the genes on screen, as one HTML
// file that prints. A project name is optional; it titles the cover.

type Status =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "saved"; path: string }
  | { kind: "problem"; text: string };

export function ExportReport({ genes }: { genes: string[] }) {
  const [open, setOpen] = useState(false);
  const [project, setProject] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const save = async () => {
    setStatus({ kind: "busy" });
    try {
      const result = await exportReport(genes, project);
      if (result.error) setStatus({ kind: "problem", text: result.error });
      else if (result.cancelled) setStatus({ kind: "idle" });
      else setStatus({ kind: "saved", path: result.path ?? "" });
    } catch (error) {
      setStatus({ kind: "problem", text: String(error) });
    }
  };

  const view = async (path: string) => {
    const result = await openExported(path).catch((error) => ({ error: String(error) }));
    if (result.error) setStatus({ kind: "problem", text: result.error });
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-ink transition-colors hover:border-azure hover:text-azure-deep"
      >
        <FileDown size={15} aria-hidden="true" />
        Export report
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-[340px] rounded-[14px] border border-line bg-surface p-4 text-[13px]">
          <label className="block text-[12px] text-slate" htmlFor="export-project">
            Project name (cover, optional)
          </label>
          <input
            id="export-project"
            value={project}
            onChange={(event) => setProject(event.target.value)}
            className="mt-1 h-9 w-full rounded-[8px] border border-line bg-frost px-3 text-ink outline-none placeholder:text-slate/70 focus:border-azure"
          />
          <p className="mt-2 text-[12px] text-slate">
            {genes.length > 1
              ? `${genes.join(", ")}: comparison, then gene profiles.`
              : `${genes[0]}: all sections, charts and sources.`}{" "}
            One HTML file. No network calls.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={status.kind === "busy"}
              className="flex items-center gap-2 rounded-full bg-azure-deep px-4 py-1.5 font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
            >
              {status.kind === "busy" && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
              {status.kind === "busy" ? "Building" : "Save report"}
            </button>
          </div>
          {status.kind === "saved" && (
            <p className="mt-3 text-[12px] text-ink">
              Saved to <span className="break-all font-mono text-[11.5px]">{status.path}</span>.{" "}
              <button type="button" onClick={() => view(status.path)} className="text-azure-deep hover:underline">
                Open it
              </button>
            </p>
          )}
          {status.kind === "problem" && (
            <p role="alert" className="mt-3 text-[12px] text-error">
              {status.text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
