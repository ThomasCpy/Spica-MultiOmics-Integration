import { useState } from "react";
import { Loader2, Search } from "lucide-react";
import { geoSearch, geoSeries, requestLocusTracks, type GeoSearch, type GeoSeries } from "../geo";
import { SeriesBody } from "./GeoSeries";

// Public datasets from NCBI GEO. Search any terms (other gene names join in)
// or open a series by accession. Each sample shows in context. The tracks of
// chosen samples go on a gene locus. The processed table of the series gives
// the values of a gene.

export function Datasets({ onOpenReport }: { onOpenReport: (symbol: string) => void }) {
  const [text, setText] = useState("");
  const [human, setHuman] = useState(true);
  const [tracks, setTracks] = useState(false);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<GeoSearch | null>(null);
  const [series, setSeries] = useState<GeoSeries | null>(null);
  const [problem, setProblem] = useState("");

  const open = async (accession: string) => {
    setBusy(true);
    setProblem("");
    try {
      const result = await geoSeries(accession);
      if (result.error) setProblem(result.error);
      else setSeries(result);
    } finally {
      setBusy(false);
    }
  };

  const search = async (offset = 0) => {
    if (!text.trim()) return;
    setBusy(true);
    setProblem("");
    try {
      const result = await geoSearch(text.trim(), human, tracks, offset);
      if (result.open) {
        setBusy(false);
        await open(result.open);
        return;
      }
      if (result.error) {
        setProblem(result.error);
        return;
      }
      setSeries(null);
      setFound(offset && found ? { ...result, results: [...found.results, ...result.results] } : result);
    } finally {
      setBusy(false);
    }
  };

  // A search that starts with a gene ("NFE2L2 ChIP-seq") suggests where to look.
  const first = (found?.query ?? "").trim().split(/\s+/)[0] ?? "";
  const searchedGene = /^[A-Za-z][A-Za-z0-9-]{1,11}$/.test(first) && !/^GSE\d/i.test(first) ? first.toUpperCase() : "";

  return (
    <div className="mx-auto w-full max-w-[1180px] px-8 py-10">
      <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Datasets</h1>
      <p className="mt-3 max-w-[70ch] text-[15px] leading-relaxed text-slate">
        NCBI GEO series: sample annotations, tracks on a locus, gene values. Network access required; opened series
        stay available offline.
      </p>

      <label htmlFor="geo-terms" className="mb-1.5 mt-6 block px-1 text-[12px] font-medium text-slate">
        Terms or GSE accession
      </label>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
        className="flex items-center gap-2 rounded-full border border-line bg-surface p-1.5 pl-4"
      >
        <Search size={17} className="text-slate" aria-hidden="true" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          id="geo-terms"
          aria-label="Search GEO"
          className="h-9 min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-slate/70"
        />
        <button type="submit" className="flex h-9 items-center gap-2 rounded-full bg-azure-deep px-4 text-[13px] font-semibold text-on-accent hover:bg-azure-hover">
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
          {/^GSE\d+$/i.test(text.trim()) ? "Open" : "Search"}
        </button>
      </form>
      <div className="mt-3 flex flex-wrap gap-5 px-4 text-[13px] text-slate">
        <label className="flex cursor-pointer items-center gap-2">
          <input type="checkbox" checked={human} onChange={(e) => setHuman(e.target.checked)} className="accent-[var(--color-azure-deep)]" />
          Human series only
        </label>
        <label className="flex cursor-pointer items-center gap-2">
          <input type="checkbox" checked={tracks} onChange={(e) => setTracks(e.target.checked)} className="accent-[var(--color-azure-deep)]" />
          Only series with browser tracks (bigWig, bigBed)
        </label>
      </div>
      {problem && (
        <p role="alert" className="mt-4 text-[13px] text-error">
          {problem}
        </p>
      )}

      {series ? (
        <div className="mt-6">
          {found && (
            <button type="button" onClick={() => setSeries(null)} className="mb-3 text-[13px] text-slate hover:text-azure-deep">
              Results
            </button>
          )}
          <h2 className="text-[20px] font-semibold leading-snug text-ink">
            <span className="font-mono text-azure-deep">{series.accession}</span> {series.title}
          </h2>
          <div className="mt-2">
            <SeriesBody
              key={series.accession}
              series={series}
              gene={searchedGene}
              onDraw={(gene, ids) => {
                requestLocusTracks(gene, ids);
                onOpenReport(gene);
              }}
            />
          </div>
        </div>
      ) : (
        found && (
          <div className="mt-6">
            <p className="text-[13px] text-slate">
              {found.total.toLocaleString("en-US")} series, by relevance. Terms:{" "}
              {found.terms.join(", ")}.
            </p>
            <ul className="mt-3 divide-y divide-line rounded-[14px] border border-line bg-surface">
              {found.results.map((hit) => (
                <li key={hit.accession} className="px-4 py-3">
                  <button type="button" onClick={() => open(hit.accession)} className="text-left">
                    <span className="font-mono text-[13px] text-azure-deep">{hit.accession}</span>{" "}
                    <span className="text-[14px] font-semibold text-ink hover:text-azure-deep">{hit.title}</span>
                  </button>
                  <p className="mt-1 text-[12px] text-slate">
                    {hit.type} · <span className="font-mono">{hit.samples}</span> samples · {hit.organisms} · {hit.date}
                    {hit.files.length > 0 && ` · files: ${hit.files.join(", ")}`}
                    {hit.tracks && <span className="ml-1.5 rounded-full bg-mist px-1.5 text-azure-deep">tracks</span>}
                  </p>
                  <p className="mt-1 line-clamp-2 max-w-[100ch] text-[12px] text-slate">{hit.summary}</p>
                </li>
              ))}
            </ul>
            {found.results.length < found.total && (
              <button type="button" onClick={() => search(found.results.length)} className="mt-2 text-[13px] text-azure-deep hover:underline">
                Show {Math.min(found.page, found.total - found.results.length)} more of{" "}
                {(found.total - found.results.length).toLocaleString("en-US")}
              </button>
            )}
          </div>
        )
      )}
    </div>
  );
}
