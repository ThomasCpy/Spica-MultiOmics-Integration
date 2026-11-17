"""Interaction partners from three kinds of evidence, side by side.

HPA's consensus network records physical binding: pairs seen together in
experiments that IntAct, BioGRID, OpenCell and BioPlex gather, much of it
from high-throughput screens. OmniPath's curated network records what the
literature says one protein does to another (signalling, modification,
activation, inhibition), each with the papers behind it. The comparison is
the point: a partner in both was seen bound and has a described role; one
only HPA has is binding with no mechanism written down; one only OmniPath
has is a described effect no screen picked up, often a transient one, as
an enzyme's with its substrate.

STRING's physical subnetwork is the third: pairs shown or predicted to
bind, scored 0 to 1 from experiments, curated databases and text mining.
A STRING-only partner joins the list at STRING's own medium confidence
(0.4) or above; a partner the other two name keeps its STRING score
whatever it is, and counts as in STRING only from 0.4.

Matched on identifiers, never on names: HPA's and STRING's pairs are Ensembl genes,
OmniPath's UniProt accessions, and HGNC maps one onto the other. OmniPath
also records interactions with complexes; a protein in a complex the gene
acts on, or acts in, counts as a partner, marked with the complex.

Reads the mirror only: the comparison needs both networks whole.
"""

from __future__ import annotations

from typing import Any

from spica import omnipath, stringdb
from spica.mirror import Mirror
from spica.sources.base import read_tsv, split_list
from spica.sources.hpa import consensus_partners

_HGNC: dict[str, dict[str, dict]] = {}

#: HPA's consensus datasets, in the order the matrix shows them.
HPA_DATASETS = ("intact", "biogrid", "opencell", "bioplex")


def _hgnc(path) -> dict[str, dict]:
    """UniProt accession to (symbol, Ensembl ID); Ensembl ID to symbol and
    to accessions."""
    key = str(path)
    if key not in _HGNC:
        maps: dict[str, dict] = {"accession": {}, "symbol": {}, "accessions": {}}
        for row in read_tsv(path, ("symbol", "ensembl_gene_id", "uniprot_ids")):
            symbol, ensembl = row["symbol"].strip(), row["ensembl_gene_id"].strip()
            accessions = split_list(row["uniprot_ids"])
            if ensembl:
                maps["symbol"][ensembl] = symbol
                maps["accessions"][ensembl] = accessions
            for accession in accessions:
                maps["accession"][accession] = (symbol, ensembl)
        _HGNC[key] = maps
    return _HGNC[key]


def _ready(mirror: Mirror, key: str, file: str) -> bool:
    entry = mirror.entry(key)
    return entry is not None and file in entry.files and entry.path(file).exists()


def named(symbols: str) -> str:
    """A row's side as people write it: a gene, or its complex's members."""
    parts = symbols.split("_")
    return f"complex {'/'.join(parts)}" if len(parts) > 1 else symbols


def _sign(row: dict[str, Any]) -> str:
    up, down = row.get("is_stimulation"), row.get("is_inhibition")
    if up and down:
        return "both"
    return "stimulates" if up else "inhibits" if down else "unsigned"


def compare(symbol: str, ensembl_id: str, mirror: Mirror) -> dict[str, Any]:
    if not (_ready(mirror, "hpa", "interactions") and _ready(mirror, "hgnc", "complete_set")
            and omnipath.available(mirror)):
        return {"error": "Interaction partners need HPA's interaction network, OmniPath and HGNC "
                         "in the local data: update them in Settings."}
    hpa, hgnc = mirror.entry("hpa"), mirror.entry("hgnc")
    maps = _hgnc(hgnc.path("complete_set"))
    wanted = ensembl_id.strip().upper()
    own = set(maps["accessions"].get(wanted, []))
    partners: dict[str, dict[str, Any]] = {}

    def partner(key: str, name: str, ensembl: str) -> dict[str, Any]:
        return partners.setdefault(key, {"symbol": name, "ensembl_id": ensembl,
                                         "hpa": None, "omnipath": None, "string": None})

    for other_id, found in consensus_partners(wanted, hpa.path("interactions")).items():
        item = partner(other_id, maps["symbol"].get(other_id) or found["name"] or other_id, other_id)
        known = [d for d in HPA_DATASETS if d in found["datasets"]]
        # A release without the datasets column still says the pair is there.
        item["hpa"] = known + [d for d in found["datasets"] if d not in known] or ["consensus"]

    curated: dict[str, dict[str, Any]] = {}
    for row in omnipath.curated_with(own, mirror):
        sides = ((row["source"], row["target"], "out"), (row["target"], row["source"], "in"))
        for mine, theirs, way in sides:
            if not own & set(omnipath.members(mine)):
                continue
            names = (row["target_genesymbol"] if way == "out" else row["source_genesymbol"]).split("_")
            accessions = omnipath.members(theirs)
            complexes = [named(row[f"{end}_genesymbol"]) for end in ("source", "target")
                         if row[end].startswith("COMPLEX:")]
            # The actor and what it acts on, each as the row has it: a link
            # through a complex is the complex's, not each member's.
            link = {"direction": way if row["is_directed"] else "none", "sign": _sign(row),
                    "from": named(row["source_genesymbol"]), "to": named(row["target_genesymbol"])}
            for index, accession in enumerate(accessions):
                # The gene inside the complex it meets is not its own partner;
                # the gene acting on itself, alone, is.
                if accession in own and (len(accessions) > 1 or mine.startswith("COMPLEX:")):
                    continue
                found = curated.setdefault(accession, {
                    "name": names[index] if index < len(names) else accession,
                    "references": set(), "links": [], "databases": set(),
                    "direct": False, "complexes": set()})
                found["references"] |= {r.split(":")[-1] for r in row.get("references", "").split(";")
                                        if r.strip()}
                found["databases"] |= {d for d in row.get("sources", "").split(";") if d}
                if link not in found["links"]:
                    found["links"].append(link)
                if complexes:
                    found["complexes"] |= set(complexes)
                else:
                    found["direct"] = True

    # Two accessions of one gene are one partner.
    by_gene: dict[str, dict[str, Any]] = {}
    for accession, found in curated.items():
        name, ensembl = maps["accession"].get(accession, (found["name"], ""))
        key = ensembl or accession
        partner(key, name, ensembl)
        into = by_gene.setdefault(key, {"references": set(), "links": [], "databases": set(),
                                        "direct": False, "complexes": set()})
        for field in ("references", "databases", "complexes"):
            into[field] |= found[field]
        into["direct"] = into["direct"] or found["direct"]
        into["links"] += [link for link in found["links"] if link not in into["links"]]
    for key, found in by_gene.items():
        partners[key]["omnipath"] = {
            "references": len(found["references"]),
            "links": sorted(found["links"], key=lambda link: tuple(link.values())),
            "databases": ", ".join(sorted(found["databases"])),
            "direct": found["direct"], "complexes": sorted(found["complexes"])}

    networks = ["hpa", "omnipath"]
    if stringdb.available(mirror):
        networks.append("string")
        for other, scores in stringdb.partners(wanted, mirror).items():
            if other == wanted:
                continue
            if other not in partners and scores["score"] < stringdb.MEDIUM:
                continue  # a weak link alone does not make a partner
            item = partner(other, maps["symbol"].get(other) or other, other)
            item["string"] = {**scores, "medium": scores["score"] >= stringdb.MEDIUM}

    def member(row: dict[str, Any]) -> list[str]:
        return [key for key in networks
                if row[key] is not None and (key != "string" or row[key]["medium"])]

    rows = list(partners.values())
    for row in rows:
        row["networks"] = member(row)
    rows.sort(key=lambda row: (-len(row["networks"]),
                               -(row["omnipath"] or {}).get("references", 0),
                               -(row["string"] or {}).get("score", 0),
                               -len(row["hpa"] or []), row["symbol"]))
    combinations: dict[tuple[str, ...], int] = {}
    for row in rows:
        combinations[tuple(row["networks"])] = combinations.get(tuple(row["networks"]), 0) + 1
    counts = {key: sum(key in row["networks"] for row in rows) for key in networks}
    in_hpa = sum(row["hpa"] is not None for row in rows)
    in_omnipath = sum(row["omnipath"] is not None for row in rows)
    both = sum(row["hpa"] is not None and row["omnipath"] is not None for row in rows)
    gene = maps["symbol"].get(wanted) or symbol
    return {
        "symbol": gene,
        "partners": rows,
        "datasets": list(HPA_DATASETS),
        "summary": {
            "hpa": in_hpa, "omnipath": in_omnipath, "both": both,
            "union": len(rows),
            # Overlap of the two partner sets, and how much of each the
            # other confirms; None where a set is empty.
            "jaccard": round(both / len(rows), 3) if rows else None,
            "omnipath_in_hpa": round(both / in_omnipath, 3) if in_omnipath else None,
            "hpa_in_omnipath": round(both / in_hpa, 3) if in_hpa else None,
            "via_complex_only": sum(1 for row in rows
                                    if row["omnipath"] and not row["omnipath"]["direct"]),
            # With STRING: the partners above medium confidence, each
            # combination of networks per partner, and the part of each
            # network that at least one other network confirms.
            "string": counts.get("string"),
            "networks": networks,
            "combinations": [{"networks": list(key), "count": n} for key, n in
                             sorted(combinations.items(), key=lambda kv: (-kv[1], kv[0]))],
            "confirmed": {key: round(sum(key in row["networks"] and len(row["networks"]) > 1
                                         for row in rows) / counts[key], 3) if counts[key] else None
                          for key in networks},
            "string_threshold": stringdb.MEDIUM,
        },
        "sources": (f"HPA {hpa.version} consensus network; {omnipath.version(mirror)}, local "
                    f"copy, records cleared for commercial use"
                    + (f"; {stringdb.version(mirror)}, physical subnetwork" if "string" in networks
                       else "; STRING not in the local data")
                    + f"; matched through HGNC {hgnc.version}"),
    }
