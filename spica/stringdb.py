"""STRING from the local mirror: the physical partners of a gene and their evidence.

The physical subnetwork: proteins shown or predicted to bind. Each pair has
a combined confidence and its evidence channels (experiments, curated
databases, text mining), all on the STRING scale of 0 to 1. The builder
maps STRING protein IDs to Ensembl genes through the STRING alias table
(`spica/mirrorbuild.py`). The pairs thus join HPA and OmniPath on
identifiers.

STRING 12.5, CC BY 4.0 (`docs/licences.md`).
"""

from __future__ import annotations

from spica.mirror import Mirror
from spica.sources.index import rows_for

#: STRING's own default threshold, "medium confidence".
MEDIUM = 0.4
CHANNELS = ("experimental", "database", "textmining")


def available(mirror: Mirror) -> bool:
    entry = mirror.entry("string")
    return entry is not None and "physical" in entry.files and not entry.missing_files()


def partners(ensembl_id: str, mirror: Mirror) -> dict[str, dict[str, float]]:
    """Every physical link of `ensembl_id`, by partner gene, at any score."""
    path = mirror.entry("string").path("physical")
    found: dict[str, dict[str, float]] = {}
    for row in rows_for(path, "gene_a", ensembl_id.strip().upper()):
        scores = {"score": int(row["combined_score"]) / 1000}
        scores.update({channel: int(row[channel] or 0) / 1000 for channel in CHANNELS})
        # One protein pair per isoform can map to one gene pair: the best.
        if row["gene_b"] not in found or scores["score"] > found[row["gene_b"]]["score"]:
            found[row["gene_b"]] = scores
    return found


def version(mirror: Mirror) -> str:
    entry = mirror.entry("string")
    return f"{entry.label} {entry.version}" if entry else ""
