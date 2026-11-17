"""Cutting extracted text into passages that remember where they came from.

A chunk is what retrieval returns and what an answer cites, so it has two
jobs that pull against each other: long enough to hold a claim with its
qualifiers, short enough that a hit points somewhere a person can check.

Adapted from Betelgeuse's chunker, including the part that matters most:
cuts prefer a paragraph break, then a sentence end, then whitespace, so a
passage rarely begins mid-word.
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

from spica.corpus.extract import unit_name

#: ~1200 characters lands near 300 tokens.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
MIN_CHUNK_CHARS = 120


@dataclasses.dataclass(frozen=True)
class Chunk:
    """One retrievable passage, carrying enough provenance to cite it."""

    text: str
    source: str  # path relative to the input folder
    unit_start: int
    unit_end: int

    @property
    def citation(self) -> str:
        """How the answer refers to this passage.

        The unit depends on the format: "p7" is meaningless for a deck and
        "slide 7" is meaningless for a paper, so it is derived from the
        extension rather than stored.
        """
        suffix = "." + self.source.rsplit(".", 1)[-1].lower()
        unit = unit_name(suffix)
        if unit == "p":
            span = (f"p{self.unit_start}" if self.unit_start == self.unit_end
                    else f"pp{self.unit_start}-{self.unit_end}")
        else:
            span = (f"{unit} {self.unit_start}" if self.unit_start == self.unit_end
                    else f"{unit}s {self.unit_start}-{self.unit_end}")
        return f"{self.source}, {span}"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def chunk_units(
    units: Sequence[str],
    source: str,
    size: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP,
    merge: bool = True,
    min_chars: int = MIN_CHUNK_CHARS,
) -> list[Chunk]:
    """Cut `units` into overlapping passages.

    With `merge` the units are joined before cutting, so a passage may span
    a page break, which is exactly where a paper splits a sentence. Pass
    `merge=False` for formats whose units stand alone, such as slides and
    worksheets: running them together blends unrelated content into one
    embedding and blurs both.
    """
    if not units:
        return []

    if not merge:
        chunks: list[Chunk] = []
        for number, unit in enumerate(units, start=1):
            if not unit.strip():
                continue
            # A slide carrying only a title is short but still worth
            # finding, so the length floor relaxes for standalone units.
            for chunk in chunk_units([unit], source, size, overlap,
                                     merge=True, min_chars=min(min_chars, 30)):
                chunks.append(dataclasses.replace(
                    chunk, unit_start=number, unit_end=number))
        return chunks

    parts: list[str] = []
    bounds: list[tuple[int, int]] = []  # offset -> unit number
    cursor = 0
    for number, unit in enumerate(units, start=1):
        if not unit:
            continue
        parts.append(unit)
        bounds.append((cursor, number))
        cursor += len(unit) + 2
    full = "\n\n".join(parts)
    if not full.strip():
        return []

    def unit_at(offset: int) -> int:
        number = bounds[0][1]
        for start, candidate in bounds:
            if start <= offset:
                number = candidate
            else:
                break
        return number

    chunks = []
    start = 0
    step = max(size - overlap, 1)
    while start < len(full):
        end = min(start + size, len(full))
        if end < len(full):
            window = full[start:end]
            for pattern in ("\n\n", ". ", " "):
                cut = window.rfind(pattern)
                # Only honour a break in the last third, else chunks get tiny.
                if cut > size * 0.6:
                    end = start + cut + len(pattern)
                    break
        body = full[start:end].strip()
        if len(body) >= min_chars:
            chunks.append(Chunk(text=body, source=source,
                                unit_start=unit_at(start),
                                unit_end=unit_at(end - 1)))
        if end >= len(full):
            break
        start = max(start + step, end - overlap)

    # A document shorter than the floor would otherwise vanish from the
    # index without a word. Dropping a fragment is housekeeping; dropping a
    # whole file is data loss.
    if not chunks and full.strip():
        chunks.append(Chunk(text=full.strip(), source=source,
                            unit_start=unit_at(0),
                            unit_end=unit_at(len(full) - 1)))
    return chunks
