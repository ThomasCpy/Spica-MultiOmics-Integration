import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ExternalLink,
  KeyRound,
  Loader2,
  Radar,
  RefreshCw,
  Search,
} from "lucide-react";
import { configurePatents, intelStatus, openWatch, runCheck, WINDOWS, type Check, type IntelStatus, type Paper, type PatentFamily, type WatchSummary, type Trial } from "../intel";
import { Timeline } from "./Timeline";

// What has been filed and published on a topic, and what is new since the
// last look. Built for one question a preclinical team asks again and
// again: other groups working on the same target, modality or concept.
//
// Two lists, kept apart because they answer different things: patents say
// who intends to own it, papers say who is working on it. Each says what it
// could not reach rather than showing an empty list.

const SHOWN = 25;

export function Intel() {
  const [status, setStatus] = useState<IntelStatus | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [topic, setTopic] = useState("");
  const [days, setDays] = useState(90);
  const [expand, setExpand] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);

  // A result replaces the list in the same pane, so start it at the top.
  useEffect(() => {
    input.current?.closest("main")?.scrollTo(0, 0);
  }, [check]);

  async function refresh() {
    try {
      setStatus(await intelStatus());
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The backend didn't respond.");
    }
  }

  useEffect(() => {
    input.current?.focus();
    refresh();
  }, []);

  async function go(text: string, window = days) {
    if (!text.trim()) {
      setProblem("Enter a target, a modality or any terms, separated by commas.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const result = await runCheck(text, window, expand);
      if (result.error) setProblem(result.error);
      else {
        setCheck(result);
        refresh();
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The backend didn't respond.");
    } finally {
      setBusy(false);
    }
  }

  async function reopen(watch: WatchSummary) {
    setBusy(true);
    setProblem("");
    try {
      const result = await openWatch(watch.slug);
      if (result.error) setProblem(result.error);
      else {
        setCheck(result);
        setTopic(result.topic);
        setDays(result.window.days);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1100px] px-8 py-10">
      {check ? (
        <button
          type="button"
          onClick={() => setCheck(null)}
          className="mb-6 flex items-center gap-1.5 text-[13px] text-slate transition-colors hover:text-azure-deep"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          All watches
        </button>
      ) : (
        <>
          <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">
            Competitive intelligence
          </h1>
          <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-slate">
            Patents, papers, preprints and clinical trials by topic. Each check is kept; the next check marks new items.
          </p>
        </>
      )}

      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          go(topic);
        }}
        className={check ? "mb-6" : "mt-8"}
      >
        <label htmlFor="intel-topic" className="mb-1.5 block px-1 text-[12px] font-medium text-slate">
          Topic terms, separated by commas
        </label>
        <div className="flex h-14 items-center gap-3 rounded-full border border-line bg-surface pl-5 pr-1.5 transition-[border-color,box-shadow] focus-within:border-azure focus-within:shadow-[0_0_0_4px_rgb(0_178_255/0.18)]">
          <Search size={20} strokeWidth={1.75} className="shrink-0 text-slate" aria-hidden="true" />
          <input
            ref={input}
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              if (problem) setProblem("");
            }}
            id="intel-topic"
            autoComplete="off"
            spellCheck={false}
            aria-label="Topic to watch"
            className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-[14px] placeholder:text-slate/70"
          />
          <button
            type="submit"
            disabled={busy}
            className="flex h-11 shrink-0 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
          >
            {busy ? (
              <Loader2 size={17} className="animate-spin" aria-hidden="true" />
            ) : (
              <Radar size={17} strokeWidth={2} aria-hidden="true" />
            )}
            Check now
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-5 text-[13px] text-slate">
          <span className="flex items-center gap-1">
            Window
            {WINDOWS.map((option) => (
              <button
                key={option.days}
                type="button"
                aria-pressed={days === option.days}
                onClick={() => setDays(option.days)}
                className={`rounded-full px-2.5 py-0.5 transition-colors ${
                  days === option.days ? "bg-mist text-azure-deep" : "hover:text-azure-deep"
                }`}
              >
                {option.label}
              </button>
            ))}
          </span>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={expand}
              onChange={(e) => setExpand(e.target.checked)}
              className="accent-[var(--color-azure-deep)]"
            />
            Add HGNC names of gene symbols
          </label>
        </div>
        {problem && (
          <p role="alert" className="mt-3 px-5 text-[13px] text-error">
            {problem}
          </p>
        )}
      </form>

      {status && !status.patents_configured && (
        <PatentKey onSaved={refresh} />
      )}
      {status && !status.online && (
        <Notice>
          Network use off (SPICA_OFFLINE). Saved checks open; new checks cannot reach the sources.
        </Notice>
      )}

      {check ? (
        <Result check={check} busy={busy} onAgain={() => go(check.topic, check.window.days)} />
      ) : (
        status && <Watches watches={status.watches} onOpen={reopen} />
      )}

      <p className="mt-8 max-w-[75ch] text-[12px] leading-relaxed text-slate">
        Not a freedom-to-operate opinion. Patent scope depends on claims and family status per country;
        a patent attorney reads them.
      </p>
    </div>
  );
}

// -- saved watches -----------------------------------------------------------

function Watches({
  watches,
  onOpen,
}: {
  watches: WatchSummary[];
  onOpen: (watch: WatchSummary) => void;
}) {
  if (!watches.length) return null;
  return (
    <section className="mt-8 rounded-[14px] border border-line bg-surface">
      <h2 className="border-b border-line px-5 py-3 text-[15px] font-semibold text-ink">
        Watches
      </h2>
      <ul className="divide-y divide-line">
        {watches.map((watch) => (
          <li key={watch.slug}>
            <button
              type="button"
              onClick={() => onOpen(watch)}
              className="grid w-full grid-cols-[1fr_auto] items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-frost"
            >
              <span className="min-w-0">
                <span className="block truncate text-[14px] text-ink">{watch.topic}</span>
                <span className="block text-[12px] text-slate">
                  Checked {when(watch.checked)} · {watch.checks}{" "}
                  {watch.checks === 1 ? "check" : "checks"}
                </span>
              </span>
              <span className="flex items-center gap-4 text-[12px] text-slate">
                <Count label="patents" value={watch.patents} fresh={watch.new.patents}
                  muted={watch.patents_state === "not_configured"} />
                <Count label="papers" value={watch.papers} fresh={watch.new.papers} />
                {watch.trials !== undefined && (
                  <Count label="trials" value={watch.trials} fresh={watch.new.trials ?? 0} />
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Count({
  label,
  value,
  fresh,
  muted = false,
}: {
  label: string;
  value: number;
  fresh: number;
  muted?: boolean;
}) {
  return (
    <span className="text-right">
      {muted ? (
        <>no key for {label}</>
      ) : (
        <>
          <span className="font-mono tabular-nums text-ink">{value}</span> {label}
        </>
      )}
      {fresh > 0 && <span className="ml-1.5 text-azure-deep">{fresh} new</span>}
    </span>
  );
}

// -- one check ---------------------------------------------------------------

function Result({ check, busy, onAgain }: { check: Check; busy: boolean; onAgain: () => void }) {
  const [onlyNew, setOnlyNew] = useState(false);
  const trials = check.new.trials ?? 0;
  const fresh = check.new.papers + check.new.patents + trials;
  const plural = (n: number, one: string, many: string) => `${n} new ${n === 1 ? one : many}`;
  const parts = [
    check.new.patents && plural(check.new.patents, "patent family", "patent families"),
    check.new.papers && plural(check.new.papers, "paper", "papers"),
    trials && plural(trials, "trial", "trials"),
  ].filter(Boolean) as string[];

  return (
    <div className="mt-7 space-y-5">
      <header>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em] text-ink">{check.topic}</h1>
        <p className="mt-1 text-[13px] text-slate">
          Published {check.window.from} to {check.window.to} · checked {when(check.at)}
          {check.checks > 1 && ` · check ${check.checks}`}
        </p>
        <p className="mt-2 text-[14px] text-ink">
          {check.first_check
            ? "First check. New items are marked from the next check."
            : fresh
              ? `${parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0]} since ${when(check.previous)}.`
              : `Nothing new since ${when(check.previous)}.`}
        </p>
        {check.search_changed && (
          <p className="mt-1 text-[12px] text-slate">
            Terms or window changed since the last check. Some items marked new are older work in the wider search.
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] text-slate">Searched</span>
          {check.terms.map((term) => (
            <span
              key={term.text}
              title={term.origin}
              className={`rounded-full border px-2.5 py-0.5 text-[12px] ${
                term.origin === "typed"
                  ? "border-line bg-surface text-ink"
                  : "border-dashed border-line bg-frost text-slate"
              }`}
            >
              {term.text}
            </span>
          ))}
          <span className="ml-auto flex items-center gap-3">
            {!check.first_check && fresh > 0 && (
              <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-slate">
                <input
                  type="checkbox"
                  checked={onlyNew}
                  onChange={(e) => setOnlyNew(e.target.checked)}
                  className="accent-[var(--color-azure-deep)]"
                />
                Only new
              </label>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={onAgain}
              className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-ink transition-colors hover:border-azure hover:text-azure-deep disabled:opacity-60"
            >
              <RefreshCw size={14} className={busy ? "animate-spin" : ""} aria-hidden="true" />
              Check again
            </button>
          </span>
        </div>
      </header>

      <Panel
        title="Patents"
        unit="families"
        block={check.patents}
        timeline={
          <Timeline
            dates={check.patents.items.map((family) => family.first || family.date)}
            window={check.window}
            noun="families"
            caption={`Patent families by first publication inside the window, ${check.patents.fetched} fetched`}
          />
        }
        facets={[
          {
            title: "Applicants",
            rows: check.patents.facets.applicant.map(([name, count]) => ({ name, count })),
          },
          {
            title: "CPC groups",
            rows: check.patents.facets.cpc.map(([code, count, label]) => ({
              name: label ? `${label}` : code,
              code,
              count,
            })),
          },
        ]}
      >
        {visible(check.patents.items, onlyNew).map((family) => (
          <Patent key={family.id} family={family} />
        ))}
      </Panel>

      <Panel
        title="Papers and preprints"
        unit="articles"
        block={check.papers}
        timeline={
          <Timeline
            dates={check.papers.items.map((paper) => paper.date)}
            window={check.window}
            noun="articles"
            caption={`Papers and preprints by first publication, ${check.papers.fetched} fetched`}
          />
        }
        facets={[
          {
            title: "Publication types",
            rows: check.papers.facets.kind.map(([name, count]) => ({ name, count })),
          },
          {
            title: "Venues",
            rows: check.papers.facets.venue.map(([name, count]) => ({ name, count })),
          },
        ]}
      >
        {visible(check.papers.items, onlyNew).map((paper) => (
          <Article key={paper.id} paper={paper} />
        ))}
      </Panel>

      {check.trials && (
        <Panel
          title="Clinical trials"
          unit="trials"
          block={check.trials}
          timeline={
            <Timeline
              dates={check.trials.items.map((trial) => trial.date)}
              window={check.window}
              noun="trials"
              caption={`Trials registered or updated inside the window, ${check.trials.fetched} fetched. ${check.trials.credit}; it may not reflect the latest data.`}
            />
          }
          facets={[
            { title: "Phase", rows: check.trials.facets.phase.map(([name, count]) => ({ name, count })) },
            { title: "Status", rows: check.trials.facets.status.map(([name, count]) => ({ name, count })) },
            { title: "Sponsor", rows: check.trials.facets.sponsor.map(([name, count]) => ({ name, count })) },
          ]}
        >
          {visible(check.trials.items, onlyNew).map((trial) => (
            <TrialRow key={trial.id} trial={trial} />
          ))}
        </Panel>
      )}
    </div>
  );
}

function visible<T extends { new: boolean }>(items: T[], onlyNew: boolean): T[] {
  return onlyNew ? items.filter((item) => item.new) : items;
}

type Facet = { title: string; rows: { name: string; count: number; code?: string }[] };

function Panel({
  title,
  unit,
  block,
  facets,
  timeline,
  children,
}: {
  title: string;
  unit: string;
  block: Check["papers"] | Check["patents"] | NonNullable<Check["trials"]>;
  facets: Facet[];
  timeline: React.ReactNode;
  children: React.ReactNode[];
}) {
  const [all, setAll] = useState(false);
  const rows = all ? children : children.slice(0, SHOWN);
  const hiddenHere = children.length - rows.length;
  const unfetched = block.total - block.fetched;

  return (
    <section className="rounded-[14px] border border-line bg-surface">
      <h2 className="flex items-baseline gap-2 border-b border-line px-5 py-3">
        <span className="text-[15px] font-semibold text-ink">{title}</span>
        {block.state === "ok" && (
          <span className="text-[12px] text-slate">
            <span className="font-mono tabular-nums text-ink">{block.total}</span>{" "}
            {block.total === 1 ? unit.replace(/s$/, "").replace(/ie$/, "y") : unit} · {block.label}
          </span>
        )}
        {block.search_url && (
          <a
            href={block.search_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto flex items-center gap-1 text-[12px] text-azure-deep hover:underline"
          >
            Same search at the source
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </h2>

      {block.state !== "ok" ? (
        <p className="px-5 py-4 text-[13px] text-slate">
          <span className="text-ink">
            {block.state === "not_configured"
              ? "Not configured. "
              : block.state === "offline"
                ? "Not checked: online access off. "
                : "Could not be checked. "}
          </span>
          {block.reason}
        </p>
      ) : block.total === 0 ? (
        <p className="px-5 py-4 text-[13px] text-slate">
          No {unit} in this window ({block.label} searched).
        </p>
      ) : (
        <>
          <div className="border-b border-line px-5 pb-4 pt-5">{timeline}</div>
          <div className="grid gap-x-8 gap-y-4 border-b border-line px-5 py-4 md:grid-cols-2">
            {facets.map((facet) => (
              <FacetBars key={facet.title} facet={facet} />
            ))}
          </div>
          <ul className="divide-y divide-line">{rows}</ul>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-[12px]">
            {hiddenHere > 0 && (
              <button type="button" onClick={() => setAll(true)} className="text-azure-deep hover:underline">
                Show all {children.length}
              </button>
            )}
            {all && children.length > SHOWN && (
              <button type="button" onClick={() => setAll(false)} className="text-azure-deep hover:underline">
                Show the newest {SHOWN}
              </button>
            )}
            {unfetched > 0 && (
              <span className="text-slate">
                {unfetched} more matches not fetched in one check. Narrower terms or window fetch them; the source search lists all.
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function FacetBars({ facet }: { facet: Facet }) {
  const [all, setAll] = useState(false);
  if (!facet.rows.length) return null;
  const peak = facet.rows[0].count;
  const shown = all ? facet.rows : facet.rows.slice(0, 6);
  return (
    <figure className="m-0 min-w-0">
      <figcaption className="mb-2 text-[12px] text-slate">{facet.title}</figcaption>
      <ul className="space-y-[5px]">
        {shown.map((row) => (
          <li key={row.code ?? row.name} className="grid grid-cols-[minmax(0,1fr)_88px_32px] items-center gap-2.5">
            <span className="truncate text-[12px] text-ink" title={row.code ? `${row.code} ${row.name}` : row.name}>
              {row.code && row.name !== row.code && (
                <span className="mr-1.5 font-mono text-slate">{row.code}</span>
              )}
              {row.name}
            </span>
            <span className="block h-[8px] rounded-full bg-mist">
              <span
                className="block h-full rounded-r-[4px] bg-azure"
                style={{ width: `${Math.max(4, (row.count / peak) * 100)}%` }}
              />
            </span>
            <span className="text-right font-mono text-[12px] tabular-nums text-ink">{row.count}</span>
          </li>
        ))}
      </ul>
      {facet.rows.length > 6 && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mt-1.5 text-[12px] text-azure-deep hover:underline"
        >
          {all ? "Show fewer" : `Show all ${facet.rows.length}`}
        </button>
      )}
    </figure>
  );
}

function Patent({ family }: { family: PatentFamily }) {
  return (
    <li className="grid grid-cols-[86px_1fr] gap-4 px-5 py-3">
      <span className="pt-0.5 font-mono text-[12px] tabular-nums text-slate">
        {family.date}
        {family.new && <New />}
      </span>
      <span className="min-w-0">
        <a
          href={family.link}
          target="_blank"
          rel="noreferrer"
          className="text-[14px] leading-snug text-ink hover:text-azure-deep hover:underline"
        >
          {family.title || "Untitled"}
        </a>
        <span className="mt-0.5 block text-[12px] text-slate">
          {family.applicants.join("; ") || "Applicant not given"}
        </span>
        <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate">
          {family.publications.map((pub) => (
            <span key={pub.number} title={pub.date} className="text-ink">
              {pub.number}
            </span>
          ))}
          {family.cpc.length > 0 && (
            <span title={family.cpc.join(", ")}>
              {family.cpc.slice(0, 3).join(" ")}
              {family.cpc.length > 3 && ` +${family.cpc.length - 3}`}
            </span>
          )}
        </span>
      </span>
    </li>
  );
}

function TrialRow({ trial }: { trial: Trial }) {
  return (
    <li className="grid grid-cols-[86px_1fr] gap-4 px-5 py-3">
      <span className="pt-0.5 font-mono text-[12px] tabular-nums text-slate">
        {trial.date}
        {trial.new && <New />}
      </span>
      <span className="min-w-0">
        <a
          href={trial.url}
          target="_blank"
          rel="noreferrer"
          className="text-[14px] leading-snug text-ink hover:text-azure-deep hover:underline"
        >
          {trial.title}
        </a>
        <span className="mt-0.5 block text-[12px] text-slate">
          <span className="mr-2 font-mono text-[11px]">{trial.nct}</span>
          <span className="mr-1.5 rounded-[5px] bg-mist px-1.5 py-0.5 text-[10px] text-azure-deep">{trial.phase}</span>
          {trial.status}, {trial.sponsor}
        </span>
        {trial.interventions.length > 0 && (
          <span className="mt-0.5 block truncate text-[12px] text-slate" title={trial.interventions.join(", ")}>
            {trial.interventions.join(", ")}
          </span>
        )}
      </span>
    </li>
  );
}

function Article({ paper }: { paper: Paper }) {
  return (
    <li className="grid grid-cols-[86px_1fr] gap-4 px-5 py-3">
      <span className="pt-0.5 font-mono text-[12px] tabular-nums text-slate">
        {paper.date}
        {paper.new && <New />}
      </span>
      <span className="min-w-0">
        <a
          href={paper.link}
          target="_blank"
          rel="noreferrer"
          className="text-[14px] leading-snug text-ink hover:text-azure-deep hover:underline"
        >
          {paper.title}
        </a>
        <span className="mt-0.5 block truncate text-[12px] text-slate" title={paper.authors}>
          {paper.authors}
        </span>
        <span className="mt-0.5 block text-[12px] text-slate">
          {paper.kind === "preprint" && (
            <span className="mr-1.5 rounded-[5px] bg-mist px-1.5 py-0.5 text-[10px] text-azure-deep">
              preprint
            </span>
          )}
          {paper.venue}
          {paper.pmid && <span className="ml-2 font-mono text-[11px]">PMID {paper.pmid}</span>}
        </span>
      </span>
    </li>
  );
}

function New() {
  return <span className="mt-1 block font-sans text-[11px] font-semibold text-azure-deep">New</span>;
}

// -- patent credentials ------------------------------------------------------

function PatentKey({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const result = await configurePatents(key, secret);
      if (!result.ok) setProblem(result.error ?? "Rejected by EPO.");
      else {
        setKey("");
        setSecret("");
        onSaved();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-5 rounded-[12px] border border-line bg-frost px-4 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <KeyRound size={15} className="text-azure-deep" aria-hidden="true" />
        <span className="text-ink">Patents: EPO Open Patent Services key required.</span>
        <span className="text-slate">Free registration on the EPO developer portal.</span>
        {!open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="ml-auto text-azure-deep hover:underline"
          >
            Add key
          </button>
        )}
      </div>
      {open && (
        <form onSubmit={save} className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-slate">Consumer key</span>
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-label="EPO consumer key"
            className="h-9 min-w-[220px] flex-1 rounded-[8px] border border-line bg-surface px-3 font-mono text-[12px] text-ink outline-none focus:border-azure"
          />
          <span className="text-[12px] text-slate">Consumer secret</span>
          <input
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            type="password"
            autoComplete="off"
            aria-label="EPO consumer secret"
            className="h-9 min-w-[220px] flex-1 rounded-[8px] border border-line bg-surface px-3 font-mono text-[12px] text-ink outline-none focus:border-azure"
          />
          <button
            type="submit"
            disabled={busy || !key || !secret}
            className="flex h-9 items-center gap-1.5 rounded-full bg-azure-deep px-4 text-[13px] font-semibold text-on-accent disabled:opacity-60"
          >
            {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Test and save
          </button>
          {problem && <p role="alert" className="w-full text-[12px] text-error">{problem}</p>}
          <p className="w-full text-[11px] text-slate">
            Stored in the local settings file. Sent to ops.epo.org only. Tested once before saving.
          </p>
        </form>
      )}
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-5 flex items-start gap-2 rounded-[10px] bg-warn-bg px-3.5 py-2.5 text-[13px] text-warn-ink">
      <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      {children}
    </p>
  );
}

/** "2026-10-25T11:44:15" -> "25 Oct 2026, 11:44". Never a relative date:
 *  a printed watch must still say when it was checked. */
function when(stamp: string): string {
  if (!stamp) return "never";
  const parsed = new Date(stamp);
  if (Number.isNaN(parsed.getTime())) return stamp;
  const day = parsed.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return stamp.includes("T")
    ? `${day}, ${parsed.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
    : day;
}
