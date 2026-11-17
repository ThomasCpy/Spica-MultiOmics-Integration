"""HGNC: the naming authority, and the gene the query means.

HGNC comes first in each build. Only HGNC can turn the user's text into
identifiers that the other sources accept. A resolution through the
authority, not through the search of each source, keeps one meaning per
gene across the record.

Mirror file: `hgnc_complete_set.txt` (tab separated, one row per gene,
multi-valued cells separated by `|`).

API fallback: `rest.genenames.org`. Its `fetch/<field>/<value>` endpoints
are exact lookups, one per identifier kind. They match as the mirror does,
one request at a time instead of a file scan.
"""

from __future__ import annotations

import re
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, read_tsv, split_list

REQUIRED = ("hgnc_id", "symbol", "status")
API = "https://rest.genenames.org/fetch"

# Tried in this order; the first level with a hit wins. Approved symbols
# come before aliases. A symbol that is current for one gene and an old
# alias of another thus resolves to its present owner.
MATCH_ORDER = (
    ("hgnc_id", "HGNC ID"),
    ("symbol", "approved symbol"),
    ("ensembl_gene_id", "Ensembl gene ID"),
    ("uniprot_ids", "UniProt accession"),
    ("entrez_id", "Entrez ID"),
    ("prev_symbol", "previous symbol"),
    ("alias_symbol", "alias symbol"),
)

MULTI_VALUED = {"uniprot_ids", "prev_symbol", "alias_symbol"}

#: The columns resolution and the record read; the index keeps only these.
KEPT = ("hgnc_id", "symbol", "name", "status", "locus_type", "location", "alias_symbol",
        "prev_symbol", "entrez_id", "ensembl_gene_id", "uniprot_ids")

_TABLES: dict[str, dict] = {}


def table(path) -> dict:
    """Approved genes, and for each match column the rows each normalised
    value points to. Built once per file (size and time), so resolving a
    list of a thousand genes reads the 16 MB file once, not a thousand
    times."""
    stat = path.stat()
    stamp = f"{path}|{stat.st_size}|{int(stat.st_mtime)}"
    if stamp not in _TABLES:
        rows: list[dict[str, str]] = []
        by: dict[str, dict[str, list[int]]] = {column: {} for column, _ in MATCH_ORDER}
        for row in read_tsv(path, REQUIRED):
            if row.get("status", "").strip() != "Approved":
                continue  # withdrawn and placeholder entries never resolve
            index = len(rows)
            rows.append({column: row.get(column, "") for column in KEPT})
            for column, _ in MATCH_ORDER:
                cell = row.get(column, "")
                if not cell:
                    continue
                values = ({_normalize(v) for v in split_list(cell)} if column in MULTI_VALUED
                          else {_normalize(cell)})
                for value in values:
                    by[column].setdefault(value, []).append(index)
        _TABLES.clear()  # one HGNC release in memory at a time
        _TABLES[stamp] = {"rows": rows, "by": by}
    return _TABLES[stamp]

ACCESSION = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)

PROTEIN_CODING = "gene with protein product"


def not_matched(query: str) -> str:
    """Why nothing resolved, with what to try next."""
    return (f"No approved HGNC gene matches {query}. Check the spelling, or try the "
            "gene's UniProt accession or Ensembl ID.")


def _normalize(text: str) -> str:
    return text.strip().upper()


def _query_forms(query: str) -> set[str]:
    """The ways a query might be written, so one pass can match them all.

    Covers the three spellings people paste: a bare HGNC number, a versioned
    Ensembl ID, and anything with surrounding whitespace or lowercase.
    """
    wanted = {_normalize(query)}
    bare = _normalize(query)
    if re.fullmatch(r"\d+", bare):
        wanted.add(f"HGNC:{bare}")
    if bare.startswith("ENSG") and "." in bare:
        wanted.add(bare.split(".")[0])
    return wanted


def _as_list(value: Any) -> list[str]:
    """HGNC's multi-values: a list over the API, a `|` cell in the file."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return split_list(str(value or ""))


def _assemble(values: dict[str, Any]) -> dict[str, Any]:
    """The fields HGNC owns, from either route's view of one gene."""
    uniprot = _as_list(values.get("uniprot_ids"))
    locus_type = str(values.get("locus_type") or "").strip()
    fields: dict[str, Any] = {
        "hgnc_id": str(values.get("hgnc_id") or "").strip(),
        "symbol": str(values.get("symbol") or "").strip(),
        "name": str(values.get("name") or "").strip(),
        "aliases": _as_list(values.get("alias_symbol")),
        "previous_symbols": _as_list(values.get("prev_symbol")),
        "locus_type": locus_type,
        "chromosomal_location": str(values.get("location") or "").strip(),
        "entrez_id": str(values.get("entrez_id") or "").strip(),
        "ensembl_gene_id": str(values.get("ensembl_gene_id") or "").strip(),
        # Where HGNC lists several accessions the first is the reviewed
        # canonical entry; the others are isoform-level duplicates.
        "uniprot_accession": uniprot[0] if uniprot else "",
    }
    if locus_type not in (PROTEIN_CODING, ""):
        # Non-coding genes have no protein to cross-reference, which is a
        # different statement from "HGNC has no accession for this gene".
        fields["uniprot_accession"] = Absent(
            NullState.NOT_COVERED, f"{locus_type} has no protein product"
        )
    return fields


def _resolution(query: str, how: str, values: dict[str, Any]) -> Resolution:
    uniprot = _as_list(values.get("uniprot_ids"))
    return Resolution(
        query=query,
        resolved=True,
        matched_on=how,
        hgnc_id=str(values.get("hgnc_id") or "").strip(),
        symbol=str(values.get("symbol") or "").strip(),
        ensembl_gene_id=str(values.get("ensembl_gene_id") or "").strip(),
        uniprot_accession=uniprot[0] if uniprot else "",
    )


def _ambiguous(query: str, how: str, rows: list[dict[str, Any]]) -> Resolution:
    """Real and common: one alias can belong to several genes. Ambiguity is
    reported, never resolved by picking the first."""
    candidates = sorted(f"{row['symbol']} ({row['hgnc_id']})" for row in rows)
    return Resolution(
        query=query,
        resolved=False,
        matched_on=how,
        reason=f"{query}: {how} of {len(rows)} genes. Gene selection required.",
        candidates=tuple(candidates),
    )


class Hgnc(Source):
    key = "hgnc"
    label = "HGNC"
    needs = ("complete_set",)

    # -- the mirror ---------------------------------------------------------

    def resolve(self, query: str, entry: MirrorEntry) -> Resolution:
        """Find the one gene the query names, or the reason none matches."""
        wanted = _query_forms(query)
        found = table(entry.path("complete_set"))
        seen: set[int] = set()
        levels: list[tuple[str, str, list[int]]] = []
        for column, how in MATCH_ORDER:
            indexes = sorted({i for value in wanted for i in found["by"][column].get(value, [])}
                             - seen)
            seen |= set(indexes)  # one row matches at its strongest level only
            if indexes:
                levels.append((column, how, indexes))

        # A bare number can be an HGNC number or an Entrez ID, and lists of
        # Entrez IDs are common: 1956 is CHRNA2's HGNC number and EGFR's
        # Entrez ID. When both readings name a gene, the user says which.
        numbered = {column: indexes for column, _, indexes in levels
                    if column in ("hgnc_id", "entrez_id")}
        if re.fullmatch(r"\s*\d+\s*", query) and len(numbered) == 2:
            rows = [found["rows"][i] for i in numbered["hgnc_id"] + numbered["entrez_id"]]
            return Resolution(
                query=query, resolved=False, matched_on="HGNC ID or Entrez ID",
                reason=f"{query.strip()}: HGNC number of {rows[0]['symbol']}, Entrez ID of "
                       f"{rows[-1]['symbol']}. Gene selection required.",
                candidates=tuple(f"{row['symbol']} ({row['hgnc_id']})" for row in rows))

        for column, how, indexes in levels:
            rows = [found["rows"][i] for i in indexes]
            if len(rows) > 1:
                return _ambiguous(query, how, rows)
            return _resolution(query, how, rows[0])

        return Resolution(
            query=query, resolved=False, reason=not_matched(query)
        )

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        return _assemble(self._row(identity.hgnc_id, entry))

    def _row(self, hgnc_id: str, entry: MirrorEntry) -> dict[str, str]:
        """The gene's row, by the ID resolution already settled on, from the
        same in-memory index resolution reads."""
        found = table(entry.path("complete_set"))
        for index in found["by"]["hgnc_id"].get(_normalize(hgnc_id), []):
            return found["rows"][index]
        raise GeneNotInSource(f"{hgnc_id} is not in HGNC {entry.version}")

    # -- the API ------------------------------------------------------------

    @staticmethod
    def _routes(query: str) -> list[tuple[str, str, str]]:
        """`(endpoint, value, how)` worth asking for, strongest first.

        An identifier is only looked up under the kind it could be, so a
        plain symbol costs three requests rather than seven.
        """
        bare = _normalize(query)
        routes: list[tuple[str, str, str]] = []
        if re.fullmatch(r"HGNC:\d+", bare):
            routes.append(("hgnc_id", bare, "HGNC ID"))
        elif re.fullmatch(r"\d+", bare):
            routes.append(("hgnc_id", f"HGNC:{bare}", "HGNC ID"))
        routes.append(("symbol", bare, "approved symbol"))
        if bare.startswith("ENSG"):
            routes.append(("ensembl_gene_id", bare.split(".")[0], "Ensembl gene ID"))
        if ACCESSION.match(bare):
            routes.append(("uniprot_ids", bare, "UniProt accession"))
        if re.fullmatch(r"\d+", bare):
            routes.append(("entrez_id", bare, "Entrez ID"))
        routes.append(("prev_symbol", bare, "previous symbol"))
        routes.append(("alias_symbol", bare, "alias symbol"))
        return routes

    def resolve_live(self, query: str, live: Live) -> Resolution:
        for endpoint, value, how in self._routes(query):
            try:
                response = live.get_json(self.key, f"{API}/{endpoint}/{value}")
            except NotFoundUpstream:
                continue
            docs = self._docs(response.payload)
            if not docs:
                continue
            if len(docs) > 1:
                return _ambiguous(query, how, docs)
            return _resolution(query, how, docs[0])

        return Resolution(
            query=query, resolved=False, reason=not_matched(query)
        )

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        url = f"{API}/hgnc_id/{identity.hgnc_id}"
        response = live.get_json(self.key, url)
        docs = self._docs(response.payload)
        if not docs:
            raise GeneNotInSource(f"{identity.hgnc_id} is not in HGNC")
        # The API publishes no release label, so the fetch date carries the
        # weight on provenance.
        return Fetched(_assemble(docs[0]), "API", response.fetched, url)

    @staticmethod
    def _docs(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        docs = payload.get("response", {}).get("docs", [])
        return [doc for doc in docs if isinstance(doc, dict) and doc.get("symbol")]
