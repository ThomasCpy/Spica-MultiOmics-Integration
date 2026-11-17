import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Dogma, DogmaCell, DogmaLayer, DogmaRow } from "../report";

// The central dogma on one organ axis: transcript on the left, protein on
// the right, one row per organ.
//
// The design decisions:
//
// *Four small scales, never one shared axis.* TPM, nTPM, staining rank and
// MS intensity have no common unit. One axis across them is the dual-axis
// error in four parts. Each column is normalised to the peak of its own
// layer, and the figure beside each bar is the fact. A bar means "high for
// this assay", never "higher than the column on its left".
//
// *One azure, as in the rest of the app.* Position and heading separate the
// columns, not hue. The chart thus stays clear in grayscale and for colour
// vision deficiency, with no legend.
//
// *An organ is an expandable claim.* GTEx measures fourteen brain regions;
// HPA stains one cerebral cortex. Only the merge to "brain" makes the two
// comparable. The row thus gives the number of merged entries and the one
// that peaked, and a click shows each member behind the number.
//
// *The maximum, not the mean.* Thirteen silent brain regions and one loud
// one make a brain where the gene is expressed. A mean would hide it.

const DEFAULT_SHOWN = 14;
//: Below this number of organs, a layer has no useful scale. HPA reports
//: one enriched tissue, and a full-width bar would mean "100% of itself".
//: Such a column keeps its figures and has no bars.
const MIN_BARS = 3;

export function DogmaChart({ dogma }: { dogma: Dogma }) {
  const [all, setAll] = useState(false);
  const [log, setLog] = useState(false);
  const [open, setOpen] = useState<string>("");

  const { layers, rows } = dogma;
  if (!layers.length || !rows.length) return null;

  // Each layer's own peak, recomputed here because the log view needs the
  // raw extent and the backend's `share` is linear.
  const peaks: Record<string, number> = {};
  for (const layer of layers) {
    peaks[layer.key] = Math.max(
      0,
      ...rows.map((row) => row.cells[layer.key]?.value ?? 0),
    );
  }

  // log1p keeps zero at zero: an organ where nothing was detected must stay
  // visible at the left edge rather than run off to minus infinity.
  function width(layer: DogmaLayer, value: number | null | undefined): number {
    if (value === null || value === undefined) return 0;
    if (layer.organs < MIN_BARS) return -1; // figures only, no scale to draw
    // An ordinal four-step scale is not a magnitude; logging it is noise.
    const useLog = log && layer.kind === "number";
    const peak = peaks[layer.key] || 0;
    const extent = useLog ? Math.log1p(peak) : peak;
    const raw = useLog ? Math.log1p(Math.max(value, 0)) : Math.max(value, 0);
    return extent > 0 ? Math.max(0.8, (raw / extent) * 100) : 0;
  }

  const shown = all ? rows : rows.slice(0, DEFAULT_SHOWN);
  const hidden = rows.length - shown.length;
  const columns = `minmax(0,116px) repeat(${layers.length}, minmax(0,1fr)) minmax(0,168px)`;
  const numeric = layers.some((layer) => layer.kind === "number");

  return (
    <figure className="m-0">
      <figcaption className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[13px] text-ink">Transcript to protein, by organ</span>
        <span className="text-[12px] text-slate">{dogma.summary}</span>
        {numeric && (
          <span className="ml-auto flex items-center gap-1">
            <ScaleButton active={!log} onClick={() => setLog(false)}>
              linear
            </ScaleButton>
            <ScaleButton active={log} onClick={() => setLog(true)}>
              log
            </ScaleButton>
          </span>
        )}
      </figcaption>

      <div
        className="grid items-end gap-x-3 border-b border-line pb-1.5 text-[11px]"
        style={{ gridTemplateColumns: columns }}
      >
        <span className="text-slate">Organ</span>
        {layers.map((layer, index) => (
          <span
            key={layer.key}
            className={
              // A rule where the message becomes the protein: the one place
              // in the row where crossing a column means something.
              index > 0 && layer.stage !== layers[index - 1].stage
                ? "border-l border-line pl-3"
                : ""
            }
          >
            <span className="block text-ink">{layer.label}</span>
            <span className="block text-slate opacity-80">
              {layer.unit} · {layer.organs}{" "}
              {layer.organs === 1 ? "organ" : "organs"}
            </span>
          </span>
        ))}
        <span className="text-right text-slate">Reading</span>
      </div>

      <ul className="divide-y divide-line">
        {shown.map((row) => (
          <Organ
            key={row.organ}
            row={row}
            layers={layers}
            columns={columns}
            width={width}
            open={open === row.organ}
            onToggle={() => setOpen(open === row.organ ? "" : row.organ)}
          />
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {hidden > 0 && (
          <button
            type="button"
            onClick={() => setAll(true)}
            className="text-[12px] text-azure-deep transition-colors hover:underline"
          >
            Show all {rows.length} organs
          </button>
        )}
        {all && rows.length > DEFAULT_SHOWN && (
          <button
            type="button"
            onClick={() => setAll(false)}
            className="text-[12px] text-azure-deep transition-colors hover:underline"
          >
            Show the top {DEFAULT_SHOWN}
          </button>
        )}
        {log && (
          <span className="text-[11px] text-slate">
            Log scale: bar length is not proportional to the value. The figures
            are. Graded levels stay on their four steps.
          </span>
        )}
      </div>

      <Footnotes dogma={dogma} />
    </figure>
  );
}

function Organ({
  row,
  layers,
  columns,
  width,
  open,
  onToggle,
}: {
  row: DogmaRow;
  layers: DogmaLayer[];
  columns: string;
  width: (layer: DogmaLayer, value: number | null | undefined) => number;
  open: boolean;
  onToggle: () => void;
}) {
  // Expandable only when the row merges more than one source entry.
  const foldable = layers.some((layer) => (row.cells[layer.key]?.merged ?? 0) > 1);

  return (
    <li>
      <div
        className={`grid items-center gap-x-3 py-2 ${
          foldable ? "cursor-pointer hover:bg-frost" : ""
        }`}
        style={{ gridTemplateColumns: columns }}
        onClick={foldable ? onToggle : undefined}
        role={foldable ? "button" : undefined}
        tabIndex={foldable ? 0 : undefined}
        aria-expanded={foldable ? open : undefined}
        onKeyDown={
          foldable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onToggle();
                }
              }
            : undefined
        }
      >
        <span className="flex min-w-0 items-center gap-1 text-[12px] text-ink">
          {foldable ? (
            <ChevronRight
              size={13}
              aria-hidden="true"
              className={`shrink-0 text-slate transition-transform ${open ? "rotate-90" : ""}`}
            />
          ) : (
            <span className="w-[13px] shrink-0" aria-hidden="true" />
          )}
          <span className="truncate" title={row.organ}>
            {row.organ}
          </span>
        </span>

        {layers.map((layer, index) => (
          <Measure
            key={layer.key}
            layer={layer}
            cell={row.cells[layer.key]}
            width={width}
            divided={index > 0 && layer.stage !== layers[index - 1].stage}
          />
        ))}

        <span className="text-right text-[11px] leading-tight text-slate">
          {row.reading}
        </span>
      </div>

      {open && <Members row={row} layers={layers} columns={columns} width={width} />}
    </li>
  );
}

function Measure({
  layer,
  cell,
  width,
  divided,
}: {
  layer: DogmaLayer;
  cell: DogmaCell | undefined;
  width: (layer: DogmaLayer, value: number | null | undefined) => number;
  divided: boolean;
}) {
  const edge = divided ? "border-l border-line pl-3" : "";
  const bar = width(layer, cell?.value);
  if (!cell || cell.value === null) {
    // Never blank. A blank cell reads as zero; this one says it was not
    // measured, which is a different fact.
    return <span className={`text-[11px] text-slate ${edge}`}>not measured</span>;
  }
  return (
    <span className={`block min-w-0 ${edge}`}>
      <span className="flex items-baseline gap-1.5">
        <span className="font-mono text-[12px] tabular-nums text-ink">
          {cell.display}
        </span>
        {cell.merged > 1 && (
          <span
            className="text-[10px] text-slate"
            title={`Highest of ${cell.merged}: ${cell.peak_tissue}`}
          >
            of {cell.merged}
          </span>
        )}
      </span>
      {bar >= 0 && (
        <span className="mt-1 block h-[8px] rounded-full bg-mist">
          <span
            className="block h-full rounded-r-[4px] bg-azure transition-[width]"
            style={{ width: `${bar}%` }}
          />
        </span>
      )}
    </span>
  );
}

function Members({
  row,
  layers,
  columns,
  width,
}: {
  row: DogmaRow;
  layers: DogmaLayer[];
  columns: string;
  width: (layer: DogmaLayer, value: number | null | undefined) => number;
}) {
  return (
    <div
      className="grid gap-x-3 bg-frost px-0 pb-3 pt-1 text-[11px]"
      style={{ gridTemplateColumns: columns }}
    >
      <span className="pl-[19px] text-slate">
        {row.organ} is made of
      </span>
      {layers.map((layer, index) => {
        const cell = row.cells[layer.key];
        const edge = index > 0 && layer.stage !== layers[index - 1].stage
          ? "border-l border-line pl-3"
          : "";
        if (!cell || !cell.members.length) {
          return <span key={layer.key} className={`text-slate ${edge}`}>none</span>;
        }
        return (
          <ul key={layer.key} className={`space-y-1 ${edge}`}>
            {cell.members.map((member) => (
              <li key={member.tissue} className="min-w-0">
                {/* The name gets a line of its own and wraps: a cell type
                    cut to "lung /..." says nothing. */}
                <MemberName name={member.tissue} />
                <span className="block font-mono tabular-nums text-ink">{member.display}</span>
                {/* Members sit on the layer's own scale, so a sub-bar is
                    directly comparable with the organ bar above it. */}
                {width(layer, member.value) >= 0 && (
                  <span className="mt-0.5 block h-[5px] rounded-full bg-mist">
                    <span
                      className="block h-full rounded-r-[3px] bg-azure"
                      style={{ width: `${width(layer, member.value)}%` }}
                    />
                  </span>
                )}
              </li>
            ))}
          </ul>
        );
      })}
      <span />
    </div>
  );
}

/** "lung / alveolar cells type II": the tissue muted, the cell type plain. */
export function MemberName({ name }: { name: string }) {
  const [tissue, cell] = name.includes(" / ") ? name.split(" / ", 2) : ["", name];
  return (
    <span className="block break-words leading-snug text-ink" title={name}>
      {tissue && <span className="text-slate">{tissue} / </span>}
      {cell}
    </span>
  );
}

function Footnotes({ dogma }: { dogma: Dogma }) {
  const stray = Object.entries(dogma.unmatched).filter(([, list]) => list.length);
  const thin = dogma.layers.filter((layer) => layer.sparse);
  if (!dogma.missing.length && !stray.length && !thin.length) return null;
  return (
    <div className="mt-3 space-y-1 border-t border-line pt-2.5 text-[11px] text-slate">
      {thin.map((layer) => (
        <p key={layer.key}>
          <span className="text-ink">{layer.label}</span> covers{" "}
          {layer.organs} of {dogma.organs} organs
          {layer.organs < MIN_BARS
            ? ", too few for a scale: figures only"
            : "; a gap can be an organ not assayed"}
          .
        </p>
      ))}
      {dogma.missing.map((layer) => (
        <p key={layer.key}>
          <span className="text-ink">{layer.label}</span> not charted:{" "}
          {layer.reason}.
        </p>
      ))}
      {stray.map(([key, list]) => (
        <p key={key}>
          Measured, not an organ (off the axis):{" "}
          {list.join(", ")}.
        </p>
      ))}
    </div>
  );
}

function ScaleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-2 py-0.5 text-[11px] transition-colors ${
        active ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"
      }`}
    >
      {children}
    </button>
  );
}

