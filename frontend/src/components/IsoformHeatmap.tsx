import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { isoformTable, type IsoformTable } from "../views";
import { sequential, textOn } from "../ramp";
import { useTheme } from "../theme";

// Which transcript each tissue uses: tissues down, transcripts across, the
// median TPM printed in every cell so the table reads without the colour.
// One sequential azure scale over the whole table, since every cell is the
// same measurement. Tissues open on the twenty where the gene is highest;
// the rest are one click away.

const SHOWN = 20;

export function IsoformHeatmap({ symbol, ensemblId }: { symbol: string; ensemblId: string }) {
  useTheme(); // colours computed in code: render again when the theme changes
  const [data, setData] = useState<IsoformTable | null>(null);
  const [problem, setProblem] = useState("");
  const [all, setAll] = useState(false);

  useEffect(() => {
    let alive = true;
    isoformTable(symbol, ensemblId)
      .then((result) => {
        if (!alive) return;
        if (result.error) setProblem(result.error);
        else setData(result);
      })
      .catch((error) => alive && setProblem(error instanceof Error ? error.message : "no answer"));
    return () => {
      alive = false;
    };
  }, [symbol, ensemblId]);

  if (problem) return <p className="px-5 py-4 text-[13px] text-slate">Isoforms not read: {problem}</p>;
  if (!data)
    return (
      <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-slate">
        <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Reading GTEx transcripts
      </p>
    );

  const total = (tissue: string) =>
    data.transcripts.reduce((sum, t) => sum + (data.values[t.id]?.[tissue] ?? 0), 0);
  const tissues = [...data.tissues].sort((a, b) => total(b) - total(a) || a.localeCompare(b));
  const shown = all ? tissues : tissues.slice(0, SHOWN);
  const max = Math.max(1e-9, ...data.transcripts.flatMap((t) => Object.values(data.values[t.id] ?? {})));
  // Log scale for colour only: one transcript at 400 TPM would otherwise
  // wash every other cell to white. The printed numbers are the values.
  const shade = (v: number) => Math.log1p(v) / Math.log1p(max);

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-2 text-[12px] text-slate">
        Transcripts by tissue: median TPM, {data.dataset.replace("gtex_", "GTEx ")}. Colour: log scale; figures:
        values. ★: Ensembl canonical transcript.
      </p>
      <div className="overflow-x-auto">
        <table className="border-collapse text-[11px]">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-surface px-2 py-1.5 text-left font-medium text-slate">Tissue</th>
              {data.transcripts.map((t) => (
                <th key={t.id} className="min-w-[74px] px-1 py-1.5 text-left align-bottom font-normal">
                  <span className="block font-mono font-medium text-ink">
                    {t.name || t.id}
                    {t.canonical ? " ★" : ""}
                  </span>
                  <span className="block text-[10px] text-slate">{t.biotype.replace(/_/g, " ")}</span>
                </th>
              ))}
              <th className="px-2 py-1.5 text-left font-medium text-slate">Leading</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((tissue) => {
              const lead = data.dominant[tissue];
              const leadName = data.transcripts.find((t) => t.id === lead?.transcript);
              return (
                <tr key={tissue}>
                  <th scope="row" className="sticky left-0 z-10 max-w-[200px] truncate bg-surface px-2 py-[3px] text-left font-normal text-ink" title={tissue}>
                    {tissue}
                  </th>
                  {data.transcripts.map((t) => {
                    const v = data.values[t.id]?.[tissue] ?? 0;
                    const s = shade(v);
                    return (
                      <td key={t.id} className="border-2 border-surface px-1.5 py-[3px] text-right font-mono tabular-nums"
                        style={{ background: sequential(s), color: textOn(s) }}
                        title={`${t.name || t.id} in ${tissue}: ${v} TPM`}>
                        {v}
                      </td>
                    );
                  })}
                  <td className="whitespace-nowrap px-2 py-[3px] text-slate">
                    {lead ? `${leadName?.name || lead.transcript}, ${lead.share}%` : "none"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {tissues.length > SHOWN && (
        <button type="button" onClick={() => setAll(!all)} className="mt-2 text-[12px] text-azure-deep hover:underline">
          {all ? `Show the top ${SHOWN} tissues` : `Show all ${tissues.length} tissues`}
        </button>
      )}
    </div>
  );
}
