"""Finding GEO series: NCBI's E-utilities over the GDS database.

A gene's other names widen the search the way they widen a watch
(`spica/intel/terms.py`): GEO titles say "NRF2" as often as "NFE2L2". The
search can keep to human series and to series that publish browser tracks
(bigWig or bigBed files), the ones the genome view can draw.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from spica.intel.terms import split, widen
from spica.live import Live, NotFoundUpstream

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PAGE_SIZE = 20


def query(terms: list[str], human: bool = True, tracks: bool = False,
          phrases: set[str] | None = None) -> str:
    """The E-utilities expression: any of the terms, a series, and the filters.

    A gene's official name is a phrase and is quoted; what the user typed is
    words, all of which must appear, in any order ("NFE2L2 ChIP-seq")."""
    phrases = phrases or set()
    quoted = [f'"{t}"' if t in phrases else f"({t})" if " " in t else t for t in terms]
    expression = "(" + " OR ".join(quoted) + ") AND gse[Entry Type]"
    if human:
        expression += ' AND "Homo sapiens"[Organism]'
    if tracks:
        expression += " AND (bw[Supplementary Files] OR bigwig[Supplementary Files] OR bb[Supplementary Files])"
    return expression


def search(text: str, live: Live, human: bool = True, tracks: bool = False, offset: int = 0,
           lookup: Callable[[str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    typed = split(text)
    if not typed:
        return {"error": "No search terms."}
    terms, phrases = list(typed), set()
    if lookup:
        for text in typed:
            words = text.split()
            # A gene among the words of a phrase ("NFE2L2 ChIP-seq") widens
            # the phrase: the same words with each of the gene's other names.
            for i, word in enumerate(words):
                widened = widen([word], lookup)
                if len(widened) > 1:
                    for term in widened[1:]:
                        variant = " ".join(words[:i] + [term.text] + words[i + 1:])
                        if variant not in terms:
                            terms.append(variant)
                            if len(words) == 1 and " " in term.text:
                                phrases.add(variant)
                    break
    expression = query(terms, human, tracks, phrases)
    params = {"db": "gds", "term": expression, "retmax": PAGE_SIZE, "retstart": max(0, int(offset)),
              "sort": "relevance", "retmode": "json"}
    try:
        found = live.get_json("geo", f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}").payload or {}
    except NotFoundUpstream:
        found = {}
    result = found.get("esearchresult") or {}
    ids = result.get("idlist") or []
    total = int(result.get("count") or 0)
    rows: list[dict[str, Any]] = []
    if ids:
        summary = live.get_json("geo", f"{EUTILS}/esummary.fcgi?db=gds&id={','.join(ids)}&retmode=json").payload or {}
        block = summary.get("result") or {}
        for uid in ids:
            item = block.get(uid) or {}
            if not item:
                continue
            files = [f.strip().upper() for f in str(item.get("suppfile") or "").split(",") if f.strip()]
            rows.append({
                "accession": item.get("accession", ""),
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "type": item.get("gdstype", ""),
                "organisms": item.get("taxon", ""),
                "samples": int(item.get("n_samples") or len(item.get("samples") or [])),
                "date": str(item.get("pdat", "")).replace("/", "-"),
                "files": files,
                "tracks": any(f in ("BW", "BIGWIG", "BB", "BIGBED") for f in files),
                "pubmed": [str(p) for p in item.get("pubmedids") or []],
            })
    return {"query": text, "terms": terms, "expression": expression, "total": total,
            "offset": offset, "results": rows, "page": PAGE_SIZE}
