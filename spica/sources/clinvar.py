"""ClinVar: the known variants of this gene in people.

Adapted from the clinical module of the MultiOmics integrator, as counts,
not a list. The ClinVar track of the genome view shows the variants. A
record needs the comparable summary: the records that name this gene, the
pathogenic or likely pathogenic ones among them, and the classes of the
rest.

Only records that name this gene alone count. A 2 Mb deletion across forty
genes says little about any one of them. A count under each gene would
inflate all genes in the region.

"Names this gene alone" comes from the gene column of the variant summary.
The API has no such column and uses the ClinVar `single_gene` property. That
property also drops variants in an overlapping transcript: an antisense RNA
(TTN-AS1) or a readthrough (INS-IGF2). Such genes then get far too low a
count (INS: 14 against 194) and lose their best-known pathogenic variants.
The mirror count is the one that the field means.

Classes overlap, as in the ClinVar filters: a "Pathogenic/Likely
pathogenic" record counts under both. The pathogenic total is calculated
once, without duplicates, so it is the number to compare.

Mirror file: `variant_summary`, the NCBI `variant_summary.txt.gz`. Each
variant occurs once per assembly; Spica reads the GRCh38 rows.

API fallback: NCBI E-utilities, one count per question, below the NCBI
limit of three requests per second.
"""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError
from spica.sources.index import rows_for

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
#: NCBI allows three requests a second without an API key.
PACE = 0.34

#: The classes, as the record names them, and ClinVar's search filter for each.
CLASSES = (
    ("Pathogenic", "clinsig pathogenic"),
    ("Likely pathogenic", "clinsig likely pathogenic"),
    ("Uncertain significance", "clinsig vus"),
    ("Likely benign", "clinsig likely benign"),
    ("Benign", "clinsig benign"),
    ("Conflicting", "clinsig has conflicts"),
)
FIELDS = ("clinvar_variants", "clinvar_pathogenic", "clinvar_classifications")


def classes_of(significance: str) -> set[str]:
    """The classes one ClinVar classification counts under.

    "Pathogenic/Likely pathogenic" is both; "Conflicting classifications of
    pathogenicity" is only conflicting, never pathogenic.
    """
    text = significance.strip().lower()
    if not text:
        return set()
    if "conflicting" in text:
        return {"Conflicting"}
    found = set()
    for part in text.replace(",", "/").split("/"):
        part = part.strip()
        if part.startswith("likely pathogenic"):
            found.add("Likely pathogenic")
        elif part.startswith("pathogenic"):
            found.add("Pathogenic")
        elif part.startswith("uncertain significance"):
            found.add("Uncertain significance")
        elif part.startswith("likely benign"):
            found.add("Likely benign")
        elif part.startswith("benign"):
            found.add("Benign")
    return found


def summarise(total: int, pathogenic: int, counts: dict[str, int]) -> dict[str, Any]:
    if not total:
        reason = "ClinVar has no record naming only this gene"
        return {name: Absent(NullState.NOT_FOUND, reason) for name in FIELDS}
    fields: dict[str, Any] = {"clinvar_variants": total, "clinvar_pathogenic": pathogenic}
    present = {name: count for name, count in counts.items() if count}
    fields["clinvar_classifications"] = present or Absent(
        NullState.NOT_FOUND,
        "every record for this gene is classified outside the standard classes "
        "(not provided, drug response and the like)")
    return fields


class ClinVar(Source):
    key = "clinvar"
    label = "ClinVar"
    needs = ("variant_summary",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        symbol = identity.symbol.strip()
        if not symbol:
            raise GeneNotInSource("ClinVar is searched by gene symbol and there is none")
        seen: set[str] = set()
        pathogenic: set[str] = set()
        counts = {name: 0 for name, _ in CLASSES}
        required = ("GeneSymbol", "ClinicalSignificance", "Assembly", "VariationID")
        # Exact match: multi-gene rows read "GENE1;GENE2" and never match.
        for row in rows_for(entry.path("variant_summary"), "GeneSymbol", symbol, required):
            if row.get("Assembly", "").strip() != "GRCh38":
                continue
            variation = row.get("VariationID", "").strip()
            if not variation or variation in seen:
                continue
            seen.add(variation)
            classes = classes_of(row.get("ClinicalSignificance", ""))
            for name in classes:
                counts[name] += 1
            if classes & {"Pathogenic", "Likely pathogenic"}:
                pathogenic.add(variation)
        if not seen:
            raise GeneNotInSource(f"ClinVar {entry.version} has no record naming only {symbol}")
        return summarise(len(seen), len(pathogenic), counts)

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        symbol = identity.symbol.strip()
        if not symbol:
            raise GeneNotInSource("ClinVar is searched by gene symbol and there is none")
        base = f"{symbol}[gene] AND single_gene[prop]"
        first_url = self._url(base)
        total = self._count(live, base)
        if not total:
            raise GeneNotInSource(f"ClinVar has no record naming only {symbol}")
        pathogenic = self._count(
            live, f'{base} AND ("clinsig pathogenic"[prop] OR "clinsig likely pathogenic"[prop])')
        counts = {name: self._count(live, f'{base} AND "{prop}"[prop]') for name, prop in CLASSES}
        response = live.get_json(self.key, first_url)  # cached: dates the values
        return Fetched(summarise(total, pathogenic, counts), "API", response.fetched, first_url)

    @staticmethod
    def _url(term: str) -> str:
        query = urllib.parse.urlencode({"db": "clinvar", "term": term, "retmax": 0,
                                        "retmode": "json"})
        return f"{ESEARCH}?{query}"

    def _count(self, live: Live, term: str) -> int:
        try:
            response = live.get_json(self.key, self._url(term))
        except NotFoundUpstream:
            return 0
        if not response.from_cache:
            time.sleep(PACE)
        result = (response.payload or {}).get("esearchresult") or {}
        if "ERROR" in result or "count" not in result:
            raise SourceError(f"ClinVar rejected the search: {result.get('ERROR', 'no count')}")
        return int(result["count"])
