"""The index: embedded passages, and brute-force search over them.

A flat matrix, searched by dot product. For a corpus of this size this is
not a compromise: a few thousand vectors take well under a millisecond. It
also avoids an approximate-nearest-neighbour dependency that needs
vendoring, tuning and trust.

Three files, so ordinary tools can inspect the index:

    chunks.jsonl   one passage per line, with its source and location
    vectors.npy    the matrix, one unit-length row per chunk
    manifest.json  each file ingested, its digest, and what it produced

The manifest makes a rebuild honest. A file with unchanged bytes produces
the same chunks. A removed file leaves the index; its passages do not stay
behind with nothing to open.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from spica.corpus.chunks import Chunk, chunk_units
from spica.corpus.extract import DISCRETE, SUPPORTED, ExtractionError, extract
from spica.paths import data_dir

INDEX_DIRNAME = "index"
INPUT_DIRNAME = "input"


def input_dir() -> Path:
    return data_dir() / INPUT_DIRNAME


def index_dir() -> Path:
    return data_dir() / INDEX_DIRNAME


def digest(path: Path) -> str:
    """The file's SHA-256, read in blocks so a 2 GB workbook does not
    have to fit in memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def discover(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    """Every readable file under `root`, and the names of those skipped.

    Documents are identified by their path relative to the input folder,
    not by basename: once whole folder trees get dropped in, two subfolders
    each holding `Figure1.png` are two different documents.
    """
    files: list[tuple[Path, str]] = []
    skipped: list[str] = []
    if not root.is_dir():
        return files, skipped

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("~$") or path.name.startswith("."):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in SUPPORTED:
            files.append((path, relative))
        else:
            skipped.append(relative)
    return files, skipped


@dataclass
class Ingested:
    """What one file turned into, for the manifest and the report."""

    source: str
    digest: str = ""
    units: int = 0
    characters: int = 0
    chunks: int = 0
    duplicate_of: str = ""
    problem: str = ""

    @property
    def usable(self) -> bool:
        return not self.problem and not self.duplicate_of and self.chunks > 0


def read_file(path: Path, source: str) -> tuple[Ingested, list[Chunk]]:
    """Extract and chunk one file. Never raises: a bad file is reported."""
    report = Ingested(source=source)
    try:
        report.digest = digest(path)
        units = extract(path)
    except ExtractionError as exc:
        report.problem = str(exc)
        return report, []
    except OSError as exc:
        report.problem = f"not read: {exc}"
        return report, []

    report.units = len(units)
    report.characters = sum(len(unit) for unit in units)
    chunks = chunk_units(units, source=source,
                         merge=path.suffix.lower() not in DISCRETE)
    report.chunks = len(chunks)

    # A file that produced nothing is the one to report. A PDF without a
    # text layer is a scan. The report turns "that paper never shows up in
    # answers" into a known cause. A short file that chunked correctly is
    # just a short file.
    if not chunks:
        report.problem = ("no text could be read"
                          + (" (a scan? it would need OCR)"
                             if path.suffix.lower() == ".pdf" else ""))
    elif (path.suffix.lower() == ".pdf" and len(units) >= 3
          and report.characters / len(units) < 200):
        report.problem = "very little text per page (probably scanned)"
    return report, chunks


class Index:
    """Embedded passages plus brute-force cosine search."""

    def __init__(self, vectors, chunks: list[Chunk], manifest: dict[str, dict]):
        self.vectors = vectors
        self.chunks = chunks
        self.manifest = manifest

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def sources(self) -> list[str]:
        return sorted({chunk.source for chunk in self.chunks})

    # -- building -----------------------------------------------------------

    @classmethod
    def build(cls, embedder, root: Path | None = None, batch: int = 16,
              progress=None) -> tuple["Index", list[Ingested]]:
        """Read every file under `root`, embed what came out, return both."""
        import numpy as np

        root = root or input_dir()
        files, _ = discover(root)
        seen: dict[str, str] = {}
        reports: list[Ingested] = []
        chunks: list[Chunk] = []

        for position, (path, source) in enumerate(files, start=1):
            if progress:
                progress(position, len(files), source)
            report, produced = read_file(path, source)
            if report.digest and report.digest in seen:
                report.duplicate_of = seen[report.digest]
                report.chunks = 0
                reports.append(report)
                continue
            if report.digest:
                seen[report.digest] = source
            reports.append(report)
            chunks.extend(produced)

        if not chunks:
            empty = np.zeros((0, getattr(embedder, "dimension", 1)), dtype="float32")
            return cls(empty, [], _manifest(reports)), reports

        vectors = []
        for start in range(0, len(chunks), batch):
            window = chunks[start:start + batch]
            if progress:
                progress(start + len(window), len(chunks), "embedding")
            vectors.append(embedder.documents([chunk.text for chunk in window]))
        matrix = np.vstack(vectors)
        return cls(matrix, chunks, _manifest(reports)), reports

    # -- on disk ------------------------------------------------------------

    def save(self, directory: Path | None = None) -> Path:
        import numpy as np

        directory = directory or index_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "chunks.jsonl", "w", encoding="utf-8") as handle:
            for chunk in self.chunks:
                handle.write(json.dumps(chunk.to_dict()) + "\n")
        np.save(directory / "vectors.npy", self.vectors)
        (directory / "manifest.json").write_text(
            json.dumps(self.manifest, indent=1), encoding="utf-8")
        return directory

    @classmethod
    def load(cls, directory: Path | None = None) -> "Index":
        import numpy as np

        directory = directory or index_dir()
        chunks_file = directory / "chunks.jsonl"
        vectors_file = directory / "vectors.npy"
        if not chunks_file.exists() or not vectors_file.exists():
            raise FileNotFoundError(f"No index in {directory}")

        chunks = [Chunk(**json.loads(line))
                  for line in chunks_file.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        vectors = np.load(vectors_file)
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"{directory} is inconsistent: {len(chunks)} passages but "
                f"{vectors.shape[0]} vectors. Rebuild it."
            )
        manifest = {}
        manifest_file = directory / "manifest.json"
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
        return cls(vectors, chunks, manifest)

    @classmethod
    def exists(cls, directory: Path | None = None) -> bool:
        directory = directory or index_dir()
        return (directory / "chunks.jsonl").exists()

    # -- searching ----------------------------------------------------------

    def search(self, vector, limit: int = 6,
               sources: list[str] | None = None) -> list[tuple[float, Chunk]]:
        """The closest passages, nearest first.

        Vectors are unit length, so cosine similarity is the dot product
        and the whole search is one matrix multiply.
        """
        import numpy as np

        if not len(self.chunks):
            return []
        scores = self.vectors @ np.asarray(vector, dtype="float32")

        order = np.argsort(-scores)
        wanted = set(sources) if sources else None
        hits: list[tuple[float, Chunk]] = []
        for position in order:
            chunk = self.chunks[int(position)]
            if wanted and chunk.source not in wanted:
                continue
            hits.append((float(scores[int(position)]), chunk))
            if len(hits) >= limit:
                break
        return hits

    def describe(self) -> dict[str, Any]:
        return {
            "chunks": len(self.chunks),
            "sources": len(self.sources),
            "dimension": int(self.vectors.shape[1]) if len(self.chunks) else 0,
            "megabytes": round(self.vectors.nbytes / 1024 ** 2, 1),
            "documents": [
                {"source": name, **meta} for name, meta in sorted(self.manifest.items())
            ],
        }


def _manifest(reports: list[Ingested]) -> dict[str, dict]:
    return {
        report.source: {
            "sha256": report.digest,
            "units": report.units,
            "chunks": report.chunks,
            "duplicate_of": report.duplicate_of,
            "problem": report.problem,
        }
        for report in reports
    }


def iter_chunks(directory: Path | None = None) -> Iterator[Chunk]:
    """Passages without loading the vectors, for inspection."""
    path = (directory or index_dir()) / "chunks.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield Chunk(**json.loads(line))
