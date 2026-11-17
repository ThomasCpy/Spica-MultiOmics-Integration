"""All tissues across the locus: the regulation atlas of the integrator.

One assay, one row per tissue, one column per segment of the window. It
shows where each tissue has open chromatin, active promoters and enhancers,
or RNA coverage. One picture gives what forty separate tracks would give:
the tissues that use the regulatory elements of the gene, and which ones.

Rows share one scale. In the organ view, TPM and staining are different
measurements. Here each row is the same assay with the same processing, so
a darker cell in one tissue is a real difference.

Rows come from the same UCSC-hosted ENCODE and GTEx signals as the
per-tissue tracks of the genome view, and from the same cache. An atlas
drawn after a tissue track thus costs nothing for that tissue.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from spica.genome.locus import Locus
from spica.genome.tracks import (DNASE_TISSUES, GTEX_TISSUES, H3K27AC_TISSUES, _tissue_label,
                                 binned, gtex_labels, ucsc_wig)
from spica.live import Live, LiveError

#: Columns across the window: about 560 bases each for a 135 kb window.
ATLAS_BINS = 240
#: Tissues fetched at once. UCSC answers a tissue in one to three seconds.
WORKERS = 8

FAMILIES: dict[str, tuple[str, tuple[str, ...], str, str]] = {
    "dnase": ("wgEncodeReg4DnaseAll", DNASE_TISSUES, "Open chromatin (ENCODE DNase)",
              "DNase-seq signal"),
    "h3k27ac": ("wgEncodeReg4MarkH3k27acAll", H3K27AC_TISSUES,
                "Active chromatin (ENCODE H3K27ac)", "H3K27ac signal"),
    "gtex_coverage": ("gtexCov", GTEX_TISSUES, "RNA-seq coverage (GTEx)",
                      "median read coverage"),
}


def atlas(family: str, locus: Locus, live: Live) -> dict[str, Any]:
    if family not in FAMILIES:
        return {"error": f"no atlas called {family}"}
    prefix, tissues, label, unit = FAMILIES[family]
    start, end = locus.window_start, locus.window_end

    def one(tissue: str) -> tuple[str, list[float | None] | None, str]:
        try:
            features = ucsc_wig(live, f"{prefix}{tissue}", locus)
        except LiveError as exc:
            return tissue, None, str(exc)
        rows = [(f["start"], f["end"], f["value"]) for f in features]
        coarse = binned(rows, start, end, ATLAS_BINS)
        width = (end - start) / ATLAS_BINS
        values: list[float | None] = [None] * ATLAS_BINS
        for s, _, value in coarse:
            values[min(ATLAS_BINS - 1, int((s - start) / width))] = round(value, 4)
        return tissue, values, ""

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(one, tissues))

    names = gtex_labels(live) if family == "gtex_coverage" else {}
    label_of = lambda tissue: names.get(tissue) or _tissue_label(tissue)
    rows, failed = [], []
    for tissue, values, problem in results:
        if values is None:
            failed.append({"tissue": label_of(tissue), "reason": problem})
            continue
        measured = [v for v in values if v is not None]
        rows.append({"tissue": label_of(tissue), "key": tissue, "values": values,
                     "peak": round(max(measured), 4) if measured else None})
    peaks = [row["peak"] for row in rows if row["peak"] is not None]
    return {
        "family": family, "label": label, "unit": unit,
        "chrom": locus.chrom, "start": start, "end": end, "bins": ATLAS_BINS,
        "gene": {"symbol": locus.symbol, "start": locus.start, "end": locus.end,
                 "strand": locus.strand},
        "rows": rows, "failed": failed,
        "max": max(peaks) if peaks else 0.0,
    }
