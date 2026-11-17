"""GTEx: median bulk RNA expression across human tissues.

Mirror file: `median_tpm`, the GCT matrix of the release (gzipped is fine).
GCT is not a plain TSV: two header lines come before the column titles.
This module thus reads the file directly, not through `read_tsv`.

One linear scan per gene takes about a tenth of a second and needs no
index. The columns are tissue IDs (`Adipose_Subcutaneous`). They show
under the GTEx display names ("Adipose - Subcutaneous"), read from the
tissue list beside the matrix (optional file `tissues`). A record thus
reads the same from the mirror as from the API.

API fallback: `gtexportal.org/api/v2`. The portal serves v10, but the
release files are at v11. A fetched record thus says v10, and a mirrored
one gives the mirrored release. Two requests: the gene, for its GENCODE ID,
then the medians.
"""

from __future__ import annotations

import statistics
from typing import Any

from spica.live import Fetched, Live
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError, open_text

API = "https://gtexportal.org/api/v2"

#: The newest release that the portal serves, and the GENCODE version of
#: its gene identifiers. The two go together. A v10 median request with a
#: v26 gencodeId returns an empty list, not an error. That silently removes
#: a full section of a record.
DATASET = "gtex_v10"
GENCODE = "v39"
GENOME = "GRCh38/hg38"


def readable(tissue: str, labels: dict[str, str] | None = None) -> str:
    """The name to show for a GTEx tissue id.

    GTEx names its 54 sites. The samples v10 added by laser-capture
    microdissection (`Liver_Hepatocyte`, `Stomach_Mixed_Cell`) have no name
    of their own in that list; they take their site's name with the part in
    parentheses, "Liver (Hepatocyte)", spelled as GTEx spells the ID.
    """
    if labels:
        if tissue in labels:
            return labels[tissue]
        parent = site_of(tissue, labels)
        if parent:
            return f"{labels[parent]} ({tissue[len(parent) + 1:].replace('_', ' ')})"
    return tissue.replace("_", " ")


def site_of(tissue: str, labels: dict[str, str]) -> str:
    """The named site a microdissected sample belongs to, or "" if the
    column is not one: `Liver_Hepatocyte` belongs to `Liver`."""
    if tissue in labels:
        return ""
    return max((key for key in labels if tissue.startswith(key + "_")), key=len, default="")


def mirror_labels(entry: MirrorEntry) -> dict[str, str]:
    """Tissue id to name, from the list the mirror builder saved, if any."""
    if "tissues" not in entry.files or not entry.path("tissues").exists():
        return {}
    labels: dict[str, str] = {}
    with open_text(entry.path("tissues")) as handle:
        for line in handle:
            key, _, name = line.rstrip("\r\n").partition("\t")
            if key and name and key != "tissueSiteDetailId":
                labels[key] = name
    return labels



_MATRICES: dict[str, tuple[list[str], dict[str, str], dict[str, str]]] = {}


def _matrix(path) -> tuple[list[str], dict[str, str], dict[str, str]] | None:
    """The median matrix as (tissues, line by gene ID, line by symbol), read
    once per process: it is gzipped, so it cannot be seeked into, and a list
    of genes would otherwise unpack it once per gene. None when the file is
    not a GCT matrix; the scan below then says what is wrong with it."""
    stat = path.stat()
    stamp = f"{path}|{stat.st_size}|{int(stat.st_mtime)}"
    if stamp in _MATRICES:
        return _MATRICES[stamp]
    by_id: dict[str, str] = {}
    by_symbol: dict[str, str] = {}
    with open_text(path) as handle:
        try:
            next(handle)
            next(handle)
            header = next(handle).rstrip("\n").split("\t")
        except StopIteration:
            return None
        if len(header) < 3 or header[0].strip() != "Name":
            return None
        for line in handle:
            name, _, rest = line.partition("\t")
            symbol = rest.partition("\t")[0].strip().upper()
            # The first row for a symbol wins, as in the scan.
            by_id.setdefault(name.split(".")[0].strip().upper(), line)
            if symbol:
                by_symbol.setdefault(symbol, line)
    _MATRICES.clear()
    _MATRICES[stamp] = ([column.strip() for column in header[2:]], by_id, by_symbol)
    return _MATRICES[stamp]


class Gtex(Source):
    key = "gtex"
    label = "GTEx"
    needs = ("median_tpm",)

    def __init__(self) -> None:
        self._tissue_labels: dict[str, str] | None = None

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        tissues, values = self._row(identity, entry)
        # From the mirror only: names borrowed from an earlier API call would
        # make the same file read differently depending on what ran before.
        labels = mirror_labels(entry)

        by_tissue: dict[str, float] = {}
        parts: dict[str, float] = {}
        for tissue, cell in zip(tissues, values):
            try:
                value = round(float(cell), 2)
            except ValueError:
                raise SourceError(
                    f"GTEx {entry.version}: {cell} under {tissue} is not a number"
                ) from None
            # A column GTEx's site list does not name is a microdissected part
            # of a site that is in the profile already (Liver_Hepatocyte): it
            # goes apart, so tau and the median count each tissue once.
            if labels and site_of(tissue, labels):
                parts[readable(tissue, labels)] = value
            else:
                by_tissue[readable(tissue, labels)] = value

        if not by_tissue:
            return {}
        return {
            "gtex_tissue_tpm": by_tissue,
            "gtex_median_across_tissues": round(
                statistics.median(by_tissue.values()), 2
            ),
            "gtex_microdissected_tpm": parts or Absent(
                NullState.NOT_COVERED,
                f"GTEx {entry.version} has no microdissected samples"
                if labels else "the mirror has no GTEx tissue list to tell them apart by"),
        }

    def _row(
        self, identity: Resolution, entry: MirrorEntry
    ) -> tuple[list[str], list[str]]:
        path = entry.path("median_tpm")
        wanted_id = identity.ensembl_gene_id.strip().upper()
        wanted_symbol = identity.symbol.strip().upper()
        matrix = _matrix(path)
        if matrix is not None:
            tissues, by_id, by_symbol_index = matrix
            line = by_id.get(wanted_id) if wanted_id else None
            if line is None and wanted_symbol:
                line = by_symbol_index.get(wanted_symbol)
            if line is not None:
                return tissues, line.rstrip("\n").split("\t")[2:]
            looked_for = wanted_id or wanted_symbol
            raise GeneNotInSource(f"{looked_for} has no row in GTEx {entry.version}")

        with open_text(path) as handle:
            try:
                next(handle)  # "#1.2"
                next(handle)  # rows / columns
                header = next(handle).rstrip("\n").split("\t")
            except StopIteration:
                raise SourceError(f"{path.name} is not a GCT matrix") from None
            if len(header) < 3 or header[0].strip() != "Name":
                raise SourceError(
                    f"{path.name} has no GCT column header (found {header[:3]})"
                )
            tissues = [column.strip() for column in header[2:]]
            by_symbol: list[str] | None = None

            for line in handle:
                row = line.rstrip("\n").split("\t")
                if len(row) < 3:
                    continue
                # The Name column is a versioned GENCODE ID (ENSG...15);
                # HGNC cross-references the unversioned one.
                gene_id = row[0].split(".")[0].strip().upper()
                if wanted_id and gene_id == wanted_id:
                    return tissues, row[2:]
                if by_symbol is None and wanted_symbol:
                    if row[1].strip().upper() == wanted_symbol:
                        # The release is built on one GENCODE version; a gene
                        # whose Ensembl ID has since been retired is still in
                        # the matrix under its symbol.
                        by_symbol = row[2:]

            if by_symbol is not None:
                return tissues, by_symbol

        looked_for = wanted_id or wanted_symbol
        raise GeneNotInSource(f"{looked_for} has no row in GTEx {entry.version}")

    # -- the API ------------------------------------------------------------

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        gencode_id = self._gencode_id(identity, live)
        url = (f"{API}/expression/medianGeneExpression?gencodeId={gencode_id}"
               f"&datasetId={DATASET}&itemsPerPage=1000")
        response = live.get_json(self.key, url)
        rows = (response.payload or {}).get("data") or []
        if not rows:
            raise GeneNotInSource(f"{gencode_id} has no medians in {DATASET}")

        labels = self._labels(live)
        by_tissue: dict[str, float] = {}
        for row in rows:
            tissue = str(row.get("tissueSiteDetailId", "")).strip()
            median = row.get("median")
            if not tissue or not isinstance(median, (int, float)):
                continue
            by_tissue[readable(tissue, labels)] = round(float(median), 2)
        if not by_tissue:
            raise SourceError(f"{DATASET} answered with no usable medians")

        fields = {
            "gtex_tissue_tpm": by_tissue,
            "gtex_median_across_tissues": round(statistics.median(by_tissue.values()), 2),
            "gtex_microdissected_tpm": Absent(
                NullState.NOT_COVERED,
                f"GTEx API: {DATASET.replace('gtex_', '')} only; microdissected samples: v11, "
                "local mirror"),
        }
        version = str(rows[0].get("datasetId", DATASET)).replace("gtex_", "")
        return Fetched(fields, version, response.fetched, url)

    def _gencode_id(self, identity: Resolution, live: Live) -> str:
        """The versioned GENCODE ID that the expression endpoint requires.

        The portal is pinned to the GENCODE release of its dataset. The
        suffix from HGNC or Ensembl is thus wrong, and the lookup must come
        from GTEx itself, for this release.
        """
        query = identity.ensembl_gene_id or identity.symbol
        url = (f"{API}/reference/gene?geneId={query}"
               f"&gencodeVersion={GENCODE}"
               f"&genomeBuild={GENOME.replace('/', '%2F')}")
        response = live.get_json(self.key, url)
        rows = (response.payload or {}).get("data") or []
        for row in rows:
            if row.get("gencodeId"):
                return str(row["gencodeId"])
        raise GeneNotInSource(f"GTEx {DATASET} has no gene {query}")

    def _labels(self, live: Live) -> dict[str, str]:
        """Tissue id to the name GTEx prints, asked for once and cached.

        The matrices key on `Brain_Cerebellar_Hemisphere`; the portal calls
        it "Brain - Cerebellar Hemisphere". Deriving one from the other is
        not safe: `Small_Intestine_Terminal_Ileum` is "Small Intestine -
        Terminal Ileum", not "Small - Intestine Terminal Ileum", so the
        mapping is fetched rather than guessed.
        """
        if self._tissue_labels is not None:
            return self._tissue_labels
        labels: dict[str, str] = {}
        try:
            response = live.get_json(
                self.key, f"{API}/dataset/tissueSiteDetail?itemsPerPage=200")
            for row in (response.payload or {}).get("data") or []:
                key, name = row.get("tissueSiteDetailId"), row.get("tissueSiteDetail")
                if key and name:
                    labels[str(key)] = str(name)
        except Exception:
            pass  # a missing label map costs readability, not the record
        self._tissue_labels = labels
        return labels
