import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { compareRegulators, type SharedRegulation as Data } from "../views";

// What regulates the compared genes together, and whether they regulate
// each other. Shared regulators come most selective first: a factor with
// a hundred targets shared by two genes says more than a hub with three
// thousand. The selectivity bar is one azure series with its figure.

export function SharedRegulation({ symbols }: { symbols: string[] }) {
  const [data, setData] = useState<Data | null>(null);
  const [all, setAll] = useState(false);
  const key = symbols.join(",");

  useEffect(() => {
    let alive = true;
    setData(null);
    compareRegulators(symbols)
      .then((result) => alive && setData(result))
      .catch((error) => alive && setData({ error: error instanceof Error ? error.message : "no answer" } as Data));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!data)
    return (
      <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-slate">
        <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Reading OmniPath
      </p>
    );
  if (data.error) return <p className="px-5 py-4 text-[13px] text-slate">{data.error}</p>;

  const most = Math.max(1, ...data.shared.map((s) => s.targets));
  const shown = all ? data.shared : data.shared.slice(0, 15);

  return (
    <div className="space-y-5 px-5 py-4">
      <div>
        <h3 className="text-[13px] font-semibold text-ink">Direct links</h3>
        {data.links.length === 0 ? (
          <p className="mt-1 text-[12px] text-slate">
            No directed edge between these genes in OmniPath commercial records.
          </p>
        ) : (
          <ul className="mt-2 space-y-1.5 text-[12px]">
            {data.links.map((link) => (
              <li key={`${link.source}-${link.target}-${link.type}`}>
                <span className="font-mono font-semibold text-ink">{link.source}</span>
                <span className="mx-1.5 text-slate">{link.effect} ({link.type}) →</span>
                <span className="font-mono font-semibold text-ink">{link.target}</span>
                <span className="ml-2 text-slate">
                  {link.references} {link.references === 1 ? "reference" : "references"}
                </span>
                <span className="block text-[11px] text-slate">{link.databases}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="text-[13px] font-semibold text-ink">Shared regulators</h3>
        <p className="mt-1 text-[12px] text-slate">
          Transcription factors of two or more of these genes, most selective first. Bar: total target genes.
        </p>
        {data.shared.length === 0 ? (
          <p className="mt-2 text-[12px] text-slate">No regulator common to two or more genes.</p>
        ) : (
          <table className="mt-2 w-full border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-line text-left text-[11px] text-slate">
                <th className="py-1.5 pr-3 font-medium">Regulator</th>
                <th className="py-1.5 pr-3 font-medium">Targets in all</th>
                {data.genes.map((gene) => (
                  <th key={gene} className="py-1.5 pr-3 font-mono font-medium text-ink">{gene}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((item) => (
                <tr key={item.tf} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-ink">{item.tf}</td>
                  <td className="py-1.5 pr-3">
                    <span className="flex items-center gap-2">
                      <span className="block h-[7px] w-24 rounded-full bg-mist">
                        <span className="block h-full rounded-r-[4px] bg-azure"
                          style={{ width: `${Math.max(3, (item.targets / most) * 100)}%` }} />
                      </span>
                      <span className="font-mono tabular-nums text-ink">{item.targets.toLocaleString("en-US")}</span>
                    </span>
                  </td>
                  {data.genes.map((gene) => (
                    <td key={gene} className="py-1.5 pr-3 text-slate">{item.genes[gene] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data.shared.length > 15 && (
          <button type="button" onClick={() => setAll(!all)} className="mt-2 text-[12px] text-azure-deep hover:underline">
            {all ? "Show the most selective 15" : `Show all ${data.shared.length}`}
          </button>
        )}
        <p className="mt-2 text-[11px] text-slate">
          Regulators per gene:{" "}
          {data.genes.map((gene) => `${gene} ${data.regulators[gene]?.length ?? 0}`).join(", ")}. {data.source}.
        </p>
      </div>
    </div>
  );
}
