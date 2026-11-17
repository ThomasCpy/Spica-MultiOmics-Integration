"""OmniPath from the local mirror: regulators and interaction partners.

Two files, both downloaded with the commercial filter of OmniPath
(`spica/mirrorbuild.py`). `regulation`: transcription factor to target,
from DoRothEA, CollecTRI and the TF-target resources. `interactions`: the
curated network of protein interactions and signalling. Each file is a few
tens of megabytes, read once per process and indexed by gene in both
directions.

Rows have the shape of the web service answers. The views that read the
service (`spica/regulators.py`, the genome view) thus read the mirror the
same way. Rows are also indexed by protein, complexes included. A complex
is written `COMPLEX:P1_P2_P3`, and each member finds the row.
"""

from __future__ import annotations

from typing import Any

from spica.mirror import Mirror
from spica.sources.base import read_tsv

_CACHE: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
COLUMNS = ("source_genesymbol", "target_genesymbol")
FLAGS = ("is_directed", "is_stimulation", "is_inhibition")


def available(mirror: Mirror) -> bool:
    entry = mirror.entry("omnipath")
    return entry is not None and not entry.missing_files() and \
        {"interactions", "regulation"} <= set(entry.files)


def _table(mirror: Mirror, key: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    path = mirror.entry("omnipath").path(key)
    stamp = f"{path}|{path.stat().st_size}|{int(path.stat().st_mtime)}"
    if stamp not in _CACHE:
        by_source: dict[str, list[dict[str, Any]]] = {}
        by_target: dict[str, list[dict[str, Any]]] = {}
        by_protein: dict[str, list[dict[str, Any]]] = {}
        for row in read_tsv(path, COLUMNS):
            for flag in FLAGS:
                row[flag] = row.get(flag, "") == "True"
            row["n_references"] = len([r for r in row.get("references", "").split(";") if r])
            by_source.setdefault(row["source_genesymbol"], []).append(row)
            by_target.setdefault(row["target_genesymbol"], []).append(row)
            for accession in set(members(row.get("source", "")) + members(row.get("target", ""))):
                by_protein.setdefault(accession, []).append(row)
        _CACHE[stamp] = {"source": by_source, "target": by_target, "protein": by_protein}
    return _CACHE[stamp]


def members(side: str) -> list[str]:
    """The UniProt accessions on one side of a row: one protein, or a
    complex's members."""
    return [part for part in side.removeprefix("COMPLEX:").split("_") if part]


def regulators_of(symbol: str, mirror: Mirror) -> list[dict[str, Any]]:
    """The transcription factors recorded as regulating `symbol`."""
    return list(_table(mirror, "regulation")["target"].get(symbol, []))


def regulated_by(symbol: str, mirror: Mirror) -> list[dict[str, Any]]:
    """The genes `symbol` is recorded as regulating, as a transcription factor."""
    return list(_table(mirror, "regulation")["source"].get(symbol, []))


def interactions_of(symbol: str, mirror: Mirror) -> list[dict[str, Any]]:
    """Every curated interaction `symbol` takes part in, either side."""
    table = _table(mirror, "interactions")
    rows = table["source"].get(symbol, []) + table["target"].get(symbol, [])
    seen, out = set(), []
    for row in rows:
        key = (row["source_genesymbol"], row["target_genesymbol"], row.get("type", ""))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def curated_with(accessions: set[str], mirror: Mirror) -> list[dict[str, Any]]:
    """Every row of the curated network one of `accessions` takes part in,
    alone or as a member of a complex, each row once."""
    by_protein = _table(mirror, "interactions")["protein"]
    seen, out = set(), []
    for accession in sorted(accessions):
        for row in by_protein.get(accession, []):
            if id(row) not in seen:
                seen.add(id(row))
                out.append(row)
    return out


def version(mirror: Mirror) -> str:
    entry = mirror.entry("omnipath")
    return f"{entry.label} {entry.version}" if entry else ""
