import type { GeneRecord } from "../bridge";

// The part of the human protein that the two model species keep: the share
// of identical residues in the closest ortholog. The scale is fixed, 0 to
// 100, so the charts of two genes read alike. Orthology type and ortholog
// name sit beside each bar. A species with no ortholog says so.

const SPECIES = [
  { prefix: "mouse", label: "Mouse" },
  { prefix: "cyno", label: "Cynomolgus" },
];

export function Orthologs({ record }: { record: GeneRecord }) {
  const rows = SPECIES.map(({ prefix, label }) => {
    const identity = record.fields[`${prefix}_protein_identity`];
    const orthology = record.fields[`${prefix}_orthology`];
    const named = record.fields[`${prefix}_orthologs`];
    return {
      label,
      value: !identity?.state && typeof identity?.value === "number" ? identity.value : null,
      kind: !orthology?.state && typeof orthology?.value === "string" ? orthology.value : "",
      first: !named?.state && Array.isArray(named?.value) ? String(named.value[0]).split(" ")[0] : "",
      more: !named?.state && Array.isArray(named?.value) ? named.value.length - 1 : 0,
      reason: identity?.state ? identity.reason : "",
    };
  });
  if (rows.every((row) => row.value === null && !row.reason)) return null;

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-3 text-[12px] text-slate">
        Protein identity, closest ortholog per model species: share of the human protein identical. Ensembl Compara.
      </p>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.label} className="grid grid-cols-[96px_minmax(0,1fr)_56px_minmax(0,1.2fr)] items-center gap-3 text-[12px]">
            <span className="text-ink">{row.label}</span>
            {row.value === null ? (
              <span className="col-span-3 text-slate">{row.reason || "no ortholog recorded"}</span>
            ) : (
              <>
                <span className="block h-[14px] bg-mist">
                  <span className="block h-full rounded-r-[4px] bg-azure" style={{ width: `${row.value}%` }} />
                </span>
                <span className="text-right font-mono tabular-nums text-ink">{row.value.toFixed(1)}%</span>
                <span className="truncate text-slate" title={`${row.first}${row.more > 0 ? ` and ${row.more} more` : ""}, ${row.kind}`}>
                  <span className="font-mono text-ink">{row.first}</span>
                  {row.more > 0 && ` and ${row.more} more`}, {row.kind}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
