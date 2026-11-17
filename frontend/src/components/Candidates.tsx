import { useEffect, useState } from "react";
import { AlertTriangle, FolderOpen, ListChecks, Loader2, Trash2 } from "lucide-react";
import {
  candidatesCriteria,
  deleteList,
  mapList,
  openList,
  readListFile,
  saveList,
  savedLists,
  type CriteriaInfo,
  type ListSummary,
  type Mapping,
  type MapStatus,
  type SavedList,
} from "../candidates";
import { RankedView } from "./RankedView";

// Candidates: a gene list in, a ranked table out. The screen maps the list
// to genes first. It ranks nothing until the user sees how each entry
// matched and settles the problem entries: an alias, a renamed symbol, a
// name that several genes share, a typo.

type Stage =
  | { kind: "home" }
  | { kind: "review"; name: string; mapping: Mapping }
  | { kind: "ranked"; list: SavedList; slug: string };

export function Candidates({ onOpenReport }: { onOpenReport: (symbol: string) => void }) {
  const [stage, setStage] = useState<Stage>({ kind: "home" });
  const [info, setInfo] = useState<CriteriaInfo | null>(null);

  useEffect(() => {
    candidatesCriteria().then(setInfo).catch(() => undefined);
  }, []);

  return (
    <div className="mx-auto w-full max-w-[1180px] px-8 py-10">
      {stage.kind === "home" && (
        <Home
          onMapped={(name, mapping) => setStage({ kind: "review", name, mapping })}
          onOpen={(slug, list) => setStage({ kind: "ranked", slug, list })}
        />
      )}
      {stage.kind === "review" && (
        <Review
          name={stage.name}
          mapping={stage.mapping}
          info={info}
          onBack={() => setStage({ kind: "home" })}
          onSaved={(slug, list) => setStage({ kind: "ranked", slug, list })}
        />
      )}
      {stage.kind === "ranked" && info && (
        <RankedView
          key={stage.slug}
          slug={stage.slug}
          list={stage.list}
          info={info}
          onBack={() => setStage({ kind: "home" })}
          onOpenReport={onOpenReport}
        />
      )}
    </div>
  );
}

function Home({
  onMapped,
  onOpen,
}: {
  onMapped: (name: string, mapping: Mapping) => void;
  onOpen: (slug: string, list: SavedList) => void;
}) {
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [lists, setLists] = useState<ListSummary[]>([]);

  const refresh = () => savedLists().then((found) => setLists(found.lists)).catch(() => undefined);
  useEffect(() => {
    refresh();
  }, []);

  const map = async () => {
    setBusy(true);
    setProblem("");
    try {
      const mapping = await mapList(text);
      if (mapping.error) setProblem(mapping.error);
      else onMapped(name.trim() || "Untitled list", mapping);
    } catch (error) {
      setProblem(String(error));
    } finally {
      setBusy(false);
    }
  };

  const open = async () => {
    const found = await readListFile().catch((error) => ({ error: String(error) }) as { error: string });
    if ("error" in found && found.error) setProblem(found.error);
    else if ("text" in found && found.text !== undefined) {
      setText(found.text);
      if (!name && found.name) setName(found.name);
    }
  };

  const entries = text.split(/[\s,;|]+/).filter(Boolean).length;

  return (
    <>
      <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Candidates</h1>
      <p className="mt-3 max-w-[66ch] text-[15px] leading-relaxed text-slate">
        Gene lists ranked on weighted criteria. Each entry is mapped to a gene; ranking starts after the
        mapping is confirmed.
      </p>

      <div className="mt-8 rounded-[16px] border border-line bg-surface p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[12px] font-medium text-slate">List name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-label="List name"
            className="h-10 min-w-[260px] flex-1 rounded-[10px] border border-line bg-frost px-3 text-[14px] text-ink outline-none placeholder:text-slate/70 focus:border-azure"
          />
          <button
            type="button"
            onClick={open}
            className="flex h-10 items-center gap-2 rounded-full border border-line px-4 text-[13px] text-ink hover:border-azure hover:text-azure-deep"
          >
            <FolderOpen size={15} aria-hidden="true" />
            Open file
          </button>
        </div>
        <p className="mt-3 text-[12px] font-medium text-slate">
          Genes: symbols, aliases, Ensembl, UniProt or Entrez IDs; one per line or comma-separated
        </p>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={9}
          spellCheck={false}
          aria-label="Genes"
          className="mt-1.5 w-full resize-y rounded-[10px] border border-line bg-frost p-3 font-mono text-[13px] leading-relaxed text-ink outline-none placeholder:font-sans placeholder:text-slate/70 focus:border-azure"
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={map}
            disabled={busy || !text.trim()}
            className="flex h-10 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-60"
          >
            {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <ListChecks size={16} aria-hidden="true" />}
            Review mappings
          </button>
          <span className="text-[12px] text-slate">
            {entries ? `${entries.toLocaleString("en-US")} entries` : "Spica reads .txt, .csv, .tsv and .xlsx"}
          </span>
        </div>
        {problem && (
          <p role="alert" className="mt-3 text-[13px] text-error">
            {problem}
          </p>
        )}
      </div>

      <h2 className="mt-10 text-[15px] font-semibold text-ink">Saved lists</h2>
      {lists.length === 0 ? (
        <p className="mt-2 text-[13px] text-slate">No saved list. A list is saved when its mapping is confirmed.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line rounded-[14px] border border-line bg-surface">
          {lists.map((item) => (
            <li key={item.slug} className="flex items-center gap-4 px-5 py-3 text-[13px]">
              <button
                type="button"
                onClick={async () => {
                  const list = await openList(item.slug);
                  if (!list.error) onOpen(item.slug, list);
                }}
                className="min-w-0 flex-1 truncate text-left font-semibold text-ink hover:text-azure-deep"
              >
                {item.name}
              </button>
              <span className="font-mono text-slate">{item.genes} genes</span>
              <span className="text-slate">{item.updated}</span>
              <button
                type="button"
                aria-label={`Delete ${item.name}`}
                title="Delete the list"
                onClick={async () => {
                  if (window.confirm(`Delete the list "${item.name}"?`)) {
                    await deleteList(item.slug);
                    refresh();
                  }
                }}
                className="text-slate hover:text-error"
              >
                <Trash2 size={15} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const STATUS: Record<MapStatus, { label: string; tone: string }> = {
  exact: { label: "exact", tone: "text-slate" },
  alias: { label: "alias", tone: "bg-mist text-azure-deep" },
  renamed: { label: "renamed", tone: "bg-mist text-azure-deep" },
  ambiguous: { label: "ambiguous", tone: "bg-warn-bg text-warn-ink" },
  not_found: { label: "not found", tone: "bg-warn-bg text-warn-ink" },
  duplicate: { label: "duplicate", tone: "text-slate" },
};

function Review({
  name,
  mapping,
  info,
  onBack,
  onSaved,
}: {
  name: string;
  mapping: Mapping;
  info: CriteriaInfo | null;
  onBack: () => void;
  onSaved: (slug: string, list: SavedList) => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [listName, setListName] = useState(name);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [only, setOnly] = useState<"all" | "review">(mapping.needs_review ? "review" : "all");

  const open = mapping.rows.filter(
    (row) =>
      (row.status === "ambiguous" && !choices[row.position]) ||
      (row.status === "not_found" && choices[row.position] !== "drop"),
  );
  const shown = only === "review" ? mapping.rows.filter((row) => row.status !== "exact") : mapping.rows;
  const kept = new Set(
    mapping.rows
      .filter((row) => choices[row.position] !== "drop")
      .map((row) => (row.status === "ambiguous" ? choices[row.position] : row.hgnc_id))
      .filter(Boolean),
  ).size;

  const confirm = async () => {
    setBusy(true);
    setProblem("");
    const preset = "antibody";
    const weights = info?.presets[preset]?.weights ?? {};
    // A not-found row is dropped by confirming: say so by recording it.
    const settled = { ...choices };
    for (const row of mapping.rows) if (row.status === "not_found") settled[row.position] = "drop";
    try {
      const saved = await saveList(listName, mapping.entries, mapping, settled, weights, preset, "");
      if (saved.error || !saved.slug) {
        setProblem(saved.error ?? "List not saved.");
        return;
      }
      const list = await openList(saved.slug);
      if (list.error) setProblem(list.error);
      else onSaved(saved.slug, list);
    } finally {
      setBusy(false);
    }
  };

  const counts = mapping.counts;
  return (
    <>
      <button type="button" onClick={onBack} className="text-[13px] text-slate hover:text-azure-deep">
        List
      </button>
      <h1 className="mt-3 text-[28px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Mapping review</h1>
      <p className="mt-2 max-w-[70ch] text-[14px] leading-relaxed text-slate">
        {mapping.entries.length} entries, {mapping.genes} genes found.{" "}
        {open.length > 0
          ? `${open.length} ${open.length === 1 ? "entry" : "entries"} to review: select a gene or drop the entry.`
          : "All entries settled. Aliases and renamed symbols are marked."}
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2 text-[12px]">
        {(Object.keys(STATUS) as MapStatus[])
          .filter((status) => counts[status])
          .map((status) => (
            <span key={status} className={`rounded-full px-2.5 py-0.5 ${STATUS[status].tone}`}>
              {counts[status]} {STATUS[status].label}
            </span>
          ))}
        <span className="mx-2 h-4 w-px bg-line" />
        {(["review", "all"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={only === value}
            onClick={() => setOnly(value)}
            className={`rounded-full px-2.5 py-0.5 ${only === value ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"}`}
          >
            {value === "review" ? "not exact" : "all"}
          </button>
        ))}
      </div>

      <div className="mt-3 overflow-hidden rounded-[14px] border border-line bg-surface">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-[11px] text-slate">
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-4 py-2 font-medium">Entry</th>
              <th className="px-4 py-2 font-medium">Match</th>
              <th className="px-4 py-2 font-medium">Gene</th>
              <th className="px-4 py-2 font-medium">Note</th>
              <th className="px-4 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => {
              const dropped = choices[row.position] === "drop";
              return (
                <tr key={row.position} className={`border-b border-line last:border-0 ${dropped ? "opacity-50" : ""}`}>
                  <td className="px-4 py-2 font-mono text-slate">{row.position + 1}</td>
                  <td className="px-4 py-2 font-mono text-ink">{row.input}</td>
                  <td className="px-4 py-2">
                    <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] ${STATUS[row.status].tone}`}>
                      {STATUS[row.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    {row.status === "ambiguous" ? (
                      <select
                        value={choices[row.position] ?? ""}
                        onChange={(event) => setChoices({ ...choices, [row.position]: event.target.value })}
                        aria-label={`Gene for ${row.input}`}
                        className="rounded-[8px] border border-line bg-frost px-2 py-1 text-[12px] text-ink"
                      >
                        <option value="">Gene</option>
                        {row.candidates.map((candidate) => (
                          <option key={candidate.hgnc_id} value={candidate.hgnc_id}>
                            {candidate.symbol}
                            {candidate.name ? `: ${candidate.name}` : ""}
                          </option>
                        ))}
                        <option value="drop">Drop entry</option>
                      </select>
                    ) : row.symbol ? (
                      <span>
                        <span className="font-mono text-ink">{row.symbol}</span>
                        {row.name && <span className="ml-2 text-[12px] text-slate">{row.name}</span>}
                      </span>
                    ) : (
                      <span className="text-[12px] text-slate">no gene</span>
                    )}
                  </td>
                  <td className="max-w-[340px] px-4 py-2 text-[12px] text-slate">{row.note}</td>
                  <td className="px-4 py-2 text-right">
                    {row.status !== "ambiguous" && row.status !== "not_found" && row.status !== "duplicate" && (
                      <button
                        type="button"
                        onClick={() => setChoices({ ...choices, [row.position]: dropped ? "" : "drop" })}
                        className="text-[12px] text-azure-deep hover:underline"
                      >
                        {dropped ? "Keep" : "Drop"}
                      </button>
                    )}
                    {row.status === "not_found" && <span className="text-[12px] text-slate">dropped on confirm</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <input
          value={listName}
          onChange={(event) => setListName(event.target.value)}
          aria-label="List name"
          className="h-10 min-w-[260px] rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-azure"
        />
        <button
          type="button"
          onClick={confirm}
          disabled={busy || mapping.rows.some((row) => row.status === "ambiguous" && !choices[row.position])}
          className="flex h-10 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-60"
        >
          {busy && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
          Confirm {kept} genes, rank
        </button>
        {mapping.rows.some((row) => row.status === "ambiguous" && !choices[row.position]) && (
          <span className="flex items-center gap-1.5 text-[12px] text-warn-ink">
            <AlertTriangle size={14} aria-hidden="true" />
            Ambiguous entries remain.
          </span>
        )}
      </div>
      {problem && (
        <p role="alert" className="mt-3 text-[13px] text-error">
          {problem}
        </p>
      )}
    </>
  );
}
