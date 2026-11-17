import { useEffect, useState } from "react";
import { interactionPartners, type InteractionPartners as Data, type Network, type PartnerLink } from "../views";

// Interaction partners from three kinds of evidence. HPA consensus network:
// binding seen in IntAct, BioGRID, OpenCell and BioPlex experiments. STRING
// physical subnetwork: binding shown or predicted, scored 0 to 1. OmniPath:
// curated effects of one protein on another, with the papers. Three sets
// overlap in seven ways, too many for a Venn diagram. The overlap is thus a
// list of combinations: dots show the networks, the bar the partner count.
// A row filters the matrix below, which shows each partner per network.

const STEP = 25;

const NETWORK_LABELS: Record<Network, string> = { hpa: "HPA", omnipath: "OmniPath", string: "STRING" };

const DATASET_LABELS: Record<string, string> = {
  intact: "IntAct",
  biogrid: "BioGRID",
  opencell: "OpenCell",
  bioplex: "BioPlex",
  consensus: "Consensus",
};

const SIGNS: Record<PartnerLink["sign"], string> = {
  stimulates: "stimulates",
  inhibits: "inhibits",
  both: "stimulates and inhibits",
  unsigned: "acts on",
};

const percent = (share: number | null | undefined) =>
  share === null || share === undefined ? "" : `${Math.round(share * 100)}%`;
const key = (networks: Network[]) => networks.join("+");

export function InteractionPartners({ symbol, ensemblId }: { symbol: string; ensemblId: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [count, setCount] = useState(STEP);
  const [only, setOnly] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    interactionPartners(symbol, ensemblId)
      .then((found) => live && setData(found))
      .catch((error) => live && setData({ error: String(error) } as Data));
    return () => {
      live = false;
    };
  }, [symbol, ensemblId]);

  if (!data) {
    return <div className="border-t border-line px-5 py-4 text-[12px] text-slate">Joining networks.</div>;
  }
  if (data.error) {
    return <div className="border-t border-line px-5 py-4 text-[12px] text-slate">{data.error}</div>;
  }

  const s = data.summary;
  const networks = s.networks;
  const hasString = networks.includes("string");
  const rows = only === null ? data.partners : data.partners.filter((row) => key(row.networks) === only);
  const shown = rows.slice(0, count);
  const topPapers = Math.max(...data.partners.map((row) => row.omnipath?.references ?? 0), 1);
  const topCombination = Math.max(...s.combinations.map((c) => c.count), 1);
  const datasets = data.partners.some((row) => row.hpa?.includes("consensus"))
    ? [...data.datasets, "consensus"]
    : data.datasets;
  const columns = `minmax(0,0.8fr) repeat(${datasets.length},3.2rem)${hasString ? " minmax(0,0.9fr)" : ""} minmax(0,0.9fr) minmax(0,1.3fr)`;
  const sizes = networks.map((n) => `${NETWORK_LABELS[n]} ${s[n] ?? 0}`).join(", ");
  const confirmed = networks
    .filter((n) => (s[n] ?? 0) > 0)
    .map((n) => `${percent(s.confirmed[n])} of ${NETWORK_LABELS[n]}'s`)
    .join(", ");

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-1 text-[12px] text-slate">
        Interaction partners: HPA experiments{hasString ? ", STRING physical network" : ""}, OmniPath curation;
        matched on identifiers.
        {hasString && ` STRING-only partners: score ${s.string_threshold} or more.`}{" "}
        <span className="opacity-70">{data.sources}</span>
      </p>
      <p className="mb-3 text-[13px] text-ink">
        {s.union.toLocaleString("en-US")} partners for {data.symbol} ({sizes}).
        {confirmed && ` ${confirmed} in two or more networks.`}
      </p>

      {s.combinations.length > 0 && (
        <div className="mb-4">
          <div
            className="grid items-end gap-x-3 pb-1 text-[11px] text-slate"
            style={{ gridTemplateColumns: `repeat(${networks.length},3.6rem) minmax(0,1fr) 3rem` }}
          >
            {networks.map((n) => (
              <span key={n} className="text-center">
                {NETWORK_LABELS[n]}
              </span>
            ))}
            <span>Partners in exactly these networks</span>
            <span />
          </div>
          <ul className="space-y-[3px]">
            {s.combinations.map((combination) => {
              const id = key(combination.networks);
              const active = only === id;
              return (
                <li key={id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setOnly(active ? null : id);
                      setCount(STEP);
                    }}
                    title={`${combination.networks.map((n) => NETWORK_LABELS[n]).join(" and ")}${
                      combination.networks.length < networks.length ? " only" : ""
                    }: ${combination.count} partners. ${active ? "Show every partner" : "Show these below"}.`}
                    className={`grid w-full items-center gap-x-3 rounded-[8px] py-0.5 text-left text-[12px] ${
                      active ? "bg-mist" : "hover:bg-mist/60"
                    }`}
                    style={{ gridTemplateColumns: `repeat(${networks.length},3.6rem) minmax(0,1fr) 3rem` }}
                  >
                    {networks.map((n) => (
                      <span key={n} className="flex justify-center">
                        <span
                          className={`block h-[10px] w-[10px] rounded-full ${
                            combination.networks.includes(n) ? "bg-azure-deep" : "border border-edge"
                          }`}
                        />
                      </span>
                    ))}
                    <span className="block h-[14px] bg-mist">
                      <span
                        className="block h-full rounded-r-[4px] bg-azure"
                        style={{ width: `${Math.max(1, (100 * combination.count) / topCombination)}%` }}
                      />
                    </span>
                    <span className="text-right font-mono tabular-nums text-ink">{combination.count}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="mb-2 flex items-center gap-3 text-[11px]">
        <span className="text-slate">
          {only === null
            ? `All partners (${s.union})`
            : `${only.split("+").map((n) => NETWORK_LABELS[n as Network]).join(" and ")}: ${rows.length}`}
        </span>
        {only !== null && (
          <button type="button" onClick={() => setOnly(null)} className="text-azure-deep hover:underline">
            All partners
          </button>
        )}
      </div>

      <div
        className="grid items-end gap-x-3 border-b border-line pb-1 text-[11px] text-slate"
        style={{ gridTemplateColumns: columns }}
      >
        <span>Partner</span>
        {datasets.map((dataset) => (
          <span key={dataset} className="text-center">
            {DATASET_LABELS[dataset] ?? dataset}
          </span>
        ))}
        {hasString && <span>STRING score</span>}
        <span>Papers (OmniPath)</span>
        <span>Effect (OmniPath)</span>
      </div>
      <ul className="mt-1 space-y-[5px]">
        {shown.map((row) => (
          <li
            key={row.ensembl_id || row.symbol}
            className="grid items-center gap-x-3 text-[12px]"
            style={{ gridTemplateColumns: columns }}
          >
            <span className="truncate font-mono text-ink">{row.symbol}</span>
            {datasets.map((dataset) => {
              const seen = row.hpa?.includes(dataset) ?? false;
              return (
                <span key={dataset} className="flex justify-center" title={`${DATASET_LABELS[dataset] ?? dataset}: ${seen ? "seen" : "not seen"}`}>
                  <span className={`block h-[9px] w-[9px] rounded-full ${seen ? "bg-azure-deep" : "border border-edge"}`} />
                </span>
              );
            })}
            {hasString &&
              (row.string ? (
                <span
                  title={`STRING ${row.string.score.toFixed(3)}: experiments ${row.string.experimental.toFixed(3)}, databases ${row.string.database.toFixed(3)}, text mining ${row.string.textmining.toFixed(3)}${row.string.medium ? "" : `. Below ${s.string_threshold}, so not counted as in STRING`}`}
                >
                  <Bar value={row.string.score} max={1} label={row.string.score.toFixed(3)} faint={!row.string.medium} />
                </span>
              ) : (
                <span className="text-[11px] text-slate">not in STRING</span>
              ))}
            {row.omnipath ? (
              <Bar value={row.omnipath.references} max={topPapers} label={String(row.omnipath.references)} />
            ) : (
              <span className="text-[11px] text-slate">not in OmniPath</span>
            )}
            {row.omnipath ? <Effect symbol={data.symbol} found={row.omnipath} /> : <span />}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex gap-4 text-[12px]">
        {rows.length > count && (
          <>
            <button type="button" onClick={() => setCount(count + STEP)} className="text-azure-deep hover:underline">
              Show {Math.min(STEP, rows.length - count)} more ({(rows.length - count).toLocaleString("en-US")} left)
            </button>
            <button type="button" onClick={() => setCount(rows.length)} className="text-azure-deep hover:underline">
              Show all {rows.length.toLocaleString("en-US")}
            </button>
          </>
        )}
        {count > STEP && (
          <button type="button" onClick={() => setCount(STEP)} className="text-azure-deep hover:underline">
            Show the first {STEP}
          </button>
        )}
      </div>
      {s.via_complex_only > 0 && (
        <p className="mt-2 text-[11px] text-slate">
          {s.via_complex_only} OmniPath partners recorded only through a complex ("via complex").
        </p>
      )}
    </div>
  );
}

// The OmniPath effect of the pair, read from the gene side: an arrow out
// when the gene acts on the partner, in when the partner acts on the gene.
// The tooltip gives each link in full, actor and target as recorded.
function Effect({ symbol, found }: { symbol: string; found: NonNullable<Data["partners"][number]["omnipath"]> }) {
  const compact = new Map<string, string>();
  for (const link of found.links) {
    const arrow = link.direction === "out" ? "→" : link.direction === "in" ? "←" : "↔";
    const word = link.direction === "none" ? "undirected" : link.sign === "unsigned" ? "unsigned" : SIGNS[link.sign];
    compact.set(`${arrow} ${word}`, `${arrow} ${word}`);
  }
  const full = found.links
    .map((link) => (link.direction === "none" ? `${link.from} with ${link.to}, undirected` : `${link.from} ${SIGNS[link.sign]} ${link.to}`))
    .join("\n");
  const title = `${full}\n\nArrows read from ${symbol}: → it acts on the partner, ← the partner acts on it.\nDatabases: ${found.databases}`;
  return (
    <span className="truncate text-ink" title={title}>
      {[...compact.values()].join(", ")}
      {!found.direct && <span className="text-slate"> (via complex)</span>}
    </span>
  );
}

function Bar({ value, max, label, faint = false }: { value: number; max: number; label: string; faint?: boolean }) {
  return (
    <span className="grid grid-cols-[1fr_auto] items-center gap-2">
      <span className="block h-[7px] rounded-full bg-mist">
        <span
          className={`block h-full rounded-r-[4px] ${faint ? "bg-edge" : "bg-azure"}`}
          style={{ width: `${Math.max(value > 0 ? 2 : 0, (100 * value) / max)}%` }}
        />
      </span>
      <span className={`w-[44px] text-right font-mono tabular-nums ${faint ? "text-slate" : "text-ink"}`}>{label}</span>
    </span>
  );
}
