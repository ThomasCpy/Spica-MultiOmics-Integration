"""The location of the protein, from three sources on one compartment set.

UniProt writes "Cell membrane", HPA "Plasma membrane", GO "plasma membrane
raft". UniProt says "Endoplasmic reticulum lumen", HPA "Endoplasmic
reticulum", GO "endoplasmic reticulum membrane". Each term maps onto one of
ten compartments. The three sources then read side by side, and their
agreement is counted. A protein that all three place at the plasma membrane
is there. A protein that only GO places in the nucleus is a lead to check,
not a fact.

The rules apply in order, most specific first: "nuclear membrane" is the
nucleus, "endosome membrane" a vesicle, "mitochondrial inner membrane" a
mitochondrion. Only the remaining terms with "membrane" go to the plasma
membrane. UniProt topology statements ("Single-pass type I membrane
protein", "GPI-anchor") tell how a protein sits in a membrane, not which
membrane. They are kept apart, not placed. A term that no rule places is
reported, never dropped.
"""

from __future__ import annotations

import re
from typing import Any

from spica.record import GeneRecord

#: The compartments, outside in, as the cell diagram draws them.
COMPARTMENTS = ("Extracellular", "Plasma membrane", "Cytoskeleton", "Cytosol",
                "Endoplasmic reticulum", "Golgi apparatus", "Vesicles", "Mitochondria",
                "Peroxisome", "Nucleus")

#: (compartment, pattern), tried in order: the specific organelles before
#: the plain words "membrane" and "cytoplasm" that every term could use.
RULES: tuple[tuple[str, str], ...] = (
    # "Perinuclear region of cytoplasm" is cytoplasm, whatever it says first.
    ("Cytosol", r"perinuclear"),
    ("Nucleus", r"nucle|chromatin|chromosom|kinetochore|centromere|spliceosom|"
                r"\bpml body|cajal|speckle|replication fork|double-strand break|telomer"),
    ("Mitochondria", r"mitochondri"),
    ("Endoplasmic reticulum", r"endoplasmic|\ber\b|sarcoplasmic|microsom"),
    ("Golgi apparatus", r"golgi"),
    ("Peroxisome", r"peroxisom"),
    ("Vesicles", r"vesic|endosom|lysosom|endolysosom|autophag|phagosom|lipid droplet|"
                 r"granule|multivesicular|clathrin|copi|melanosom|exocytic|secretory"),
    ("Cytoskeleton", r"cytoskelet|actin|microtubul|intermediate filament|centrosom|centriol|"
                     r"cilium|cilia|flagell|spindle|midbody|cytokinetic|basal body|"
                     r"sarcomere|z disc|myofibril|stress fiber|\b(?:end|mid|principal) piece\b"),
    ("Extracellular", r"extracellular|secreted|exosome|basement membrane|"
                      r"blood microparticle|collagen-containing|interstitial|"
                      r"lipoprotein particle|chylomicron"),
    ("Plasma membrane", r"plasma membrane|cell membrane|cell surface|junction|adhesion|"
                        r"desmosom|synap|microvill|lamellipod|filopod|ruffle|cell projection|"
                        r"apical|basolateral|lateral membrane|caveola|raft|axon|dendrit|"
                        r"\bmembrane\b"),
    ("Cytosol", r"cytosol|cytoplasm|aggresome|rods & rings|cytoplasmic bod"),
)
COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in RULES)

#: How a protein sits in a membrane, not where: UniProt's topology terms.
TOPOLOGY = re.compile(r"membrane protein$|anchor|topology|^note\b", re.IGNORECASE)

SOURCES = (
    ("uniprot", "UniProt", ("uniprot_subcellular_locations",)),
    ("hpa", "HPA", ("hpa_subcellular_main", "hpa_subcellular_additional")),
    ("go", "GO", ("go_component",)),
)


def place(term: str) -> str | None:
    """The compartment a location term belongs to, or None."""
    for name, pattern in COMPILED:
        if pattern.search(term):
            return name
    return None


def compartments(record: GeneRecord) -> dict[str, Any]:
    """Each compartment with the terms each source used for it."""
    rows: dict[str, dict[str, Any]] = {name: {"name": name, "sources": {}, "main": False}
                                       for name in COMPARTMENTS}
    unplaced: list[dict[str, str]] = []
    topology: list[str] = []
    stamps: dict[str, str] = {}
    for key, label, fields in SOURCES:
        for field in fields:
            value = record[field]
            if not value.present:
                continue
            if value.provenance:
                stamps[key] = f"{value.provenance.source} {value.provenance.version}"
            for term in value.value or []:
                term = str(term).strip()
                if not term:
                    continue
                if key == "uniprot" and TOPOLOGY.search(term):
                    topology.append(term)
                    continue
                compartment = place(term)
                if compartment is None:
                    unplaced.append({"source": label, "term": term})
                    continue
                terms = rows[compartment]["sources"].setdefault(key, [])
                if term not in terms:
                    terms.append(term)
                if field == "hpa_subcellular_main":
                    rows[compartment]["main"] = True
    reported = [key for key, _, fields in SOURCES
                if any(record[field].present for field in fields)]
    for row in rows.values():
        row["count"] = len(row["sources"])
    return {
        "compartments": [rows[name] for name in COMPARTMENTS],
        "sources": [{"key": key, "label": label, "reported": key in reported,
                     "stamp": stamps.get(key, "")} for key, label, _ in SOURCES],
        "topology": topology,
        "unplaced": unplaced,
    }
