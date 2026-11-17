"""The position of a gene, the window around it, and the window sequence.

The window is the gene plus a 50 kb flank on each side, as in the
integrator. The flanks hold enhancers and promoters outside the gene body.
Each track covers the full window, so panning inside it costs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from spica.live import Live, LiveError, NotFoundUpstream

ENSEMBL = "https://rest.ensembl.org"
UCSC = "https://api.genome.ucsc.edu"
ASSEMBLY = "GRCh38"
#: Flank fetched on each side of the gene, in bases.
FLANK = 50_000
#: Flank shown when the view opens.
VIEW_FLANK = 10_000
#: Ensembl serves at most 10 Mb of sequence per request.
MAX_SEQUENCE = 10_000_000
#: GRCh38 chromosome lengths (UCSC hg38), so a locus read from the mirror
#: needs no request to bound its window.
LENGTHS = {
    "1": 248956422, "2": 242193529, "3": 198295559, "4": 190214555, "5": 181538259,
    "6": 170805979, "7": 159345973, "8": 145138636, "9": 138394717, "10": 133797422,
    "11": 135086622, "12": 133275309, "13": 114364328, "14": 107043718, "15": 101991189,
    "16": 90338345, "17": 83257441, "18": 80373285, "19": 58617616, "20": 64444167,
    "21": 46709983, "22": 50818468, "X": 156040895, "Y": 57227415, "MT": 16569,
}


class LocusError(Exception):
    pass


@dataclass(frozen=True)
class Locus:
    symbol: str
    ensembl_id: str
    chrom: str  # "chr3", UCSC style, which every track source but Ensembl uses
    start: int  # gene, 0-based half-open
    end: int
    strand: str
    length: int  # of the chromosome
    window_start: int
    window_end: int

    @property
    def ensembl_chrom(self) -> str:
        return self.chrom[3:] if self.chrom.startswith("chr") else self.chrom

    @property
    def view(self) -> str:
        """The locus string igv.js opens on, 1-based inclusive."""
        lo = max(1, self.start + 1 - VIEW_FLANK)
        hi = min(self.length, self.end + VIEW_FLANK)
        return f"{self.chrom}:{lo}-{hi}"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "ensembl_id": self.ensembl_id,
            "chrom": self.chrom, "start": self.start, "end": self.end,
            "strand": self.strand, "assembly": ASSEMBLY,
            "window": {"start": self.window_start, "end": self.window_end},
            "view": self.view,
        }


def _mirrored(ensembl_id: str, mirror) -> dict | None:
    """The gene's position from the local Ensembl data, in the REST shape."""
    from spica.sources.ensembl import ID_COLUMN, REQUIRED
    from spica.sources.index import rows_for

    entry = mirror.entry("ensembl") if mirror is not None and ensembl_id else None
    if entry is None or not str(entry.extra.get("assembly") or ASSEMBLY).startswith(ASSEMBLY):
        return None
    try:
        for row in rows_for(entry.path("genes"), ID_COLUMN, ensembl_id, REQUIRED):
            region = row.get("Chromosome/scaffold name", "").strip()
            start, end = row.get("Gene start (bp)", "").strip(), row.get("Gene end (bp)", "").strip()
            if region in LENGTHS and start.isdigit() and end.isdigit():
                return {"seq_region_name": region, "start": int(start), "end": int(end),
                        "strand": -1 if row.get("Strand", "").strip() == "-1" else 1}
    except Exception:  # an unreadable mirror file leaves the API to answer
        return None
    return None


def find(symbol: str, ensembl_id: str, live: Live, mirror=None) -> Locus:
    """The gene's coordinates, and the window around them.

    From the local Ensembl data when it holds the gene, so the genome view
    does not wait on Ensembl's REST API; from the API otherwise.
    """
    gene = _mirrored(ensembl_id, mirror)
    if gene is None:
        try:
            gene = live.get_json(
                "ensembl", f"{ENSEMBL}/lookup/id/{ensembl_id}?content-type=application/json").payload
        except NotFoundUpstream:
            raise LocusError(f"Ensembl has no gene {ensembl_id}") from None
        except LiveError as exc:
            raise LocusError(f"Ensembl not reached: {exc}") from None
    region = str(gene.get("seq_region_name") or "")
    if not region or gene.get("start") is None:
        raise LocusError(f"Ensembl gives no position for {ensembl_id}")
    length = LENGTHS.get(region, 0)
    if not length:
        try:
            info = live.get_json(
                "ensembl",
                f"{ENSEMBL}/info/assembly/homo_sapiens/{region}?content-type=application/json").payload
            length = int(info.get("length") or 0)
        except (LiveError, NotFoundUpstream, ValueError):
            length = 0
    start = int(gene["start"]) - 1  # Ensembl is 1-based inclusive
    end = int(gene["end"])
    length = length or end + FLANK
    window_start = max(0, start - FLANK)
    window_end = min(length, end + FLANK)
    if window_end - window_start > MAX_SEQUENCE:
        # A gene longer than ten megabases (a handful exist) keeps its whole
        # body and loses flank, never the other way round.
        window_start, window_end = start, min(end, start + MAX_SEQUENCE)
    return Locus(
        symbol=symbol, ensembl_id=ensembl_id, chrom=f"chr{region}",
        start=start, end=end, strand="-" if gene.get("strand") == -1 else "+",
        length=length, window_start=window_start, window_end=window_end,
    )


def reference(locus: Locus, live: Live) -> dict:
    """The window's sequence as a FASTA igv.js reads with real coordinates.

    igv.js offsets a sequence named `chr3:FROM-TO` when the header also
    carries the chromosome length as `@len=`; without it the slice would be
    placed at position 1 and every track would be drawn in the wrong place.
    """
    # UCSC first: it answers a 125 kb window in about a second where
    # Ensembl's sequence endpoint has timed out at thirty. Both serve the
    # same GRCh38 bases (checked), so either is the reference.
    routes = [
        ("ucsc", f"{UCSC}/getData/sequence?genome=hg38;chrom={locus.chrom};"
                 f"start={locus.window_start};end={locus.window_end}", "dna", "UCSC"),
        ("ensembl", f"{ENSEMBL}/sequence/region/human/{locus.ensembl_chrom}:"
                    f"{locus.window_start + 1}..{locus.window_end}:1"
                    f"?coord_system_version={ASSEMBLY};content-type=application/json", "seq", "Ensembl"),
    ]
    sequence, source, problems = "", "", []
    for key, url, field_name, label in routes:
        try:
            sequence = str((live.get_json(key, url).payload or {}).get(field_name) or "")
        except (LiveError, NotFoundUpstream) as exc:
            problems.append(f"{label}: {exc}")
            continue
        if sequence:
            source = label
            break
    if not sequence:
        raise LocusError("the reference sequence could not be read: " + "; ".join(problems))
    header = (f">{locus.chrom}:{locus.window_start + 1}-{locus.window_end}"
              f" @len={locus.length}")
    lines = [sequence[i:i + 100] for i in range(0, len(sequence), 100)]
    return {
        "id": f"{ASSEMBLY}-{locus.symbol}",
        "name": f"{ASSEMBLY}, {locus.symbol} window",
        "fasta": header + "\n" + "\n".join(lines) + "\n",
        "chrom": locus.chrom,
        "length": locus.length,
        "source": source,
    }
