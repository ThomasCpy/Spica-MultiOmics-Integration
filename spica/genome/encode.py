"""ENCODE experiments that can become tracks on a locus.

Two questions, as in the epigenetic explorer of the integrator:

- *Measurements in one organ.* ATAC-seq, DNase-seq, H3K27ac, WGBS and
  chromatin states. Adult samples only by default: an embryonic "right
  lung" ATAC-seq says little about an adult target.
- *Binding of the gene's regulators.* TF ChIP-seq for the TFs that OmniPath
  names as regulators. Measured occupancy can then sit on the locus next to
  the gene model. Absence means "not assayed by ENCODE", never "does not
  bind", and the list says so.

The list holds all experiments found, not a top few. Each one offers its
most useful GRCh38 file, by the preference order below. It becomes a track
named `encode:<file accession>`.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream

SEARCH = "https://www.encodeproject.org/search/"
SITE = "https://www.encodeproject.org"
LIFE_STAGE = "replicates.library.biosample.life_stage"

#: Assay -> search filters and the files worth drawing, best first.
ASSAYS: dict[str, dict[str, Any]] = {
    "atac": {"label": "ATAC-seq", "filters": {"type": "Experiment", "assay_title": "ATAC-seq"},
             "files": [("bigWig", "fold change over control"),
                       ("bigBed", "IDR thresholded peaks"), ("bigBed", "pseudoreplicated peaks")]},
    "dnase": {"label": "DNase-seq", "filters": {"type": "Experiment", "assay_title": "DNase-seq"},
              "files": [("bigWig", "read-depth normalized signal"), ("bigBed", "peaks")]},
    "h3k27ac": {"label": "H3K27ac ChIP-seq",
                "filters": {"type": "Experiment", "assay_title": "Histone ChIP-seq",
                            "target.label": "H3K27ac"},
                "files": [("bigWig", "fold change over control"),
                          ("bigBed", "replicated peaks"), ("bigBed", "pseudoreplicated peaks")]},
    "wgbs": {"label": "DNA methylation (WGBS)", "filters": {"type": "Experiment", "assay_title": "WGBS"},
             "files": [("bigBed", "methylation state at CpG")]},
    "chromhmm": {"label": "Chromatin states (ChromHMM)",
                 "filters": {"type": "Annotation", "annotation_type": "chromatin state"},
                 "files": [("bigBed", None)]},
}

#: Peak files ranked by how final the call is, as in the integrator:
#: IDR-thresholded first, raw peaks last.
PEAK_RANK = ("optimal idr thresholded peaks", "conservative idr thresholded peaks",
             "pseudoreplicated idr thresholded peaks", "idr thresholded peaks",
             "replicated peaks", "stable peaks", "peaks")

FIELDS = ["accession", "biosample_summary", "biosample_ontology.term_name", "target.label",
          "description", "files.accession", "files.file_format", "files.output_type",
          "files.assembly", "files.status"]

#: ENCODE's organ slims, the vocabulary its search filters on.
ORGANS = (
    "adipose tissue", "adrenal gland", "blood", "blood vessel", "bone marrow", "brain", "breast", "colon",
    "esophagus", "heart", "intestine", "kidney", "large intestine", "liver", "lung",
    "lymph node", "musculature of body", "nerve", "ovary", "pancreas", "placenta",
    "prostate gland", "skin of body", "small intestine", "spleen", "stomach", "testis",
    "thymus", "thyroid gland", "uterus", "vagina",
)


def _search(live: Live, params: dict[str, Any]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({**params, "status": "released", "limit": "all",
                                    "format": "json", "field": FIELDS}, doseq=True)
    try:
        payload = live.get_json("encode", f"{SEARCH}?{query}").payload
    except NotFoundUpstream:
        return []  # ENCODE answers an empty search with 404
    return list((payload or {}).get("@graph") or [])


def _pick(files: list[dict[str, Any]], wanted: list[tuple[str, str | None]]) -> dict[str, Any] | None:
    usable = [f for f in files if f.get("assembly") == "GRCh38"
              and f.get("status") in (None, "released")
              and f.get("file_format") in ("bigWig", "bigBed")]
    for fmt, output in wanted:
        for f in usable:
            if f.get("file_format") == fmt and (output is None or f.get("output_type") == output):
                return f
    return None


def _entry(experiment: dict[str, Any], chosen: dict[str, Any], assay: str) -> dict[str, Any]:
    target = experiment.get("target")
    tf = target.get("label") if isinstance(target, dict) else ""
    where = (experiment.get("biosample_summary") or
             (experiment.get("biosample_ontology") or {}).get("term_name") or
             experiment.get("description") or "biosample not given")
    return {
        "id": f"encode:{chosen['accession']}",
        "experiment": experiment.get("accession", ""),
        "file": chosen["accession"],
        "assay": assay,
        "target": tf,
        "biosample": str(where).replace("Homo sapiens ", ""),
        "format": chosen.get("file_format", ""),
        "output": chosen.get("output_type", ""),
        "url": f"{SITE}/experiments/{experiment.get('accession', '')}/",
    }


def by_organ(live: Live, organ: str, assay: str, adult: bool = True) -> dict[str, Any]:
    """Every released experiment of one assay in one organ, with a file to draw."""
    spec = ASSAYS[assay]
    params: dict[str, Any] = {**spec["filters"], "biosample_ontology.organ_slims": organ}
    if adult and spec["filters"]["type"] == "Experiment":
        params[LIFE_STAGE] = "adult"
    try:
        experiments = _search(live, params)
    except LiveError as exc:
        return {"state": "failed", "reason": f"ENCODE: {exc}", "items": []}
    items, without = [], 0
    for experiment in experiments:
        chosen = _pick(experiment.get("files") or [], spec["files"])
        if chosen:
            items.append(_entry(experiment, chosen, spec["label"]))
        else:
            without += 1
    items.sort(key=lambda item: (item["biosample"], item["file"]))
    return {"state": "ok", "items": items, "without_files": without,
            "organ": organ, "assay": spec["label"], "adult_only": adult}


def for_regulators(live: Live, tfs: list[str], adult: bool = False) -> dict[str, Any]:
    """TF ChIP-seq peaks for a gene's regulators, best peak file per experiment.

    Adult-only is off here by default: most TF ChIP-seq is in cell lines,
    and a cell line's measured binding is still measured binding.
    """
    names = sorted({part for tf in tfs for part in str(tf).split("_") if part})
    if not names:
        return {"state": "ok", "items": [], "with_chipseq": [], "without_chipseq": []}
    params: dict[str, Any] = {"type": "Experiment", "assay_title": "TF ChIP-seq",
                              "target.label": names}
    if adult:
        params[LIFE_STAGE] = "adult"
    try:
        experiments = _search(live, params)
    except LiveError as exc:
        return {"state": "failed", "reason": f"ENCODE: {exc}", "items": []}

    def quality(f: dict[str, Any]) -> tuple[int, int]:
        output = str(f.get("output_type") or "").lower()
        rank = next((i for i, key in enumerate(PEAK_RANK) if key in output), len(PEAK_RANK))
        return rank, 0 if f.get("file_format") == "bigBed" else 1

    items = []
    for experiment in experiments:
        peaks = [f for f in experiment.get("files") or []
                 if f.get("assembly") == "GRCh38" and f.get("status") in (None, "released")
                 and f.get("file_format") == "bigBed"
                 and "peak" in str(f.get("output_type") or "").lower()]
        if peaks:
            items.append(_entry(experiment, min(peaks, key=quality), "TF ChIP-seq"))
    found = sorted({item["target"] for item in items})
    items.sort(key=lambda item: (item["target"], item["biosample"], item["file"]))
    return {"state": "ok", "items": items, "with_chipseq": found,
            "without_chipseq": [name for name in names if name not in found]}


def file_info(live: Live, accession: str) -> dict[str, Any]:
    """What one ENCODE file is, and where its bytes are."""
    payload = live.get_json("encode", f"{SITE}/files/{accession}/?format=json").payload or {}
    href = payload.get("href") or ""
    if not href:
        raise LiveError(f"ENCODE file {accession} has no download link")
    target = payload.get("target")
    return {
        "accession": accession,
        "url": f"{SITE}{href}",
        "format": payload.get("file_format", ""),
        "output": payload.get("output_type", ""),
        "assay": payload.get("assay_title", ""),
        "target": target.get("label", "") if isinstance(target, dict) else "",
        "biosample": ((payload.get("biosample_ontology") or {}).get("term_name") or ""),
    }
