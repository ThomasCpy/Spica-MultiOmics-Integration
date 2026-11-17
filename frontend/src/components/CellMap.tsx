import { useState } from "react";
import type { Locations } from "../report";

// The location of the protein. Python maps UniProt, HPA and GO onto ten
// compartments (`spica/locations.py`), and this draws them as one cell. The
// shade of a compartment is the number of sources that place the protein
// there, on one azure ramp. The large areas (cytosol, outside) use the pale
// end, so the cell never turns blue overall. The table beside it gives the
// count and the terms of each source. Colour is never the only signal.

// Tokens, so the diagram follows the theme (index.css).
const STRONG = ["var(--color-surface)", "var(--color-seq-1)", "var(--color-seq-2)", "var(--color-seq-3)"];
const SOFT = ["var(--color-surface)", "var(--color-soft-1)", "var(--color-soft-2)", "var(--color-soft-3)"];
const LINE = "var(--color-line)";
const INK = "var(--color-ink)";
const EDGE = "var(--color-edge)";
const FAINT = "var(--color-faint)";

export function CellMap({ locations }: { locations: Locations }) {
  const [focus, setFocus] = useState("");
  const reporting = locations.sources.filter((s) => s.reported);
  if (!reporting.length) return null;
  const total = reporting.length;
  const by = Object.fromEntries(locations.compartments.map((c) => [c.name, c]));
  const level = (name: string) => Math.min(3, Math.round((3 * (by[name]?.count ?? 0)) / total));
  const strong = (name: string) => STRONG[level(name)];
  const soft = (name: string) => SOFT[level(name)];
  const edge = (name: string, base = LINE) =>
    focus === name ? INK : by[name]?.count ? STRONG[Math.max(1, level(name))] : base;
  const hover = (name: string) => ({
    onMouseEnter: () => setFocus(name),
    onMouseLeave: () => setFocus(""),
  });

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-3 text-[12px] text-slate">
        Subcellular location: {reporting.map((s) => s.label).join(", ")}, one compartment set. Shade: number of
        sources in agreement.
      </p>
      <div className="flex flex-wrap items-start gap-6">
        <svg
          viewBox="0 0 400 290"
          width={400}
          height={290}
          role="img"
          aria-label="Cell diagram of where the protein is located"
          className="shrink-0"
        >
          {/* Outside the cell */}
          <rect x={0} y={0} width={400} height={290} rx={14} fill={soft("Extracellular")} {...hover("Extracellular")}
            stroke={focus === "Extracellular" ? INK : "none"} strokeWidth={2} />
          {[[372, 30], [352, 18], [384, 58], [24, 260], [44, 274]].map(([cx, cy]) => (
            <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={5} fill={by.Extracellular?.count ? strong("Extracellular") : LINE}
              {...hover("Extracellular")} />
          ))}
          {/* The cell: cytosol inside, the plasma membrane its edge */}
          <ellipse cx={200} cy={148} rx={168} ry={118} fill={soft("Cytosol")}
            stroke={edge("Plasma membrane")} strokeWidth={8} {...hover("Plasma membrane")} />
          <ellipse cx={200} cy={148} rx={158} ry={108} fill="transparent" {...hover("Cytosol")} />
          {/* Cytoskeleton */}
          {[[96, 220, 330, 70], [80, 110, 345, 190], [190, 262, 260, 34]].map(([x1, y1, x2, y2]) => (
            <line key={`${x1}-${y1}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={edge("Cytoskeleton", FAINT)}
              strokeWidth={focus === "Cytoskeleton" ? 3 : 2} strokeDasharray="10 5" {...hover("Cytoskeleton")} />
          ))}
          {/* Endoplasmic reticulum: folds around the nucleus */}
          {[66, 78, 90].map((r) => (
            <path key={r} d={`M ${145 - r * 0.5} ${150 + r * 0.866} A ${r} ${r} 0 1 1 ${145 + r * 0.866} ${150 - r * 0.5}`}
              fill="none" stroke={by["Endoplasmic reticulum"]?.count ? strong("Endoplasmic reticulum") : LINE}
              strokeWidth={6} strokeLinecap="round" {...hover("Endoplasmic reticulum")}
              opacity={focus && focus !== "Endoplasmic reticulum" ? 0.6 : 1} />
          ))}
          {/* Nucleus */}
          <circle cx={145} cy={150} r={50} fill={strong("Nucleus")} stroke={edge("Nucleus", EDGE)} strokeWidth={3}
            {...hover("Nucleus")} />
          {/* Golgi: a stack of arcs */}
          {[0, 11, 22].map((d) => (
            <path key={d} d={`M ${246 + d * 0.2} ${92 + d} q 30 -16 60 0`} fill="none"
              stroke={by["Golgi apparatus"]?.count ? strong("Golgi apparatus") : LINE}
              strokeWidth={7} strokeLinecap="round" {...hover("Golgi apparatus")} />
          ))}
          {/* Vesicles */}
          {[[318, 136], [300, 160], [332, 168], [286, 136], [270, 196]].map(([cx, cy]) => (
            <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={8} fill={strong("Vesicles")}
              stroke={edge("Vesicles", EDGE)} strokeWidth={2} {...hover("Vesicles")} />
          ))}
          {/* Peroxisome */}
          <circle cx={238} cy={232} r={10} fill={strong("Peroxisome")} stroke={edge("Peroxisome", EDGE)}
            strokeWidth={2} {...hover("Peroxisome")} />
          {/* Mitochondria */}
          {[[300, 222, -15], [196, 238, 10]].map(([cx, cy, angle]) => (
            <ellipse key={`${cx}-${cy}`} cx={cx} cy={cy} rx={26} ry={11} transform={`rotate(${angle} ${cx} ${cy})`}
              fill={strong("Mitochondria")} stroke={edge("Mitochondria", EDGE)} strokeWidth={2}
              {...hover("Mitochondria")} />
          ))}
        </svg>

        <table className="min-w-[300px] flex-1 text-[12px]">
          <thead>
            <tr className="text-left text-slate">
              <th className="py-1 font-medium">Compartment</th>
              <th className="py-1 text-right font-medium">Sources</th>
              {locations.sources.map((s) => (
                <th key={s.key} className="w-[54px] py-1 text-center font-medium" title={s.stamp}>
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {locations.compartments.map((row) => (
              <tr
                key={row.name}
                {...hover(row.name)}
                className={focus === row.name ? "bg-mist" : ""}
              >
                <td className="py-1.5">
                  <span className="mr-2 inline-block size-[10px] rounded-[3px] align-[-1px]"
                    style={{ background: row.count ? STRONG[Math.max(1, Math.min(3, Math.round((3 * row.count) / total)))] : LINE }} />
                  <span className={row.count ? "text-ink" : "text-slate"}>{row.name}</span>
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-ink">
                  {row.count ? `${row.count} of ${total}` : ""}
                </td>
                {locations.sources.map((s) => {
                  const terms = row.sources[s.key];
                  return (
                    <td key={s.key} className="py-1.5 text-center" title={terms?.join(", ") ?? ""}>
                      {terms ? (
                        <span className="inline-flex items-center gap-1">
                          <span aria-hidden="true" className="inline-block size-[9px] rounded-full bg-azure-deep" />
                          {s.key === "hpa" && row.main && (
                            <span className="text-[10px] text-azure-deep">main</span>
                          )}
                          <span className="sr-only">{terms.join(", ")}</span>
                        </span>
                      ) : !s.reported ? (
                        <span className="text-[11px] text-slate" title={`${s.label} has no location data for this protein`}>no data</span>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(locations.topology.length > 0 || locations.unplaced.length > 0) && (
        <p className="mt-3 text-[11px] leading-relaxed text-slate">
          {locations.topology.length > 0 && <>Membrane topology (UniProt): {locations.topology.join(", ")}. </>}
          {locations.unplaced.length > 0 && (
            <>Not a compartment: {locations.unplaced.map((u) => `${u.term} (${u.source})`).join(", ")}.</>
          )}
        </p>
      )}
    </div>
  );
}
