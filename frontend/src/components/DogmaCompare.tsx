import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { DogmaCompare as Data, DogmaStageCell } from "../report";
import { MemberName } from "./DogmaChart";

// Several genes on one organ axis: transcript above, protein below, one
// column per gene.
//
// The axis is shared; the scales are not. The transcript column of a gene is
// one assay against the own peak of that gene, and so is its protein column.
// The backend picks the widest layer and keeps it for the full column, so no
// column mixes two scales. Compare the shape across genes (where in the body
// the chain holds), never the height.

const DEFAULT_SHOWN = 12;
const MIN_BARS = 3; // as on the report: fewer points than this have no scale

export function DogmaCompare({ data }: { data: Data }) {
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState("");
  if (!data.rows.length || data.genes.length < 2) return null;

  const genes = data.genes;
  const columns = `minmax(0,112px) 64px repeat(${genes.length}, minmax(0,1fr))`;
  const shown = all ? data.rows : data.rows.slice(0, DEFAULT_SHOWN);
  const hidden = data.rows.length - shown.length;

  return (
    <figure className="m-0">
      <figcaption className="mb-3 text-[12px] leading-relaxed text-slate">
        {data.summary}
      </figcaption>

      <div
        className="grid items-end gap-x-3 border-b border-line pb-1.5 text-[11px]"
        style={{ gridTemplateColumns: columns }}
      >
        <span className="text-slate">Organ</span>
        <span />
        {genes.map((gene) => (
          <span key={gene.query} className="min-w-0">
            <span className="block font-mono text-[13px] font-semibold text-ink">
              {gene.symbol}
            </span>
            {(["transcript", "protein"] as const).map((stage) => {
              const layer = gene.layers[stage];
              return (
                <span key={stage} className="block truncate text-slate">
                  {stage === "transcript" ? "Message" : "Protein"}:{" "}
                  {layer ? `${layer.label}, ${layer.organs} organs` : "none"}
                </span>
              );
            })}
          </span>
        ))}
      </div>

      <ul className="divide-y divide-line">
        {shown.map((row) => {
          const foldable = row.cells.some(
            (cell) => (cell.transcript?.merged ?? 0) > 1 || (cell.protein?.merged ?? 0) > 1,
          );
          const isOpen = open === row.organ;
          const toggle = () => setOpen(isOpen ? "" : row.organ);
          return (
            <li key={row.organ}>
              <div
                className={`grid gap-x-3 gap-y-1 py-2 ${foldable ? "cursor-pointer hover:bg-frost" : ""}`}
                style={{ gridTemplateColumns: columns }}
                onClick={foldable ? toggle : undefined}
                role={foldable ? "button" : undefined}
                tabIndex={foldable ? 0 : undefined}
                aria-expanded={foldable ? isOpen : undefined}
                onKeyDown={
                  foldable
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          toggle();
                        }
                      }
                    : undefined
                }
              >
                <span className="row-span-2 flex min-w-0 items-start gap-1 text-[12px] text-ink">
                  {foldable ? (
                    <ChevronRight
                      size={13}
                      aria-hidden="true"
                      className={`mt-0.5 shrink-0 text-slate transition-transform ${isOpen ? "rotate-90" : ""}`}
                    />
                  ) : (
                    <span className="w-[13px] shrink-0" aria-hidden="true" />
                  )}
                  <span className="truncate" title={row.organ}>{row.organ}</span>
                </span>
                {(["transcript", "protein"] as const).map((stage) => (
                  <Stage
                    key={stage}
                    label={stage === "transcript" ? "Message" : "Protein"}
                    cells={row.cells.map((cell) => cell[stage])}
                    organs={genes.map((gene) => gene.layers[stage]?.organs ?? 0)}
                  />
                ))}
              </div>
              {isOpen && (
                <div
                  className="grid gap-x-3 bg-frost pb-3 pt-1 text-[11px]"
                  style={{ gridTemplateColumns: columns }}
                >
                  <span className="pl-[19px] text-slate">{row.organ} is made of</span>
                  <span />
                  {row.cells.map((cell, index) => (
                    <div key={genes[index].query} className="min-w-0 space-y-2">
                      {(["transcript", "protein"] as const).map((stage) => {
                        const value = cell[stage];
                        if (!value || !value.members.length) return null;
                        return (
                          <ul key={stage} className="space-y-0.5">
                            <li className="text-slate">{value.layer}</li>
                            {value.members.map((member) => (
                              <li key={member.tissue} className="min-w-0">
                                <MemberName name={member.tissue} />
                                <span className="block font-mono tabular-nums text-ink">
                                  {member.display}
                                </span>
                              </li>
                            ))}
                          </ul>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 flex flex-wrap gap-x-4">
        {hidden > 0 && (
          <button
            type="button"
            onClick={() => setAll(true)}
            className="text-[12px] text-azure-deep hover:underline"
          >
            Show all {data.rows.length} organs
          </button>
        )}
        {all && data.rows.length > DEFAULT_SHOWN && (
          <button
            type="button"
            onClick={() => setAll(false)}
            className="text-[12px] text-azure-deep hover:underline"
          >
            Show the top {DEFAULT_SHOWN}
          </button>
        )}
      </div>

      {data.notes.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-line pt-2.5 text-[11px] text-slate">
          {data.notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      )}
    </figure>
  );
}

// One stage line: its label, then one cell per gene. Rendered as a grid
// fragment so it occupies columns 2 onward of the organ's row.
function Stage({
  label,
  cells,
  organs,
}: {
  label: string;
  cells: (DogmaStageCell | null)[];
  organs: number[];
}) {
  return (
    <>
      <span className="text-[11px] text-slate">{label}</span>
      {cells.map((cell, index) => {
        if (!cell || cell.value === null) {
          return (
            <span key={index} className="text-[11px] text-slate">
              not measured
            </span>
          );
        }
        const bars = organs[index] >= MIN_BARS;
        return (
          <span key={index} className="flex min-w-0 items-center gap-2">
            <span
              className="w-[52px] shrink-0 text-right font-mono text-[12px] tabular-nums text-ink"
              title={`${cell.layer}, ${cell.unit}${cell.merged > 1 ? ` (highest of ${cell.merged}: ${cell.peak_tissue})` : ""}`}
            >
              {cell.display}
            </span>
            {bars && (
              <span className="block h-[7px] min-w-0 flex-1 rounded-full bg-mist">
                <span
                  className="block h-full rounded-r-[4px] bg-azure"
                  style={{ width: `${Math.max(0.8, cell.share * 100)}%` }}
                />
              </span>
            )}
          </span>
        );
      })}
    </>
  );
}
