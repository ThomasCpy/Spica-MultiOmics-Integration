"""The central dogma on one axis: transcript, then protein.

GTEx says `Brain - Cerebellum`, HPA says `cerebellum`, the antibody data
says `cerebral cortex`. Three vocabularies for one body. A record can thus
hold an RNA profile and a protein profile and still not answer the central
question: whether the protein is where the transcript is.

Each layer thus maps onto a canonical organ, and the organ is the row. The
method comes from the tissue atlas of the MultiOmics integrator, with its
two rules for honesty:

*Several tissues to one organ take the maximum.* GTEx has thirteen brain
regions; the brain row is the highest of them. The row gives the number of
merged regions: "brain 23 TPM" from thirteen regions is a different claim
from "brain 23 TPM" from one.

*A tissue that maps to no organ is reported, never dropped.* A silent drop
would reduce the evidence. Cell lines (`Cells - EBV-transformed
lymphocytes`, `Cells - Cultured fibroblasts`) get their own row, "cultured
cells". They never merge into a real organ.

Units never mix. TPM, nTPM and staining intensity are three scales with no
common unit. Each layer is normalised to its own peak and keeps its own
figure. There is no shared axis here, and there must never be one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spica import metrics
from spica.record import GeneRecord

#: Antibody staining, weakest first, so a graded profile can be ranked and
#: normalised like a numeric one.
LEVELS = ("not detected", "low", "medium", "high")
LEVEL_VALUE = {level: index for index, level in enumerate(LEVELS)}


@dataclass(frozen=True)
class Layer:
    """One measurement layer, and where in the record it comes from."""

    key: str
    field: str
    label: str
    unit: str
    kind: str  # "number" | "level"
    stage: str  # "transcript" | "protein"
    #: A finer field to prefer when the record has it: cell types within
    #: tissues, keyed "tissue / cell type". The organ is read from the
    #: tissue part only, so "lung / endothelial cells" stays lung.
    finer: str = ""


#: In dogma order. Transcript layers first, then protein: the point of the
#: view is reading left to right and seeing where the chain breaks.
LAYERS: tuple[Layer, ...] = (
    Layer("gtex", "gtex_tissue_tpm", "RNA (GTEx)", "median TPM", "number",
          "transcript"),
    Layer("hpa_rna", "hpa_rna_tissue_ntpm", "RNA (HPA)", "nTPM", "number",
          "transcript"),
    # Single-cell RNA, cell types within tissues: present once HPA's
    # rna_single_cell_type_tissue file is mirrored, and folded like the
    # antibody cell types, so an organ opens into its clusters.
    Layer("hpa_sc", "hpa_single_cell_tissue", "RNA (single cell)", "nCPM", "number",
          "transcript"),
    Layer("hpa_ihc", "hpa_protein_tissue_level", "Protein (antibody)", "level",
          "level", "protein", finer="hpa_protein_cell_type_level"),
    Layer("hpa_ms", "hpa_protein_tissue_intensity", "Protein (mass spec)",
          "intensity", "number", "protein"),
)


@dataclass
class Member:
    """One tissue or cell type that was folded into an organ."""

    tissue: str
    value: float
    display: str

    def to_dict(self) -> dict[str, Any]:
        return {"tissue": self.tissue, "value": self.value,
                "display": self.display}


@dataclass
class Cell:
    value: float | None = None
    display: str = ""
    members: list[Member] = field(default_factory=list)
    share: float = 0.0  # against this layer's own peak, 0 to 1

    @property
    def peak_tissue(self) -> str:
        return self.members[0].tissue if self.members else ""

    def to_dict(self) -> dict[str, Any]:
        # Members ride along so an organ can open into the cell types and
        # regions it stands for. The row shows one number; the number is
        # always answerable for.
        ordered = sorted(self.members, key=lambda m: (-m.value, m.tissue))
        return {
            "value": self.value,
            "display": self.display,
            "members": [member.to_dict() for member in ordered],
            "merged": len(ordered),
            "peak_tissue": ordered[0].tissue if ordered else "",
            "share": round(self.share, 4),
        }


@dataclass
class Row:
    organ: str
    cells: dict[str, Cell] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organ": self.organ,
            "cells": {key: cell.to_dict() for key, cell in self.cells.items()},
            "reading": reading(self),
        }


def readable(value: float) -> str:
    """A figure a person can read, without losing which is bigger.

    Mass-spec intensities run to eight digits and TPMs to two decimals; one
    format has to carry both. The exact number stays on the cell, so this
    only ever changes how it is written, never what is compared.
    """
    if value == 0:
        return "0"  # not detected reads as nothing, not as a measured 0.00
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 10_000:
        return f"{value:,.0f}"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _level(value: Any) -> float | None:
    rank = LEVEL_VALUE.get(str(value).strip().lower())
    return None if rank is None else float(rank)


#: How a cell-type key separates its tissue from its cell type.
CELL_TYPE_KEY = " / "


def project(profile: dict[str, Any], kind: str) -> tuple[dict[str, Cell], list[str]]:
    """Map a per-tissue (or per tissue and cell type) profile onto organs.

    A key "lung / alveolar cells type II" goes to its tissue, "lung", and
    stays whole as the member. The organ row thus opens into cell types.

    Returns the organ cells and the labels with no organ. The caller shows
    these labels; it does not discard them.
    """
    folded: dict[str, Cell] = {}
    unmatched: list[str] = []

    for tissue, raw in (profile or {}).items():
        number = _level(raw) if kind == "level" else _numeric(raw)
        if number is None:
            continue
        place = str(tissue).split(CELL_TYPE_KEY, 1)[0]
        organs = metrics.organs(place)
        if not organs:
            unmatched.append(str(tissue))
            continue
        shown = str(raw) if kind == "level" else readable(number)
        for organ in organs:
            cell = folded.setdefault(organ, Cell())
            cell.members.append(Member(str(tissue), number, shown))
            # The maximum, not the mean: thirteen brain regions where one is
            # high and twelve are silent is a brain where it is expressed.
            if cell.value is None or number > cell.value:
                cell.value = number
                cell.display = shown
    return folded, sorted(set(unmatched))


@dataclass
class Aligned:
    """One record folded onto organs: the shared work behind both views."""

    present: list[Layer] = field(default_factory=list)
    folded: dict[str, dict[str, Cell]] = field(default_factory=dict)
    unmatched: dict[str, list[str]] = field(default_factory=dict)
    missing: list[dict[str, str]] = field(default_factory=list)

    @property
    def organs(self) -> set[str]:
        return {organ for cells in self.folded.values() for organ in cells}

    def row(self, organ: str) -> Row:
        return Row(organ=organ,
                   cells={key: cells[organ] for key, cells in self.folded.items()
                          if organ in cells})

    def best(self, organ: str, stage: str) -> tuple[Layer, Cell] | None:
        """The loudest layer of a stage at this organ.

        A stage has up to two layers and they disagree: HPA's mass spec
        covers a few dozen tissues, the antibody atlas covers most of the
        body. Taking the highest is the same rule as merging tissues into
        an organ: the strongest evidence that the protein is there.
        """
        found = [(layer, self.folded[layer.key][organ]) for layer in self.present
                 if layer.stage == stage and organ in self.folded.get(layer.key, {})]
        return max(found, key=lambda pair: pair[1].share) if found else None


def fold(record: GeneRecord) -> Aligned:
    """Project every per-tissue layer of a record onto canonical organs."""
    present: list[Layer] = []
    folded: dict[str, dict[str, Cell]] = {}
    unmatched: dict[str, list[str]] = {}
    missing: list[dict[str, str]] = []

    for layer in LAYERS:
        value = record.fields.get(layer.field)
        finer = record.fields.get(layer.finer) if layer.finer else None
        if finer is not None and finer.present and isinstance(finer.value, dict):
            # Cell types fold to the same organ maximum as their tissue,
            # and the row can then open into them.
            value = finer
        if value is None or not value.present or not isinstance(value.value, dict):
            missing.append({
                "key": layer.key,
                "label": layer.label,
                "reason": (value.reason if value is not None and value.state
                           else "no per-tissue values in this record"),
            })
            continue
        cells, stray = project(value.value, layer.kind)
        if not cells:
            missing.append({"key": layer.key, "label": layer.label,
                            "reason": "no values map to a known organ"})
            if stray:
                unmatched[layer.key] = stray
            continue
        present.append(layer)
        folded[layer.key] = cells
        if stray:
            unmatched[layer.key] = stray

    # Each layer against its own peak. Three units with nothing in common
    # must never share a scale.
    for key, cells in folded.items():
        peak = max((cell.value or 0.0) for cell in cells.values()) or 0.0
        for cell in cells.values():
            cell.share = (cell.value or 0.0) / peak if peak > 0 else 0.0

    return Aligned(present=present, folded=folded, unmatched=unmatched,
                   missing=missing)


def align(record: GeneRecord) -> dict[str, Any]:
    """Every layer the record holds, on one organ axis."""
    it = fold(record)
    present, unmatched, missing = it.present, it.unmatched, it.missing
    rows = [it.row(organ) for organ in sorted(it.organs)]

    # Ordered by the transcript layer, so the eye runs down the message and
    # across to the protein.
    lead = next((layer.key for layer in present if layer.stage == "transcript"),
                present[0].key if present else "")
    rows.sort(key=lambda row: -(row.cells[lead].share if lead in row.cells else 0.0))

    out_rows = [row.to_dict() for row in rows]
    return {
        "layers": [_coverage(layer, it.folded[layer.key], len(rows))
                   for layer in present],
        "missing": missing,
        "rows": out_rows,
        "unmatched": unmatched,
        "organs": len(rows),
        "summary": summarize(rows, present),
        "agreement": agreement(out_rows, [layer.key for layer in present]),
    }


def agreement(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """How far every two sources agree on where the gene is expressed.

    Pearson's r of log(1 + value) over the organs both measure
    (`metrics.log_correlation`): GTEx against HPA asks whether a profile is
    real or one pipeline's artefact; RNA against protein asks whether the
    message is where the protein is. Units differ between sources (TPM,
    nCPM, a staining level), and a correlation does not need them to match:
    it asks whether the two rise and fall together across organs.
    """
    out = []
    for at, first in enumerate(keys):
        for second in keys[at + 1:]:
            shared = [(row["cells"][first]["value"], row["cells"][second]["value"])
                      for row in rows if first in row["cells"] and second in row["cells"]]
            rho = metrics.log_correlation([a for a, _ in shared], [b for _, b in shared])
            out.append({"a": first, "b": second, "n": len(shared),
                        "rho": round(rho, 2) if rho is not None else None})
    return out


def reading(row: Row) -> str:
    """What this organ's row says about the chain, in a phrase."""
    transcript = [layer.key for layer in LAYERS if layer.stage == "transcript"]
    protein = [layer.key for layer in LAYERS if layer.stage == "protein"]

    rna = max((row.cells[key].share for key in transcript if key in row.cells),
              default=None)
    prot = max((row.cells[key].share for key in protein if key in row.cells),
               default=None)
    if rna is None and prot is None:
        return ""
    if prot is None:
        # The distinction matters: a sparse layer that happens not to cover
        # this organ is not the same as there being no protein data at all.
        return "No protein measured here"
    if rna is None:
        return "Protein without a transcript measured here"
    if rna >= 0.5 and prot >= 0.5:
        return "Both high"
    if rna >= 0.5 and prot < 0.2:
        return "Message without protein"
    if rna < 0.2 and prot >= 0.5:
        return "Protein without message"
    return "Both low" if rna < 0.2 and prot < 0.2 else "Both present"


def summarize(rows: list[Row], layers: list[Layer]) -> str:
    """One line in the product's voice."""
    if not rows:
        return "No layer in this record has per-tissue values to align."
    names = ", ".join(layer.label for layer in layers)
    stages = {layer.stage for layer in layers}
    if stages == {"transcript"}:
        return (f"{len(rows)} organs, transcript only ({names}). No protein "
                f"layer to align against.")
    breaks = sum(1 for row in rows if reading(row) == "Message without protein")
    thin = sum(1 for row in rows if reading(row) == "No protein measured here")
    line = f"{len(rows)} organs across {names}."
    if breaks:
        line += (f" {breaks} where the message is high and the protein is not:"
                 f" the gap worth explaining.")
    if thin:
        line += f" {thin} have no protein measurement at all."
    return line


#: Under this many organs, a layer's own-peak scale stops meaning much:
#: the single tissue HPA reports as enriched is 100% of itself, which is
#: true and says nothing. Such a layer is marked so the chart can say so.
THIN_LAYER = 4


def _coverage(layer: Layer, cells: dict[str, Cell], axis: int) -> dict[str, Any]:
    """A layer's entry, with how much of the axis it covers."""
    covered = len(cells)
    return {**vars(layer), "organs": covered,
            "sparse": covered < THIN_LAYER or covered * 3 < axis}


#: The two stages, as the comparison shows them. Four layers collapse to
#: two columns per gene there: with three genes on screen, sixteen columns
#: would be a spreadsheet, and the question is only ever message-then-protein.
STAGES = (("transcript", "Message"), ("protein", "Protein"))


def _widest(it: Aligned, stage: str) -> Layer | None:
    """The layer of a stage that covers the most of the gene's body.

    One layer per column, for the full column. A column that takes the
    strongest layer organ by organ mixes two scales on one axis (mass spec
    in the lung, antibody elsewhere). That is the dual-axis error in
    disguise. The widest layer wins, and the header names it. Where it did
    not measure, the cell says so.
    """
    options = [layer for layer in it.present if layer.stage == stage]
    if not options:
        return None
    return max(options, key=lambda layer: (len(it.folded[layer.key]), -LAYERS.index(layer)))


def _stage_cell(it: Aligned, organ: str, layer: Layer | None) -> dict[str, Any] | None:
    if layer is None or organ not in it.folded.get(layer.key, {}):
        return None
    out = it.folded[layer.key][organ].to_dict()
    out.update({"layer": layer.label, "unit": layer.unit, "kind": layer.kind})
    return out


def align_many(records: list[GeneRecord]) -> dict[str, Any]:
    """Several genes on one shared organ axis.

    The axis is shared; the scales are not. The bars of each gene are
    normalised to the own peak of that gene. A TPM of one gene against a TPM
    of another is a comparison that this project refuses; the record has tau
    and fold over median for that reason. The shape does compare across the
    columns: where in the body the chain holds and where it breaks.
    """
    folded = [(record, fold(record)) for record in records]
    chosen = [{stage: _widest(it, stage) for stage, _ in STAGES}
              for _, it in folded]
    genes = []
    for (record, it), pick in zip(folded, chosen):
        genes.append({
            "query": record.query,
            "symbol": record.resolution.symbol or record.query,
            # Which assay each of this gene's two columns is drawn from,
            # so a reader is never guessing what the bar measures.
            "layers": {stage: ({"label": layer.label, "unit": layer.unit,
                                "kind": layer.kind,
                                "organs": len(it.folded[layer.key])}
                               if layer else None)
                       for stage, layer in pick.items()},
        })

    organs = sorted({organ for _, it in folded for organ in it.organs})
    rows: list[dict[str, Any]] = []
    for organ in organs:
        cells = []
        for (_, it), pick in zip(folded, chosen):
            cells.append({
                "transcript": _stage_cell(it, organ, pick["transcript"]),
                "protein": _stage_cell(it, organ, pick["protein"]),
                "reading": reading(it.row(organ)) if organ in it.organs else "",
            })
        lead = max((cell["transcript"]["share"] if cell["transcript"] else 0.0)
                   for cell in cells)
        rows.append({"organ": organ, "cells": cells, "lead": lead})
    rows.sort(key=lambda row: (-row["lead"], row["organ"]))

    contributing = {layer.key: layer for _, it in folded for layer in it.present}
    # Across genes a layer is as wide as its widest gene: if one gene has a
    # full antibody profile the column is not thin, even where another's is.
    layers = []
    for layer in LAYERS:
        if layer.key not in contributing:
            continue
        widest = max((it.folded.get(layer.key, {}) for _, it in folded),
                     key=len, default={})
        layers.append(_coverage(layer, widest, len(rows)))

    # Which gene is missing which layer, named per gene: "no protein here"
    # means something different when one of three genes has no protein data
    # at all than when the organ was not assayed.
    notes = []
    # A layer no gene has is said once, with its reason, not once per gene.
    missing_everywhere = set.intersection(
        *({entry["key"] for entry in it.missing} for _, it in folded)) if folded else set()
    for layer in LAYERS:
        if layer.key in missing_everywhere:
            reason = next(entry["reason"] for entry in folded[0][1].missing
                          if entry["key"] == layer.key)
            notes.append(f"{layer.label} is in none of these records: {reason}.")
    for (record, it), gene in zip(folded, genes):
        gaps = [entry["label"] for entry in it.missing if entry["key"] not in missing_everywhere]
        if gaps:
            notes.append(f"{gene['symbol']} has no per-tissue values for "
                         f"{', '.join(gaps)}.")
        for key, stray in it.unmatched.items():
            notes.append(f"{gene['symbol']}, {contributing[key].label if key in contributing else key}: "
                         f"measured but not an organ, so off the axis rather than "
                         f"dropped: {', '.join(stray)}.")

    return {
        "genes": genes,
        "stages": [{"key": key, "label": label} for key, label in STAGES],
        "layers": layers,
        "rows": rows,
        "notes": notes,
        "organs": len(rows),
        "summary": _compare_summary(rows, genes),
    }


def _compare_summary(rows: list[dict[str, Any]], genes: list[dict[str, str]]) -> str:
    if not rows:
        return "No gene here has per-tissue values to align."
    breaks = sum(1 for row in rows for cell in row["cells"]
                 if cell["reading"] == "Message without protein")
    line = (f"{len(rows)} organs across {len(genes)} genes. Each gene is scaled "
            f"against its own peak, so read across the columns for shape, not "
            f"for height.")
    if breaks:
        line += (f" {breaks} organ-gene pairs carry the message without the "
                 f"protein.")
    return line
