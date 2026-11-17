"""DepMap: how much cancer cell lines need the gene.

DepMap knocks out each gene by CRISPR in about a thousand cancer cell lines
and scores the effect with Chronos: 0 is no effect, -1 is the median of the
common essential genes. Two readings matter for a target. Inhibition of a
common essential gene also reaches healthy dividing cells. A gene that only
some lines need, grouped in one lineage, is a selective dependency: the
profile of a good oncology target.

Mirror files: `genes`, one row per gene, built by `spica/mirrorbuild.py`
from the CRISPRGeneEffect and CRISPRGeneDependency matrices of the release
(`docs/data-mirror.md` gives the columns). The key is the HGNC ID, through
the Entrez ID in the DepMap column names. `models` is the Model.csv of the
release, with the name and lineage of each cell line.

No API: the portal is behind a browser check, so DepMap comes from the
mirror or not at all. DepMap, Broad Institute, CC BY 4.0.
"""

from __future__ import annotations

import csv
import json
from typing import Any

from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError
from spica.sources.index import rows_for

#: Lower edges of the gene-effect distribution's bins, as the builder cut
#: them (`EFFECT_EDGES` in spica/mirrorbuild.py): 0.1 wide from -3 to 1.
EDGES = [round(-3 + 0.1 * i, 1) for i in range(40)]

_MODELS: dict[str, dict[str, tuple[str, str]]] = {}


def models(path) -> dict[str, tuple[str, str]]:
    """ModelID to (cell line name, lineage), read once per file."""
    key = str(path)
    if key not in _MODELS:
        with open(path, encoding="utf-8", newline="") as handle:
            _MODELS[key] = {row["ModelID"]: (row.get("CellLineName") or row["ModelID"],
                                             row.get("OncotreeLineage") or "Unknown")
                            for row in csv.DictReader(handle)}
    return _MODELS[key]


class DepMap(Source):
    key = "depmap"
    label = "DepMap"
    needs = ("genes", "models")

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        row = self._row(identity, entry)
        try:
            lineages = json.loads(row["lineages"])
            bins = [int(count) for count in row["histogram"].split(",")]
            lines = int(row["lines"])
        except (ValueError, KeyError) as exc:
            raise SourceError(f"DepMap's gene summary is unreadable for {row.get('symbol')}: {exc}")
        names = models(entry.path("models"))
        dependent = []
        for pair in filter(None, row.get("dependent_lines", "").split("|")):
            model, _, effect = pair.partition(":")
            name, lineage = names.get(model, (model, "Unknown"))
            dependent.append(f"{name} ({lineage}) {effect}")
        nobody = Absent(NullState.NOT_FOUND,
                        f"No line in DepMap {entry.version} depends on it "
                        f"(dependency probability above 0.5)")
        return {
            "depmap_lines": lines,
            "depmap_mean_effect": round(float(row["mean_effect"]), 3),
            "depmap_dependent_share": (round(float(row["dependent_share"]), 1)
                                       if row.get("dependent_share") else
                                       Absent(NullState.NOT_FOUND, "no dependency probabilities")),
            "depmap_common_essential": ("yes, in DepMap's inferred common essentials"
                                        if row.get("common_essential") == "1" else "no"),
            # Keyed with the number of lines, so a share from three lines
            # never reads like one from three hundred.
            "depmap_lineage_dependency": {
                f"{name}, {n} line{'' if n == 1 else 's'}": round(100 * dep / n, 1)
                for name, (n, dep, _mean) in lineages.items() if n},
            "depmap_effect_distribution": {f"{EDGES[i]:.1f}": count for i, count in enumerate(bins)
                                           if i < len(EDGES)},
            "depmap_dependent_lines": dependent or nobody,
        }

    def _row(self, identity: Resolution, entry: MirrorEntry) -> dict[str, str]:
        """By HGNC ID; by symbol only for a gene DepMap's Entrez ID did not
        map, which can then only match a symbol the two agree on."""
        path = entry.path("genes")
        if identity.hgnc_id:
            for row in rows_for(path, "hgnc_id", identity.hgnc_id):
                return row
        if identity.symbol:
            for row in rows_for(path, "symbol", identity.symbol):
                if not row.get("hgnc_id"):
                    return row
        raise GeneNotInSource(f"{identity.symbol or identity.query} is not in DepMap "
                              f"{entry.version}'s CRISPR screens")

    def locator(self, field_name: str, entry: MirrorEntry) -> str:
        return entry.files.get("genes", "")
