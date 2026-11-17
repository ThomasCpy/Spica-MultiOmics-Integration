import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Square } from "lucide-react";
import {
  mirrorCheck,
  mirrorStatus,
  mirrorStop,
  mirrorUpdate,
  size,
  type MirrorRow,
  type MirrorStatus,
} from "../mirror";

// The local data: the release of each source on this computer, the newer
// releases upstream, and an update that brings them level. The same panel
// shows in Settings and on the Databases page.
//
// A check sends each source one small request. An update downloads in a
// separate process. Reports keep working and read the old release of a
// source until the new one is complete.

const POLL_MS = 2000;

export function MirrorPanel() {
  const [status, setStatus] = useState<MirrorStatus | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "update" | "stop">("");
  const [problem, setProblem] = useState("");

  const act = useCallback(
    async (kind: "check" | "update" | "stop", run: () => Promise<MirrorStatus>) => {
      setBusy(kind);
      setProblem("");
      try {
        const next = await run();
        setStatus(next);
        if (next.error) setProblem(next.error);
      } catch (error) {
        setProblem(error instanceof Error ? error.message : "No backend response.");
      } finally {
        setBusy("");
      }
    },
    [],
  );

  useEffect(() => {
    mirrorStatus()
      .then(setStatus)
      .catch((error) =>
        setProblem(error instanceof Error ? error.message : "No backend response."),
      );
  }, []);

  // While an update runs, follow it.
  const running = !!status?.job.running;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      mirrorStatus()
        .then(setStatus)
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  if (!status) {
    return (
      <section className="rounded-[14px] border border-line bg-surface px-6 py-5 text-[14px] text-slate">
        {problem || "Reading local data."}
      </section>
    );
  }

  const built = status.rows.filter((row) => row.version);
  const stale = status.rows.filter((row) => row.newer || !row.version);
  const total = built.reduce((sum, row) => sum + row.bytes, 0);

  return (
    <section className="rounded-[14px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-3">
        <h2 className="text-[15px] font-semibold text-ink">Local data</h2>
        <span className="text-[12px] text-slate">
          {built.length} of {status.rows.length} sources local, {size(total)}
          {status.checked ? `, checked ${status.checked}` : ", releases not checked"}
        </span>
        <span className="ml-auto flex items-center gap-2">
          {running ? (
            <button
              type="button"
              onClick={() => act("stop", mirrorStop)}
              disabled={busy !== ""}
              className="flex items-center gap-1.5 rounded-full border border-line px-3.5 py-1.5 text-[13px] text-ink transition-colors hover:border-azure disabled:opacity-60"
            >
              <Square size={13} aria-hidden="true" />
              Stop
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => act("check", mirrorCheck)}
                disabled={busy !== ""}
                className="flex items-center gap-1.5 rounded-full border border-line px-3.5 py-1.5 text-[13px] text-ink transition-colors hover:border-azure disabled:opacity-60"
              >
                {busy === "check" ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw size={14} aria-hidden="true" />
                )}
                Check releases
              </button>
              {stale.length > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    act("update", () => mirrorUpdate(stale.map((row) => row.key), true))
                  }
                  disabled={busy !== ""}
                  className="flex items-center gap-1.5 rounded-full bg-azure-deep px-4 py-1.5 text-[13px] font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
                >
                  {busy === "update" && (
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                  )}
                  {stale.every((row) => !row.version)
                    ? `Build ${stale.length} ${stale.length === 1 ? "source" : "sources"}`
                    : `Update ${stale.length} ${stale.length === 1 ? "source" : "sources"}`}
                </button>
              )}
            </>
          )}
        </span>
      </div>

      {problem && (
        <p
          role="alert"
          className="mx-6 mt-4 flex items-start gap-2 rounded-[10px] bg-warn-bg px-4 py-3 text-[13px] text-warn-ink"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          {problem}
        </p>
      )}

      {running ? <Progress status={status} /> : <LastRun status={status} />}

      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-left text-[12px] text-slate">
            <th className="px-6 py-2 font-medium">Source</th>
            <th className="px-3 py-2 font-medium">Local</th>
            <th className="px-3 py-2 font-medium">Newest</th>
            <th className="px-3 py-2 text-right font-medium">Size</th>
            <th className="px-6 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-line border-t border-line">
          {status.rows.map((row) => (
            <Row
              key={row.key}
              row={row}
              checked={!!status.checked}
              disabled={running || busy !== ""}
              onRebuild={() => act("update", () => mirrorUpdate([row.key], true))}
            />
          ))}
        </tbody>
      </table>

      <p className="border-t border-line px-6 py-3 text-[12px] leading-relaxed text-slate">
        Update: download from each source site{built.length === status.rows.length ? `, about ${size(total)} in total` : ""}.
        Independent of online access. Folder: <span className="font-mono text-ink">{status.folder}</span>.
        {!status.parquet && (
          <span className="mt-1 block text-warn-ink">
            No Parquet reader: Open Targets not buildable.
          </span>
        )}
      </p>
    </section>
  );
}

function Row({
  row,
  checked,
  disabled,
  onRebuild,
}: {
  row: MirrorRow;
  checked: boolean;
  disabled: boolean;
  onRebuild: () => void;
}) {
  return (
    <tr>
      <td className="px-6 py-2.5 text-ink">{row.label}</td>
      <td className="px-3 py-2.5">
        {row.version ? (
          <>
            <span className="font-mono text-ink">{row.version}</span>
            <span className="ml-2 text-[11px] text-slate">{row.retrieved}</span>
            {row.missing.length > 0 && (
              <span className="ml-2 text-[11px] text-warn-ink" title={row.missing.join(", ")}>
                {row.missing.length} {row.missing.length === 1 ? "file" : "files"} missing
              </span>
            )}
          </>
        ) : (
          <span className="text-slate">not built</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {row.latest ? (
          row.newer ? (
            <span className="rounded-full bg-mist px-2 py-0.5 font-mono text-[12px] text-azure-deep">
              {row.latest} available
            </span>
          ) : row.version ? (
            <span className="text-slate">up to date</span>
          ) : (
            <span className="font-mono text-ink">{row.latest}</span>
          )
        ) : row.error ? (
          <span className="text-slate" title={row.error}>
            no answer
          </span>
        ) : (
          <span className="text-slate" title={checked ? "No published release to compare" : ""}>
            {checked ? "no release data" : "not checked"}
          </span>
        )}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-ink">
        {row.version ? size(row.bytes) : ""}
      </td>
      <td className="px-6 py-2.5 text-right">
        <button
          type="button"
          onClick={onRebuild}
          disabled={disabled}
          className="text-[12px] text-azure-deep hover:underline disabled:text-slate disabled:no-underline"
        >
          {row.version ? "Rebuild" : "Build"}
        </button>
      </td>
    </tr>
  );
}

function Progress({ status }: { status: MirrorStatus }) {
  const job = status.job;
  const sources = job.sources ?? [];
  const at = Math.max(0, sources.indexOf(job.current ?? "")) + 1;
  const label = status.rows.find((row) => row.key === job.current)?.label ?? job.current;
  const file = job.file;
  const share = file && file.total ? Math.min(100, (100 * file.done) / file.total) : null;
  return (
    <div className="border-b border-line px-6 py-4">
      <p className="flex items-center gap-2 text-[13px] text-ink">
        <Loader2 size={15} className="animate-spin text-azure-deep" aria-hidden="true" />
        {job.current
          ? `Updating ${label}, ${at} of ${sources.length}`
          : "Starting"}
      </p>
      {file && (
        <div className="mt-2.5 grid grid-cols-[minmax(0,200px)_1fr_auto] items-center gap-3 text-[12px]">
          <span className="truncate font-mono text-slate">{file.name}</span>
          <span className="block h-[7px] rounded-full bg-mist">
            {share !== null && (
              <span
                className="block h-full rounded-r-[4px] bg-azure"
                style={{ width: `${Math.max(1, share)}%` }}
              />
            )}
          </span>
          <span className="font-mono tabular-nums text-ink">
            {size(file.done)}
            {file.total ? ` of ${size(file.total)}` : ""}
          </span>
        </div>
      )}
      {(job.log ?? []).length > 0 && (
        <pre className="mt-3 max-h-[140px] overflow-y-auto whitespace-pre-wrap rounded-[10px] bg-frost px-3 py-2 font-mono text-[11px] leading-relaxed text-slate">
          {(job.log ?? []).slice(-8).join("\n")}
        </pre>
      )}
    </div>
  );
}

function LastRun({ status }: { status: MirrorStatus }) {
  const job = status.job;
  const failed = Object.entries(job.failed ?? {});
  if (job.interrupted) {
    return (
      <p className="mx-6 my-4 flex items-start gap-2 rounded-[10px] bg-warn-bg px-4 py-3 text-[13px] text-warn-ink">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
        Last update incomplete. Sources not reached keep their release.
      </p>
    );
  }
  if (!job.finished) return null;
  return (
    <div className="border-b border-line px-6 py-3 text-[12px] text-slate">
      Last update {job.finished}:{" "}
      {(job.done ?? []).length > 0
        ? `${(job.done ?? []).join(", ")} done`
        : "nothing completed"}
      {failed.length > 0 && (
        <span className="mt-2 flex items-start gap-2 rounded-[10px] bg-warn-bg px-3 py-2 text-[12px] text-warn-ink">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            {failed.map(([key, why]) => (
              <span key={key} className="block">
                {key}: {why}
              </span>
            ))}
          </span>
        </span>
      )}
    </div>
  );
}
