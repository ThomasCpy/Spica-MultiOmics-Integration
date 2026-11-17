import type { GeneRecord } from "../bridge";

// Tractability and clinical precedent. Two views over the record:
//
// The tractability matrix: the Open Targets framework, each category for
// each modality, met or not met. Open Targets fixes the categories, so an
// unmet category is a finding ("no structure with a ligand"), not a gap. It
// shows as a hollow mark beside the met ones.
//
// Drugs by phase: each drug and candidate that ChEMBL records against the
// target, under the highest phase it reached. The list is complete: a
// target with sixty drugs shows sixty.

const FRAMEWORK: { modality: string; categories: string[] }[] = [
  {
    modality: "Small molecule",
    categories: ["Approved Drug", "Advanced Clinical", "Phase 1 Clinical", "Structure with Ligand",
      "High-Quality Ligand", "High-Quality Pocket", "Med-Quality Pocket", "Druggable Family"],
  },
  {
    modality: "Antibody",
    categories: ["Approved Drug", "Advanced Clinical", "Phase 1 Clinical", "UniProt loc high conf",
      "GO CC high conf", "UniProt loc med conf", "UniProt SigP or TMHMM", "GO CC med conf",
      "Human Protein Atlas loc"],
  },
  {
    modality: "PROTAC",
    categories: ["Approved Drug", "Advanced Clinical", "Phase 1 Clinical", "Literature",
      "UniProt Ubiquitination", "Database Ubiquitination", "Half-life Data", "Small Molecule Binder"],
  },
  { modality: "Other clinical", categories: ["Approved Drug", "Advanced Clinical", "Phase 1 Clinical"] },
];
const CLINICAL = 3; // the first three categories of every modality are clinical precedent

const PHASES = ["approved", "phase 3", "phase 2", "phase 1", "early phase 1"] as const;
const PHASE_LABEL: Record<string, string> = {
  approved: "Approved",
  "phase 3": "Phase 3",
  "phase 2": "Phase 2",
  "phase 1": "Phase 1",
  "early phase 1": "Early phase 1",
  other: "Phase unknown",
};

export function Druggability({ record }: { record: GeneRecord }) {
  const tractability = record.fields.tractability;
  const drugs = record.fields.chembl_drugs;
  const met = new Set(
    !tractability?.state && Array.isArray(tractability?.value)
      ? (tractability.value as string[])
      : [],
  );
  return (
    <>
      <div className="border-t border-line px-5 py-4">
        <p className="mb-3 text-[12px] text-slate">
          Tractability by modality, Open Targets. Filled: met; hollow: not met. First three per modality:
          clinical precedent.
          {tractability?.provenance && (
            <span className="opacity-70">
              {" "}
              {tractability.provenance.source} {tractability.provenance.version}
            </span>
          )}
        </p>
        {tractability?.state ? (
          <p className="text-[13px] text-slate">{tractability.reason}</p>
        ) : (
          <div className="space-y-3">
            {FRAMEWORK.map(({ modality, categories }) => {
              const count = categories.filter((c) => met.has(`${modality}: ${c}`)).length;
              return (
                <div key={modality} className="grid grid-cols-[120px_1fr_auto] items-start gap-3">
                  <span className="pt-0.5 text-[13px] text-ink">{modality}</span>
                  <ul className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    {categories.map((category, at) => {
                      const on = met.has(`${modality}: ${category}`);
                      return (
                        <li
                          key={category}
                          className={`flex items-center gap-1.5 text-[12px] ${
                            at === CLINICAL ? "border-l border-line pl-3" : ""
                          } ${on ? "text-ink" : "text-slate"}`}
                        >
                          <span
                            aria-hidden="true"
                            className={`inline-block size-[11px] rounded-full border-2 ${
                              on ? "border-azure-deep bg-azure-deep" : "border-line bg-surface"
                            }`}
                          />
                          <span className={on ? "" : "line-through decoration-line"}>{category}</span>
                          <span className="sr-only">{on ? "met" : "not met"}</span>
                        </li>
                      );
                    })}
                  </ul>
                  <span className="pt-0.5 font-mono text-[12px] tabular-nums text-ink">
                    {count} of {categories.length}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-line px-5 py-4">
        <p className="mb-3 text-[12px] text-slate">
          Drugs and candidates by highest phase, ChEMBL.
          {drugs?.provenance && (
            <span className="opacity-70">
              {" "}
              {drugs.provenance.source} {drugs.provenance.version}
            </span>
          )}
        </p>
        {drugs?.state ? (
          <p className="text-[13px] text-slate">{drugs.reason}</p>
        ) : (
          <Phases items={(drugs?.value as string[]) ?? []} />
        )}
      </div>
    </>
  );
}

type Drug = { name: string; phase: string; action: string };

function parse(item: string): Drug {
  // "ALIROCUMAB (approved, inhibitor)", as the ChEMBL adapter writes it.
  const found = item.match(/^(.*) \(([^,()]+)(?:, ([^()]+))?\)$/);
  if (!found) return { name: item, phase: "other", action: "" };
  const phase = (PHASES as readonly string[]).includes(found[2]) ? found[2] : "other";
  return { name: found[1], phase, action: found[3] ?? "" };
}

function Phases({ items }: { items: string[] }) {
  const drugs = items.map(parse);
  const columns = [...PHASES, "other"]
    .map((phase) => ({ phase, drugs: drugs.filter((d) => d.phase === phase) }))
    .filter((column) => column.drugs.length > 0);
  const most = Math.max(...columns.map((c) => c.drugs.length), 1);
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))` }}>
      {columns.map(({ phase, drugs: list }) => (
        <div key={phase} className="min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[12px] font-medium text-ink">{PHASE_LABEL[phase]}</span>
            <span className="font-mono text-[12px] tabular-nums text-ink">{list.length}</span>
          </div>
          <span className="mt-1 block h-[7px] rounded-full bg-mist">
            <span
              className="block h-full rounded-r-[4px] bg-azure"
              style={{ width: `${Math.max(4, (100 * list.length) / most)}%` }}
            />
          </span>
          <ul className="mt-2 space-y-1">
            {list.map((drug) => (
              <li key={`${drug.name}-${drug.action}`} className="text-[12px] leading-snug">
                <span className="break-words text-ink">{drug.name}</span>
                {drug.action && <span className="ml-1 text-slate">{drug.action}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
