"""The source interface, and the small amount of shared file reading.

A source adapter does one job: for a resolved identity, it returns the
fields that it owns. The mirror entry decides provenance; the schema
decides which fields exist.

There are two ways in. `collect` reads the mirrored release, and `fetch`
asks the public API of the source. `collect` is the main one. `fetch` lets
the app work before the mirror exists. It runs only for unmirrored sources,
and it is optional: a source without it reports why its fields are empty.

Three ways to return nothing, as in the null states of the record:

    return {} or omit a field      the source was read and had nothing there
    return Absent(state, reason)   for one field, with the state given
    raise GeneNotInSource(reason)  the gene is absent from this source entirely
    raise SourceError(reason)      the read itself failed

The builder catches any other exception from an adapter and records it as
`failed` with the exception text. A broken adapter thus affects one source,
not the full record.
"""

from __future__ import annotations

import csv
import gzip
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from spica.live import Fetched, Live, NoLiveRoute
from spica.mirror import Mirror, MirrorEntry
from spica.record import NullState, Resolution


class SourceError(Exception):
    """The source could not be read: missing column, unreadable file, bad format."""


class GeneNotInSource(Exception):
    """The source was read and has no entry for this gene."""


@dataclass(frozen=True)
class Absent:
    """A per-field null returned by an adapter that knows why."""

    state: NullState
    reason: str


class Source(ABC):
    """One mirrored database."""

    key: str = ""
    label: str = ""
    needs: tuple[str, ...] = ()  # manifest file keys this adapter reads

    def availability(self, mirror: Mirror) -> tuple[bool, str]:
        """`(ok, reason)`. Cheap: it never opens a data file.

        Borrowed from the MultiOmics integrator's dataset explorers, where the
        same contract keeps a missing download from looking like missing data.
        """
        entry = mirror.entry(self.key)
        if entry is None:
            if not mirror.present:
                return False, mirror.problem
            return False, f"{self.label} is not in the mirror manifest"
        missing = [name for name in self.needs if name not in entry.files]
        if missing:
            return False, (
                f"{self.label} {entry.version} declares no "
                f"{', '.join(missing)} file in the manifest"
            )
        absent = entry.missing_files()
        if absent:
            return False, (
                f"{self.label} {entry.version} is listed but "
                f"{', '.join(absent)} is not in {entry.root}"
            )
        return True, ""

    @abstractmethod
    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        """The fields this source owns, read from the mirror."""

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        """The same fields, from the source's public API.

        Only called when the source is not mirrored and the network is
        allowed. Raises the same `GeneNotInSource` and `SourceError` as
        `collect`, plus `NoLiveRoute` where a source has no API to fall
        back to.
        """
        raise NoLiveRoute(f"{self.label} has no API fallback")

    def locator(self, field_name: str, entry: MirrorEntry) -> str:
        """Which mirrored file a field was read from, for its provenance.

        One file for most sources; those that read several override this so
        a value points at the file it is in.
        """
        return next(iter(entry.files.values()), "")


# -- shared file reading ----------------------------------------------------


def open_text(path: Path) -> io.TextIOBase:
    """Open a mirrored file, gzipped or not.

    Release files arrive both ways and are often left as downloaded, so the
    suffix decides rather than the manifest.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "rt", encoding="utf-8", newline="")


def read_tsv(path: Path, required: tuple[str, ...] = ()) -> Iterator[dict[str, str]]:
    """Rows of a tab-separated file, keyed by column name.

    Column *names* are the contract, not column order: release files gain and
    reorder columns between versions, and a mirror a year apart should still
    read. A required column that is missing is a format error, not a null,
    so it raises rather than quietly yielding blanks.

    Quoting is off. Protein and disease names carry stray quote characters
    that the csv module would otherwise swallow. A cell quoted at both ends
    is unwrapped, though: HGNC's newer files wrap their multi-value cells
    ("p53|LFS1"), and read raw the first and last values keep a quote mark.
    """
    with open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            header = next(reader)
        except StopIteration:
            raise SourceError(f"{path.name} is empty") from None
        header = [column.strip().lstrip("﻿") for column in header]
        gaps = [column for column in required if column not in header]
        if gaps:
            raise SourceError(
                f"{path.name} has no {', '.join(gaps)} column "
                f"(found: {', '.join(header[:8])}...)"
            )
        width = len(header)
        for row in reader:
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            if len(row) < width:  # short rows: pad, a trailing empty column is common
                row = row + [""] * (width - len(row))
            yield dict(zip(header, (unwrap(cell) for cell in row)))


def unwrap(cell: str) -> str:
    """The value inside a cell quoted at both ends, as CSV would read it.

    Only a cell quoted at both ends: names carry stray quote characters of
    their own ('"Hairy" protein') that must survive.
    """
    if len(cell) >= 2 and cell[0] == '"' and cell[-1] == '"':
        return cell[1:-1].replace('""', '"')
    return cell


def split_list(cell: str, separator: str = "|") -> list[str]:
    """A multi-value cell as a list, blanks dropped, order kept.

    Order is the file's own. It is kept rather than sorted so that the record
    reproduces what the release says, and stays stable across rebuilds.
    """
    return [part.strip() for part in cell.split(separator) if part.strip()]
