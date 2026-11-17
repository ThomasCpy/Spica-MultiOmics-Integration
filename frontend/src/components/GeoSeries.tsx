import { useMemo, useState } from "react";
import { geoGene, geoTrackId, locateGene, sampleTracks, type GeoGene, type GeoSample, type GeoSeries } from "../geo";
import { DiffExpression } from "./DiffExpression";
import { GenomeView } from "./GenomeView";
import { PanelBoundary } from "./PanelBoundary";

// One GEO series, read for a target project. It shows what each sample is:
// its characteristics, and the fields that seperate the samples as filter
// facets. It shows which files go on a locus. It reads the values of a gene
// in the processed table of the series, grouped by any field.

const STEP = 40;
const FACET_STEP = 12;

const KIND_LABEL: Record<string, string> = {
  bigwig: "bigWig signal",
  bigbed: "bigBed",
  peaks: "peaks",
  bedgraph: "bedGraph signal",
  wig: "WIG signal",
  bed: "BED",
  matrix: "table",
  sheet: "Excel table",
  archive: "archive",
  other: "file",
};

export function SeriesBody({
  series,
  gene,
  onDraw,
}: {
  series: GeoSeries;
  gene?: string;
  /** Draw the chosen track ids on this gene's locus. */
  onDraw?: (gene: string, ids: string[]) => void;
}) {
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [text, setText] = useState("");
  const [count, setCount] = useState(STEP);
  const [open, setOpen] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const [target, setTarget] = useState(gene ?? "");
  const [locus, setLocus] = useState<{ symbol: string; ensembl_id: string } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locusProblem, setLocusProblem] = useState("");

  const showLocus = async (symbol = target) => {
    if (!symbol.trim()) return;
    setLocating(true);
    setLocusProblem("");
    try {
      const found = await locateGene(symbol.trim());
      if (found.error || !found.symbol || !found.ensembl_id) setLocusProblem(found.error ?? "Gene not placed.");
      else setLocus({ symbol: found.symbol, ensembl_id: found.ensembl_id });
    } finally {
      setLocating(false);
    }
  };
  const [allFacets, setAllFacets] = useState<Record<string, boolean>>({});
  const [readAll, setReadAll] = useState(false);

  const fieldOf = (sample: GeoSample, field: string) =>
    field === "organism"
      ? sample.organism
      : field === "source"
        ? sample.source
        : field === "library strategy"
          ? sample.strategy
          : sample.characteristics[field] ?? "";

  const shown = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return series.samples.filter((sample) => {
      for (const [field, values] of Object.entries(filters)) {
        if (values.length && !values.includes(fieldOf(sample, field))) return false;
      }
      if (!needle) return true;
      const hay = [sample.accession, sample.title, sample.source, ...Object.values(sample.characteristics)].join(" ").toLowerCase();
      return hay.includes(needle);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, filters, text]);

  const toggleFilter = (field: string, value: string) => {
    const current = filters[field] ?? [];
    setFilters({ ...filters, [field]: current.includes(value) ? current.filter((v) => v !== value) : [...current, value] });
    setCount(STEP);
  };

  const chosenIds = Object.keys(chosen).filter((id) => chosen[id]);
  const varying = series.facets.map((f) => f.field);
  const summary = series.summary.length > 600 && !readAll ? `${series.summary.slice(0, 600).replace(/\s+\S*$/, "")} ...` : series.summary;

  return (
    <div>
      <p className="text-[12px] text-slate">
        {series.types.join("; ")} · {series.counts.samples} samples
        {series.counts.human !== series.counts.samples && `, ${series.counts.human} human`} ·{" "}
        {series.organisms.join(", ")} · submitted {series.submitted}, updated {series.updated}
        {series.pubmed.length > 0 && (
          <>
            {" "}
            · PubMed{" "}
            {series.pubmed.map((id, i) => (
              <span key={id}>
                {i > 0 && ", "}
                <a href={`https://pubmed.ncbi.nlm.nih.gov/${id}/`} className="font-mono text-azure-deep hover:underline">
                  {id}
                </a>
              </span>
            ))}
          </>
        )}{" "}
        ·{" "}
        <a href={series.url} className="text-azure-deep hover:underline">
          at GEO
        </a>
      </p>
      {series.summary && (
        <p className="mt-3 max-w-[90ch] text-[13px] leading-relaxed text-ink">
          {summary}
          {series.summary.length > 600 && (
            <button type="button" onClick={() => setReadAll(!readAll)} className="ml-1 text-azure-deep hover:underline">
              {readAll ? "Less" : "Read all"}
            </button>
          )}
        </p>
      )}
      {series.design && <p className="mt-2 max-w-[90ch] text-[12px] leading-relaxed text-slate">Design: {series.design}</p>}
      <p className="mt-3 text-[12px] text-slate">
        <span className="font-mono text-ink">{series.counts.files}</span> {series.counts.files === 1 ? "file" : "files"}:{" "}
        <span className="font-mono text-ink">{series.counts.tracks}</span> drawable on GRCh38,{" "}
        <span className="font-mono text-ink">{series.counts.matrices}</span>{" "}
        {series.counts.matrices === 1 ? "table" : "tables"}.
        {series.counts.tracks === 0 &&
          series.counts.files > 0 &&
          " No human GRCh38 or GRCh37 track (other build, other organism or no track format)."}
      </p>

      {series.facets.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-[12px] font-medium text-slate">Sample variables</p>
          {series.facets.map((facet) => {
            const all = allFacets[facet.field] || facet.values.length <= FACET_STEP + 2;
            const values = all ? facet.values : facet.values.slice(0, FACET_STEP);
            return (
              <div key={facet.field} className="flex flex-wrap items-baseline gap-1.5 text-[12px]">
                <span className="mr-1 text-slate">{facet.field}:</span>
                {values.map((v) => {
                  const on = (filters[facet.field] ?? []).includes(v.value);
                  return (
                    <button
                      key={v.value}
                      type="button"
                      aria-pressed={on}
                      onClick={() => toggleFilter(facet.field, v.value)}
                      className={`rounded-full border px-2.5 py-0.5 ${on ? "border-azure bg-mist text-azure-deep" : "border-line bg-surface text-ink hover:border-azure"}`}
                    >
                      {v.value} <span className="font-mono text-slate">{v.samples}</span>
                    </button>
                  );
                })}
                {!all && (
                  <button
                    type="button"
                    onClick={() => setAllFacets({ ...allFacets, [facet.field]: true })}
                    className="text-azure-deep hover:underline"
                  >
                    +{facet.values.length - FACET_STEP} more
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="text-[12px] font-medium text-slate">Filter</span>
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setCount(STEP);
          }}
          aria-label="Filter samples"
          className="h-9 w-[320px] rounded-full border border-line bg-surface px-4 text-[13px] text-ink outline-none focus:border-azure"
        />
        <span className="text-[12px] text-slate">
          {shown.length.toLocaleString("en-US")} of {series.samples.length.toLocaleString("en-US")} samples
          {Object.values(filters).some((v) => v.length) && (
            <button type="button" onClick={() => setFilters({})} className="ml-2 text-azure-deep hover:underline">
              Clear filters
            </button>
          )}
        </span>
      </div>

      <div className="mt-3 overflow-x-auto rounded-[14px] border border-line bg-surface">
        <table className="w-full min-w-[820px] text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-slate">
              <th className="w-8 px-3 py-2" />
              <th className="py-2 pr-3 font-medium">Sample</th>
              <th className="py-2 pr-3 font-medium">Title</th>
              <th className="py-2 pr-3 font-medium">Context</th>
              <th className="py-2 pr-3 font-medium">Assay</th>
              <th className="py-2 pr-3 font-medium">Tracks</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, count).map((sample) => {
              const tracks = sampleTracks(series, sample);
              const ids = tracks.map((f) => geoTrackId(f, sample.accession));
              const all = ids.length > 0 && ids.every((id) => chosen[id]);
              const expanded = open === sample.accession;
              return (
                <SampleRows key={sample.accession}>
                  <tr className="border-b border-line align-top hover:bg-mist/40">
                    <td className="px-3 py-2">
                      {ids.length > 0 && (
                        <input
                          type="checkbox"
                          checked={all}
                          aria-label={`Choose the tracks of ${sample.accession}`}
                          onChange={() => {
                            const next = { ...chosen };
                            for (const id of ids) next[id] = !all;
                            setChosen(next);
                          }}
                          className="accent-[var(--color-azure-deep)]"
                        />
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        onClick={() => setOpen(expanded ? null : sample.accession)}
                        className="font-mono text-azure-deep hover:underline"
                        aria-expanded={expanded}
                      >
                        {sample.accession}
                      </button>
                    </td>
                    <td className="py-2 pr-3 text-ink">
                      {sample.title}
                      {sample.arm === "control" && <span className="ml-1.5 rounded-full bg-mist px-1.5 text-[11px] text-slate">control</span>}
                    </td>
                    <td className="py-2 pr-3 text-slate">
                      {varying
                        .filter((field) => fieldOf(sample, field))
                        .map((field) => (
                          <span key={field} className="mr-2 inline-block">
                            {field}: <span className="text-ink">{fieldOf(sample, field)}</span>
                          </span>
                        ))}
                    </td>
                    <td className="py-2 pr-3 text-slate">{sample.strategy}</td>
                    <td className="py-2 pr-3 font-mono text-slate">{tracks.length || ""}</td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-line bg-frost">
                      <td />
                      <td colSpan={5} className="py-2 pr-3 text-[12px]">
                        <dl className="grid grid-cols-[minmax(0,160px)_1fr] gap-x-4 gap-y-1">
                          {Object.entries(sample.characteristics).map(([k, v]) => (
                            <FragmentPair key={k} k={k} v={v} />
                          ))}
                          <FragmentPair k="source" v={sample.source} />
                          <FragmentPair k="organism" v={sample.organism} />
                          {sample.treatment && <FragmentPair k="treatment protocol" v={sample.treatment} />}
                          {sample.processing && <FragmentPair k="processing" v={sample.processing} />}
                        </dl>
                        {[...sample.files, ...series.files.filter((f) => f.sample === sample.accession)].length > 0 && (
                          <ul className="mt-2 space-y-1">
                            {[...sample.files, ...series.files.filter((f) => f.sample === sample.accession)].map((file) => {
                              const id = geoTrackId(file, sample.accession);
                              return (
                                <li key={file.url} className="flex items-center gap-2">
                                  {file.track ? (
                                    <input
                                      type="checkbox"
                                      checked={!!chosen[id]}
                                      onChange={() => setChosen({ ...chosen, [id]: !chosen[id] })}
                                      aria-label={`Choose ${file.name}`}
                                      className="accent-[var(--color-azure-deep)]"
                                    />
                                  ) : (
                                    <span className="inline-block w-[13px]" />
                                  )}
                                  <a href={file.url} className="font-mono text-[11px] text-ink hover:text-azure-deep">
                                    {file.name}
                                  </a>
                                  <span className="text-[11px] text-slate">
                                    {KIND_LABEL[file.kind] ?? file.kind}
                                    {file.assembly && `, ${file.assembly}`}
                                    {!file.track && file.kind in KIND_LABEL && ["bigwig", "bigbed", "peaks", "bedgraph", "wig", "bed"].includes(file.kind) &&
                                      ", not drawable on GRCh38"}
                                  </span>
                                </li>
                              );
                            })}
                          </ul>
                        )}
                      </td>
                    </tr>
                  )}
                </SampleRows>
              );
            })}
          </tbody>
        </table>
      </div>
      {shown.length > count && (
        <button type="button" onClick={() => setCount(count + STEP)} className="mt-2 text-[12px] text-azure-deep hover:underline">
          Show {Math.min(STEP, shown.length - count)} more of {(shown.length - count).toLocaleString("en-US")}
        </button>
      )}

      {series.counts.tracks > 0 && (
        <section id={`locus-${series.accession}`} className="mt-4 rounded-[14px] border border-line bg-surface">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              showLocus();
            }}
            className="flex flex-wrap items-center gap-3 px-4 py-3"
          >
            <h3 className="text-[14px] font-semibold text-ink">On the genome</h3>
            <span className="text-[12px] text-slate">Gene</span>
            <input
              value={target}
              onChange={(e) => setTarget(e.target.value.toUpperCase())}
              aria-label="Gene whose locus to show"
              className="h-9 w-[120px] rounded-full border border-line bg-frost px-3 font-mono text-[13px] text-ink outline-none focus:border-azure"
            />
            <button
              type="submit"
              disabled={!target.trim() || locating}
              className="rounded-full bg-azure-deep px-4 py-1.5 text-[13px] font-semibold text-on-accent hover:bg-azure-hover disabled:opacity-50"
            >
              {locus && locus.symbol === target.trim() ? "Shown" : "Show locus"}
            </button>
            <span className="text-[12px] text-slate">
              <span className="font-mono text-ink">{chosenIds.length}</span> {chosenIds.length === 1 ? "track" : "tracks"} chosen.
              {locus
                ? " Ticked samples add their tracks; unticked samples remove them."
                : ""}
            </span>
            {locus && onDraw && (
              <button
                type="button"
                onClick={() => onDraw(locus.symbol, chosenIds)}
                className="ml-auto text-[12px] text-azure-deep hover:underline"
              >
                {locus.symbol} report, with these tracks
              </button>
            )}
          </form>
          {locusProblem && <p className="px-4 pb-3 text-[12px] text-error">{locusProblem}</p>}
          {locus && (
            <div className="border-t border-line">
              <PanelBoundary name="genome view">
                <GenomeView key={locus.ensembl_id} symbol={locus.symbol} ensemblId={locus.ensembl_id} topTissue="" selected={chosenIds} />
              </PanelBoundary>
            </div>
          )}
        </section>
      )}

      {series.files.filter((f) => !f.sample).length > 0 && (
        <details className="mt-3 text-[12px]">
          <summary className="cursor-pointer text-slate">Series files ({series.files.filter((f) => !f.sample).length})</summary>
          <ul className="mt-1 space-y-1">
            {series.files
              .filter((f) => !f.sample)
              .map((file) => {
                const id = geoTrackId(file, series.accession);
                return (
                  <li key={file.url} className="flex items-center gap-2">
                    {file.track ? (
                      <input
                        type="checkbox"
                        checked={!!chosen[id]}
                        onChange={() => setChosen({ ...chosen, [id]: !chosen[id] })}
                        aria-label={`Choose ${file.name}`}
                        className="accent-[var(--color-azure-deep)]"
                      />
                    ) : (
                      <span className="inline-block w-[13px]" />
                    )}
                    <a href={file.url} className="font-mono text-[11px] text-ink hover:text-azure-deep">
                      {file.name}
                    </a>
                    <span className="text-[11px] text-slate">
                      {KIND_LABEL[file.kind] ?? file.kind}
                      {file.assembly && `, ${file.assembly}`}
                    </span>
                  </li>
                );
              })}
          </ul>
        </details>
      )}

      <GeneInSeries series={series} initial={gene ?? ""} />
      <DiffExpression
        series={series}
        onGene={(symbol) => {
          // On the genome view under the series when it has tracks; else the report.
          if (series.counts.tracks > 0) {
            setTarget(symbol.toUpperCase());
            showLocus(symbol);
            document.getElementById(`locus-${series.accession}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
          } else onDraw?.(symbol, []);
        }}
      />
    </div>
  );
}

function SampleRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function FragmentPair({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-slate">{k}</dt>
      <dd className="text-ink [overflow-wrap:anywhere]">{v}</dd>
    </>
  );
}

/** A gene's values in the series' processed table, grouped by any field. */
export function GeneInSeries({ series, initial }: { series: GeoSeries; initial: string }) {
  const [gene, setGene] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<GeoGene | null>(null);
  const [field, setField] = useState("");

  const read = async (fileUrl = "") => {
    if (!gene.trim()) return;
    setBusy(true);
    try {
      const result = await geoGene(series.accession, gene.trim(), fileUrl);
      setFound(result);
      setField(result.groups?.[0]?.field ?? "");
    } finally {
      setBusy(false);
    }
  };

  if (!series.counts.matrices) return null;
  const groups = found?.groups?.find((g) => g.field === field)?.groups ?? [];
  const top = Math.max(...groups.map((g) => Math.max(g.mean, ...g.values)), 1e-9);
  const how = found?.columns?.reduce<Record<string, number>>((acc, c) => {
    acc[c.matched_by || "unmatched"] = (acc[c.matched_by || "unmatched"] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="mt-6 rounded-[14px] border border-line bg-surface p-4">
      <h3 className="text-[14px] font-semibold text-ink">Gene values</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          read();
        }}
        className="mt-2 flex flex-wrap items-center gap-2"
      >
        <span className="text-[12px] text-slate">Gene</span>
        <input
          value={gene}
          onChange={(e) => setGene(e.target.value.toUpperCase())}
          aria-label="Gene to read in the series' table"
          className="h-9 w-[120px] rounded-full border border-line bg-frost px-3 font-mono text-[13px] text-ink outline-none focus:border-azure"
        />
        <button type="submit" disabled={busy} className="rounded-full border border-line px-3 py-1.5 text-[13px] text-azure-deep hover:border-azure disabled:opacity-60">
          {busy ? "Reading" : "Read"}
        </button>
        {found?.tables && found.tables.length > 1 && (
          <select
            value={found.url}
            onChange={(e) => read(e.target.value)}
            aria-label="Table to read"
            className="h-9 rounded-full border border-line bg-surface px-3 font-mono text-[11px] text-ink"
          >
            {found.tables.map((name, i) => (
              <option key={name} value={found.table_urls?.[i]}>
                {name}
              </option>
            ))}
          </select>
        )}
      </form>
      {found?.error && <p className="mt-2 text-[12px] text-error">{found.error}</p>}
      {found && !found.error && found.state !== "ok" && <p className="mt-2 text-[12px] text-slate">{found.message}</p>}
      {found?.state === "ok" && found.columns && (
        <>
          <p className="mt-3 text-[12px] text-slate">
            <span className="font-mono text-ink">{found.gene}</span> in <span className="font-mono">{found.file}</span>:{" "}
            {found.columns.length} columns, {found.matched} matched to samples
            {how &&
              ` (${Object.entries(how)
                .map(([k, n]) => `${n} by ${k === "order" ? "series order (confirmed by names)" : k}`)
                .join(", ")})`}
            . {found.note}
          </p>
          {found.groups && found.groups.length > 0 ? (
            <>
              <label className="mt-3 flex items-center gap-2 text-[12px] text-slate">
                Grouped by
                <select value={field} onChange={(e) => setField(e.target.value)} className="rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] text-ink">
                  {found.groups.map((g) => (
                    <option key={g.field} value={g.field}>
                      {g.field}
                    </option>
                  ))}
                </select>
              </label>
              <ul className="mt-2 space-y-1.5">
                {groups.map((g) => (
                  <li key={g.value} className="grid grid-cols-[minmax(0,220px)_1fr_7rem] items-center gap-3 text-[12px]">
                    <span className="truncate text-ink" title={g.value}>
                      {g.value}
                    </span>
                    <span className="relative h-[14px] rounded-r-[4px] bg-mist">
                      <span className="absolute inset-y-0 left-0 rounded-r-[4px] bg-azure" style={{ width: `${(100 * g.mean) / top}%` }} />
                      {g.values.map((v, i) => (
                        <span
                          key={i}
                          title={`${v}`}
                          className="absolute top-1/2 size-[6px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface bg-ink"
                          style={{ left: `${(100 * v) / top}%` }}
                        />
                      ))}
                    </span>
                    <span className="text-right font-mono text-ink">
                      {g.mean.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                      <span className="text-slate"> n={g.samples}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-slate">Bar: group mean. Dots: samples. Published values.</p>
            </>
          ) : (
            <p className="mt-2 text-[12px] text-slate">No variable differs between the matched samples.</p>
          )}
          <details className="mt-3 text-[12px]">
            <summary className="cursor-pointer text-slate">Every column ({found.columns.length})</summary>
            <table className="mt-1 w-full text-[11px]">
              <tbody>
                {found.columns.map((c, i) => (
                  <tr key={`${c.column}${i}`} className="border-b border-line">
                    <td className="py-0.5 pr-3 font-mono">{c.column || "(unnamed)"}</td>
                    <td className="py-0.5 pr-3 font-mono text-azure-deep">{c.sample}</td>
                    <td className="py-0.5 pr-3">{c.title}</td>
                    <td className="py-0.5 pr-3 text-right font-mono">{c.value.toLocaleString("en-US", { maximumFractionDigits: 3 })}</td>
                    <td className="py-0.5 text-slate">{c.matched_by ? `by ${c.matched_by}` : "not matched"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}
