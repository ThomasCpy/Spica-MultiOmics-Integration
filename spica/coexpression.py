"""Genes whose tissue profile moves with this one.

From the co-expression pipeline of the integrator, reduced to its sound
core: the Pearson correlation of log-expression across GTEx tissues, between
the target and each other gene in the mirrored GTEx matrix. Genes that rise
and fall with a target often share its regulation or its cell type. This is
a lead, not a mechanism, and the screen says so.

Mirror only. A correlation against each gene needs the profile of each
gene. The mirror holds it as the GTEx median-TPM matrix; no API gives it in
one request. Without the mirror, the function says so.

All genes are ranked and returned. The view shows the strongest first and
opens to the rest.
"""

from __future__ import annotations

import math
from typing import Any

from spica.mirror import Mirror
from spica.sources.base import open_text
from spica.sources.gtex import mirror_labels, site_of

#: Genes expressed nowhere above this (TPM, every tissue) are left out of
#: the ranking: a gene that is off everywhere correlates with noise.
MIN_PEAK = 1.0


def _profile(cells: list[str]) -> list[float] | None:
    try:
        return [math.log1p(max(float(c), 0.0)) for c in cells]
    except ValueError:
        return None


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    sa = math.sqrt(sum(x * x for x in da))
    sb = math.sqrt(sum(y * y for y in db))
    if not sa or not sb:
        return None
    return sum(x * y for x, y in zip(da, db)) / (sa * sb)


def correlated(symbol: str, ensembl_id: str, mirror: Mirror) -> dict[str, Any]:
    entry = mirror.entry("gtex")
    if entry is None or "median_tpm" not in entry.files or not entry.path("median_tpm").exists():
        return {"error": "Co-expression needs the GTEx median-TPM matrix in the mirror: it "
                         "correlates this gene against every other gene, and no API answers "
                         "that in one request."}
    wanted = ensembl_id.strip().upper()
    genes: list[tuple[str, str, list[float], float]] = []
    target: list[float] | None = None
    with open_text(entry.path("median_tpm")) as handle:
        next(handle)
        next(handle)
        header = next(handle).rstrip("\n").split("\t")
        # The 54 sites only: v11's microdissected samples are parts of sites
        # already counted, and two columns for one liver would pull every
        # liver gene towards every other.
        labels = mirror_labels(entry)
        columns = [at for at, tissue in enumerate(header[2:], start=2)
                   if not (labels and site_of(tissue.strip(), labels))]
        tissues = len(columns)
        for line in handle:
            row = line.rstrip("\n").split("\t")
            if len(row) < len(header):
                continue
            profile = _profile([row[at] for at in columns])
            if profile is None:
                continue
            gene_id = row[0].split(".")[0].upper()
            if gene_id == wanted or (not wanted and row[1].upper() == symbol.upper()):
                target = profile
                continue
            peak = math.expm1(max(profile))
            genes.append((row[1], gene_id, profile, peak))
    if target is None:
        return {"error": f"{symbol} has no row in GTEx {entry.version}"}
    ranked = []
    left_out = 0
    for name, gene_id, profile, peak in genes:
        if peak < MIN_PEAK:
            left_out += 1
            continue
        r = _pearson(target, profile)
        if r is not None:
            ranked.append({"symbol": name, "ensembl_id": gene_id, "r": round(r, 3)})
    ranked.sort(key=lambda g: (-g["r"], g["symbol"]))
    return {"symbol": symbol, "source": f"GTEx {entry.version}", "tissues": tissues,
            "genes": ranked, "left_out": left_out, "min_peak": MIN_PEAK,
            "method": "Pearson correlation of log(1 + median TPM) across tissues"}
