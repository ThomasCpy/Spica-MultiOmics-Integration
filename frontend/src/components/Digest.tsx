import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { follow } from "../candidates";
import {
  KIND_LABEL,
  addFeed,
  digestLatest,
  digestRunning,
  stopJob,
  digestSearch,
  digestStatus,
  digestTranscript,
  removeFeed,
  setFeed,
  setPerFeed,
  startDigestUpdate,
  startSpeechDownload,
  type DigestPassage,
  type DigestResults,
  type DigestStatus,
  type Transcript,
} from "../digest";

// The digest: podcasts from journals and learned societies, transcribed on
// this computer, beside the trials and papers that the watches found. One
// search box covers all of it. Without a query, the screen shows the latest
// items. The source transcript of a quote is one click away. Each source
// shows whether its publisher permits transcription.

const STEP = 25;
const KINDS = [
  ["", "everything"],
  ["podcast", "talks"],
  ["trial", "trials"],
  ["paper", "papers"],
  ["notes", "show notes"],
] as const;
const SINCE = [
  ["", "any time"],
  [30, "30 days"],
  [90, "90 days"],
  [365, "a year"],
] as const;

function daysAgo(days: number): string {
  const day = new Date(Date.now() - days * 86400000);
  return day.toISOString().slice(0, 10);
}

export function Digest({ onOpenReport }: { onOpenReport: (symbol: string) => void }) {
  const [status, setStatus] = useState<DigestStatus | null>(null);
  const [query, setQuery] = useState("");
  const [gene, setGene] = useState("");
  const [kind, setKind] = useState("");
  const [since, setSince] = useState<number | "">("");
  const [results, setResults] = useState<DigestResults | null>(null);
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState({ query: "", gene: "" });
  const [reading, setReading] = useState<{ episode: string; start: number | null } | null>(null);

  const kinds = kind ? [kind] : [];
  const from = since === "" ? "" : daysAgo(since);

  const load = async (offset = 0, keep = false) => {
    setBusy(true);
    try {
      const found =
        query.trim() || gene.trim()
          ? await digestSearch(query, kinds, gene.trim(), from, offset)
          : await digestLatest(kinds, from, offset);
      setAsked({ query: query.trim(), gene: gene.trim() });
      setResults(keep && results ? { ...found, results: [...results.results, ...found.results] } : found);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    digestStatus().then(setStatus).catch(() => undefined);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (status) load();
    // Filters apply at once; the query waits for Search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, since]);

  const terms = useMemo(() => (results?.terms ?? []).filter((term) => term.length > 1), [results]);

  return (
    <div className="mx-auto grid w-full max-w-[1180px] grid-cols-[minmax(0,1fr)_330px] gap-8 px-8 py-10">
      <div className="min-w-0">
        <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Digest</h1>
        <p className="mt-3 max-w-[66ch] text-[15px] leading-relaxed text-slate">
          Podcasts of journals and learned societies, transcribed locally, with the trials and papers of the
          watches.
        </p>

        <div className="mt-6 flex items-center gap-2 pl-[52px] pr-[96px] text-[12px] font-medium text-slate">
          <span className="flex-1">Terms</span>
          <span className="w-[92px]">Gene</span>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            load();
          }}
          className="mt-1.5 flex items-center gap-2 rounded-full border border-line bg-surface p-1.5 pl-4"
        >
          <Search size={17} className="text-slate" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search the digest"
            className="h-9 min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-slate/70"
          />
          <input
            value={gene}
            onChange={(event) => setGene(event.target.value.toUpperCase())}
            aria-label="Only passages naming this gene"
            title="Gene filter"
            className="h-9 w-[92px] rounded-full border border-line bg-frost px-3 font-mono text-[13px] text-ink outline-none placeholder:font-sans placeholder:text-slate/70 focus:border-azure"
          />
          <button
            type="submit"
            className="flex h-9 items-center gap-2 rounded-full bg-azure-deep px-4 text-[13px] font-semibold text-on-accent hover:bg-azure-hover"
          >
            {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Search
          </button>
        </form>

        <div className="mt-3 flex flex-wrap items-center gap-1 text-[12px]">
          {KINDS.map(([value, label]) => (
            <Chip key={value} on={kind === value} onClick={() => setKind(value)}>
              {label}
            </Chip>
          ))}
          <span className="mx-2 h-4 w-px bg-line" />
          {SINCE.map(([value, label]) => (
            <Chip key={String(value)} on={since === value} onClick={() => setSince(value)}>
              {label}
            </Chip>
          ))}
        </div>

        {results?.error && (
          <p role="alert" className="mt-4 text-[13px] text-error">
            {results.error}
          </p>
        )}
        {results && !results.error && (
          <>
            <p className="mt-5 text-[13px] text-slate">
              {asked.query || asked.gene
                ? `${results.total.toLocaleString("en-US")} ${results.total === 1 ? "passage" : "passages"}${asked.query ? ` for "${asked.query}"` : ""}${
                    results.genes?.length ? `, taken to name ${results.genes.join(", ")}` : ""
                  }, best first${results.meaning ? ", by words and meaning" : ""}.${
                    results.genes?.length && results.total && !results.naming
                      ? ` None names ${results.genes.join(", ")}; matches share words only.`
                      : ""
                  }`
                : `${results.total.toLocaleString("en-US")} items, newest first.`}
              {results.total === 0 &&
                (results.passages
                  ? ` No match in ${results.passages.toLocaleString("en-US")} passages.`
                  : " Digest empty. Update the sources.")}
            </p>
            <ul className="mt-3 divide-y divide-line rounded-[14px] border border-line bg-surface">
              {results.results.map((item) => (
                <Result
                  key={item.id}
                  item={item}
                  terms={terms}
                  onRead={(episode, start) => setReading({ episode, start })}
                  onGene={(symbol) => {
                    setGene(symbol);
                    setQuery("");
                    setTimeout(() => document.querySelector<HTMLFormElement>("form")?.requestSubmit(), 0);
                  }}
                  onReport={onOpenReport}
                />
              ))}
            </ul>
            {results.results.length < results.total && (
              <button
                type="button"
                onClick={() => load(results.results.length, true)}
                className="mt-3 text-[12px] text-azure-deep hover:underline"
              >
                Show {Math.min(STEP, results.total - results.results.length)} more (
                {(results.total - results.results.length).toLocaleString("en-US")} left)
              </button>
            )}
          </>
        )}
      </div>

      <Sources status={status} onStatus={setStatus} onUpdated={() => load()} />

      {reading && <Reader episode={reading.episode} start={reading.start} terms={terms} onClose={() => setReading(null)} />}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`rounded-full px-2.5 py-0.5 ${on ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"}`}
    >
      {children}
    </button>
  );
}

function Marked({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return (
    <>
      {text.split(pattern).map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="rounded-[3px] bg-mist px-0.5 text-ink">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function Result({
  item,
  terms,
  onRead,
  onGene,
  onReport,
}: {
  item: DigestPassage;
  terms: string[];
  onRead: (episode: string, start: number | null) => void;
  onGene: (symbol: string) => void;
  onReport: (symbol: string) => void;
}) {
  return (
    <li className="grid grid-cols-[92px_minmax(0,1fr)] gap-4 px-5 py-3.5">
      <span className="pt-0.5 text-[12px] text-slate">
        <span className="block font-mono tabular-nums">{item.date}</span>
        <span className="mt-1 inline-block rounded-[5px] bg-mist px-1.5 py-0.5 text-[10px] text-azure-deep">
          {KIND_LABEL[item.kind]}
        </span>
      </span>
      <span className="min-w-0">
        <a
          href={item.link}
          target="_blank"
          rel="noreferrer"
          className="text-[14px] font-semibold leading-snug text-ink hover:text-azure-deep hover:underline"
        >
          {item.title}
        </a>
        <span className="mt-0.5 block text-[12px] text-slate">
          {item.source}
          {item.at && (
            <button
              type="button"
              onClick={() => onRead(item.episode, item.start)}
              className="ml-2 font-mono text-azure-deep hover:underline"
              title="Transcript from this point"
            >
              at {item.at}
            </button>
          )}
          {item.kind === "notes" && item.episode && (
            <button type="button" onClick={() => onRead(item.episode, null)} className="ml-2 text-azure-deep hover:underline">
              transcript
            </button>
          )}
        </span>
        {item.kind !== "title" && (
          <span className="mt-1.5 block text-[13px] leading-relaxed text-ink">
            <Marked text={item.snippet} terms={terms} />
          </span>
        )}
        {item.genes.length > 0 && (
          <span className="mt-1.5 flex flex-wrap gap-1">
            {item.genes.map((symbol) => (
              <span key={symbol} className="inline-flex overflow-hidden rounded-full border border-line text-[11px]">
                <button
                  type="button"
                  onClick={() => onGene(symbol)}
                  className="px-2 font-mono text-ink hover:bg-mist"
                  title={`Everything naming ${symbol}`}
                >
                  {symbol}
                </button>
                <button
                  type="button"
                  onClick={() => onReport(symbol)}
                  className="border-l border-line px-1.5 text-slate hover:bg-mist hover:text-azure-deep"
                  title={`Open the ${symbol} report`}
                >
                  report
                </button>
              </span>
            ))}
          </span>
        )}
      </span>
    </li>
  );
}

function Reader({
  episode,
  start,
  terms,
  onClose,
}: {
  episode: string;
  start: number | null;
  terms: string[];
  onClose: () => void;
}) {
  const [found, setFound] = useState<Transcript | null>(null);
  const target = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    digestTranscript(episode).then(setFound).catch((error) => setFound({ error: String(error) } as Transcript));
  }, [episode]);
  useEffect(() => {
    target.current?.scrollIntoView({ block: "center" });
  }, [found]);

  const at = start ?? -1;
  const lead = found?.segments.findIndex(([begin]) => begin >= at - 0.5) ?? -1;
  const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-ink/20" onClick={onClose}>
      <aside
        className="flex h-full w-[min(640px,92vw)] flex-col border-l border-line bg-surface"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold leading-snug text-ink">{found?.title ?? "Loading the transcript"}</p>
            {found && !found.error && (
              <p className="mt-1 text-[12px] text-slate">
                {found.date}. Transcribed with {found.engine || "nothing yet"}.{" "}
                <a href={found.link} target="_blank" rel="noreferrer" className="text-azure-deep hover:underline">
                  The episode
                </a>
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-slate hover:text-ink">
            <X size={18} />
          </button>
        </header>
        <ol className="flex-1 space-y-1.5 overflow-y-auto px-5 py-4 text-[13px] leading-relaxed">
          {found?.error && <li className="text-error">{found.error}</li>}
          {found?.note && <li className="text-slate">{found.note}</li>}
          {found && !found.error && found.segments.length === 0 && !found.note && (
            <li className="text-slate">Not transcribed.</li>
          )}
          {found?.segments.map(([begin, , text], index) => (
            <li
              key={index}
              ref={index === lead ? target : undefined}
              className={`grid grid-cols-[52px_1fr] gap-2 rounded-[6px] px-1 ${index === lead ? "bg-mist" : ""}`}
            >
              <span className="font-mono text-[11px] tabular-nums text-slate">{clock(begin)}</span>
              <span className="text-ink">
                <Marked text={text} terms={terms} />
              </span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

function Sources({
  status,
  onStatus,
  onUpdated,
}: {
  status: DigestStatus | null;
  onStatus: (status: DigestStatus) => void;
  onUpdated: () => void;
}) {
  const [progress, setProgress] = useState<string>("");
  const [problem, setProblem] = useState("");
  const [address, setAddress] = useState("");
  // The digest job being followed, so "Stop" can reach it; "Process all"
  // runs for hours and a reopened screen picks it up again.
  const [job, setJob] = useState<{ id: string; everything: boolean; left: string; stopping: boolean } | null>(null);
  const [confirming, setConfirming] = useState(false);

  const watch = async (id: string, everything: boolean) => {
    setJob({ id, everything, left: "", stopping: false });
    const done = await follow<{ feeds: number; new: number; transcribed: number; problems: string[]; stopped?: boolean }>(id, (state) => {
      const at = Math.min(state.done + 1, state.total);
      setProgress(state.total ? `Transcribing ${at.toLocaleString("en-US")} of ${state.total.toLocaleString("en-US")}` : "Reading the feeds");
      let left = "";
      if (state.started && state.done > 0 && state.total > state.done) {
        const per = (Date.now() / 1000 - state.started) / state.done;
        const hours = (per * (state.total - state.done)) / 3600;
        left = hours >= 1 ? `about ${Math.round(hours)} h left` : `about ${Math.max(1, Math.round(hours * 60))} min left`;
      }
      setJob({ id, everything, left, stopping: !!state.stopping });
    });
    setProgress("");
    setJob(null);
    if (done.state !== "done") setProblem(done.error ?? "Update not finished.");
    onStatus(await digestStatus());
    onUpdated();
  };

  useEffect(() => {
    digestRunning()
      .then((running) => {
        if (running.job && running.state === "running") watch(running.job, true);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!status) return <aside className="text-[13px] text-slate">Reading sources.</aside>;
  if (status.error) return <aside className="text-[13px] text-error">{status.error}</aside>;

  const update = async (everything = false) => {
    setProblem("");
    setConfirming(false);
    setProgress("Reading the feeds");
    const started = await startDigestUpdate(everything);
    if (started.error || !started.job) {
      setProblem(started.error ?? "Update not started.");
      setProgress("");
      return;
    }
    await watch(started.job, everything);
  };

  const backlog = status.backlog;
  const estimate =
    backlog?.estimate_hours != null
      ? `Estimate: ${backlog.estimate_hours < 1 ? "under 1 h" : `${Math.round(backlog.estimate_hours)} h`} (local pace).`
      : "Estimate available after the first transcriptions.";

  const download = async (name: string) => {
    setProblem("");
    const started = await startSpeechDownload(name);
    if (started.error || !started.job) {
      setProblem(started.error ?? "Download not started.");
      return;
    }
    const job = await follow(started.job, (state) =>
      setProgress(state.total ? `Speech model, ${Math.round((100 * state.done) / state.total)}%` : "Speech model"),
    );
    setProgress("");
    if (job.state !== "done") setProblem(job.error ?? "Download not finished.");
    onStatus(await digestStatus());
  };

  const last = status.last_update;
  return (
    <aside className="space-y-5 self-start">
      <section className="rounded-[16px] border border-line bg-surface p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-[14px] font-semibold text-ink">Sources</h2>
          <button
            type="button"
            onClick={() => update(false)}
            disabled={!!progress}
            className="flex items-center gap-1.5 rounded-full bg-azure-deep px-3 py-1 text-[12px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-70"
          >
            {progress ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={13} aria-hidden="true" />}
            {progress || "Update"}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-slate">
          {status.episodes.toLocaleString("en-US")} episodes, {status.transcribed} transcribed.{" "}
          {last ? `Last update ${last.at.replace("T", " ").slice(0, 16)}: ${last.new} new, ${last.transcribed} transcribed.` : "Never updated."}
          {!status.online && " Online access off: search only."}
        </p>
        {job?.everything ? (
          <div className="mt-3 rounded-[10px] border border-line bg-frost p-3 text-[12px] text-ink">
            <p>
              Process all: {progress || "starting"}
              {job.left && `, ${job.left}`}.
            </p>
            <p className="mt-1 text-[11px] text-slate">
              {job.stopping
                ? "Stops after the current episode. Completed transcripts stay."
                : "Background job. Stop keeps completed transcripts; the next run continues."}
            </p>
            {!job.stopping && (
              <button
                type="button"
                onClick={() => stopJob(job.id).then(() => setJob({ ...job, stopping: true }))}
                className="mt-2 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-ink hover:border-azure hover:text-azure-deep"
              >
                Stop
              </button>
            )}
          </div>
        ) : (
          backlog &&
          backlog.episodes > 0 && (
            <div className="mt-3 rounded-[10px] border border-line bg-frost p-3 text-[12px] text-ink">
              <p>
                <span className="font-mono">{backlog.episodes.toLocaleString("en-US")}</span>{" "}
                {backlog.episodes === 1 ? "episode" : "episodes"} not transcribed
                {backlog.audio_hours > 0 && (
                  <>
                    , <span className="font-mono">{backlog.audio_hours.toLocaleString("en-US")}</span> h of audio
                    {backlog.unknown_length > 0 && ` (${backlog.unknown_length.toLocaleString("en-US")} without length, median used)`}
                  </>
                )}
                . Update: newest {status.per_feed} per feed. Process all: all episodes.
              </p>
              {confirming ? (
                <>
                  <p className="mt-2 text-[11px] text-slate">
                    {estimate} Local background job, newest first. Stop keeps completed transcripts.
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={() => update(true)}
                      disabled={!!progress || !status.online}
                      className="rounded-full bg-azure-deep px-3 py-1 text-[12px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-60"
                    >
                      Start
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(false)}
                      className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-ink hover:border-azure"
                    >
                      Not now
                    </button>
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  disabled={!!progress}
                  className="mt-2 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-azure-deep hover:border-azure disabled:opacity-60"
                >
                  Process all
                </button>
              )}
            </div>
          )
        )}
        {problem && <p className="mt-1 text-[11px] text-warn-ink [overflow-wrap:anywhere]">{problem}</p>}
        {!problem && last && last.problems.length > 0 && (
          <details className="mt-1 text-[11px] text-warn-ink">
            <summary className="cursor-pointer">
              {last.problems.length} {last.problems.length === 1 ? "episode" : "episodes"} not read
            </summary>
            <ul className="mt-1 space-y-1 [overflow-wrap:anywhere]">
              {last.problems.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
        <ul className="mt-3 space-y-2.5">
          {status.feeds.map((feed) => (
            <li key={feed.key} className="text-[12px]">
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={feed.on}
                  onChange={async (event) => onStatus(await setFeed(feed.key, event.target.checked))}
                  className="mt-0.5 accent-[var(--color-azure-deep)]"
                />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink" title={feed.about}>
                    {feed.name}
                  </span>
                  <span className="block text-[11px] text-slate">{feed.publisher}</span>
                  <span className={`block text-[11px] ${feed.reserved ? "text-warn-ink" : "text-slate"}`} title={feed.reserved}>
                    {feed.reserved
                      ? "Titles only: text and data mining reserved."
                      : `${feed.episodes} episodes, ${feed.transcribed} transcribed`}
                  </span>
                </span>
                {feed.added && (
                  <button
                    type="button"
                    aria-label={`Remove ${feed.name}`}
                    onClick={async () => onStatus(await removeFeed(feed.key))}
                    className="text-slate hover:text-error"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </label>
            </li>
          ))}
        </ul>
        <form
          className="mt-3 flex gap-1.5"
          onSubmit={async (event) => {
            event.preventDefault();
            const added = await addFeed(address);
            if (added.error) setProblem(added.error);
            else {
              setAddress("");
              onStatus(added);
              if (added.reserved) setProblem(`Added, titles only: ${added.reserved}`);
            }
          }}
        >
          <span className="shrink-0 text-[12px] text-slate">Feed URL</span>
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            aria-label="Podcast feed address"
            title="Feed URL"
            className="h-8 min-w-0 flex-1 rounded-[8px] border border-line bg-frost px-2 text-[12px] text-ink outline-none focus:border-azure"
          />
          <button type="submit" aria-label="Add the feed" className="rounded-full border border-line px-2 text-azure-deep hover:border-azure">
            <Plus size={14} />
          </button>
        </form>
        <label className="mt-3 flex items-center justify-between text-[12px] text-slate">
          Episodes per feed, per update
          <select
            value={status.per_feed}
            onChange={async (event) => onStatus(await setPerFeed(Number(event.target.value)))}
            className="rounded-[6px] border border-line bg-frost px-1.5 py-0.5 text-ink"
          >
            {[0, 1, 3, 5, 10, 25].map((count) => (
              <option key={count} value={count}>
                {count === 0 ? "none" : `${count} newest`}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="rounded-[16px] border border-line bg-surface p-4 text-[12px]">
        <h2 className="text-[14px] font-semibold text-ink">Transcription</h2>
        <p className="mt-1 text-slate">
          {status.speech.ready
            ? `whisper.cpp, ${status.speech.model}, local. Audio deleted after transcription.`
            : status.speech.problem || "No speech model installed."}
        </p>
        <ul className="mt-2 space-y-1.5">
          {status.speech.models.map((model) => (
            <li key={model.name} className="flex items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="font-mono text-ink">{model.name}</span>
                <span className="block text-[11px] text-slate">
                  {model.megabytes} MB. {model.about}
                </span>
              </span>
              {model.present ? (
                <span className="text-[11px] text-slate">installed</span>
              ) : (
                <button
                  type="button"
                  onClick={() => download(model.name)}
                  disabled={!!progress || !status.speech.engine}
                  className="shrink-0 rounded-full border border-line px-2.5 py-0.5 text-azure-deep hover:border-azure disabled:opacity-50"
                >
                  Download
                </button>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-slate">
          Trials: from the Intelligence watches (ClinicalTrials.gov).
        </p>
      </section>
    </aside>
  );
}
