"""UniProt: the protein, its sequence, and its annotated location.

Mirror file: `entries`, a tab-separated UniProtKB export. Columns: Entry,
Reviewed, Protein names, Gene Names, Length, Sequence and `Subcellular
location [CC]`. Optional: `Function [CC]`, the three `Gene Ontology (...)`
columns, `PDB` and `Alternative products (isoforms)`. The PDB column is
the `xref_pdb_full` field of the export (method, resolution and chain
ranges per entry). Resolution and coverage come from it, as on the API
route. An older export with only the IDs gives the count only.

API fallback: `rest.uniprot.org`. It returns the same facts already parsed
(locations as controlled-vocabulary terms, not as prose) and names its
release in a response header.
"""

from __future__ import annotations

import re
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError, read_tsv
from spica.sources.index import rows_for

ACCESSION_COLUMN = "Entry"
LOCATION_COLUMN = "Subcellular location [CC]"
REQUIRED = (ACCESSION_COLUMN,)

EVIDENCE = re.compile(r"\{[^}]*\}")  # {ECO:0000255|PROSITE-ProRule:PRU00448}
ISOFORM = re.compile(r"^\[[^\]]*\]:\s*")  # [Isoform 2]:
PREFIX = "SUBCELLULAR LOCATION:"

API = "https://rest.uniprot.org/uniprotkb"

GO_ASPECTS = {"P": "go_process", "F": "go_function", "C": "go_component"}
GO_COLUMNS = {"Gene Ontology (biological process)": "go_process",
              "Gene Ontology (molecular function)": "go_function",
              "Gene Ontology (cellular component)": "go_component"}
GO_TERM = re.compile(r"\s*\[GO:\d+\]\s*$")
NAMED_ISOFORMS = re.compile(r"Named isoforms=(\d+)")
CHAIN_RANGE = re.compile(r"=(\d+)-(\d+)")
RESOLUTION = re.compile(r"([\d.]+)\s*A")


def clean_text(text: str) -> str:
    """UniProt prose without its evidence tags or a leading FUNCTION:."""
    text = EVIDENCE.sub("", text)
    text = re.sub(r"^\s*FUNCTION:\s*", "", text)
    text = re.sub(r"\(PubMed:[^)]*\)", "", text)
    text = " ".join(text.split()).strip()
    # What the tags leave behind: "homeostasis ." and "binds ,".
    return re.sub(r"\s+([.,;:])", r"\1", text)


def join_statements(statements: list[str]) -> str:
    """Several FUNCTION statements as one paragraph of sentences.

    The export joins them as "...(By similarity).; FUNCTION: [Isoform 2]:
    May act..."; the API gives them one by one. Both become "...(By
    similarity). May act...", so a record reads the same from either.
    """
    out = []
    for statement in statements:
        text = clean_text(ISOFORM.sub("", statement.strip()))
        text = text.rstrip(" ;").rstrip(".").rstrip()
        if text:
            out.append(text + ".")
    return " ".join(out)


def function_statements(cell: str) -> list[str]:
    """The export's Function column split into its statements."""
    return [part for part in re.split(r";?\s*FUNCTION:\s*", cell) if part.strip()]


#: An alternative name in parentheses at the end of a protein name, which
#: may itself hold one level of parentheses: "(GABA(A) receptor subunit alpha-1)".
TRAILING_NAME = re.compile(r"\s\((?:[^()]|\([^()]*\))*\)$")
#: The parts of a precursor: "[Cleaved into: Insulin B chain; Insulin A chain]".
PARTS = re.compile(r"\s*\[(?:Cleaved into|Includes|Contains):.*$")


def recommended_name(cell: str) -> str:
    """The recommended name out of the export's Protein names column.

    The column is "Recommended (Alternative) (EC number) [Cleaved into: ...]";
    the API route reads recommendedName.fullName, which is the first part.
    """
    text = PARTS.sub("", cell.strip())
    while True:
        found = TRAILING_NAME.search(text)
        if not found or found.start() == 0:
            return text.strip()
        text = text[:found.start()]


def structures(xrefs: list[dict[str, Any]], length: int) -> dict[str, Any]:
    """Count, best resolution and sequence coverage from PDB cross-references.

    Coverage is the union of every chain's residue range over the canonical
    length: one 1-692 chain covers PCSK9 whole, ten overlapping fragments of
    the same domain cover only that domain.
    """
    pdb = [x for x in xrefs if x.get("database") == "PDB"]
    if not pdb:
        return {}
    covered: set[int] = set()
    best: float | None = None
    for xref in pdb:
        props = {p.get("key"): str(p.get("value", "")) for p in xref.get("properties", [])}
        match = RESOLUTION.search(props.get("Resolution", ""))
        if match:
            value = float(match.group(1))
            best = value if best is None else min(best, value)
        for start, end in CHAIN_RANGE.findall(props.get("Chains", "")):
            covered.update(range(int(start), int(end) + 1))
    out: dict[str, Any] = {"pdb_structures": len(pdb)}
    if best is not None:
        out["pdb_best_resolution"] = best
    if length:
        out["pdb_coverage"] = round(100 * len(covered & set(range(1, length + 1))) / length, 1)
    return out


def pdb_xrefs(cell: str) -> list[dict[str, Any]]:
    """The export's full PDB column as API-shaped cross-references.

        "2P4E; X-ray; 1.98 A; A/P=1-692.";"2PMW; X-ray; 2.30 A; A=31-152, B=153-692."

    An export with the IDs alone ("2P4E;2PMW;") has nothing to parse: [].
    """
    out = []
    for quoted in re.findall(r'"([^"]+)"', cell):
        parts = [part.strip() for part in quoted.strip().rstrip(".").split(";")]
        if len(parts) < 4:
            continue
        keys = ("Method", "Resolution", "Chains")
        out.append({"database": "PDB", "id": parts[0],
                    "properties": [{"key": key, "value": value}
                                   for key, value in zip(keys, parts[1:4])]})
    return out


def segments(xrefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every PDB entry with its method, resolution and residue ranges, for a plot."""
    out = []
    for xref in xrefs:
        if xref.get("database") != "PDB":
            continue
        props = {p.get("key"): str(p.get("value", "")) for p in xref.get("properties", [])}
        match = RESOLUTION.search(props.get("Resolution", ""))
        out.append({
            "id": str(xref.get("id", "")),
            "method": props.get("Method", ""),
            "resolution": float(match.group(1)) if match else None,
            "ranges": [[int(a), int(b)] for a, b in CHAIN_RANGE.findall(props.get("Chains", ""))],
        })
    return out


def parse_locations(cell: str) -> list[str]:
    """Location terms out of a UniProt subcellular-location comment.

    The comment is prose with annotation furniture in it:

        SUBCELLULAR LOCATION: [Isoform 1]: Cell membrane {ECO:0000250};
        Single-pass type I membrane protein. Note=Retained in the ER.

    Evidence tags, isoform markers and the free-text Note are dropped;
    everything else is kept verbatim and in order, topology statements
    included, because "single-pass type I membrane protein" is the part a
    triage decision turns on.
    """
    text = EVIDENCE.sub("", cell)
    terms: list[str] = []
    for statement in text.split(PREFIX):
        # The free-text Note runs to the end of its statement, sentences and
        # all; everything after "Note=" is commentary, not a location.
        statement = ISOFORM.sub("", statement.split("Note=", 1)[0].strip())
        if not statement:
            continue
        for part in re.split(r"[;.]", statement):
            part = part.strip()
            if not part or part.lower().startswith("note="):
                continue
            if part not in terms:  # keeps first-mention order, drops repeats
                terms.append(part)
    return terms


class UniProt(Source):
    key = "uniprot"
    label = "UniProt"
    needs = ("entries",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        row = self._row(identity, entry)
        fields: dict[str, Any] = {}

        name = recommended_name(row.get("Protein names", ""))
        if name:
            fields["protein_name"] = name

        sequence = row.get("Sequence", "").strip().upper()
        if sequence:
            fields["protein_sequence"] = sequence

        length = row.get("Length", "").strip()
        if length:
            try:
                fields["protein_length"] = int(length)
            except ValueError:
                raise SourceError(
                    f"UniProt {entry.version}: length {length} for "
                    f"{row.get(ACCESSION_COLUMN, '')} is not a number"
                ) from None
        elif sequence:
            # Derivable, but a record should say what the release says.
            fields["protein_length"] = len(sequence)

        locations = parse_locations(row.get(LOCATION_COLUMN, ""))
        if locations:
            fields["uniprot_subcellular_locations"] = locations

        function = join_statements(function_statements(row.get("Function [CC]", "")))
        if function:
            fields["uniprot_function"] = function
        for column, field_name in GO_COLUMNS.items():
            terms = [GO_TERM.sub("", t).strip() for t in row.get(column, "").split(";")]
            terms = [t for t in terms if t]
            if terms:
                fields[field_name] = terms
        isoforms = NAMED_ISOFORMS.search(row.get("Alternative products (isoforms)", ""))
        if isoforms:
            fields["uniprot_isoforms"] = int(isoforms.group(1))
        xrefs = pdb_xrefs(row.get("PDB", ""))
        if xrefs:
            fields.update(structures(xrefs, fields.get("protein_length") or 0))
            return fields
        pdb_ids = [p for p in row.get("PDB", "").replace(";", " ").split() if p]
        if pdb_ids:
            fields["pdb_structures"] = len(pdb_ids)
            reason = "UniProt export: PDB IDs only; chains from the API"
            fields["pdb_best_resolution"] = Absent(NullState.NOT_COVERED, reason)
            fields["pdb_coverage"] = Absent(NullState.NOT_COVERED, reason)
        return fields

    def _row(self, identity: Resolution, entry: MirrorEntry) -> dict[str, str]:
        """The protein entry, by accession when HGNC gives one.

        The fallback is the gene symbol, with a preference for reviewed
        entries. An unreviewed TrEMBL entry for the same gene is often a
        fragment. Its length as the protein length would be silently wrong.
        """
        wanted = identity.uniprot_accession.strip().upper()
        symbol = identity.symbol.strip().upper()
        reviewed_hit: dict[str, str] | None = None
        any_hit: dict[str, str] | None = None

        if wanted:
            for row in rows_for(entry.path("entries"), ACCESSION_COLUMN, wanted, REQUIRED):
                return row

        for row in read_tsv(entry.path("entries"), REQUIRED):
            if wanted and row.get(ACCESSION_COLUMN, "").strip().upper() == wanted:
                return row
            if symbol and reviewed_hit is None:
                names = {n.upper() for n in row.get("Gene Names", "").split()}
                if symbol in names:
                    is_reviewed = row.get("Reviewed", "").strip().lower() == "reviewed"
                    if is_reviewed:
                        reviewed_hit = row
                    elif any_hit is None:
                        any_hit = row

        hit = reviewed_hit or any_hit
        if hit is not None:
            return hit
        raise GeneNotInSource(f"{wanted or symbol} is not in UniProt {entry.version}")

    # -- the API ------------------------------------------------------------

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        entry, url, response = self._entry(identity, live)

        fields: dict[str, Any] = {}
        description = entry.get("proteinDescription", {})
        name = (description.get("recommendedName", {})
                .get("fullName", {}).get("value", ""))
        if not name:  # unreviewed entries carry a submitted name instead
            submitted = description.get("submissionNames") or []
            if submitted:
                name = submitted[0].get("fullName", {}).get("value", "")
        if name:
            fields["protein_name"] = str(name)

        sequence = entry.get("sequence", {})
        if sequence.get("value"):
            fields["protein_sequence"] = str(sequence["value"]).upper()
        if isinstance(sequence.get("length"), int):
            fields["protein_length"] = sequence["length"]

        locations: list[str] = []
        for comment in entry.get("comments", []):
            if comment.get("commentType") != "SUBCELLULAR LOCATION":
                continue
            for place in comment.get("subcellularLocations", []):
                for part in ("location", "topology"):
                    value = str(place.get(part, {}).get("value", "")).strip()
                    if value and value not in locations:
                        locations.append(value)
        if locations:
            fields["uniprot_subcellular_locations"] = locations

        texts = [t.get("value", "")
                 for c in entry.get("comments", []) if c.get("commentType") == "FUNCTION"
                 for t in c.get("texts", [])]
        function = join_statements(texts)
        if function:
            fields["uniprot_function"] = function
        for comment in entry.get("comments", []):
            if comment.get("commentType") == "ALTERNATIVE PRODUCTS":
                isoforms = comment.get("isoforms") or []
                if isoforms:
                    fields["uniprot_isoforms"] = len(isoforms)

        xrefs = entry.get("uniProtKBCrossReferences") or []
        go: dict[str, list[str]] = {}
        for xref in xrefs:
            if xref.get("database") != "GO":
                continue
            for prop in xref.get("properties", []):
                if prop.get("key") == "GoTerm" and ":" in str(prop.get("value", "")):
                    aspect, term = str(prop["value"]).split(":", 1)
                    name = GO_ASPECTS.get(aspect)
                    if name and term.strip() not in go.setdefault(name, []):
                        go[name].append(term.strip())
        fields.update(go)
        fields.update(structures(xrefs, int(sequence.get("length") or 0)))

        release = response.headers.get("X-UniProt-Release") or "API"
        return Fetched(fields, release, response.fetched, url)

    def _entry(self, identity: Resolution, live: Live):
        """The entry JSON, by accession where there is one, else by symbol."""
        if identity.uniprot_accession:
            url = f"{API}/{identity.uniprot_accession}.json"
            try:
                response = live.get_json(self.key, url)
            except NotFoundUpstream:
                raise GeneNotInSource(
                    f"UniProt has no entry {identity.uniprot_accession}"
                ) from None
            if isinstance(response.payload, dict):
                return response.payload, url, response
            raise SourceError("UniProt answered with something other than an entry")

        # Reviewed only. An unreviewed entry for the same gene is often a
        # fragment, and its length as the protein length would be silently
        # wrong.
        url = (f"{API}/search?query=gene_exact:{identity.symbol}"
               f"+AND+organism_id:9606+AND+reviewed:true&size=1&format=json")
        response = live.get_json(self.key, url)
        results = (response.payload or {}).get("results") or []
        if not results:
            raise GeneNotInSource(f"UniProt has no reviewed entry for {identity.symbol}")
        return results[0], url, response
