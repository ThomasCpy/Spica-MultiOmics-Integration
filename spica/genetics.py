"""Disease evidence of two kinds, side by side: association and genetics.

Open Targets scores how strongly a disease is associated with a target,
integrating every kind of evidence it holds. ClinVar records the variants
in the gene that clinical labs classified, condition by condition. The two
answer different questions, and the comparison is the point: a disease
with a high association score *and* pathogenic variants in the gene has
human genetics behind it; a high score without them rests on other
evidence; pathogenic variants for a condition Open Targets barely links
are a lead worth reading.

Matched on identifiers, never on names: Open Targets says "familial
hypercholesterolemia" and ClinVar "Hypercholesterolemia, familial, 1".
Each Open Targets disease brings its own ID and its cross-references
(OMIM, Orphanet, UMLS, MONDO); each ClinVar condition its identifier group
(MONDO, MedGen, OMIM, Orphanet). A disease and a condition match when any
identifier is shared. A ClinVar condition that matches no disease is
listed on its own, never dropped.

GWAS, when the GWAS Catalog is mirrored, is the third column: common
variants at the gene, each trait carrying the ontology terms the Catalog
mapped it to (EFO, MONDO), matched to the same disease identifiers. A trait
that matches no disease (most measurements: cholesterol levels, blood
counts) is listed on its own, never dropped.

Reads the mirror only (`opentargets/disease_xrefs.tsv`,
`clinvar/conditions.tsv`, `gwas/traits.tsv`): the join needs them whole,
which no API gives.
"""

from __future__ import annotations

import json
import re
from typing import Any

from spica.mirror import Mirror
from spica.sources.base import read_tsv
from spica.sources.index import lines_for, rows_for

_XREFS: dict[str, dict[str, set[str]]] = {}


#: An ontology accession written the Open Targets way: EFO_0000275.
UNDERSCORED = re.compile(r"\b(EFO|MONDO|HP|Orphanet|OTAR|GO|DOID)_(\w+)$")


def normal(identifier: str) -> str:
    """One spelling per identifier: "MONDO_0005439", "MONDO:MONDO:0005439" and
    "MONDO:0005439" are one; so are "EFO: The Experimental Factor
    Ontology:EFO_0000275" and "EFO_0000275"; a MedGen concept is its UMLS CUI."""
    text = identifier.strip()
    found = UNDERSCORED.search(text)
    if found:
        prefix, local = found.groups()
    else:
        parts = [part.strip() for part in text.split(":")]
        prefix, local = (parts[-2], parts[-1]) if len(parts) >= 2 else (parts[0], "")
    prefix = prefix.upper()
    if prefix in ("MEDGEN", "UMLS", "UMLS_CUI") and local.startswith("C"):
        return f"CUI:{local}"
    if prefix in ("ORPHANET", "ORPHA"):
        return f"ORPHANET:{local}"
    if prefix in ("MIM",):
        prefix = "OMIM"
    return f"{prefix}:{local}"


def _xrefs(path) -> dict[str, set[str]]:
    key = str(path)
    if key not in _XREFS:
        table: dict[str, set[str]] = {}
        for row in read_tsv(path, ("id", "xrefs")):
            table[row["id"]] = {normal(x) for x in row["xrefs"].split("|") if ":" in x}
        _XREFS[key] = table
    return _XREFS[key]


def evidence(symbol: str, ensembl_id: str, mirror: Mirror) -> dict[str, Any]:
    ot, clinvar = mirror.entry("opentargets"), mirror.entry("clinvar")
    if ot is None or clinvar is None or "disease_xrefs" not in ot.files \
            or "conditions" not in clinvar.files or ot.missing_files() or clinvar.missing_files():
        return {"error": "Disease against genetics needs Open Targets and ClinVar in the local "
                         "data, built with their disease identifiers: update both in Settings."}
    wanted = ensembl_id.strip().upper()
    target = None
    for line in lines_for(ot.path("targets"), "ensemblId", wanted):
        found = json.loads(line)
        if str(found.get("ensemblId", "")).upper() == wanted:
            target = found
            break
    associations = ((target or {}).get("associatedDiseases") or {}).get("rows") or []
    xrefs = _xrefs(ot.path("disease_xrefs"))

    conditions = []
    for row in rows_for(clinvar.path("conditions"), "GeneSymbol", symbol,
                        ("GeneSymbol", "Condition", "IDs", "Pathogenic", "Records")):
        ids = {normal(x) for x in row["IDs"].split(",") if ":" in x}
        conditions.append({"condition": row["Condition"], "ids": sorted(ids),
                           "pathogenic": int(row["Pathogenic"] or 0),
                           "records": int(row["Records"] or 0), "matched": False})
    by_id: dict[str, list[dict[str, Any]]] = {}
    for condition in conditions:
        for identifier in condition["ids"]:
            by_id.setdefault(identifier, []).append(condition)

    gwas_entry = mirror.entry("gwas")
    gwas_ready = (gwas_entry is not None and "traits" in gwas_entry.files
                  and not gwas_entry.missing_files())
    traits: list[dict[str, Any]] = []
    if gwas_ready:
        from spica.sources.gwas import traits as gwas_traits

        for row in gwas_traits(wanted, gwas_entry.path("traits")):
            ids = {normal(uri.rstrip("/").rsplit("/", 1)[-1])
                   for uri in row["trait_uris"].split(",") if uri.strip()}
            traits.append({"trait": row["trait"], "ids": sorted(ids), "mlog10p": row["mlog10p"],
                           "associations": row["associations"], "relation": row["relation"],
                           "variant": row["risk_allele"], "matched": False})
    by_trait: dict[str, list[dict[str, Any]]] = {}
    for trait in traits:
        for identifier in trait["ids"]:
            by_trait.setdefault(identifier, []).append(trait)

    rows = []
    for association in sorted(associations, key=lambda a: (-float(a.get("score") or 0),
                                                            a["disease"].get("name", ""))):
        disease = association["disease"]
        did = disease.get("id", "")
        keys = {normal(did)} | xrefs.get(did, set()) if did else set()
        matched: list[dict[str, Any]] = []
        for key in keys:
            for condition in by_id.get(key, []):
                if condition not in matched:
                    matched.append(condition)
        for condition in matched:
            condition["matched"] = True
        hits: list[dict[str, Any]] = []
        for key in keys:
            for trait in by_trait.get(key, []):
                if trait not in hits:
                    hits.append(trait)
        for trait in hits:
            trait["matched"] = True
        rows.append({
            "disease": disease.get("name", did), "id": did,
            "score": round(float(association.get("score") or 0), 3),
            "pathogenic": sum(c["pathogenic"] for c in matched),
            "records": sum(c["records"] for c in matched),
            "conditions": [c["condition"] for c in matched],
            # The strongest matched GWAS association, as -log10 p; 0 when none.
            "gwas": max((t["mlog10p"] for t in hits), default=0.0),
            "gwas_traits": [t["trait"] for t in hits],
        })
    unmatched = sorted((c for c in conditions if not c["matched"]),
                       key=lambda c: (-c["pathogenic"], -c["records"], c["condition"]))
    supported = [row for row in rows if row["pathogenic"]]
    gwas_only = [{k: v for k, v in t.items() if k != "matched"} for t in traits if not t["matched"]]
    return {
        "symbol": symbol,
        "rows": rows,
        "clinvar_only": [{k: v for k, v in c.items() if k != "matched"} for c in unmatched],
        "gwas": gwas_ready,
        "gwas_only": gwas_only,
        "summary": {
            "associations": len(rows),
            "with_pathogenic": len(supported),
            "conditions": len(conditions),
            "unmatched": len(unmatched),
            "top_supported": supported[0]["disease"] if supported else "",
            "with_gwas": sum(1 for row in rows if row["gwas"]),
            "gwas_traits": len(traits),
        },
        "sources": f"{ot.label} {ot.version}, {clinvar.label} {clinvar.version}"
                   + (f", {gwas_entry.label} {gwas_entry.version}" if gwas_ready else ""),
    }
