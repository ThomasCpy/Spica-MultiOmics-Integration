"""The protein along its sequence: what has been seen, and what is predicted.

One plot's worth of data, residue by residue: AlphaFold's confidence, the
mean AlphaMissense pathogenicity of changing that residue, and every PDB
entry's chains as segments. Read together they answer the structural triage
questions at a glance: which parts have been solved, which are predicted
well, and where change is least tolerated.

Derived from the same answers the record's fields come from. The PDB
segments and the length are read from the UniProt mirror when it carries
the full PDB column; the per-residue confidence and missense scores from
the mirror's AlphaFold files when the build kept them (`plddt_residues`,
`missense_residues`), otherwise from AlphaFold DB's API, cached.
"""

from __future__ import annotations

from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream
from spica.sources.alphafold import per_residue_missense, prediction, substitutions
from spica.sources.base import GeneNotInSource, SourceError
from spica.sources.index import rows_for
from spica.sources.uniprot import ACCESSION_COLUMN, API as UNIPROT, pdb_xrefs, segments


def _mirrored(accession: str, mirror) -> tuple[int, list[dict[str, Any]]] | None:
    """Length and PDB segments from the UniProt mirror, if it has them."""
    entry = mirror.entries.get("uniprot") if mirror is not None else None
    if entry is None or "entries" not in entry.files or entry.missing_files():
        return None
    for row in rows_for(entry.path("entries"), ACCESSION_COLUMN, accession, (ACCESSION_COLUMN,)):
        xrefs = pdb_xrefs(row.get("PDB", ""))
        if xrefs or not row.get("PDB", "").strip():
            try:
                length = int(row.get("Length", "") or 0)
            except ValueError:
                length = 0
            return length, segments(xrefs)
    return None


def _residues(accession: str, mirror) -> tuple[list, list, bool] | None:
    """(plddt, missense, both found) from the mirror's per-residue files, or
    None when the mirror has neither."""
    entry = mirror.entries.get("alphafold") if mirror is not None else None
    if entry is None or not {"plddt_residues", "missense_residues"} & set(entry.files):
        return None
    plddt, missense = [], []
    if "plddt_residues" in entry.files and entry.path("plddt_residues").exists():
        for row in rows_for(entry.path("plddt_residues"), "accession", accession):
            start = int(row.get("start") or 1)
            plddt = [[start + i, float(v)] for i, v in enumerate(row["plddt"].split(",")) if v]
            break
    if "missense_residues" in entry.files and entry.path("missense_residues").exists():
        for row in rows_for(entry.path("missense_residues"), "accession", accession):
            missense += [[i + 1, float(v)] for i, v in enumerate(row["means"].split(",")) if v]
    return plddt, sorted(missense), bool(plddt and missense)


def profile(accession: str, live: Live, mirror=None) -> dict[str, Any]:
    accession = accession.strip().upper()
    if not accession:
        return {"error": "No UniProt accession."}
    out: dict[str, Any] = {"accession": accession, "length": 0, "plddt": [],
                           "missense": [], "pdb": [], "notes": []}
    local = _mirrored(accession, mirror)
    if local:
        out["length"], out["pdb"] = local
    else:
        try:
            entry = live.get_json("uniprot", f"{UNIPROT}/{accession}.json").payload or {}
            out["length"] = int((entry.get("sequence") or {}).get("length") or 0)
            out["pdb"] = segments(entry.get("uniProtKBCrossReferences") or [])
        except (LiveError, NotFoundUpstream) as exc:
            out["notes"].append(f"UniProt could not be read: {exc}")

    mirrored = _residues(accession, mirror)
    if mirrored and mirrored[2]:
        out["plddt"], out["missense"] = mirrored[0], mirrored[1]
        out["model_version"] = str(mirror.entries["alphafold"].version).lstrip("v")
        out["length"] = out["length"] or max(r for r, _ in out["plddt"])
        out["source"] = f"{mirror.entries['alphafold'].label} {mirror.entries['alphafold'].version}, local copy"
        return out
    # Whatever half the mirror holds is used; only the missing half is asked
    # of AlphaFold DB, so a gap in one file does not cost the other.
    if mirrored:
        out["plddt"], out["missense"] = mirrored[0], mirrored[1]
        out["source"] = f"{mirror.entries['alphafold'].label} {mirror.entries['alphafold'].version}, local copy"
    try:
        model, _, _ = prediction(accession, live)
        out["model_version"] = model.get("latestVersion")
        doc = model.get("plddtDocUrl")
        if doc and not out["plddt"]:
            confidence = live.get_json("alphafold", doc).payload or {}
            out["plddt"] = [[int(r), float(c)] for r, c in
                            zip(confidence.get("residueNumber", []),
                                confidence.get("confidenceScore", []))]
        if not out["missense"]:
            table = substitutions(model, live)
            if table:
                out["missense"] = sorted([p, v] for p, v in per_residue_missense(table).items())
            else:
                out["notes"].append("AlphaFold DB has no AlphaMissense table for this model.")
        out["length"] = out["length"] or int(model.get("uniprotEnd") or 0)
    except (GeneNotInSource, SourceError, LiveError, NotFoundUpstream) as exc:
        missing = "confidence per residue" if out["missense"] else "this protein"
        out["notes"].append(f"AlphaFold DB, for {missing}: {exc}")
    if not out["length"]:
        return {"error": "Neither UniProt nor AlphaFold DB could be read for this protein.",
                "notes": out["notes"]}
    return out
