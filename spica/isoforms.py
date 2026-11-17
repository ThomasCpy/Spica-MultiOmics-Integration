"""The transcripts of a gene that each tissue uses.

From the isoform work of the integrator, as one table: median TPM for each
transcript of the gene in each tissue, with Ensembl names and biotypes
beside the IDs. The data comes from the mirror when it holds the HPA
transcript medians and the Ensembl transcript table (`spica/mirrorbuild.py`).
Otherwise it comes from the GTEx API, cached. A problem target can express
in its tissue of interest a different isoform from the one used to raise an
antibody. Gene-level numbers cannot show this.

All transcripts and all tissues stay. The GTEx API pages its answers at
250 rows by default. For a gene with six transcripts, that is already less
than the 324 values. The request thus asks for all of them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream
from spica.sources.base import GeneNotInSource
from spica.sources.gtex import API, DATASET, Gtex, readable

ENSEMBL = "https://rest.ensembl.org"


def local(symbol: str, ensembl_id: str, mirror) -> dict[str, Any] | None:
    """The table from HPA's transcript medians, or None when the mirror lacks
    them (the API route then answers)."""
    from spica.sources.index import rows_for

    hpa, ensembl = mirror.entry("hpa"), mirror.entry("ensembl")
    if not (hpa and ensembl and "transcripts" in hpa.files and "transcripts" in ensembl.files
            and hpa.path("transcripts").exists() and ensembl.path("transcripts").exists()):
        return None
    gene = ensembl_id.strip().upper()
    names = {}
    for row in rows_for(ensembl.path("transcripts"), "Gene stable ID", gene):
        names[row.get("Transcript stable ID", "")] = {
            "name": row.get("Transcript name", ""), "biotype": row.get("Transcript type", ""),
            "canonical": row.get("Ensembl Canonical", "").strip() == "1"}
    values: dict[str, dict[str, float]] = {}
    for row in rows_for(hpa.path("transcripts"), "ensgid", gene):
        per = {}
        for tissue, cell in row.items():
            if tissue in ("ensgid", "enstid") or cell == "":
                continue
            try:
                per[tissue] = float(cell)
            except ValueError:
                continue
        values[row["enstid"]] = per
    if not values:
        return {"error": f"HPA {hpa.version} has no transcript expression for {symbol}"}
    return _shape(symbol, values, names, f"HPA {hpa.version} tissue RNA-seq, with Ensembl "
                                         f"{ensembl.version}'s transcript names", "median TPM", "")


def _shape(symbol: str, values: dict[str, dict[str, float]], names: dict[str, dict[str, Any]],
           dataset: str, unit: str, fetched: str) -> dict[str, Any]:
    # Transcripts by how much they are used overall, most first; tissues by name.
    order = sorted(values, key=lambda t: -sum(values[t].values()))
    tissues = sorted({tissue for per in values.values() for tissue in per})
    transcripts = []
    for transcript in order:
        info = names.get(transcript.split(".")[0], {})
        total = sum(values[transcript].values())
        transcripts.append({"id": transcript, "name": info.get("name", ""),
                            "biotype": info.get("biotype", ""),
                            "canonical": bool(info.get("canonical")),
                            "expressed_in": sum(1 for v in values[transcript].values() if v >= 1),
                            "total": round(total, 2)})
    # Per tissue, which transcript leads and with what share of the gene.
    dominant = {}
    for tissue in tissues:
        per = {t: values[t].get(tissue, 0.0) for t in order}
        total = sum(per.values())
        if total > 0:
            lead = max(per, key=per.get)
            dominant[tissue] = {"transcript": lead, "share": round(100 * per[lead] / total, 1)}
    return {"symbol": symbol, "dataset": dataset, "unit": unit, "transcripts": transcripts,
            "tissues": tissues, "values": {t: values[t] for t in order}, "dominant": dominant,
            "fetched": fetched}


def table(symbol: str, ensembl_id: str, live: Live, mirror=None) -> dict[str, Any]:
    found = local(symbol, ensembl_id, mirror) if mirror is not None else None
    if found is not None:
        return found
    gtex = Gtex()
    identity = SimpleNamespace(ensembl_gene_id=ensembl_id, symbol=symbol)
    try:
        gencode = gtex._gencode_id(identity, live)
        response = live.get_json(
            "gtex", f"{API}/expression/medianTranscriptExpression?gencodeId={gencode}"
                    f"&datasetId={DATASET}&itemsPerPage=100000")
    except GeneNotInSource as exc:
        return {"error": str(exc)}
    except (LiveError, NotFoundUpstream) as exc:
        return {"error": f"GTEx not read: {exc}"}

    rows = [r for r in (response.payload or {}).get("data") or [] if isinstance(r, dict)]
    if not rows:
        return {"error": f"GTEx {DATASET} has no transcript expression for {symbol}"}
    labels = gtex._labels(live)

    names = transcript_names(ensembl_id, live)
    values: dict[str, dict[str, float]] = {}
    for row in rows:
        transcript = str(row.get("transcriptId", ""))
        tissue = readable(str(row.get("tissueSiteDetailId", "")), labels)
        try:
            values.setdefault(transcript, {})[tissue] = round(float(row.get("median") or 0.0), 2)
        except (TypeError, ValueError):
            continue

    return _shape(symbol, values, names, DATASET, "median TPM", response.fetched)


def transcript_names(ensembl_id: str, live: Live) -> dict[str, dict[str, Any]]:
    """Ensembl's display name, biotype and canonical flag per transcript."""
    try:
        gene = live.get_json(
            "ensembl", f"{ENSEMBL}/lookup/id/{ensembl_id}?expand=1;content-type=application/json"
        ).payload or {}
    except (LiveError, NotFoundUpstream):
        return {}
    out = {}
    for transcript in gene.get("Transcript") or []:
        out[str(transcript.get("id", ""))] = {
            "name": transcript.get("display_name", ""),
            "biotype": transcript.get("biotype", ""),
            "canonical": transcript.get("is_canonical") in (1, "1", True),
        }
    return out
