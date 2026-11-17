import { useEffect, useState } from "react";
import { tfAnalysis, type TfAnalysis as Data, type TfRow } from "../views";

// Transcription factors at the promoter: the gene's regulators (OmniPath),
// each one's JASPAR motif scanned on both strands, and ENCODE's ChIP-seq
// peaks of the same factor over the same bases. A motif site inside the
// factor's own peak has two independent kinds of evidence behind it; the
// map puts every site and every peak on one axis, TSS at zero, so the
// strongest cases read at a glance. Shape carries what colour does (filled
// for a site in its own peak, outlined for motif only), so it reads in grey.

const UPSTREAM = [1000, 2000, 5000, 10000];
const DOWNSTREAM = [200, 500, 1000];
const EFFECT: Record<TfRow["effect"], string> = {
  activates: "activates",
  represses: "represses",
  both: "both ways",
  unsigned: "sign not recorded",
};
const LETTER_COLOR: Record<string, string> = {
  A: "var(--color-azure-deep)",
  C: "var(--color-up)",
  G: "var(--color-ink)",
  T: "var(--color-slate)",
};

const signed = (n: number) => (n > 0 ? `+${n.toLocaleString("en-US")}` : n < 0 ? `−${(-n).toLocaleString("en-US")}` : "0");
const pText = (p: number) =>
  p < 0.001 ? p.toExponential(1).replace(".0e", "e").replace("e-", "e−") : String(p);
const cells = (n: number) => `${n} cell ${n === 1 ? "type" : "types"}`;

export function TfAnalysis({
  symbol,
  ensemblId,
  onShowInGenome,
}: {
  symbol: string;
  ensemblId: string;
  onShowInGenome?: () => void;
}) {
  const [upstream, setUpstream] = useState(2000);
  const [downstream, setDownstream] = useState(500);
  const [data, setData] = useState<Data | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [complexes, setComplexes] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    tfAnalysis(symbol, ensemblId, upstream, downstream)
      .then((found) => live && setData(found))
      .catch((error) => live && setData({ state: "failed", error: String(error) } as Data));
    return () => {
      live = false;
    };
  }, [symbol, ensemblId, upstream, downstream]);

  const head = (
    <>
      <h3 className="text-[14px] font-semibold text-ink">Transcription factors at the promoter</h3>
      <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-slate">
        OmniPath regulators. JASPAR motifs scanned on both strands, from{" "}
        <Choice options={UPSTREAM} value={upstream} onChange={setUpstream} /> bp upstream of the TSS to{" "}
        <Choice options={DOWNSTREAM} value={downstream} onChange={setDownstream} /> bp downstream. ENCODE ChIP-seq peaks
        of each factor over the same interval.
      </p>
    </>
  );

  if (!data) {
    return (
      <div className="border-t border-line px-5 py-4">
        {head}
        <p className="mt-3 text-[12px] text-slate">Scan running.</p>
      </div>
    );
  }
  if (data.state !== "ok") {
    return (
      <div className="border-t border-line px-5 py-4">
        {head}
        <p className="mt-3 text-[12px] text-slate">
          {data.state === "offline"
            ? "Network access required (sequence, JASPAR, ENCODE). Online access off."
            : data.error}
        </p>
      </div>
    );
  }

  const s = data.summary;
  // Dimers OmniPath records as one regulator (FOS_JUN) repeat their
  // members' motif: folded away until asked for, never dropped.
  const listed = complexes ? data.regulators : data.regulators.filter((row) => !row.complex);
  const mapped = listed.filter((row) => row.hits.length || row.chip.peaks.length);
  const quiet = listed.length - mapped.length;

  return (
    <div className="border-t border-line px-5 py-4">
      {head}
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        {[
          ["Regulators", `${s.regulators}`, s.complexes ? `${s.regulators - s.complexes} factors, ${s.complexes} dimers` : ""],
          ["JASPAR motif", `${s.with_motif}`, ""],
          ["Motif sites", `${s.with_sites}`, `${s.sites} ${s.sites === 1 ? "site" : "sites"}`],
          ["Site in own peak", `${s.supported}`, `${s.supported_sites} ${s.supported_sites === 1 ? "site" : "sites"}`],
          ["ENCODE assayed", `${s.assayed}`, ""],
          ["Bound here", `${s.bound_here}`, ""],
          ["Bound, no motif", `${s.bound_without_motif}`, s.bound_without_motif ? "binding through a partner" : ""],
        ].map(([label, value, note]) => (
          <div key={label}>
            <dt className="text-[11px] text-slate">{label}</dt>
            <dd className="font-mono text-[15px] text-ink">
              {value}
              {note && <span className="ml-1.5 font-sans text-[11px] text-slate">{note}</span>}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-[11px] text-slate">
        TSS: {data.tss_from}, {data.chrom}:{(data.tss + 1).toLocaleString("en-US")} ({data.strand} strand). Sites at p{" "}
        &lt; {pText(data.p_value)}, background {data.background}. Peaks: {data.sources.binding}.
        {data.chip_state !== "ok" && ` ENCODE search failed (${data.chip_state}); assay status unknown.`}
      </p>

      {s.complexes > 0 && (
        <button
          type="button"
          onClick={() => setComplexes(!complexes)}
          className="mt-3 text-[12px] text-azure-deep hover:underline"
        >
          {complexes ? `Hide ${s.complexes} dimers` : `Show ${s.complexes} dimers (${data.regulators
            .filter((r) => r.complex)
            .slice(0, 3)
            .map((r) => r.tf)
            .join(", ")}${s.complexes > 3 ? ", ..." : ""})`}
        </button>
      )}
      {mapped.length > 0 && <PromoterMap data={data} rows={mapped} />}
      {quiet > 0 && (
        <p className="mt-1 text-[11px] text-slate">
          {quiet} {quiet === 1 ? "regulator" : "regulators"} without site or peak: table only.
        </p>
      )}
      {onShowInGenome && (
        <button
          type="button"
          onClick={onShowInGenome}
          className="mt-3 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-azure-deep hover:border-azure"
        >
          Sites in the genome view
        </button>
      )}
      {onShowInGenome && (upstream !== 2000 || downstream !== 500) && (
        <span className="ml-2 text-[11px] text-slate">Genome view track: -2,000 to +500 bp.</span>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[740px] text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[12px] font-medium text-slate">
              <th className="py-1.5 pr-3 font-medium">Factor</th>
              <th className="py-1.5 pr-3 font-medium" title="DoRothEA's confidence (A highest) and the papers OmniPath cites">
                Effect, evidence
              </th>
              <th className="py-1.5 pr-3 font-medium">Motif (JASPAR)</th>
              <th className="whitespace-nowrap py-1.5 pr-3 text-right font-medium">Sites</th>
              <th className="whitespace-nowrap py-1.5 pr-3 text-right font-medium">In own peak</th>
              <th className="py-1.5 font-medium">ENCODE ChIP-seq</th>
            </tr>
          </thead>
          <tbody>
            {listed.map((row) => {
              const expanded = open === row.tf;
              const best = row.hits.reduce<TfRow["hits"][number] | null>((a, h) => (!a || h.p < a.p ? h : a), null);
              return (
                <FragmentRows key={row.tf}>
                  <tr
                    className={`border-b border-line align-middle ${row.hits.length ? "cursor-pointer hover:bg-mist/60" : ""}`}
                    onClick={() => row.hits.length && setOpen(expanded ? null : row.tf)}
                  >
                    <td className="whitespace-nowrap py-1.5 pr-3 font-mono text-[12px] text-ink">
                      {row.hits.length > 0 && (
                        <span aria-hidden="true" className="mr-1 inline-block w-2 text-slate">
                          {expanded ? "▾" : "▸"}
                        </span>
                      )}
                      {row.tf}
                    </td>
                    <td className="py-1.5 pr-3 text-slate">
                      {EFFECT[row.effect]}
                      <span className="block text-[11px]">
                        {row.level && <span className="font-mono text-ink">DoRothEA {row.level}, </span>}
                        <span className="font-mono">{row.references}</span> {row.references === 1 ? "paper" : "papers"}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3">
                      {row.motif ? (
                        <span className="flex items-center gap-2" title={`${row.motif.id} ${row.motif.name}${row.motif_note ? `, ${row.motif_note}` : ""}`}>
                          <Logo frequencies={row.motif.frequencies} />
                          <span className="min-w-0">
                            <span className="block font-mono text-[11px] text-ink [overflow-wrap:anywhere]">{row.motif.consensus}</span>
                            <a
                              href={row.motif.url}
                              onClick={(e) => e.stopPropagation()}
                              className="font-mono text-[10px] text-azure-deep hover:underline"
                            >
                              {row.motif.id}
                              {row.motif_note && ` (${row.motif_note})`}
                            </a>
                          </span>
                        </span>
                      ) : (
                        <span className="text-slate">{row.motif_note}</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {row.motif ? row.hits.length : "not scanned"}
                      {best && (
                        <span className="block whitespace-nowrap text-[10px] text-slate" title={`best site, p ${pText(best.p)}`}>
                          best {signed(best.offset)}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {row.motif ? (
                        <span className={row.supported ? "font-semibold text-azure-deep" : "text-slate"}>{row.supported}</span>
                      ) : (
                        ""
                      )}
                    </td>
                    <td className="py-1.5 text-slate">
                      {row.chip.assayed === null
                        ? "could not be checked"
                        : !row.chip.assayed
                          ? "not assayed by ENCODE"
                          : `${row.chip.experiments} ${row.chip.experiments === 1 ? "experiment" : "experiments"}; ${
                              row.chip.peaks.length
                                ? `bound here in up to ${cells(Math.max(...row.chip.peaks.map((p) => p.cells)))}`
                                : "no peak here in the clustered set"
                            }`}
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-line bg-frost">
                      <td colSpan={6} className="px-3 py-2">
                        <table className="w-full text-[11px]">
                          <thead>
                            <tr className="text-left text-slate">
                              <th className="pr-3 font-medium">From the TSS</th>
                              <th className="pr-3 font-medium">Strand</th>
                              <th className="pr-3 font-medium">Site, 5' to 3'</th>
                              <th className="pr-3 font-medium">p</th>
                              <th className="pr-3 font-medium">Position</th>
                              <th className="font-medium">ChIP-seq</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row.hits.map((hit) => (
                              <tr key={`${hit.start}${hit.strand}`}>
                                <td className="pr-3 font-mono">{signed(hit.offset)}</td>
                                <td className="pr-3 font-mono">{hit.strand}</td>
                                <td className="pr-3 font-mono text-ink">{hit.site}</td>
                                <td className="pr-3 font-mono">{pText(hit.p)}</td>
                                <td className="pr-3 font-mono">
                                  {data.chrom}:{(hit.start + 1).toLocaleString("en-US")}
                                </td>
                                <td className={hit.in_peak ? "text-azure-deep" : "text-slate"}>
                                  {hit.in_peak ? `inside ${row.tf}'s peak (${cells(hit.cells)})` : "motif only"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </FragmentRows>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-slate">
        No JASPAR matrix: not a curated sequence-specific binder. Not assayed: no ENCODE ChIP-seq; not evidence
        of absent binding. Sources:{" "}
        {data.sources.regulators}; {data.sources.motifs} (CC BY 4.0); {data.sources.binding}.
      </p>
    </div>
  );
}

function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function Choice({ options, value, onChange }: { options: number[]; value: number; onChange: (v: number) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="rounded-full border border-line bg-surface px-1.5 py-0 font-mono text-[12px] text-ink"
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {option.toLocaleString("en-US")}
        </option>
      ))}
    </select>
  );
}

/** A sequence logo: letter height is its share times the position's information. */
function Logo({ frequencies }: { frequencies: number[][] }) {
  const W = 7;
  const H = 18;
  return (
    <svg width={frequencies.length * W} height={H} aria-hidden="true" className="shrink-0">
      {frequencies.map((column, i) => {
        const info = 2 + column.reduce((sum, f) => (f > 0 ? sum + f * Math.log2(f) : sum), 0);
        let y = H;
        return [...column.keys()]
          .sort((a, b) => column[a] - column[b])
          .map((b) => {
            const h = (column[b] * info * H) / 2;
            y -= h;
            if (h < 0.6) return null;
            const letter = "ACGT"[b];
            return (
              <text
                key={b}
                transform={`translate(${i * W},${y + h}) scale(${W / 6.1},${h / 7.3})`}
                fontFamily="JetBrains Mono, monospace"
                fontSize={10}
                fontWeight={700}
                fill={LETTER_COLOR[letter]}
              >
                {letter}
              </text>
            );
          });
      })}
    </svg>
  );
}

/** Every site and every own peak on one axis, TSS at zero. */
function PromoterMap({ data, rows }: { data: Data; rows: TfRow[] }) {
  const W = 760;
  const LEFT = 96;
  const RIGHT = 70;
  const ROW = 18;
  const TOP = 26;
  const lo = -data.region.upstream;
  const hi = data.region.downstream;
  const x = (offset: number) => LEFT + ((Math.max(lo, Math.min(hi, offset)) - lo) / (hi - lo)) * (W - LEFT - RIGHT);
  const step = hi - lo > 6000 ? 2000 : hi - lo > 2600 ? 1000 : 500;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
  const height = TOP + rows.length * ROW + 8;

  return (
    <figure className="mt-3">
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate">
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden="true">
            <rect x="1" y="1" width="8" height="8" rx="1.5" fill="var(--color-azure-deep)" />
          </svg>
          site inside the factor's own ChIP-seq peak
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden="true">
            <rect x="1.5" y="1.5" width="7" height="7" rx="1.5" fill="var(--color-surface)" stroke="var(--color-slate)" />
          </svg>
          motif only
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="18" height="10" aria-hidden="true">
            <rect x="0" y="2" width="18" height="6" rx="2" fill="var(--color-soft-3)" />
          </svg>
          the factor's ChIP-seq peak
        </span>
        <span>Right: sites in own peak / sites</span>
      </div>
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={`Motif sites and ChIP-seq peaks of ${rows.length} regulators around the TSS`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={height - 6} stroke="var(--color-line)" />
            <text x={x(t)} y={12} textAnchor="middle" fontSize={10} fill="var(--color-slate)" fontFamily="JetBrains Mono, monospace">
              {t === 0 ? "TSS" : signed(t)}
            </text>
          </g>
        ))}
        <line x1={x(0)} x2={x(0)} y1={TOP - 6} y2={height - 6} stroke="var(--color-ink)" strokeDasharray="3 3" />
        {rows.map((row, i) => {
          const y = TOP + i * ROW;
          return (
            <g key={row.tf}>
              <text x={LEFT - 8} y={y + 12} textAnchor="end" fontSize={11} fill="var(--color-ink)" fontFamily="JetBrains Mono, monospace">
                {row.tf}
              </text>
              {row.chip.peaks.map((peak) => {
                const a = x(Math.min(peak.from, peak.to));
                const b = x(Math.max(peak.from, peak.to));
                return (
                  <rect key={`${peak.start}`} x={a} y={y + 4} width={Math.max(2, b - a)} height={10} rx={2} fill="var(--color-soft-3)">
                    <title>{`${row.tf} ChIP-seq peak, ${signed(Math.min(peak.from, peak.to))} to ${signed(Math.max(peak.from, peak.to))}, in ${cells(peak.cells)}`}</title>
                  </rect>
                );
              })}
              {row.hits.map((hit) => {
                const half = Math.max(1.5, ((hit.end - hit.start) / (hi - lo)) * (W - LEFT - RIGHT) / 2);
                return (
                  <rect
                    key={`${hit.start}${hit.strand}`}
                    x={x(hit.offset) - half}
                    y={y + 3}
                    width={half * 2}
                    height={12}
                    rx={1.5}
                    fill={hit.in_peak ? "var(--color-azure-deep)" : "var(--color-surface)"}
                    stroke={hit.in_peak ? "none" : "var(--color-slate)"}
                    strokeWidth={1}
                  >
                    <title>{`${row.tf} ${hit.site} at ${signed(hit.offset)} (${hit.strand}), p ${pText(hit.p)}${hit.in_peak ? `, inside its ChIP-seq peak in ${cells(hit.cells)}` : ", motif only"}`}</title>
                  </rect>
                );
              })}
              <text x={W - RIGHT + 10} y={y + 12} fontSize={11} fill="var(--color-slate)" fontFamily="JetBrains Mono, monospace">
                {row.motif ? `${row.supported} / ${row.hits.length}` : "no motif"}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
