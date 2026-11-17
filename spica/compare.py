"""Several genes, one table.

This is the reason for the insights section of the record. A peak
expression value does not compare between genes; a specificity index does.
This module puts records side by side, so the comparison is on screen and
not rebuilt across separate database pages.

It is deterministic, as the records are. No model takes part, and the same
genes against the same releases give the same table.

It does not rank. The "best" gene depends on the modality, the indication
and the accepted safety risk. A single score would hide all three behind
one arbitrary number. Rows mark the highest value where a high value has a
meaning, and the decision stays with the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spica.build import build_record
from spica.dogma import align_many
from spica.record import GeneRecord
from spica.schema import FIELDS, SECTIONS, FieldSpec

#: Fields where the largest value is the notable one. Everywhere else a
#: number is a description, not a score: a longer protein is not a better
#: one, and more diseases is not more promising.
HIGHEST_IS_NOTABLE = {
    "rna_specificity_tau",
    "rna_fold_over_median",
    "gtex_median_across_tissues",
    "single_cell_tau",
    # Further along is further along: a drug that reached approval, a fold
    # that was predicted confidently, a sequence that has been solved.
    "chembl_max_phase",
    "alphafold_mean_plddt",
    "pdb_coverage",
    # A closer ortholog is a model species that says more about the human.
    "mouse_protein_identity",
    "cyno_protein_identity",
}

#: Shown first, because they are the comparable ones.
LEAD_SECTION = "insights"


@dataclass
class Cell:
    """One gene's answer for one field."""

    display: str = ""
    value: Any = None
    state: str = ""
    reason: str = ""
    source: str = ""
    version: str = ""
    notable: bool = False  # the highest, where highest means something

    def to_dict(self) -> dict[str, Any]:
        return {
            "display": self.display,
            "value": self.value,
            "state": self.state,
            "reason": self.reason,
            "source": self.source,
            "version": self.version,
            "notable": self.notable,
        }


@dataclass
class Row:
    spec: FieldSpec
    cells: list[Cell] = field(default_factory=list)

    @property
    def filled(self) -> int:
        return sum(1 for cell in self.cells if not cell.state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.spec.name,
            "label": self.spec.label,
            "section": self.spec.section,
            "unit": self.spec.unit,
            "mono": self.spec.mono,
            "type": self.spec.type,
            "derived": self.spec.derived,
            "description": self.spec.description,
            "filled": self.filled,
            "cells": [cell.to_dict() for cell in self.cells],
        }


def render(spec: FieldSpec, value: Any) -> str:
    """One value, short enough for a column.

    Maps are the awkward case: a 54-tissue profile cannot go in a cell, so
    the top few go in and the rest are counted. The full profile is still
    in the record; this is a table, not the record.
    """
    if isinstance(value, dict):
        items = list(value.items())
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in value.values()):
            items = sorted(items, key=lambda kv: -kv[1])
        shown = ", ".join(f"{key} {item}" for key, item in items[:3])
        if len(items) > 3:
            shown += f" +{len(items) - 3}"
        return shown
    if isinstance(value, list):
        shown = ", ".join(str(item) for item in value[:3])
        if len(value) > 3:
            shown += f" +{len(value) - 3}"
        return shown
    if spec.type == "sequence" and isinstance(value, str) and len(value) > 24:
        return f"{value[:24]}... ({len(value)} aa)"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def compare(queries: list[str], records: list[GeneRecord] | None = None,
            **build_args) -> dict[str, Any]:
    """Build the comparison table for `queries`."""
    cleaned = [query.strip() for query in queries if query and query.strip()]
    if records is None:
        # Genes are independent and each mostly waits on the network, so
        # they are built side by side; the table keeps the order typed.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(cleaned)))) as pool:
            records = list(pool.map(lambda query: build_record(query, **build_args), cleaned))

    genes = [
        {
            "query": record.query,
            "symbol": record.resolution.symbol or record.query,
            "resolved": record.resolution.resolved,
            "reason": record.resolution.reason,
            "matched_on": record.resolution.matched_on,
            "candidates": list(record.resolution.candidates),
            "filled": len(record.present_fields()),
            "fingerprint": record.fingerprint(),
        }
        for record in records
    ]

    rows: list[Row] = []
    for spec in FIELDS:
        row = Row(spec=spec)
        for record in records:
            value = record.fields.get(spec.name)
            if value is None or not value.present:
                row.cells.append(Cell(
                    state=value.state.value if value and value.state else "not_found",
                    reason=value.reason if value else "the field was never built",
                ))
                continue
            provenance = value.provenance
            row.cells.append(Cell(
                display=render(spec, value.value),
                value=value.value,
                source=provenance.source if provenance else "",
                version=provenance.version if provenance else "",
            ))
        _mark_notable(spec, row)
        rows.append(row)

    # Sections in schema order, but the comparable ones lead: that is what
    # the table is for.
    order = [LEAD_SECTION] + [key for key in SECTIONS if key != LEAD_SECTION]
    sections = [
        {
            "key": key,
            "label": SECTIONS[key],
            "rows": [row.to_dict() for row in rows if row.spec.section == key],
        }
        for key in order
        if any(row.spec.section == key for row in rows)
    ]

    return {
        "genes": genes,
        "sections": sections,
        "rows": [row.to_dict() for row in rows],
        "compared": len(genes),
        # The table answers "which is higher"; this answers "where in the
        # body", which is the question a table of medians cannot reach.
        "dogma": align_many([record for record in records
                             if record.resolution.resolved]),
    }


def _mark_notable(spec: FieldSpec, row: Row) -> None:
    """Mark the highest value, where being highest means anything."""
    if spec.name not in HIGHEST_IS_NOTABLE or len(row.cells) < 2:
        return
    numbers = [
        (index, cell.value) for index, cell in enumerate(row.cells)
        if not cell.state and isinstance(cell.value, (int, float))
        and not isinstance(cell.value, bool)
    ]
    if len(numbers) < 2:
        return
    best = max(numbers, key=lambda pair: pair[1])
    # A tie is not a winner; marking one of two equal values would be a
    # claim the data does not make.
    if sum(1 for _, value in numbers if value == best[1]) == 1:
        row.cells[best[0]].notable = True
