import { useEffect, useRef, useState } from "react";
import { geoSeries, geoTrackId, sampleTracks, type GeoSeries } from "../geo";
import igv from "igv";
import { Loader2, Plus, X } from "lucide-react";
import { AtlasHeatmap } from "./AtlasHeatmap";
import {
  fetchTrack,
  findEncode,
  findRegulators,
  openLocus,
  tissueLabel,
  type Experiment,
  type ExperimentList,
  type LocusResult,
  type TrackResult,
  type TrackSpec,
} from "../genome";

// The gene locus in igv.js, with all tracks that Spica can put on it.
//
// Adapted from the IGV reports of the MultiOmics integrator, with no network
// access in the interface. Python fetches each track for the gene window and
// gives igv.js plain features. igv.js does not load its genome list or its
// search service. The reference is the sequence of the window, and the CSP
// of the page blocks any other request.
//
// Colours follow the art direction: azure for data, orange only as a second
// pole (pathogenic variants, cleavage-validated miRNA sites, conserved
// bases), slate and ink for the rest. Red and green are never a pair, also
// not for the bases.

type Igv = typeof igv;
type Browser = Awaited<ReturnType<Igv["createBrowser"]>>;
type Handle = Awaited<ReturnType<Browser["loadTrack"]>>;

type Loaded = {
  state: "loading" | "ok" | "failed" | "offline";
  count?: number;
  reason?: string;
  handle?: Handle;
  name?: string;
};

const BASES = { A: "#0077CC", C: "#F97316", G: "#0B1B2B", T: "#5B6B7C", N: "#9AA8B6" };
const GROUP_ORDER = ["Genes", "Regulation", "TF binding", "miRNA", "Variants", "Conservation", "By tissue"];

export function GenomeView({
  symbol,
  ensemblId,
  topTissue,
  request,
  selected,
}: {
  symbol: string;
  ensemblId: string;
  topTissue: string;
  /** Tracks another panel asked for; a new nonce asks again. */
  request?: { ids: string[]; nonce: number } | null;
  /** Tracks another panel keeps chosen (a GEO series' ticked samples): what
   * joins the list is drawn, what leaves it is taken off. Tracks turned on
   * here by hand are left alone. */
  selected?: string[];
}) {
  const host = useRef<HTMLDivElement>(null);
  const browser = useRef<Browser | null>(null);
  const [info, setInfo] = useState<LocusResult | null>(null);
  const [problem, setProblem] = useState("");
  const [tracks, setTracks] = useState<Record<string, Loaded>>({});
  const loadedRef = useRef<Record<string, Loaded>>({});

  const update = (id: string, value: Loaded | null) => {
    const next = { ...loadedRef.current };
    if (value) next[id] = value;
    else delete next[id];
    loadedRef.current = next;
    setTracks(next);
  };

  async function add(id: string) {
    if (!browser.current || loadedRef.current[id]?.state === "loading") return;
    update(id, { state: "loading" });
    let result: TrackResult;
    try {
      result = await fetchTrack(symbol, ensemblId, id);
    } catch (error) {
      update(id, { state: "failed", reason: error instanceof Error ? error.message : "no answer" });
      return;
    }
    if (result.state !== "ok" || !result.config || !browser.current) {
      update(id, { state: result.state === "offline" ? "offline" : "failed", reason: result.reason });
      return;
    }
    // A track the user turned off while it loaded stays off.
    if (!loadedRef.current[id]) return;
    const handle = await browser.current.loadTrack({
      ...result.config,
      features: result.features ?? [],
    } as never);
    update(id, { state: "ok", count: result.count, handle, name: result.config.name });
  }

  function remove(id: string) {
    const entry = loadedRef.current[id];
    if (entry?.handle && browser.current) browser.current.removeTrack(entry.handle as never);
    update(id, null);
  }

  const toggle = (id: string) => (loadedRef.current[id] ? remove(id) : add(id));

  // Asked for before igv.js is up: kept, and loaded once the browser exists.
  const asked = useRef<string[]>([]);
  useEffect(() => {
    if (!request) return;
    host.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    if (!browser.current) {
      asked.current = request.ids;
      return;
    }
    for (const id of request.ids) if (!loadedRef.current[id]) add(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.nonce]);

  const followed = useRef<string[]>([]);
  const selectedRef = useRef<string[]>([]);
  selectedRef.current = selected ?? [];
  const selectedKey = (selected ?? []).join("\n");
  useEffect(() => {
    if (!selected || !browser.current) return; // picked up when the browser exists
    const before = new Set(followed.current);
    const now = new Set(selected);
    for (const id of selected) if (!before.has(id) && !loadedRef.current[id]) add(id);
    for (const id of followed.current) if (!now.has(id) && loadedRef.current[id]) remove(id);
    followed.current = [...selected];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);

  useEffect(() => {
    let alive = true;
    (async () => {
      let result: LocusResult;
      try {
        result = await openLocus(symbol, ensemblId, topTissue);
      } catch (error) {
        setProblem(error instanceof Error ? error.message : "No backend response.");
        return;
      }
      if (!alive) return;
      if (result.error) {
        setProblem(result.error);
        return;
      }
      setInfo(result);
      if (!host.current) return;
      const fasta = `data:text/plain;base64,${btoa(result.reference.fasta)}`;
      const config = {
        reference: { id: result.reference.id, name: result.reference.name, fastaURL: fasta, indexed: false },
        locus: result.locus.view,
        tracks: [],
        // Both of these would reach igv.org: the genome list on start, the
        // search service when a name is typed in the locus box.
        loadDefaultGenomes: false,
        search: false,
        nucleotideColors: BASES,
        showSampleNames: false,
        // A window slice has no cytobands, so the ideogram would be an
        // empty bar with a red marker: nothing to read, and off-palette.
        showIdeogram: false,
      };
      const created = await igv.createBrowser(host.current, config as never);
      if (!alive) {
        igv.removeBrowser(created);
        return;
      }
      browser.current = created;
      // The igv.js menus can remove a track; keep the panel in step.
      // igv.js applies its event arguments, so the handler recieves the
      // removed track itself, not a list as its type file says.
      created.on("trackremoved", ((...args: unknown[]) => {
        const removed = (Array.isArray(args[0]) ? args[0] : args) as { name?: string }[];
        for (const track of removed) {
          const id = Object.keys(loadedRef.current).find((key) => loadedRef.current[key].name === track?.name);
          if (id) update(id, null);
        }
      }) as never);
      // Defaults in catalog order: fetched together, drawn in order.
      const defaults = result.catalog.filter((track) => track.default).map((track) => track.id);
      for (const id of defaults) update(id, { state: "loading" });
      const pending = defaults.map((id) => fetchTrack(symbol, ensemblId, id).catch(() => null));
      for (let i = 0; i < defaults.length; i++) {
        const fetched = await pending[i];
        if (!alive || !browser.current) return;
        const id = defaults[i];
        if (!fetched || fetched.state !== "ok" || !fetched.config) {
          update(id, { state: fetched?.state === "offline" ? "offline" : "failed", reason: fetched?.reason ?? "no answer" });
          continue;
        }
        const handle = await browser.current.loadTrack({ ...fetched.config, features: fetched.features ?? [] } as never);
        update(id, { state: "ok", count: fetched.count, handle, name: fetched.config.name });
      }
      for (const id of asked.current) if (!loadedRef.current[id]) add(id);
      asked.current = [];
      for (const id of selectedRef.current) if (!loadedRef.current[id]) add(id);
      followed.current = [...selectedRef.current];
    })();
    return () => {
      alive = false;
      if (browser.current) igv.removeBrowser(browser.current);
      browser.current = null;
    };
    // The view belongs to one gene; a new gene remounts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, ensemblId]);

  if (problem) {
    return <p className="px-5 py-4 text-[13px] text-slate">Genome view not opened: {problem}</p>;
  }

  const groups = info
    ? GROUP_ORDER.map((group) => ({ group, items: info.catalog.filter((t) => t.group === group) }))
    : [];

  return (
    // igv.js draws a light canvas of its own, so the genome view stays light
    // in the dark theme rather than half-following it.
    <div data-theme="light" className="border-t border-line bg-surface text-ink">
      {info && (
        <p className="px-5 pt-4 text-[12px] text-slate">
          <span className="font-mono text-ink">
            {info.locus.chrom}:{(info.locus.window.start + 1).toLocaleString("en-US")}-
            {info.locus.window.end.toLocaleString("en-US")}
          </span>{" "}
          ({info.locus.assembly}, {symbol} ±50 kb). Reference sequence: {info.reference.source}.
          {!info.online && " Network use off: cached tracks only."}
        </p>
      )}
      <div ref={host} className="px-3 pb-2 pt-3" />
      {!info && (
        <p className="flex items-center gap-2 px-5 pb-4 text-[13px] text-slate">
          <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Reading the {symbol} locus
        </p>
      )}
      {info && (
        <div className="grid gap-x-8 gap-y-5 border-t border-line px-5 py-5 md:grid-cols-2 xl:grid-cols-3">
          {groups.map(({ group, items }) =>
            items.length ? (
              <section key={group}>
                <h3 className="mb-2 text-[12px] font-semibold text-ink">{group}</h3>
                <ul className="space-y-2.5">
                  {items.map((track) =>
                    track.tissues.length ? (
                      <TissueFamily key={track.id} track={track} start={info.hint[track.id as keyof LocusResult["hint"]] ?? ""}
                        labels={track.id === "gtex_coverage" ? info.labels : {}}
                        tracks={tracks} onAdd={add} onRemove={remove} />
                    ) : (
                      <TrackRow key={track.id} id={track.id} label={track.label} source={track.source}
                        licence={track.licence} verified={track.verified} description={track.description}
                        loaded={tracks[track.id]} onToggle={toggle} />
                    ),
                  )}
                </ul>
              </section>
            ) : null,
          )}
          <EncodeFinder info={info} symbol={symbol} ensemblId={ensemblId} tracks={tracks} onToggle={toggle} />
          <Regulators symbol={symbol} ensemblId={ensemblId} tracks={tracks} onToggle={toggle} />
          <GeoTracks tracks={tracks} onToggle={toggle} />
        </div>
      )}
      {info && <AtlasHeatmap symbol={symbol} ensemblId={ensemblId} />}
    </div>
  );
}

function Status({ loaded }: { loaded?: Loaded }) {
  if (!loaded) return null;
  if (loaded.state === "loading")
    return <Loader2 size={13} className="shrink-0 animate-spin text-slate" aria-label="loading" />;
  if (loaded.state === "ok")
    return (
      <span className="shrink-0 font-mono text-[11px] tabular-nums text-slate">
        {(loaded.count ?? 0).toLocaleString("en-US")}
      </span>
    );
  return <span className="shrink-0 text-[11px] text-error">{loaded.state === "offline" ? "offline" : "failed"}</span>;
}

function TrackRow({
  id,
  label,
  source,
  licence,
  verified,
  description,
  loaded,
  onToggle,
}: {
  id: string;
  label: string;
  source: string;
  licence: string;
  verified: boolean;
  description?: string;
  loaded?: Loaded;
  onToggle: (id: string) => void;
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-2">
        <input
          type="checkbox"
          checked={Boolean(loaded)}
          onChange={() => onToggle(id)}
          className="mt-[3px] accent-[var(--color-azure-deep)]"
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-[13px] leading-snug text-ink" title={description}>{label}</span>
            <Status loaded={loaded} />
          </span>
          <span className="block text-[11px] leading-snug text-slate" title={licence}>
            {source}
            {!verified && (
              <span className="ml-1.5 rounded-[5px] bg-mist px-1.5 py-px text-[10px] text-azure-deep">
                terms unverified
              </span>
            )}
          </span>
          {loaded?.reason && loaded.state !== "ok" && (
            <span className="block text-[11px] text-error">{loaded.reason}</span>
          )}
        </span>
      </label>
    </li>
  );
}

function TissueFamily({
  track,
  start,
  labels,
  tracks,
  onAdd,
  onRemove,
}: {
  track: TrackSpec;
  start: string;
  labels: Record<string, string>;
  tracks: Record<string, Loaded>;
  onAdd: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const [tissue, setTissue] = useState(start || track.tissues[0]);
  const added = Object.keys(tracks).filter((id) => id.startsWith(`${track.id}:`));
  return (
    <li>
      <span className="block text-[13px] leading-snug text-ink" title={track.description}>{track.label}</span>
      <span className="block text-[11px] text-slate" title={track.licence}>{track.source}</span>
      <span className="mt-1.5 flex items-center gap-1.5">
        <select
          value={tissue}
          onChange={(e) => setTissue(e.target.value)}
          aria-label={`Tissue for ${track.label}`}
          className="h-7 min-w-0 flex-1 rounded-[8px] border border-line bg-surface px-2 text-[12px] text-ink outline-none focus:border-azure"
        >
          {track.tissues.map((name) => (
            <option key={name} value={name}>
              {labels[name] ?? tissueLabel(name)}
              {name === start ? " (this gene's peak)" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => onAdd(`${track.id}:${tissue}`)}
          disabled={Boolean(tracks[`${track.id}:${tissue}`])}
          className="flex h-7 items-center gap-1 rounded-full border border-line bg-surface px-2.5 text-[12px] text-ink transition-colors hover:border-azure hover:text-azure-deep disabled:opacity-50"
        >
          <Plus size={12} aria-hidden="true" /> Add
        </button>
      </span>
      {added.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {added.map((id) => (
            <li key={id} className="flex items-center gap-2 text-[12px] text-ink">
              <span className="min-w-0 flex-1 truncate">{labels[id.split(":")[1]] ?? tissueLabel(id.split(":")[1])}</span>
              <Status loaded={tracks[id]} />
              <button type="button" onClick={() => onRemove(id)} aria-label={`Remove ${id}`}
                className="text-slate hover:text-azure-deep">
                <X size={13} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function ExperimentRows({
  items,
  tracks,
  onToggle,
  label,
}: {
  items: Experiment[];
  tracks: Record<string, Loaded>;
  onToggle: (id: string) => void;
  label: (item: Experiment) => string;
}) {
  // Every experiment found is listed; the list scrolls rather than stops.
  return (
    <ul className="mt-2 max-h-[260px] space-y-1.5 overflow-y-auto pr-1">
      {items.map((item) => (
        <li key={item.id}>
          <label className="flex cursor-pointer items-start gap-2">
            <input type="checkbox" checked={Boolean(tracks[item.id])} onChange={() => onToggle(item.id)}
              className="mt-[3px] accent-[var(--color-azure-deep)]" />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="text-[12px] leading-snug text-ink">{label(item)}</span>
                <Status loaded={tracks[item.id]} />
              </span>
              <span className="block font-mono text-[10px] text-slate">
                {item.file} · {item.output}
              </span>
              {tracks[item.id]?.reason && (
                <span className="block text-[11px] text-error">{tracks[item.id].reason}</span>
              )}
            </span>
          </label>
        </li>
      ))}
    </ul>
  );
}

function EncodeFinder({
  info,
  symbol,
  ensemblId,
  tracks,
  onToggle,
}: {
  info: LocusResult;
  symbol: string;
  ensemblId: string;
  tracks: Record<string, Loaded>;
  onToggle: (id: string) => void;
}) {
  const [organ, setOrgan] = useState(info.hint.encode && info.organs.includes(info.hint.encode) ? info.hint.encode : "liver");
  const [assay, setAssay] = useState("atac");
  const [adult, setAdult] = useState(true);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<ExperimentList | null>(null);

  async function search() {
    setBusy(true);
    try {
      setFound(await findEncode(symbol, ensemblId, organ, assay, adult));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h3 className="mb-2 text-[12px] font-semibold text-ink">ENCODE experiments</h3>
      <p className="mb-2 text-[11px] leading-snug text-slate">
        Released experiments, read for this window only.
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <select value={organ} onChange={(e) => setOrgan(e.target.value)} aria-label="Organ"
          className="h-7 rounded-[8px] border border-line bg-surface px-2 text-[12px] text-ink outline-none focus:border-azure">
          {info.organs.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <select value={assay} onChange={(e) => setAssay(e.target.value)} aria-label="Assay"
          className="h-7 rounded-[8px] border border-line bg-surface px-2 text-[12px] text-ink outline-none focus:border-azure">
          {Object.entries(info.assays).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <label className="flex items-center gap-1 text-[12px] text-slate">
          <input type="checkbox" checked={adult} onChange={(e) => setAdult(e.target.checked)}
            className="accent-[var(--color-azure-deep)]" />
          adult only
        </label>
        <button type="button" onClick={search} disabled={busy}
          className="flex h-7 items-center gap-1 rounded-full bg-azure-deep px-3 text-[12px] font-semibold text-on-accent disabled:opacity-60">
          {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Find
        </button>
      </div>
      {found && found.state !== "ok" && <p className="mt-2 text-[11px] text-error">{found.reason}</p>}
      {found && found.state === "ok" && (
        <>
          <p className="mt-2 text-[11px] text-slate">
            {found.items.length} {found.items.length === 1 ? "experiment" : "experiments"}
            {found.without_files ? `; ${found.without_files} without a GRCh38 file` : ""}.
          </p>
          <ExperimentRows items={found.items} tracks={tracks} onToggle={onToggle} label={(item) => item.biosample} />
        </>
      )}
    </section>
  );
}

function GeoTracks({ tracks, onToggle }: { tracks: Record<string, Loaded>; onToggle: (id: string) => void }) {
  const [accession, setAccession] = useState("");
  const [busy, setBusy] = useState(false);
  const [series, setSeries] = useState<GeoSeries | null>(null);
  const [problem, setProblem] = useState("");
  const [filter, setFilter] = useState("");

  async function open() {
    setBusy(true);
    setProblem("");
    try {
      const found = await geoSeries(accession.trim());
      if (found.error) setProblem(found.error);
      else setSeries(found);
    } finally {
      setBusy(false);
    }
  }

  const needle = filter.trim().toLowerCase();
  const rows = series
    ? series.samples
        .map((sample) => ({ sample, files: sampleTracks(series, sample) }))
        .filter(({ sample, files }) => files.length && (!needle ||
          [sample.accession, sample.title, sample.source, ...Object.values(sample.characteristics)].join(" ").toLowerCase().includes(needle)))
    : [];
  const loose = series ? series.files.filter((f) => f.track && !f.sample) : [];

  return (
    <section>
      <h3 className="mb-2 text-[12px] font-semibold text-ink">Tracks from GEO</h3>
      <p className="mb-2 text-[11px] leading-snug text-slate">
        bigWig, bigBed, peak and signal files of a GEO series, read for this window only. GRCh37 mapped to GRCh38.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); open(); }} className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-slate">GSE</span>
        <input value={accession} onChange={(e) => setAccession(e.target.value.toUpperCase())} title="GSE accession"
          aria-label="GEO series accession"
          className="h-7 w-[120px] rounded-[8px] border border-line bg-surface px-2 font-mono text-[12px] text-ink outline-none focus:border-azure" />
        <button type="submit" disabled={busy || !accession.trim()}
          className="flex h-7 items-center gap-1 rounded-full bg-azure-deep px-3 text-[12px] font-semibold text-on-accent disabled:opacity-60">
          {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Open
        </button>
      </form>
      {problem && <p className="mt-2 text-[11px] text-error">{problem}</p>}
      {series && (
        <>
          <p className="mt-2 text-[11px] text-slate">
            <span className="text-ink">{series.title}</span>. {series.counts.tracks} of {series.counts.files} files
            drawable.
          </p>
          {series.counts.tracks > 0 && (
            <>
            <span className="mt-2 block text-[11px] text-slate">Filter</span>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} title="Filter samples"
              aria-label="Filter GEO samples"
              className="mt-1 h-7 w-full rounded-[8px] border border-line bg-surface px-2 text-[12px] text-ink outline-none focus:border-azure" />
            </>
          )}
          <ul className="mt-2 max-h-[340px] space-y-2 overflow-y-auto pr-1">
            {rows.map(({ sample, files }) => (
              <li key={sample.accession} className="text-[12px]">
                <p className="text-ink">
                  <span className="font-mono text-slate">{sample.accession}</span> {sample.title}
                </p>
                <p className="text-[11px] text-slate">
                  {Object.entries(sample.characteristics).map(([k, v]) => `${k}: ${v}`).join("; ")}
                </p>
                <ul className="mt-0.5 space-y-0.5">
                  {files.map((file) => {
                    const id = geoTrackId(file, sample.accession);
                    return (
                      <li key={file.url}>
                        <label className="flex cursor-pointer items-center gap-1.5">
                          <input type="checkbox" checked={!!tracks[id]} onChange={() => onToggle(id)}
                            className="accent-[var(--color-azure-deep)]" />
                          <span className="truncate font-mono text-[11px] text-ink" title={file.name}>{file.name}</span>
                          <Status loaded={tracks[id]} />
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
            {loose.map((file) => {
              const id = geoTrackId(file, series.accession);
              return (
                <li key={file.url} className="text-[12px]">
                  <label className="flex cursor-pointer items-center gap-1.5">
                    <input type="checkbox" checked={!!tracks[id]} onChange={() => onToggle(id)} className="accent-[var(--color-azure-deep)]" />
                    <span className="truncate font-mono text-[11px] text-ink" title={file.name}>{file.name}</span>
                    <Status loaded={tracks[id]} />
                  </label>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function Regulators({
  symbol,
  ensemblId,
  tracks,
  onToggle,
}: {
  symbol: string;
  ensemblId: string;
  tracks: Record<string, Loaded>;
  onToggle: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<ExperimentList | null>(null);

  async function search() {
    setBusy(true);
    try {
      setFound(await findRegulators(symbol, ensemblId));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h3 className="mb-2 text-[12px] font-semibold text-ink">Regulator ChIP-seq</h3>
      <p className="mb-2 text-[11px] leading-snug text-slate">
        OmniPath regulators of {symbol} (commercial records), with ENCODE ChIP-seq peaks.
      </p>
      {!found && (
        <button type="button" onClick={search} disabled={busy}
          className="flex h-7 items-center gap-1 rounded-full bg-azure-deep px-3 text-[12px] font-semibold text-on-accent disabled:opacity-60">
          {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Find regulators
        </button>
      )}
      {found && found.state !== "ok" && <p className="mt-2 text-[11px] text-error">{found.reason}</p>}
      {found && found.state === "ok" && (
        <>
          <p className="text-[12px] text-ink">
            {found.regulators?.length ? (
              <span className="font-mono">{found.regulators.join(", ")}</span>
            ) : (
              "No regulator in OmniPath commercial records."
            )}
          </p>
          {Boolean(found.without_chipseq?.length) && (
            <p className="mt-1 text-[11px] text-slate">
              Not assayed by ENCODE:{" "}
              <span className="font-mono">{found.without_chipseq?.join(", ")}</span>.
            </p>
          )}
          {found.items.length > 0 && (
            <ExperimentRows items={found.items} tracks={tracks} onToggle={onToggle}
              label={(item) => `${item.target}, ${item.biosample}`} />
          )}
        </>
      )}
    </section>
  );
}
