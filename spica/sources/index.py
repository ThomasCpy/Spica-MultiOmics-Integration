"""The rows of one gene from a large mirrored file, without a full scan.

The HPA single-cell-by-tissue table is 1.5 GB, its staining table 95 MB,
the reduced ClinVar summary over 100 MB. A line-by-line scan for each
record would make a mirror report slower than an API report.

Each large file thus gets a byte index, built once. For each key (a gene
ID, a symbol, an accession) it records where the rows start and end. The
release files are grouped by gene, so a key is one or two byte ranges. The
full index of a 1.5 GB file is a few hundred kilobytes. It stays on disk
beside the cache and rebuilds only when the file changes (size or time).

Plain files only: a gzipped file does not allow seeks, so Spica scans it.
Spica also scans files under `SMALL` bytes. The test fixtures (a few
kilobytes) thus leave no index files. A file of one megabyte is already
worth an index when a gene list reads it a hundred times.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Callable, Iterator

from spica.paths import data_dir
from spica.sources.base import SourceError, read_tsv, unwrap

#: Below this size a file is scanned without an index.
SMALL = 1024 * 1024

_memory: dict[str, dict[str, list[list[int]]]] = {}
_lock = threading.Lock()


def _store(path: Path, column: str) -> Path:
    stat = path.stat()
    stamp = f"{path.resolve()}|{column}|{stat.st_size}|{int(stat.st_mtime)}"
    name = hashlib.sha1(stamp.encode()).hexdigest()[:16]
    return data_dir() / "cache" / "index" / f"{path.stem}-{name}.json"


def _key_reader(header: list[str], column: str) -> Callable[[bytes], str | None]:
    if column.startswith("json:"):
        # JSON Lines: the key is a top-level string field; a regex is enough
        # and far faster than parsing every line.
        pattern = re.compile(rb'"' + column[5:].encode() + rb'"\s*:\s*"([^"]+)"')

        def key(line: bytes) -> str | None:
            found = pattern.search(line, 0, 400)
            return found.group(1).decode() if found else None
        return key
    if column not in header:
        raise SourceError(f"no {column} column to index on")
    at = header.index(column)

    def key(line: bytes) -> str | None:
        parts = line.split(b"\t", at + 1)
        return parts[at].decode("utf-8", "replace").strip() if len(parts) > at else None
    return key


def build(path: Path, column: str) -> dict[str, list[list[int]]]:
    """One pass over the file: key -> [[start, end], ...] byte ranges."""
    ranges: dict[str, list[list[int]]] = {}
    with open(path, "rb") as handle:
        first = handle.readline()
        header = first.decode("utf-8", "replace").rstrip("\r\n").lstrip("﻿").split("\t")
        key_of = _key_reader(header if not column.startswith("json:") else [], column)
        if column.startswith("json:"):
            handle.seek(0)
        offset = handle.tell()
        current, start = None, offset
        for line in handle:
            key = key_of(line)
            if key != current:
                if current is not None:
                    ranges.setdefault(current, []).append([start, offset])
                current, start = key, offset
            offset += len(line)
        if current is not None:
            ranges.setdefault(current, []).append([start, offset])
    ranges.pop(None, None)  # type: ignore[arg-type]
    return ranges


def index(path: Path, column: str) -> dict[str, list[list[int]]]:
    """The index for (file, column): from memory, from disk, or built now."""
    store = _store(path, column)
    with _lock:
        if str(store) in _memory:
            return _memory[str(store)]
        try:
            ranges = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ranges = build(path, column)
            try:
                store.parent.mkdir(parents=True, exist_ok=True)
                temporary = store.with_suffix(".tmp")
                temporary.write_text(json.dumps(ranges), encoding="utf-8")
                os.replace(temporary, store)
            except OSError:
                pass  # an index that cannot be saved is rebuilt next time
        _memory[str(store)] = ranges
        return ranges


def indexable(path: Path) -> bool:
    return path.suffix != ".gz" and path.exists() and path.stat().st_size >= SMALL


def rows_for(path: Path, column: str, key: str,
             required: tuple[str, ...] = ()) -> Iterator[dict[str, str]]:
    """The rows of a tab-separated file whose `column` is `key`."""
    if not indexable(path):
        for row in read_tsv(path, required or (column,)):
            if row.get(column, "").strip() == key:
                yield row
        return
    with open(path, "rb") as handle:
        header = handle.readline().decode("utf-8", "replace").rstrip("\r\n").lstrip("﻿").split("\t")
    gaps = [name for name in (required or (column,)) if name not in header]
    if gaps:
        raise SourceError(f"{path.name} has no {', '.join(gaps)} column")
    width = len(header)
    with open(path, "rb") as handle:
        for start, end in index(path, column).get(key, []):
            handle.seek(start)
            for line in handle.read(end - start).decode("utf-8", "replace").splitlines():
                cells = [unwrap(cell) for cell in line.split("\t")]
                if len(cells) < width:
                    cells += [""] * (width - len(cells))
                yield dict(zip(header, cells))


def lines_for(path: Path, field: str, key: str) -> Iterator[str]:
    """The lines of a JSON Lines file whose top-level `field` is `key`."""
    if not indexable(path):
        pattern = re.compile(r'"' + re.escape(field) + r'"\s*:\s*"' + re.escape(key) + r'"')
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if pattern.search(line[:400]):
                    yield line
        return
    with open(path, "rb") as handle:
        for start, end in index(path, f"json:{field}").get(key, []):
            handle.seek(start)
            yield from handle.read(end - start).decode("utf-8").splitlines()
