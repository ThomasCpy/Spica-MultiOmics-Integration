"""The file of a GEO sample, read over a gene window for the genome view.

bigWig and bigBed files use byte ranges (`spica/genome/bigfile.py`): a few
requests, whatever the file size. Their chromosome lengths identify the
genome build with certainty (chr1 is 248,956,422 bases in GRCh38 and
249,250,621 in GRCh37). Peak and signal text files (BED, narrowPeak,
bedGraph, WIG, gzipped or not) have no index. Spica streams them once, up
to a size limit, and keeps only the lines in the window.

The genome view uses GRCh38. For a GRCh37 file, Spica reads the GRCh37
segment that Ensembl maps the window to. Each record then goes back onto
GRCh38 through the same mapping, and the track says so. An NCBI36 (hg18)
or mouse file is not drawn: no mapping onto the human GRCh38 window would
be honest.
"""

from __future__ import annotations

import gzip
import io
import urllib.request
from typing import Any, Callable, Iterator

from spica.genome import tracks as genome_tracks
from spica.genome.bigfile import BigFile, BigFileError, Ranged
from spica.genome.locus import ENSEMBL, Locus
from spica.geo import records
from spica.live import Live, LiveError, NotFoundUpstream, OFF

#: Text files are streamed whole; past this many bytes (compressed) Spica
#: stops and says so rather than spend minutes on one track.
MAX_TEXT_BYTES = 400 * 1024 * 1024
CHR1 = {248956422: "GRCh38", 249250621: "GRCh37", 247249719: "NCBI36"}


class GeoTrackError(Exception):
    pass


def assembly_of(big: BigFile) -> str:
    for name in ("chr1", "1"):
        if name in big.chroms:
            return CHR1.get(big.chroms[name][1], "")
    return ""


def blocks(locus: Locus, assembly: str, live: Live) -> list[tuple[str, int, int, int]]:
    """(chromosome, start, end, shift) in the file's build covering the window,
    where position + shift is the GRCh38 position. 0-based, half-open."""
    if assembly in ("GRCh38", ""):
        return [(locus.chrom, locus.window_start, locus.window_end, 0)]
    if assembly != "GRCh37":
        raise GeoTrackError(f"the file is on {assembly}, which Spica does not map onto GRCh38")
    region = f"{locus.ensembl_chrom}:{locus.window_start + 1}..{locus.window_end}:1"
    try:
        payload = live.get_json("ensembl", f"{ENSEMBL}/map/human/GRCh38/{region}/GRCh37"
                                           "?content-type=application/json").payload or {}
    except NotFoundUpstream:
        payload = {}
    out = []
    for pair in payload.get("mappings") or []:
        original, mapped = pair.get("original") or {}, pair.get("mapped") or {}
        if mapped.get("strand", 1) != original.get("strand", 1) or not mapped.get("start"):
            continue  # an inverted stretch would need every record flipped; it is left out
        out.append((f"chr{mapped['seq_region_name']}", int(mapped["start"]) - 1, int(mapped["end"]),
                    int(original["start"]) - int(mapped["start"])))
    if not out:
        raise GeoTrackError("Ensembl could not map this window onto GRCh37")
    return out


def _same(a: str, b: str) -> bool:
    return a.removeprefix("chr") == b.removeprefix("chr")


def stream_lines(url: str, limit: int = MAX_TEXT_BYTES) -> Iterator[str]:
    """A remote text file's lines, gunzipped when it is gzipped, streamed."""
    request = urllib.request.Request(url, headers={"User-Agent": "Spica"})
    with urllib.request.urlopen(request, timeout=120) as response:
        size = int(response.headers.get("Content-Length") or 0)
        if size > limit:
            raise GeoTrackError(f"the file is {size / 1e6:,.0f} MB; Spica streams text files of up to "
                                f"{limit / 1e6:,.0f} MB. Open it at GEO, or choose its bigWig or bigBed")
        raw: Any = response
        if url.lower().endswith(".gz"):
            raw = gzip.GzipFile(fileobj=response)
        for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
            yield line.rstrip("\n")


def parse_text(lines: Iterator[str], kind: str, wanted: list[tuple[str, int, int, int]]
               ) -> tuple[str, list[tuple[int, int, Any]]]:
    """Records inside the wanted stretches, already on GRCh38.

    Returns ("wig", [(start, end, value)]) for signal, ("bed", [(start, end,
    rest)]) for intervals."""
    signal = kind in ("bedgraph", "wig")
    out: list[tuple[int, int, Any]] = []

    def keep(chrom: str, start: int, end: int, payload: Any) -> None:
        for name, lo, hi, shift in wanted:
            if _same(chrom, name) and start < hi and end > lo:
                out.append((max(start, lo) + shift, min(end, hi) + shift, payload))

    step_chrom, step_start, step, span, mode = "", 0, 1, 1, ""
    for line in lines:
        if not line or line.startswith(("#", "track", "browser")):
            continue
        if line.startswith(("variableStep", "fixedStep")):
            fields = dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)
            mode = "variable" if line.startswith("variable") else "fixed"
            step_chrom = fields.get("chrom", "")
            span = int(fields.get("span", 1))
            step = int(fields.get("step", 1))
            step_start = int(fields.get("start", 1)) - 1  # WIG is 1-based
            continue
        parts = line.split()
        try:
            if mode == "variable" and len(parts) == 2:
                start = int(parts[0]) - 1
                keep(step_chrom, start, start + span, float(parts[1]))
            elif mode == "fixed" and len(parts) == 1:
                keep(step_chrom, step_start, step_start + span, float(parts[0]))
                step_start += step
            elif len(parts) >= 3:
                mode = ""
                start, end = int(parts[1]), int(parts[2])
                keep(parts[0], start, end, float(parts[3]) if signal and len(parts) > 3 else parts[3:])
        except ValueError:
            continue
    return ("wig" if signal else "bed"), out


def read(url: str, locus: Locus, live: Live, hint: str = "",
         lines: Callable[[str], Iterator[str]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One GEO file's records over the gene's window, as genome-view features."""
    name = url.rsplit("/", 1)[-1]
    kind = records.kind(name)
    if kind not in records.TRACK_KINDS:
        raise GeoTrackError(f"{name} is not a track file (bigWig, bigBed, BED, peaks, bedGraph or WIG)")
    key = f"geo:{url}#{locus.chrom}:{locus.window_start}-{locus.window_end};bins={genome_tracks.WIG_BINS}"

    def produce() -> dict[str, Any]:
        if not live.allowed:
            raise LiveError(OFF)
        try:
            if kind in ("bigwig", "bigbed"):
                big = BigFile(Ranged(url))
                assembly = assembly_of(big) or hint or records.build(name)
                wanted = blocks(locus, assembly, live)
                rows: list[list[Any]] = []
                for chrom, lo, hi, shift in wanted:
                    if big.kind == "bigwig":
                        rows += [[s + shift, e + shift, v] for s, e, v in big.wig(chrom, lo, hi, genome_tracks.WIG_BINS)]
                    else:
                        rows += [[s + shift, e + shift, rest] for s, e, rest in big.bed(chrom, lo, hi)]
                return {"kind": "wig" if big.kind == "bigwig" else "bed", "rows": rows,
                        "assembly": assembly or "not stated"}
            assembly = hint or records.build(name)
            wanted = blocks(locus, assembly, live)
            shape, found = parse_text((lines or stream_lines)(url), kind, wanted)
            if shape == "wig":
                found = genome_tracks.binned([(s, e, float(v)) for s, e, v in found],
                                             locus.window_start, locus.window_end)
            return {"kind": shape, "rows": [[s, e, p] for s, e, p in found],
                    "assembly": assembly or "not stated, read as GRCh38"}
        except (BigFileError, GeoTrackError) as exc:
            raise LiveError(str(exc)) from None
        except OSError as exc:
            raise LiveError(f"{name} not read: {exc}") from None

    data = live.remember("geo", key, produce).payload or {}
    meta = {"assembly": data.get("assembly", ""), "name": name,
            "mapped": data.get("assembly") == "GRCh37"}
    if data.get("kind") == "wig":
        features = [{"chr": locus.chrom, "start": int(s), "end": int(e), "value": round(float(v), 4)}
                    for s, e, v in data.get("rows", [])]
        return features, {**meta, "kind": "wig"}
    records_ = [(int(s), int(e), list(rest) if isinstance(rest, list) else []) for s, e, rest in data.get("rows", [])]
    return genome_tracks.bed_features(records_, locus.chrom, "ChIP-seq" if kind == "peaks" else "GEO"), \
        {**meta, "kind": "annotation"}
