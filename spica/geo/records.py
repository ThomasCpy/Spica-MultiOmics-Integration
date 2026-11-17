"""A GEO series and its samples, from the GEO text records.

GEO serves each series and sample as SOFT text (`acc.cgi ... form=text`):
one `!Key = value` line per fact. The context of a sample is in its
characteristics (`cell type: HepG2`, `treatment: sulforaphane`), its source,
organism and library strategy, and its data-processing notes. Submitters
give the genome build in these notes.

Spica never reads contact details (names, e-mails, telephone numbers,
addresses). They identify people and add nothing to the science.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from spica.live import Live, NotFoundUpstream

ACC = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
PAGE = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc}"
ACCESSION = re.compile(r"^G(SE|SM|PL|DS)\d+$")
#: Keys never kept: they identify people, not samples.
PRIVATE = ("contact_", "_email", "_phone", "_fax")

#: What a file is, from its name. Track kinds can be drawn on a locus.
KINDS = (
    ("bigwig", re.compile(r"\.(bw|bigwig)$", re.I)),
    ("bigbed", re.compile(r"\.(bb|bigbed)$", re.I)),
    ("peaks", re.compile(r"\.(narrowpeak|broadpeak|gappedpeak)(\.gz)?$", re.I)),
    ("bedgraph", re.compile(r"\.(bedgraph|bdg)(\.gz)?$", re.I)),
    ("wig", re.compile(r"\.wig(\.gz)?$", re.I)),
    ("bed", re.compile(r"\.bed(\.gz)?$", re.I)),
    ("matrix", re.compile(r"\.(txt|tsv|csv)(\.gz)?$", re.I)),
    ("sheet", re.compile(r"\.xlsx?(\.gz)?$", re.I)),
    ("archive", re.compile(r"\.(tar|zip)(\.gz)?$", re.I)),
)
TRACK_KINDS = ("bigwig", "bigbed", "peaks", "bedgraph", "wig", "bed")

#: Genome builds as people write them, to the names Spica uses.
BUILDS = (
    ("GRCh38", re.compile(r"\b(hg38|grch38|grch\s*38)\b", re.I)),
    ("GRCh37", re.compile(r"\b(hg19|grch37|grch\s*37|b37)\b", re.I)),
    ("NCBI36", re.compile(r"\b(hg18|ncbi36|ncbi\s*build\s*36)\b", re.I)),
    ("mouse", re.compile(r"\b(mm9|mm10|mm39|grcm38|grcm39)\b", re.I)),
)

#: Words that mark a sample as a control arm, from the integrator.
CONTROL = ("control", "ctrl", "vehicle", "dmso", "untreated", "mock", "placebo", "wild type",
           "wildtype", "wt", "baseline", "sham", "scramble", "scrambled", "sincontrol", "sinc",
           "non-targeting", "nontargeting", "input", "igg", "pbs")


def https(url: str) -> str:
    """GEO lists files as ftp:// addresses; the same files are served over HTTPS."""
    return re.sub(r"^ftp://ftp\.ncbi\.nlm\.nih\.gov/", "https://ftp.ncbi.nlm.nih.gov/", url.strip())


def kind(name: str) -> str:
    for label, pattern in KINDS:
        if pattern.search(name):
            return label
    return "other"


def build(*texts: str) -> str:
    """The genome build a file name or a note states, or ""."""
    for text in texts:
        for label, pattern in BUILDS:
            if text and pattern.search(text.replace("_", " ").replace(".", " ")):
                return label
    return ""


def parse_soft(text: str) -> list[dict[str, list[str]]]:
    """Every `^ENTITY` block as {key: [values]}, keys without their prefix."""
    blocks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    for line in text.splitlines():
        if line.startswith("^"):
            current = {"_entity": [line[1:].split("=", 1)[-1].strip()]}
            blocks.append(current)
        elif line.startswith("!") and current is not None and " = " in line:
            key, value = line[1:].split(" = ", 1)
            key = re.sub(r"^(Series|Sample|Platform)_", "", key)
            if any(mark in key.lower() for mark in PRIVATE):
                continue
            current.setdefault(key, []).append(value.strip())
    return blocks


def _first(block: dict[str, list[str]], key: str) -> str:
    values = block.get(key) or [""]
    return values[0]


def _files(values: list[str], organism: str, notes: str, sample: str = "") -> list[dict[str, Any]]:
    out = []
    for value in values:
        if not value or value.upper() == "NONE":
            continue
        url = https(value)
        name = url.rsplit("/", 1)[-1]
        label = kind(name)
        assembly = build(name) or build(notes)
        human = "homo sapiens" in organism.lower() if organism else assembly.startswith("GRCh")
        out.append({"url": url, "name": name, "kind": label, "sample": sample,
                    "assembly": assembly, "human": human,
                    "track": label in TRACK_KINDS and human and assembly not in ("NCBI36", "mouse")})
    return out


def arm(sample: dict[str, Any]) -> str:
    """"control" when the sample's own labels say so, else ""."""
    words = " ".join([sample["title"], sample["source"], *sample["characteristics"].values()]).lower()
    tokens = set(re.findall(r"[a-z0-9\-]+", words))
    if any((" " in w and w in words) or w in tokens for w in CONTROL):
        return "control"
    return ""


def sample(block: dict[str, list[str]]) -> dict[str, Any]:
    characteristics: dict[str, str] = {}
    for line in block.get("characteristics_ch1", []):
        key, sep, value = line.partition(":")
        if sep:
            name = key.strip().lower()
            characteristics[name] = (characteristics[name] + "; " if name in characteristics else "") + value.strip()
        else:
            characteristics.setdefault("note", line.strip())
    organism = _first(block, "organism_ch1")
    notes = " ".join(block.get("data_processing", []))
    accession = _first(block, "geo_accession") or block["_entity"][0]
    files = _files([v for key, values in block.items() if key.startswith("supplementary_file")
                    for v in values], organism, notes, accession)
    out = {
        "accession": accession,
        "title": _first(block, "title"),
        "source": _first(block, "source_name_ch1"),
        "organism": organism,
        "molecule": _first(block, "molecule_ch1"),
        "strategy": _first(block, "library_strategy"),
        "platform": _first(block, "platform_id"),
        "characteristics": characteristics,
        "treatment": " ".join(block.get("treatment_protocol_ch1", []))[:600],
        "processing": notes[:1500],
        "assembly": build(notes),
        "files": files,
        "url": PAGE.format(acc=accession),
    }
    out["arm"] = arm(out)
    return out


def series(block: dict[str, list[str]]) -> dict[str, Any]:
    accession = _first(block, "geo_accession") or block["_entity"][0]
    notes = " ".join(block.get("overall_design", []) + block.get("summary", []))
    return {
        "accession": accession,
        "title": _first(block, "title"),
        "summary": " ".join(block.get("summary", [])),
        "design": " ".join(block.get("overall_design", [])),
        "types": block.get("type", []),
        "pubmed": block.get("pubmed_id", []),
        "platforms": block.get("platform_id", []),
        "samples": block.get("sample_id", []),
        "submitted": _first(block, "submission_date"),
        "updated": _first(block, "last_update_date"),
        "files": _files(block.get("supplementary_file", []), "", notes),
        "url": PAGE.format(acc=accession),
    }


def facets(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What sets the samples apart: each characteristic (and source, strategy,
    organism) that takes more than one value, with how many samples hold each.
    A field every sample shares says nothing about the design and is left out."""
    fields: dict[str, Counter] = {}
    for s in samples:
        values = {"organism": s["organism"], "source": s["source"], "library strategy": s["strategy"],
                  **s["characteristics"]}
        for key, value in values.items():
            if value:
                fields.setdefault(key, Counter())[value] += 1
    out = []
    for key, counts in fields.items():
        if len(counts) > 1:
            out.append({"field": key, "values": [{"value": v, "samples": n} for v, n in counts.most_common()]})
    out.sort(key=lambda f: (len(f["values"]) > len(samples) * 0.8, f["field"]))
    return out


def read(accession: str, live: Live) -> dict[str, Any]:
    """A series with every sample, its context and its files."""
    acc = accession.strip().upper()
    if not ACCESSION.match(acc) or not acc.startswith("GSE"):
        raise ValueError(f"{accession!r} is not a GEO series accession (GSE followed by digits)")
    head = live.get_text("geo", f"{ACC}?acc={acc}&targ=self&form=text&view=brief").payload
    blocks = [b for b in parse_soft(str(head)) if b.get("_entity", [""])[0] == acc]
    if not blocks:
        raise NotFoundUpstream(f"GEO has no series {acc}")
    found = series(blocks[0])
    body = live.get_text("geo", f"{ACC}?acc={acc}&targ=gsm&form=text&view=brief").payload
    found["samples"] = [sample(b) for b in parse_soft(str(body)) if b.get("_entity", [""])[0].startswith("GSM")]
    # A series-level file named after a sample belongs to that sample.
    for f in found["files"]:
        owner = re.match(r"(GSM\d+)", f["name"])
        if owner:
            f["sample"] = owner.group(1)
    found["facets"] = facets(found["samples"])
    every = found["files"] + [f for s in found["samples"] for f in s["files"]]
    found["counts"] = {"samples": len(found["samples"]),
                       "human": sum(1 for s in found["samples"] if "homo sapiens" in s["organism"].lower()),
                       "files": len(every),
                       "tracks": sum(1 for f in every if f["track"]),
                       "matrices": sum(1 for f in every if f["kind"] == "matrix"),
                       "sheets": sum(1 for f in every if f["kind"] == "sheet")}
    found["organisms"] = sorted({s["organism"] for s in found["samples"] if s["organism"]})
    return found
