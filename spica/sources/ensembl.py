"""Ensembl: biotype, where the gene sits on the genome, and its orthologs
in the two species a programme leans on, mouse and cynomolgus macaque.

Mirror files: `genes`, a BioMart gene export, tab separated, with the
default column titles. The assembly it was taken against is not in the file,
so the manifest states it:

    "ensembl": {"version": "115", "assembly": "GRCh38.p14", ...}

`orthologs_mouse` and `orthologs_cyno` (optional): BioMart exports of every
human gene's orthologs in each species, from Ensembl Compara, with BioMart's
column titles, which name the species ("Mouse gene stable ID").

API fallback: `rest.ensembl.org/lookup`, which answers with the assembly in
the payload, so nothing has to be declared for the live route; orthologs
from `rest.ensembl.org/homology`, which gives no confidence call.

Identity is the share of the *human* protein identical in the ortholog.
BioMart titles that column "%id. target Mouse gene identical to query
gene" and the REST API puts it under `source.perc_id`; both are the
identical residues over the human length, checked against the alignment.
"""

from __future__ import annotations

from typing import Any

from spica.live import Fetched, Live, LiveError, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError, read_tsv
from spica.sources.index import rows_for

ID_COLUMN = "Gene stable ID"
REQUIRED = (ID_COLUMN, "Gene type")

STRAND = {"1": "+", "-1": "-", "+1": "+"}

API = "https://rest.ensembl.org"

#: The model species, by field prefix: how BioMart's titles and the REST API
#: name each, and the mirror file that holds it.
SPECIES = {
    "mouse": {"title": "Mouse", "rest": "mus_musculus", "file": "orthologs_mouse",
              "name": "mouse"},
    "cyno": {"title": "Crab-eating macaque", "rest": "macaca_fascicularis",
             "file": "orthologs_cyno", "name": "cynomolgus"},
}
PARTS = ("orthologs", "orthology", "protein_identity")
TYPES = {"ortholog_one2one": "one-to-one", "ortholog_one2many": "one-to-many",
         "ortholog_many2many": "many-to-many"}


def _number(text: str) -> float | None:
    try:
        return float(str(text).strip())
    except ValueError:
        return None


def ortholog_fields(prefix: str, found: list[dict[str, Any]], species: str, gene: str,
                    version: str) -> dict[str, Any]:
    """The three fields for one species, from its orthologs, closest first."""
    if not found:
        reason = f"Ensembl {version} records no {species} ortholog for {gene}"
        return {f"{prefix}_{part}": Absent(NullState.NOT_FOUND, reason) for part in PARTS}
    found = sorted(found, key=lambda o: (-(o["identity"] or 0), o["id"]))
    best = found[0]
    kind = TYPES.get(best["type"], best["type"].replace("_", " "))
    if best["confidence"] is not None:
        kind += ", high confidence" if best["confidence"] else ", low confidence"
    identity: Any = round(best["identity"], 1) if best["identity"] is not None else Absent(
        NullState.NOT_FOUND, f"Ensembl {version} gives no identity for {best['id']}")
    return {f"{prefix}_orthologs": [f"{o['name'] or 'unnamed'} {o['id']}" for o in found],
            f"{prefix}_orthology": kind, f"{prefix}_protein_identity": identity}


class Ensembl(Source):
    key = "ensembl"
    label = "Ensembl"
    needs = ("genes",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        row = self._row(identity, entry)
        fields: dict[str, Any] = {"gene_biotype": row.get("Gene type", "").strip()}

        chromosome = row.get("Chromosome/scaffold name", "").strip()
        start = row.get("Gene start (bp)", "").strip()
        end = row.get("Gene end (bp)", "").strip()
        if chromosome and start and end:
            assembly = entry.extra.get("assembly", "").strip()
            strand = STRAND.get(row.get("Strand", "").strip(), "")
            span = f"{chromosome}:{start}-{end}"
            fields["genomic_location"] = " ".join(
                part for part in (assembly, span, f"({strand})" if strand else "") if part
            )
        gene_id = row.get(ID_COLUMN, "").strip()
        for prefix, species in SPECIES.items():
            fields.update(self._orthologs(prefix, species, gene_id, entry))
        return fields

    def _orthologs(self, prefix: str, species: dict[str, str], gene_id: str,
                   entry: MirrorEntry) -> dict[str, Any]:
        key, title = species["file"], species["title"]
        if key not in entry.files or not entry.path(key).exists():
            reason = f"no {species['name']} orthologs in the local Ensembl data; Ensembl update required"
            return {f"{prefix}_{part}": Absent(NullState.FAILED, reason) for part in PARTS}
        found: dict[str, dict[str, Any]] = {}
        for row in rows_for(entry.path(key), ID_COLUMN, gene_id):
            other = row.get(f"{title} gene stable ID", "").strip()
            if not other or other in found:
                continue
            confidence = row.get(f"{title} orthology confidence [0 low, 1 high]", "").strip()
            found[other] = {
                "id": other, "name": row.get(f"{title} gene name", "").strip(),
                "type": row.get(f"{title} homology type", "").strip(),
                "identity": _number(row.get(f"%id. target {title} gene identical to query gene", "")),
                "confidence": {"1": True, "0": False}.get(confidence)}
        return ortholog_fields(prefix, list(found.values()), species["name"], gene_id, entry.version)

    def locator(self, field_name: str, entry: MirrorEntry) -> str:
        for prefix, species in SPECIES.items():
            if field_name.startswith(prefix + "_"):
                return entry.files.get(species["file"], "")
        return entry.files.get("genes", "")

    def _row(self, identity: Resolution, entry: MirrorEntry) -> dict[str, str]:
        """The gene's row, by Ensembl ID where HGNC cross-references one.

        The fallback to the symbol is there for the genes HGNC has not
        cross-referenced yet; it matches Ensembl's own gene name, so it can
        only find a gene the two authorities already agree on.
        """
        wanted_id = identity.ensembl_gene_id.strip()
        wanted_symbol = identity.symbol.strip().upper()
        by_symbol: dict[str, str] | None = None

        if wanted_id:
            for row in rows_for(entry.path("genes"), ID_COLUMN, wanted_id, REQUIRED):
                return row
        for row in read_tsv(entry.path("genes"), REQUIRED):
            stable_id = row.get(ID_COLUMN, "").strip()
            if wanted_id and stable_id == wanted_id:
                return row
            if by_symbol is None and wanted_symbol:
                if row.get("Gene name", "").strip().upper() == wanted_symbol:
                    by_symbol = row

        if by_symbol is not None:
            return by_symbol
        looked_for = wanted_id or wanted_symbol
        raise GeneNotInSource(f"{looked_for} is not in Ensembl {entry.version}")

    # -- the API ------------------------------------------------------------

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        if identity.ensembl_gene_id:
            url = f"{API}/lookup/id/{identity.ensembl_gene_id}?content-type=application/json"
        else:
            url = (f"{API}/lookup/symbol/homo_sapiens/{identity.symbol}"
                   f"?content-type=application/json")
        try:
            response = live.get_json(self.key, url)
        except NotFoundUpstream:
            looked_for = identity.ensembl_gene_id or identity.symbol
            raise GeneNotInSource(f"Ensembl has no record for {looked_for}") from None

        payload = response.payload
        if not isinstance(payload, dict):
            raise SourceError("Ensembl answered with something other than a gene")

        fields: dict[str, Any] = {}
        if payload.get("biotype"):
            fields["gene_biotype"] = str(payload["biotype"])

        chromosome = payload.get("seq_region_name")
        start, end = payload.get("start"), payload.get("end")
        if chromosome and start and end:
            strand = STRAND.get(str(payload.get("strand", "")), "")
            assembly = str(payload.get("assembly_name", "")).strip()
            span = f"{chromosome}:{start}-{end}"
            fields["genomic_location"] = " ".join(
                part for part in (assembly, span, f"({strand})" if strand else "") if part
            )
        release = self._release(live)
        fields.update(self._orthologs_live(str(payload.get("id") or identity.ensembl_gene_id),
                                           live, release))
        return Fetched(fields, release, response.fetched, url)

    def _orthologs_live(self, gene_id: str, live: Live, release: str) -> dict[str, Any]:
        species = ";".join(f"target_species={s['rest']}" for s in SPECIES.values())
        url = (f"{API}/homology/id/human/{gene_id}?{species};type=orthologues;sequence=none;"
               f"content-type=application/json")
        try:
            payload = live.get_json(self.key, url).payload
        except NotFoundUpstream:
            payload = {}
        except LiveError as exc:
            reason = f"Ensembl homology service not reached: {exc}"
            return {f"{prefix}_{part}": Absent(NullState.FAILED, reason)
                    for prefix in SPECIES for part in PARTS}
        homologies = [h for block in (payload.get("data") or [] if isinstance(payload, dict) else [])
                      for h in block.get("homologies") or []]
        fields: dict[str, Any] = {}
        for prefix, species in SPECIES.items():
            found = []
            for h in homologies:
                target = h.get("target") or {}
                if target.get("species") != species["rest"] or not target.get("id"):
                    continue
                found.append({"id": str(target["id"]), "name": self._name(str(target["id"]), live),
                              "type": str(h.get("type") or ""),
                              "identity": _number((h.get("source") or {}).get("perc_id", "")),
                              "confidence": None})  # the REST answer does not carry it
            fields.update(ortholog_fields(prefix, found, species["name"], gene_id, release))
        return fields

    def _name(self, stable_id: str, live: Live) -> str:
        """An ortholog's gene name: the homology answer gives only its ID."""
        try:
            payload = live.get_json(self.key, f"{API}/lookup/id/{stable_id}"
                                              f"?content-type=application/json").payload
        except Exception:
            return ""  # a missing name is not worth failing the ortholog over
        return str(payload.get("display_name") or "") if isinstance(payload, dict) else ""

    def _release(self, live: Live) -> str:
        """The Ensembl release number, asked for once and then cached."""
        try:
            info = live.get_json(self.key, f"{API}/info/data?content-type=application/json")
            releases = info.payload.get("releases") if isinstance(info.payload, dict) else None
            if releases:
                return str(releases[0])
        except Exception:
            pass  # a missing release label is not worth failing a record over
        return "API"
