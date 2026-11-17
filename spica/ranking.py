"""The ranked table: candidates scored on visible criteria that the user weighs.

`spica/compare.py` does not rank: the best gene depends on the modality,
the indication and the accepted safety risk. This module ranks only on
those terms. Each criterion has a name, says what it reads and how it gives
a score from 0 to 1, and has a weight that the user sets. A preset per
modality is a start point, never a verdict.

Rules that keep the table honest:

- The score of a gene on a criterion depends on its own record only, never
  on the other genes. A gene thus scores the same in any list, and a new
  gene never changes the score of another one.
- A criterion with no data for a gene says so. It stays out of the total of
  that gene, or counts as zero on request. The share of weight with data
  shows beside the score.
- The total is the weighted mean of the scores. The contribution of each
  criterion is thus readable in the row.

Deterministic, as the records are: the same genes, weights and releases
give the same table.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from spica.record import GeneRecord, NullState

Measure = tuple[float | None, str]


@dataclass(frozen=True)
class Context:
    """What a criterion may need beyond the record."""

    indication: str = ""
    mirror: Any = None


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    group: str
    describe: str
    reads: tuple[str, ...]
    measure: Callable[[GeneRecord, Context], Measure]
    #: Benchmark modalities whose label this criterion carries: scoring
    #: approved-antibody targets on clinical phase would only find the label.
    leaks: tuple[str, ...] = ()


# -- reading the record -------------------------------------------------------------------------


def _value(record: GeneRecord, name: str) -> tuple[Any, str]:
    """(value, why missing): a not-found field is an answer (None, "none"),
    a failed or not-covered one is missing data (None, reason)."""
    value = record.fields.get(name)
    if value is None:
        return None, "the field was never built"
    if value.present:
        return value.value, ""
    if value.state is NullState.NOT_FOUND:
        return None, "none"
    return None, value.reason or (value.state.value if value.state else "missing")


def _number(record: GeneRecord, name: str, scale: float, unit: str = "",
            none_is_zero: bool = False) -> Measure:
    value, why = _value(record, name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value) / scale)), f"{value:g}{unit}"
    if why == "none" and none_is_zero:
        return 0.0, "none recorded"
    return None, why if why != "none" else "none recorded"


def _tau(name: str) -> Callable[[GeneRecord, Context], Measure]:
    return lambda record, context: _number(record, name, 1.0)


def _fold(record: GeneRecord, context: Context) -> Measure:
    value, why = _value(record, "rna_fold_over_median")
    if isinstance(value, (int, float)):
        # On a log scale: 10x is a third of the way, 1000x and beyond is 1.
        return max(0.0, min(1.0, math.log10(max(float(value), 1.0)) / 3)), f"{value:g}x"
    return None, why or "not measured"


def _surface(record: GeneRecord, context: Context) -> Measure:
    from spica.locations import compartments

    found = compartments(record)
    rows = {row["name"]: row for row in found.get("compartments", [])}
    if not any(row["count"] for row in rows.values()):
        return None, "no location data"
    best = max((rows.get(name, {"count": 0})["count"], name)
               for name in ("Plasma membrane", "Extracellular"))
    if not best[0]:
        return 0.0, "not at the surface"
    return best[0] / 3, f"{best[1].lower()}, {best[0]} of 3 sources"


#: Open Targets' tractability buckets that predict, by modality; the
#: clinical ones (approved, advanced clinical, phase 1) are precedent, and
#: are scored apart.
PREDICTIVE = {
    "Small molecule": ("Structure with Ligand", "High-Quality Ligand", "High-Quality Pocket",
                       "Med-Quality Pocket", "Druggable Family"),
    "Antibody": ("UniProt loc high conf", "GO CC high conf", "UniProt loc med conf",
                 "UniProt SigP or TMHMM", "GO CC med conf", "Human Protein Atlas loc"),
    "PROTAC": ("Literature", "UniProt Ubiquitination", "Database Ubiquitination", "Half-life Data",
               "Small Molecule Binder"),
}
CLINICAL = ("Approved Drug", "Advanced Clinical", "Phase 1 Clinical")


def _tractability(modality: str) -> Callable[[GeneRecord, Context], Measure]:
    def measure(record: GeneRecord, context: Context) -> Measure:
        value, why = _value(record, "tractability")
        if value is None and why != "none":
            return None, why
        present = {line.split(":", 1)[1].strip() for line in value or []
                   if line.split(":", 1)[0].strip() == modality and ":" in line}
        buckets = PREDICTIVE[modality]
        hit = [bucket for bucket in buckets if bucket in present]
        return len(hit) / len(buckets), f"{len(hit)} of {len(buckets)} predictive buckets"
    return measure


def _precedent(record: GeneRecord, context: Context) -> Measure:
    return _number(record, "chembl_max_phase", 4.0, "", none_is_zero=True)


def _matches(name: str, indication: str) -> bool:
    return indication.lower() in name.lower()


def _association(record: GeneRecord, context: Context) -> Measure:
    value, why = _value(record, "disease_associations")
    if value is None:
        return (0.0, "none recorded") if why == "none" else (None, why)
    if context.indication:
        scores = [(score, name) for name, score in value.items()
                  if _matches(name, context.indication)]
        if not scores:
            return 0.0, f"no disease matching {context.indication}"
        score, name = max(scores)
        return float(score), f"{name} {score:g}"
    name, score = max(value.items(), key=lambda kv: (kv[1], kv[0]))
    return float(score), f"{name} {score:g}"


def _genetics(record: GeneRecord, context: Context) -> Measure:
    """Human genetics: pathogenic variants (ClinVar) and genome-wide GWAS
    associations, half the score each; for the indication's diseases when
    one is set and the disease join can be read, else for the gene."""
    if context.indication and context.mirror is not None:
        from spica import genetics

        found = genetics.evidence(record.resolution.symbol, record.resolution.ensembl_gene_id,
                                  context.mirror)
        if not found.get("error"):
            rows = [row for row in found["rows"] if _matches(row["disease"], context.indication)]
            rare = any(row["pathogenic"] for row in rows)
            common = any(row.get("gwas", 0) >= 7.3 for row in rows)
            found = " and ".join(name for name, present in (("pathogenic variants", rare),
                                                            ("genome-wide GWAS", common)) if present)
            return 0.5 * rare + 0.5 * common, f"{found or 'neither'} for {context.indication}"
    pathogenic, why_rare = _value(record, "clinvar_pathogenic")
    traits, why_common = _value(record, "gwas_genome_wide_traits")
    if pathogenic is None and why_rare != "none" and traits is None and why_common != "none":
        return None, why_rare
    rare, common = bool(pathogenic), bool(traits)
    return 0.5 * rare + 0.5 * common, (f"{pathogenic or 0} pathogenic variants, "
                                       f"{traits or 0} genome-wide GWAS traits")


def _lineages(record: GeneRecord) -> list[tuple[float, str, int]]:
    value, _ = _value(record, "depmap_lineage_dependency")
    out = []
    for key, share in (value or {}).items():
        name, _, count = key.rpartition(", ")
        found = re.match(r"(\d+)", count)
        out.append((float(share), name, int(found.group(1)) if found else 0))
    return out


def _selective(record: GeneRecord, context: Context) -> Measure:
    essential, why = _value(record, "depmap_common_essential")
    if essential is None:
        return None, why if why != "none" else "not screened"
    if str(essential).startswith("yes"):
        return 0.0, "common essential"
    gathered = [item for item in _lineages(record) if item[2] >= 10]
    if not gathered:
        return 0.0, "no lineage of 10 lines or more"
    share, name, lines = max(gathered)
    overall, _ = _value(record, "depmap_dependent_share")
    overall = float(overall or 0)
    # Needed in one lineage and spared in the rest: a gene most lines need is
    # not selective however high its best lineage reads.
    return (share / 100) * (1 - overall / 100), (f"{name} {share:g}% of {lines} lines, "
                                                f"{overall:g}% overall")


def _spared(record: GeneRecord, context: Context) -> Measure:
    essential, why = _value(record, "depmap_common_essential")
    share, _ = _value(record, "depmap_dependent_share")
    if essential is None:
        return None, why if why != "none" else "not screened"
    if str(essential).startswith("yes"):
        return 0.0, "common essential"
    share = float(share or 0)
    return 1 - share / 100, f"{share:g}% of lines depend on it"


def _knockout(record: GeneRecord, context: Context) -> Measure:
    value, why = _value(record, "mouse_phenotypes")
    if value is None:
        return None, "no knockout phenotypes recorded" if why == "none" else why
    lethal = [p for p in value if "lethal" in p.lower()]
    if lethal:
        return 0.0, lethal[0]
    return 1.0, f"{len(value)} phenotypes, none lethal"


def _liabilities(record: GeneRecord, context: Context) -> Measure:
    value, why = _value(record, "safety_liabilities")
    if value is None:
        return (1.0, "none recorded") if why == "none" else (None, why)
    return 1 / (1 + len(value)), f"{len(value)} recorded"


def _identity(species: str) -> Callable[[GeneRecord, Context], Measure]:
    return lambda record, context: _number(record, f"{species}_protein_identity", 100.0, "%",
                                           none_is_zero=True)


def _structure(record: GeneRecord, context: Context) -> Measure:
    return _number(record, "pdb_coverage", 100.0, "% of the sequence", none_is_zero=True)


def _fold_confidence(record: GeneRecord, context: Context) -> Measure:
    return _number(record, "alphafold_mean_plddt", 100.0, " mean pLDDT")


CRITERIA: tuple[Criterion, ...] = (
    Criterion("specificity", "RNA specificity", "Expression",
              "Tau over GTEx tissues: 0, uniform; 1, one tissue. Fewer tissues, less off-tissue risk.",
              ("rna_specificity_tau",), _tau("rna_specificity_tau")),
    Criterion("cell_specificity", "Cell-type specificity", "Expression",
              "Tau over the HPA single-cell atlas, as tissue tau.",
              ("single_cell_tau",), _tau("single_cell_tau")),
    Criterion("peak", "Peak over typical tissue", "Expression",
              "Peak tissue over median tissue, log scale: 10x scores 1/3; 1000x or more scores 1.",
              ("rna_fold_over_median",), _fold),
    Criterion("surface", "At the cell surface", "Expression",
              "Sources of three (UniProt, HPA, GO) with a plasma membrane or extracellular location. "
              "Antibody and CAR access.",
              ("uniprot_subcellular_locations", "hpa_subcellular_main", "go_component"), _surface),
    Criterion("ab_tractability", "Antibody tractability", "Druggability",
              "Share of Open Targets predictive antibody buckets met (location, signal peptide). "
              "Clinical buckets scored separately.",
              ("tractability",), _tractability("Antibody")),
    Criterion("sm_tractability", "Small-molecule tractability", "Druggability",
              "Share of Open Targets predictive small-molecule buckets met: ligands, pockets, "
              "druggable family.", ("tractability",), _tractability("Small molecule")),
    Criterion("protac_tractability", "PROTAC tractability", "Druggability",
              "Share of Open Targets predictive PROTAC buckets met: ubiquitination, half-life, "
              "small-molecule binder.", ("tractability",), _tractability("PROTAC")),
    Criterion("structure", "Experimental structure", "Druggability",
              "Share of the sequence in PDB structures.", ("pdb_coverage",), _structure),
    Criterion("fold", "Predicted fold confidence", "Druggability",
              "AlphaFold mean pLDDT, of 100.",
              ("alphafold_mean_plddt",), _fold_confidence),
    Criterion("precedent", "Clinical precedent", "Precedent",
              "Highest phase of a drug on the target; phase 4 (approved) scores 1.",
              ("chembl_max_phase",), _precedent, leaks=("antibody", "small_molecule")),
    Criterion("association", "Disease association", "Disease relevance",
              "Open Targets association score: strongest disease matching the indication, "
              "or strongest overall.",
              ("disease_associations",), _association, leaks=("antibody", "small_molecule")),
    Criterion("genetics", "Human genetics", "Disease relevance",
              "ClinVar pathogenic variants and genome-wide GWAS associations, half each; "
              "indication diseases when set.",
              ("clinvar_pathogenic", "gwas_genome_wide_traits"), _genetics),
    Criterion("selective", "Selective dependency", "Disease relevance",
              "DepMap: dependent share in the most dependent lineage (10 lines or more) times "
              "the non-dependent share of all lines; 0 for a common essential. Oncology profile: "
              "one lineage dependent, others spared.",
              ("depmap_lineage_dependency", "depmap_common_essential"), _selective),
    Criterion("spared", "Healthy cells spared", "Safety",
              "DepMap: 1 minus the dependent share; 0 for a common essential.",
              ("depmap_dependent_share", "depmap_common_essential"), _spared),
    Criterion("knockout", "Knockout tolerated", "Safety",
              "Mouse knockout: 0 with a lethal phenotype; 1 with phenotypes, none lethal.", ("mouse_phenotypes",), _knockout),
    Criterion("liabilities", "Few safety liabilities", "Safety",
              "1/(1+n), n: recorded liabilities.", ("safety_liabilities",),
              _liabilities),
    Criterion("cyno", "Cynomolgus identity", "Translation",
              "Share of the human protein identical in cynomolgus (toxicology species).",
              ("cyno_protein_identity",), _identity("cyno")),
    Criterion("mouse", "Mouse identity", "Translation",
              "Share of the human protein identical in mouse (efficacy models).",
              ("mouse_protein_identity",), _identity("mouse")),
)
BY_KEY = {criterion.key: criterion for criterion in CRITERIA}

#: Weights run 0 to SCALE. Lists and benchmarks saved before the scale
#: was 10 ran 0 to 3; `upgraded` multiplies them by OLD_FACTOR, the factor
#: the presets moved by, so their rankings stay the same.
SCALE = 10
OLD_FACTOR = 3

#: Starting weights per modality. A preset is where the user starts, and
#: every weight stays theirs to change.
PRESETS: dict[str, dict[str, Any]] = {
    "antibody": {"label": "Antibody or ADC", "weights": {
        "surface": 9, "specificity": 6, "cell_specificity": 3, "peak": 3, "ab_tractability": 6,
        "association": 6, "genetics": 3, "spared": 3, "knockout": 3, "liabilities": 3, "cyno": 6}},
    "small_molecule": {"label": "Small molecule", "weights": {
        "sm_tractability": 9, "structure": 6, "fold": 3, "association": 6, "genetics": 6,
        "specificity": 3, "spared": 3, "knockout": 3, "liabilities": 3, "mouse": 3}},
    "cell_therapy": {"label": "CAR-T or cell therapy", "weights": {
        "surface": 9, "specificity": 9, "cell_specificity": 6, "peak": 6, "association": 6,
        "spared": 3, "liabilities": 3}},
    "oncology": {"label": "Oncology dependency", "weights": {
        "selective": 9, "spared": 6, "association": 6, "genetics": 3, "sm_tractability": 3,
        "protac_tractability": 3, "specificity": 3}},
}


def upgraded(saved: dict[str, Any]) -> dict[str, Any]:
    """A saved list or benchmark, its weights on the 0 to 10 scale."""
    if saved.get("scale") == SCALE or not saved.get("weights"):
        return {**saved, "scale": SCALE}
    weights = {key: float(value) * OLD_FACTOR for key, value in saved["weights"].items()}
    return {**saved, "weights": weights, "scale": SCALE}


def weights_for(preset: str) -> dict[str, float]:
    chosen = PRESETS.get(preset, PRESETS["antibody"])["weights"]
    return {criterion.key: float(chosen.get(criterion.key, 0)) for criterion in CRITERIA}


def score(record: GeneRecord, weights: dict[str, float], context: Context,
          missing: str = "skip") -> dict[str, Any]:
    """The row of one gene: the score, value and contribution of each
    criterion, and the weighted mean over the criteria with data. With
    `missing` set to "zero", the mean covers all criteria and missing data
    counts as zero."""
    parts: dict[str, dict[str, Any]] = {}
    total = weighed = available = 0.0
    for criterion in CRITERIA:
        weight = max(0.0, float(weights.get(criterion.key, 0)))
        try:
            value, shown = criterion.measure(record, context)
        except Exception as exc:  # one criterion failing never costs the row
            value, shown = None, f"could not be read: {exc}"
        parts[criterion.key] = {"score": None if value is None else round(value, 4),
                                "value": shown, "weight": weight}
        if not weight:
            continue
        weighed += weight
        if value is None:
            if missing == "zero":
                available += 0  # counted in the denominator, adds nothing
            continue
        available += weight
        total += weight * value
    denominator = weighed if missing == "zero" else available
    for part in parts.values():
        part["contribution"] = (round(part["weight"] * part["score"] / denominator, 4)
                                if denominator and part["score"] is not None and part["weight"]
                                else 0.0)
    return {"symbol": record.resolution.symbol or record.query,
            "hgnc_id": record.resolution.hgnc_id,
            "ensembl_id": record.resolution.ensembl_gene_id,
            "score": round(total / denominator, 4) if denominator else None,
            "coverage": round(available / weighed, 3) if weighed else None,
            "parts": parts}


def rank(records: list[GeneRecord], weights: dict[str, float], indication: str = "",
         missing: str = "skip", mirror=None) -> dict[str, Any]:
    """The ranked table: rows best first, ties by coverage then symbol."""
    context = Context(indication=indication.strip(), mirror=mirror)
    rows = [score(record, weights, context, missing) for record in records
            if record.resolution.resolved]
    rows.sort(key=lambda row: (-(row["score"] if row["score"] is not None else -1),
                               -(row["coverage"] or 0), row["symbol"]))
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
    used = [c for c in CRITERIA if weights.get(c.key, 0)]
    return {
        "rows": rows,
        "criteria": [criterion_dict(c, weights) for c in CRITERIA],
        "weights": {c.key: float(weights.get(c.key, 0)) for c in CRITERIA},
        "indication": indication.strip(),
        "missing": missing,
        "summary": (f"{len(rows)} genes ranked on {len(used)} weighted criteria"
                    + (f" for {indication.strip()}" if indication.strip() else "")
                    + ("; missing data counts as zero" if missing == "zero"
                       else "; a gene is scored on the criteria it has data for")),
    }


def criterion_dict(criterion: Criterion, weights: dict[str, float] | None = None) -> dict[str, Any]:
    return {"key": criterion.key, "label": criterion.label, "group": criterion.group,
            "describe": criterion.describe, "reads": list(criterion.reads),
            "leaks": list(criterion.leaks),
            "weight": float((weights or {}).get(criterion.key, 0))}


def presets() -> dict[str, Any]:
    return {key: {"label": preset["label"], "weights": weights_for(key)}
            for key, preset in PRESETS.items()}
