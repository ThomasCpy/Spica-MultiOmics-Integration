"""A region from a remote bigBed or bigWig file, by byte range.

ENCODE publishes peaks, signal, methylation and chromatin states as bigBed
and bigWig files of hundreds of megabytes each. A full download for a 100 kb
locus makes no sense, and the format does not need it: a header, a
chromosome B+ tree, and an R-tree over compressed data blocks. A region
read takes a few HTTP range requests.

This follows the UCSC format documentation (Kent et al., Bioinformatics
2010, and `bbiFile.h`). It uses only `struct` and `zlib`, so the genome view
needs no compiled dependancy. It holds only what Spica uses: full-resolution
data for bigBed, and full or zoomed data for bigWig.

The caller controls network access. `Ranged` takes an opener, and
`spica.genome.tracks` gives it one that respects `SPICA_OFFLINE`.
"""

from __future__ import annotations

import struct
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Callable

BIGWIG_MAGIC = 0x888FFC26
BIGBED_MAGIC = 0x8789F2EB
CHROM_TREE_MAGIC = 0x78CA8C91
RTREE_MAGIC = 0x2468ACE0

#: The first read. Header, zoom headers and usually the chromosome tree fit
#: in it, which saves two round trips on every file.
HEAD = 65536


class BigFileError(Exception):
    pass


def http_range(url: str, offset: int, size: int, timeout: int = 60) -> bytes:
    """One byte range of a remote file. Redirects are followed by urllib."""
    request = urllib.request.Request(
        url, headers={"Range": f"bytes={offset}-{offset + size - 1}",
                      "User-Agent": "Spica/0.1 (target triage)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            if response.status == 200 and len(data) > size:
                # A server that ignores Range sends the whole file; keep the
                # part that was asked for rather than fail.
                data = data[offset:offset + size]
            return data
    except urllib.error.HTTPError as exc:
        raise BigFileError(f"HTTP {exc.code} reading {url}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise BigFileError(f"could not reach {url}: {getattr(exc, 'reason', exc)}") from None


def resolve(url: str, timeout: int = 60) -> str:
    """Where a URL finally lands. ENCODE answers every download with a
    redirect to its storage bucket; following it once, rather than on every
    range request, takes a region read from minutes to seconds."""
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0",
                                                   "User-Agent": "Spica/0.1 (target triage)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.geturl() or url
    except (urllib.error.URLError, OSError):
        return url


#: Ranges closer than this are fetched as one: a few kilobytes of slack
#: cost far less than another round trip.
COALESCE = 65536


class Ranged:
    """A remote file read in spans, each span fetched once per instance."""

    def __init__(self, url: str, fetch: Callable[[str, int, int], bytes] = http_range,
                 follow: bool = True):
        self.url = resolve(url) if follow and fetch is http_range else url
        self._fetch = fetch
        self._spans: list[tuple[int, bytes]] = []

    def _cached(self, offset: int, size: int) -> bytes | None:
        for start, data in self._spans:
            if start <= offset and offset + size <= start + len(data):
                return data[offset - start:offset - start + size]
        return None

    def read(self, offset: int, size: int) -> bytes:
        hit = self._cached(offset, size)
        if hit is not None:
            return hit
        data = self._fetch(self.url, offset, size)
        self._spans.append((offset, data))
        return data[:size]

    def prefetch(self, ranges: list[tuple[int, int]]) -> None:
        """Fetch many ranges in as few requests as their spacing allows."""
        pending = sorted((o, s) for o, s in ranges if self._cached(o, s) is None)
        merged: list[list[int]] = []
        for offset, size in pending:
            if merged and offset - (merged[-1][0] + merged[-1][1]) <= COALESCE:
                merged[-1][1] = max(merged[-1][1], offset + size - merged[-1][0])
            else:
                merged.append([offset, size])
        for offset, size in merged:
            self.read(offset, size)


@dataclass
class Zoom:
    reduction: int
    data_offset: int
    index_offset: int


class BigFile:
    """One bigBed or bigWig file, open for region queries."""

    def __init__(self, source: Ranged):
        self.source = source
        head = source.read(0, HEAD)
        if len(head) < 64:
            raise BigFileError("file too short to be a bigBed or bigWig")
        magic = struct.unpack("<I", head[:4])[0]
        if magic in (BIGWIG_MAGIC, BIGBED_MAGIC):
            self.e = "<"
        elif struct.unpack(">I", head[:4])[0] in (BIGWIG_MAGIC, BIGBED_MAGIC):
            self.e = ">"
            magic = struct.unpack(">I", head[:4])[0]
        else:
            raise BigFileError("not a bigBed or bigWig file")
        self.kind = "bigwig" if magic == BIGWIG_MAGIC else "bigbed"
        (_, self.version, zoom_levels, self.chrom_tree, self.data_offset,
         self.index_offset, self.field_count, self.defined_fields,
         self.autosql_offset, self.summary_offset,
         self.uncompress) = struct.unpack(self.e + "IHHQQQHHQQI", head[:56])
        self.zooms = []
        for level in range(zoom_levels):
            at = 64 + level * 24
            reduction, _, data, index = struct.unpack(self.e + "IIQQ", head[at:at + 24])
            self.zooms.append(Zoom(reduction, data, index))
        self.chroms = self._chromosomes()

    # -- structure ------------------------------------------------------------

    def _chromosomes(self) -> dict[str, tuple[int, int]]:
        header = self.source.read(self.chrom_tree, 32)
        magic, block, key_size, _, _ = struct.unpack(self.e + "IIIIQ", header[:24])
        if magic != CHROM_TREE_MAGIC:
            raise BigFileError("chromosome index is damaged")
        out: dict[str, tuple[int, int]] = {}

        def walk(offset: int) -> None:
            # One request for the whole node: header and every item.
            self.source.read(offset, 4 + block * (key_size + 8))
            node = self.source.read(offset, 4)
            leaf, _, count = struct.unpack(self.e + "BBH", node)
            width = key_size + 8
            body = self.source.read(offset + 4, count * width)
            for i in range(count):
                item = body[i * width:(i + 1) * width]
                key = item[:key_size].rstrip(b"\x00").decode("ascii", "replace")
                if leaf:
                    chrom_id, size = struct.unpack(self.e + "II", item[key_size:])
                    out[key] = (chrom_id, size)
                else:
                    (child,) = struct.unpack(self.e + "Q", item[key_size:])
                    walk(child)

        walk(self.chrom_tree + 32)
        return out

    def chrom_id(self, chrom: str) -> int | None:
        """`chr3` and `3` are the same chromosome to a reader."""
        for name in (chrom, chrom[3:] if chrom.startswith("chr") else f"chr{chrom}"):
            if name in self.chroms:
                return self.chroms[name][0]
        return None

    def _blocks(self, index_offset: int, cid: int, start: int, end: int) -> list[tuple[int, int]]:
        header = self.source.read(index_offset, 48)
        magic, block = struct.unpack(self.e + "II", header[:8])
        if magic != RTREE_MAGIC:
            raise BigFileError("data index is damaged")
        found: list[tuple[int, int]] = []

        def overlaps(sc: int, sb: int, ec: int, eb: int) -> bool:
            return (sc, sb) < (cid, end) and (ec, eb) > (cid, start)

        def walk(offset: int) -> None:
            self.source.read(offset, 4 + block * 32)  # the whole node in one request
            node = self.source.read(offset, 4)
            leaf, _, count = struct.unpack(self.e + "BBH", node)
            width = 32 if leaf else 24
            body = self.source.read(offset + 4, count * width)
            for i in range(count):
                item = body[i * width:(i + 1) * width]
                sc, sb, ec, eb = struct.unpack(self.e + "IIII", item[:16])
                if not overlaps(sc, sb, ec, eb):
                    continue
                if leaf:
                    found.append(struct.unpack(self.e + "QQ", item[16:32]))
                else:
                    walk(struct.unpack(self.e + "Q", item[16:24])[0])

        walk(index_offset + 48)
        return found

    def _data(self, offset: int, size: int) -> bytes:
        raw = self.source.read(offset, size)
        return zlib.decompress(raw) if self.uncompress else raw

    # -- queries --------------------------------------------------------------

    def bed(self, chrom: str, start: int, end: int) -> list[tuple[int, int, list[str]]]:
        """Records overlapping [start, end): (start, end, the remaining fields)."""
        if self.kind != "bigbed":
            raise BigFileError("not a bigBed file")
        cid = self.chrom_id(chrom)
        if cid is None:
            return []
        out = []
        blocks = self._blocks(self.index_offset, cid, start, end)
        self.source.prefetch(blocks)
        for offset, size in blocks:
            block = self._data(offset, size)
            at = 0
            while at + 12 <= len(block):
                rec_chrom, rec_start, rec_end = struct.unpack(self.e + "III", block[at:at + 12])
                stop = block.index(b"\x00", at + 12)
                rest = block[at + 12:stop].decode("utf-8", "replace")
                at = stop + 1
                if rec_chrom == cid and rec_end > start and rec_start < end:
                    out.append((rec_start, rec_end, rest.split("\t") if rest else []))
        out.sort(key=lambda r: (r[0], r[1]))
        return out

    def wig(self, chrom: str, start: int, end: int, bins: int = 2000) -> list[tuple[int, int, float]]:
        """Mean signal in up to `bins` equal bins over [start, end).

        Uses the coarsest zoom level that is still finer than one bin, so a
        100 kb view reads a few kilobytes rather than every base. Bins with
        no data are left out, never reported as zero.
        """
        if self.kind != "bigwig":
            raise BigFileError("not a bigWig file")
        cid = self.chrom_id(chrom)
        if cid is None or end <= start:
            return []
        bins = max(1, min(bins, end - start))
        width = (end - start) / bins
        zoom = None
        for level in sorted(self.zooms, key=lambda z: z.reduction):
            if level.reduction <= width / 2:
                zoom = level
        total = [0.0] * bins
        covered = [0.0] * bins

        def add(s: int, e: int, value: float) -> None:
            s, e = max(s, start), min(e, end)
            if e <= s:
                return
            first = int((s - start) / width)
            last = min(bins - 1, int((e - 1 - start) / width))
            for b in range(first, last + 1):
                lo = start + b * width
                hi = lo + width
                overlap = min(e, hi) - max(s, lo)
                if overlap > 0:
                    total[b] += value * overlap
                    covered[b] += overlap

        if zoom is not None:
            blocks = self._blocks(zoom.index_offset, cid, start, end)
            self.source.prefetch(blocks)
            for offset, size in blocks:
                block = self._data(offset, size)
                for at in range(0, len(block) - 31, 32):
                    c, s, e, valid, _, _, sum_data, _ = struct.unpack(
                        self.e + "IIIIffff", block[at:at + 32])
                    if c == cid and valid:
                        add(s, e, sum_data / valid)
        else:
            blocks = self._blocks(self.index_offset, cid, start, end)
            self.source.prefetch(blocks)
            for offset, size in blocks:
                block = self._data(offset, size)
                c, s, _, step, span, kind, _, count = struct.unpack(
                    self.e + "IIIIIBBH", block[:24])
                if c != cid:
                    continue
                at = 24
                for i in range(count):
                    if kind == 1:  # bedGraph
                        rs, re_, value = struct.unpack(self.e + "IIf", block[at:at + 12])
                        at += 12
                    elif kind == 2:  # variableStep
                        rs, value = struct.unpack(self.e + "If", block[at:at + 8])
                        re_ = rs + span
                        at += 8
                    else:  # fixedStep
                        (value,) = struct.unpack(self.e + "f", block[at:at + 4])
                        rs = s + i * step
                        re_ = rs + span
                        at += 4
                    add(rs, re_, value)
        out = []
        for b in range(bins):
            if covered[b] > 0:
                lo = int(start + b * width)
                hi = int(start + (b + 1) * width)
                out.append((lo, max(hi, lo + 1), total[b] / covered[b]))
        return out
