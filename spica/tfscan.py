"""Transcription factors at the promoter of a gene: their motifs, and the
measured binding that supports them.

From the transcription-factor menu of the integrator (`modules/regulation.py`).
It listed the regulators of a gene, their JASPAR consensus, and whether
ENCODE had ChIP-seq for them. This module crosses the two:

1. **The regulators.** The transcriptional regulators of the gene from
   OmniPath (DoRothEA, CollecTRI and its other regulons), commercial records
   only, with the sign of each edge and its paper count.
2. **The binding motif of each one.** The JASPAR 2024 matrix of the factor
   (CORE, vertebrates, non-redundant), its consensus in IUPAC letters, and a
   scan of the promoter on both strands. A site counts when its score has a
   p-value below 1e-4 under a uniform background, the JASPAR cut-off. The
   p-value comes exactly from the matrix, not as a fraction of the best
   score.
3. **The measured binding.** ENCODE clustered TF ChIP-seq peaks over the
   same segment, factor by factor. A motif site inside a peak of the same
   factor has both kinds of evidence. That is the strongest case for direct
   regulation that the public data can give.

Absences are stated plainly. A regulator without a JASPAR matrix is not a
sequence-specific binder that JASPAR curates. A factor that ENCODE never
assayed has no peak to show; this is not evidence against binding.

Deterministic: the same inputs give the same answer. No model takes part.

Licences: JASPAR CC BY 4.0 (stated on its site). OmniPath records filtered
to commercial use. ENCODE data usable without restriction. The sequence is
GRCh38 from UCSC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from spica.genome import encode as genome_encode
from spica.genome import locus as genome_locus
from spica.genome.tracks import UCSC, ucsc_rows
from spica.live import Live, LiveError, NotFoundUpstream, OFF

JASPAR_URL = ("https://jaspar.elixir.no/download/data/2024/CORE/"
              "JASPAR2024_CORE_vertebrates_non-redundant_pfms_jaspar.txt")
JASPAR_RELEASE = "JASPAR 2024, CORE vertebrates, non-redundant"
#: The promoter, in the gene's own direction: this far upstream of the TSS
#: and this far into the gene.
UPSTREAM, DOWNSTREAM = 2000, 500
#: Longest stretch the scan accepts, so a request cannot ask for a chromosome.
MAX_REGION = 50_000
#: JASPAR's own cut-off (a UCSC track score of 400 is p < 1e-4).
P_VALUE = 1e-4
#: Pseudocount added to a column's counts, spread by the background.
PSEUDOCOUNT = 0.8
#: Scores are summed as integers in hundredths of a bit, so the exact
#: p-value comes from a convolution rather than an approximation.
SCALE = 100
BASES = "ACGT"
CHIP_TRACK = "encRegTfbsClustered"
CHIP_LABEL = "ENCODE clustered TF ChIP-seq (UCSC, 340 factors, 2019)"
_IUPAC = {
    frozenset("A"): "A", frozenset("C"): "C", frozenset("G"): "G", frozenset("T"): "T",
    frozenset("AC"): "M", frozenset("AG"): "R", frozenset("AT"): "W", frozenset("CG"): "S",
    frozenset("CT"): "Y", frozenset("GT"): "K", frozenset("ACG"): "V", frozenset("ACT"): "H",
    frozenset("AGT"): "D", frozenset("CGT"): "B", frozenset("ACGT"): "N",
}


class ScanError(Exception):
    pass


@dataclass(frozen=True)
class Matrix:
    id: str
    name: str
    counts: tuple[tuple[float, ...], ...]  # four rows, A C G T, one column per position

    @property
    def length(self) -> int:
        return len(self.counts[0])

    def to_dict(self) -> dict[str, Any]:
        total = [sum(self.counts[b][i] for b in range(4)) or 1.0 for i in range(self.length)]
        return {"id": self.id, "name": self.name, "length": self.length,
                "consensus": consensus(self),
                # Frequencies per position, for the sequence logo.
                "frequencies": [[round(self.counts[b][i] / total[i], 4) for b in range(4)]
                                for i in range(self.length)],
                "url": f"https://jaspar.elixir.no/matrix/{self.id}/"}


# -- matrices -----------------------------------------------------------------------------


def parse_jaspar(text: str) -> list[Matrix]:
    """Matrices from a file in JASPAR's own format."""
    out: list[Matrix] = []
    blocks = re.split(r"^>", text, flags=re.M)
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 5:
            continue
        head = lines[0].split(None, 1)
        rows = {}
        for line in lines[1:5]:
            match = re.match(r"([ACGT])\s*\[?([^\]]*)\]?", line)
            if match:
                rows[match.group(1)] = tuple(float(x) for x in match.group(2).split())
        if set(rows) == set(BASES) and len({len(r) for r in rows.values()}) == 1:
            out.append(Matrix(head[0], head[1].strip() if len(head) > 1 else head[0],
                              tuple(rows[b] for b in BASES)))
    return out


def matrices(live: Live) -> list[Matrix]:
    """JASPAR's matrices: one file, read once and kept in the cache."""
    try:
        text = live.get_text("jaspar", JASPAR_URL).payload
    except NotFoundUpstream as exc:
        raise ScanError(f"JASPAR: {exc}") from None
    found = parse_jaspar(str(text))
    if not found:
        raise ScanError("JASPAR's matrix file could not be read")
    return found


def pick(all_matrices: list[Matrix], factor: str) -> tuple[Matrix | None, str]:
    """The matrix for a factor: its own, else one it binds as part of a dimer."""
    names = [part.upper() for part in re.split(r"[_:]+", factor) if part]
    for name in names:
        own = [m for m in all_matrices if m.name.upper() == name]
        if own:
            return own[0], ""
    for name in names:
        dimer = [m for m in all_matrices if name in m.name.upper().split("::")]
        if dimer:
            return dimer[0], f"as part of {dimer[0].name}"
    return None, "no JASPAR CORE matrix (not a sequence-specific binder JASPAR curates)"


def consensus(matrix: Matrix, threshold: float = 0.25) -> str:
    """The matrix in IUPAC letters: each position names every base at a
    quarter of the counts or more."""
    out = []
    for i in range(matrix.length):
        column = {b: matrix.counts[k][i] for k, b in enumerate(BASES)}
        total = sum(column.values()) or 1.0
        keep = {b for b, c in column.items() if c / total >= threshold} or {max(column, key=column.get)}
        out.append(_IUPAC[frozenset(keep)])
    return "".join(out)


def weights(matrix: Matrix, background: float = 0.25) -> np.ndarray:
    """Log-odds in hundredths of a bit, positions by bases, as integers."""
    counts = np.array(matrix.counts, dtype=float).T  # positions x 4
    total = counts.sum(axis=1, keepdims=True)
    probability = (counts + PSEUDOCOUNT * background) / (total + PSEUDOCOUNT)
    return np.rint(np.log2(probability / background) * SCALE).astype(np.int64)


def tail(table: np.ndarray) -> tuple[int, np.ndarray]:
    """The exact chance that a random sequence (uniform background) scores at
    least each total, by convolving the columns: (lowest total, P(score >= s))."""
    low = int(table.min(axis=1).sum())
    distribution = np.ones(1)
    for column in table:
        floor = int(column.min())
        span = int(column.max()) - floor
        grown = np.zeros(distribution.size + span)
        for value in column:
            shift = int(value) - floor
            grown[shift:shift + distribution.size] += distribution * 0.25
        distribution = grown
    return low, np.cumsum(distribution[::-1])[::-1]


def threshold(table: np.ndarray, p_value: float = P_VALUE) -> tuple[int, int, np.ndarray]:
    """The lowest integer score whose tail is at or below `p_value`."""
    low, chance = tail(table)
    passing = np.nonzero(chance <= p_value)[0]
    cut = low + int(passing[0]) if passing.size else low + chance.size
    return cut, low, chance


def scan(sequence: str, matrix: Matrix, p_value: float = P_VALUE) -> list[dict[str, Any]]:
    """Every site on either strand scoring at or past the cut-off.

    Positions are 0-based in `sequence`; `strand` is the strand the motif
    reads on; `site` is the matched bases read 5' to 3' along the motif."""
    table = weights(matrix)
    length = table.shape[0]
    codes = np.array([BASES.find(base) for base in sequence.upper()], dtype=np.int64)
    if codes.size < length:
        return []
    cut, low, chance = threshold(table, p_value)
    windows = np.lib.stride_tricks.sliding_window_view(codes, length)
    clean = (windows >= 0).all(axis=1)  # a window holding an N is not scored
    safe = np.where(windows >= 0, windows, 0)
    positions = np.arange(length)
    found = []
    # Reverse complement: positions reversed and A<->T, C<->G swapped.
    for strand, table_here in (("+", table), ("-", table[::-1, ::-1])):
        scores = table_here[positions, safe].sum(axis=1)
        for i in np.nonzero(clean & (scores >= cut))[0]:
            site = sequence[i:i + length].upper()
            if strand == "-":
                site = site[::-1].translate(str.maketrans("ACGT", "TGCA"))
            score = int(scores[i])
            found.append({"start": int(i), "end": int(i + length), "strand": strand,
                          "score": round(score / SCALE, 2),
                          "p": float(f"{chance[score - low]:.2g}"), "site": site})
    # A palindromic motif matches the same bases on both strands: one site,
    # kept on the strand that scores better.
    best: dict[int, dict[str, Any]] = {}
    for hit in found:
        if hit["start"] not in best or hit["p"] < best[hit["start"]]["p"]:
            best[hit["start"]] = hit
    return [best[start] for start in sorted(best)]


# -- the gene -----------------------------------------------------------------------------


def _tss(found: genome_locus.Locus, live: Live) -> tuple[int, str]:
    """The canonical transcript's start (0-based), else the gene's 5' end."""
    try:
        gene = live.get_json(
            "ensembl", f"{genome_locus.ENSEMBL}/lookup/id/{found.ensembl_id}"
                       "?expand=1;content-type=application/json").payload or {}
        for transcript in gene.get("Transcript") or []:
            if transcript.get("is_canonical") in (1, "1", True):
                if found.strand == "+":
                    return int(transcript["start"]) - 1, f"canonical transcript {transcript.get('id')}"
                return int(transcript["end"]), f"canonical transcript {transcript.get('id')}"
    except (LiveError, NotFoundUpstream, KeyError, TypeError, ValueError):
        pass
    return (found.start if found.strand == "+" else found.end), "the gene's 5' end"


def _sequence(live: Live, chrom: str, start: int, end: int) -> str:
    url = f"{UCSC.replace('/track', '/sequence')}?genome=hg38;chrom={chrom};start={start};end={end}"
    payload = live.get_json("ucsc", url).payload or {}
    sequence = str(payload.get("dna") or "")
    if len(sequence) != end - start:
        raise ScanError(f"UCSC returned {len(sequence):,} bases for a {end - start:,}-base region")
    return sequence


def _level(sources: str) -> str:
    """DoRothEA's confidence letter for an edge, if DoRothEA graded it."""
    letters = sorted(set(re.findall(r"DoRothEA-([A-E])", sources or "")))
    return letters[0] if letters else ""


def _regulators(symbol: str, live: Live, mirror=None) -> tuple[list[dict[str, Any]], str]:
    from spica import regulators as omnipath_regulators

    reader = omnipath_regulators._Reader(live, mirror)
    rows = reader.regulating(symbol)
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("source_genesymbol") or "")
        if not name:
            continue
        entry = merged.setdefault(name, {"tf": name, "effect": omnipath_regulators._effect(row),
                                         "level": "", "references": 0})
        level = _level(str(row.get("sources") or ""))
        if level and (not entry["level"] or level < entry["level"]):
            entry["level"] = level
        refs = row.get("n_references")
        if refs is None:
            refs = len({r.split(":")[-1] for r in str(row.get("references") or "").split(";") if r})
        entry["references"] = max(entry["references"], int(refs or 0))
    return sorted(merged.values(), key=lambda e: e["tf"]), reader.source


def analyse(symbol: str, ensembl_id: str, live: Live, mirror=None,
            upstream: int = UPSTREAM, downstream: int = DOWNSTREAM,
            p_value: float = P_VALUE) -> dict[str, Any]:
    """The gene's regulators, their motifs in its promoter and the measured
    binding over the same bases."""
    upstream, downstream = max(0, int(upstream)), max(0, int(downstream))
    if upstream + downstream < 20 or upstream + downstream > MAX_REGION:
        return {"state": "failed", "error": f"Region outside 20 to {MAX_REGION:,} bases."}
    try:
        found = genome_locus.find(symbol, ensembl_id, live, mirror)
        tss, tss_from = _tss(found, live)
        if found.strand == "+":
            start, end = max(0, tss - upstream), tss + downstream
        else:
            start, end = max(0, tss - downstream), tss + upstream
        sequence = _sequence(live, found.chrom, start, end)
        all_matrices = matrices(live)
        regulators, regulators_from = _regulators(symbol, live, mirror)
        peaks_rows = ucsc_rows(live, CHIP_TRACK, found, start, end)
    except (LiveError, genome_locus.LocusError, ScanError) as exc:
        state = "offline" if OFF in str(exc) else "failed"
        return {"state": state, "error": str(exc)}

    names = [r["tf"] for r in regulators]
    assayed_state = "ok"
    try:
        chip = genome_encode.for_regulators(live, names) if names else {"with_chipseq": [], "items": []}
        if chip.get("state") == "failed":
            assayed_state = chip.get("reason", "ENCODE could not be searched")
    except LiveError as exc:
        chip, assayed_state = {"with_chipseq": [], "items": []}, str(exc)
    assayed = {name.upper() for name in chip.get("with_chipseq") or []}
    experiments: dict[str, int] = {}
    for item in chip.get("items") or []:
        experiments[str(item.get("target", "")).upper()] = experiments.get(str(item.get("target", "")).upper(), 0) + 1

    peaks: dict[str, list[dict[str, Any]]] = {}
    for row in peaks_rows:
        name = str(row.get("name") or "").upper()
        if not name:
            continue
        peaks.setdefault(name, []).append({
            "start": int(row.get("chromStart", 0)), "end": int(row.get("chromEnd", 0)),
            "cells": int(row.get("sourceCount") or 0), "score": int(row.get("score") or 0)})

    def offset(position: int) -> int:
        """Bases from the TSS in the gene's direction; negative is upstream."""
        return position - tss if found.strand == "+" else tss - position

    rows = []
    for regulator in regulators:
        matrix, note = pick(all_matrices, regulator["tf"])
        parts = {p.upper() for p in re.split(r"[_:]+", regulator["tf"]) if p}
        own_peaks = sorted((p for name in parts for p in peaks.get(name, [])), key=lambda p: p["start"])
        hits = []
        if matrix is not None:
            for hit in scan(sequence, matrix, p_value):
                g0, g1 = start + hit["start"], start + hit["end"]
                inside = [p for p in own_peaks if p["start"] < g1 and p["end"] > g0]
                hits.append({**hit, "start": g0, "end": g1,
                             "offset": offset((g0 + g1) // 2),
                             "in_peak": bool(inside),
                             "cells": max((p["cells"] for p in inside), default=0)})
        if names and assayed_state == "ok":
            is_assayed: bool | None = bool(parts & assayed)
        else:
            is_assayed = None
        rows.append({
            **regulator,
            # OmniPath names a dimer it records as one regulator "FOS_JUN".
            "members": sorted(parts) if len(parts) > 1 else [],
            "complex": len(parts) > 1,
            "motif": matrix.to_dict() if matrix else None,
            "motif_note": note,
            "hits": hits,
            "supported": sum(1 for h in hits if h["in_peak"]),
            "chip": {"assayed": is_assayed,
                     "experiments": sum(experiments.get(p, 0) for p in parts),
                     "peaks": [{**p, "from": offset(p["start"] if found.strand == "+" else p["end"]),
                                "to": offset(p["end"] if found.strand == "+" else p["start"])}
                               for p in own_peaks]},
        })
    rows.sort(key=lambda r: (-r["supported"], -len(r["hits"]), -len(r["chip"]["peaks"]), r["tf"]))

    summary = {
        "regulators": len(rows),
        "complexes": sum(1 for r in rows if r["complex"]),
        "with_motif": sum(1 for r in rows if r["motif"]),
        "with_sites": sum(1 for r in rows if r["hits"]),
        "sites": sum(len(r["hits"]) for r in rows),
        "assayed": sum(1 for r in rows if r["chip"]["assayed"]),
        "bound_here": sum(1 for r in rows if r["chip"]["peaks"]),
        "supported": sum(1 for r in rows if r["supported"]),
        "supported_sites": sum(r["supported"] for r in rows),
        "bound_without_motif": sum(1 for r in rows if r["chip"]["peaks"] and r["motif"] and not r["hits"]),
    }
    return {
        "state": "ok", "gene": symbol, "chrom": found.chrom, "strand": found.strand,
        "tss": tss, "tss_from": tss_from,
        "region": {"start": start, "end": end, "upstream": upstream, "downstream": downstream},
        "p_value": p_value, "background": "uniform (25% each base)",
        "regulators": rows, "summary": summary,
        "chip_state": assayed_state,
        "sources": {"regulators": f"OmniPath, commercial records ({regulators_from})",
                    "motifs": JASPAR_RELEASE, "binding": CHIP_LABEL,
                    "assayed": "ENCODE TF ChIP-seq experiments, any biosample",
                    "sequence": "GRCh38 from UCSC"},
    }


def features(result: dict[str, Any], chrom: str) -> list[dict[str, Any]]:
    """The scanned sites as genome-view features: deep azure where the
    factor's own peak covers the site, slate where only the motif says so."""
    out = []
    for row in result.get("regulators") or []:
        for hit in row["hits"]:
            out.append({"chr": chrom, "start": hit["start"], "end": hit["end"],
                        "strand": hit["strand"],
                        "name": f"{row['tf']} {hit['site']} (p {hit['p']:g}"
                                f"{', in its ChIP-seq peak' if hit['in_peak'] else ''})",
                        "color": "#0077CC" if hit["in_peak"] else "#5B6B7C"})
    return out
