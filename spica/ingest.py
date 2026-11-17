"""Index the user's documents for AI mode.

    python -m spica.ingest                 build the index from data/input
    python -m spica.ingest --dry-run       report what would be indexed, cheaply
    python -m spica.ingest --stats         describe the index that exists
    python -m spica.ingest --input <dir>   ingest another folder

Each run rebuilds from scratch, by design. An incremental path that
silently disagrees with the files on disk is worse than the wait. Also, the
manifest is only reliable when the run that made the vectors also wrote it.

`--dry-run` extracts and reports without a model, because embedding is the
slow step and it comes last. A scanned PDF with no text layer, a duplicate
under a second name, a workbook that does not parse: otherwise these show
only after a long wait, or never.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from spica.corpus import Index, input_dir
from spica.corpus.index import discover, index_dir, read_file


def report_line(report) -> str:
    if report.duplicate_of:
        note = f"duplicate of {report.duplicate_of}"
    elif report.problem:
        note = report.problem
    else:
        note = ""
    return (f"{report.source[-58:]:<58} {report.units:>5} {report.characters:>9,} "
            f"{report.chunks:>7}  {note}")


def dry_run(root: Path) -> int:
    files, skipped = discover(root)
    if not files:
        print(f"Nothing readable under {root}.", file=sys.stderr)
        print(f"Handled: {', '.join(sorted(set(s.lstrip('.') for s in __import__('spica.corpus', fromlist=['SUPPORTED']).SUPPORTED)))}",
              file=sys.stderr)
        return 1

    print(f"{'file':<58} {'units':>5} {'chars':>9} {'chunks':>7}  note")
    print("-" * 98)
    seen: dict[str, str] = {}
    reports = []
    for path, source in files:
        report, _ = read_file(path, source)
        if report.digest and report.digest in seen:
            report.duplicate_of = seen[report.digest]
            report.chunks = 0
        elif report.digest:
            seen[report.digest] = source
        reports.append(report)
        print(report_line(report))

    print("-" * 98)
    usable = [r for r in reports if r.usable]
    print(f"files read        : {len(reports)}  ({len(usable)} usable)")
    print(f"characters        : {sum(r.characters for r in reports):,}")
    print(f"chunks to embed   : {sum(r.chunks for r in reports):,}")
    for label, rows in (
        ("unsupported", skipped),
        ("duplicates", [r.source for r in reports if r.duplicate_of]),
        ("problems", [f"{r.source} ({r.problem})" for r in reports if r.problem]),
    ):
        if rows:
            print(f"{label:<18}: {len(rows)} -> {', '.join(rows[:4])}"
                  + (" ..." if len(rows) > 4 else ""))
    print("\nNothing was embedded. Run without --dry-run to build the index.")
    return 0


def stats(directory: Path) -> int:
    try:
        index = Index.load(directory)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    described = index.describe()
    print(f"index     : {directory}")
    print(f"passages  : {described['chunks']:,}")
    print(f"documents : {described['sources']}")
    print(f"dimension : {described['dimension']}")
    print(f"vectors   : {described['megabytes']} MB\n")
    for document in described["documents"]:
        note = document.get("duplicate_of") or document.get("problem") or ""
        print(f"  {document['source'][-60:]:<60} {document.get('chunks', 0):>5} passages"
              + (f"  {note}" if note else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spica.ingest", description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="folder to ingest (default: data/input)")
    parser.add_argument("--index", help="where to write it (default: data/index)")
    parser.add_argument("--model", help="embedding model to use")
    parser.add_argument("--batch", type=int, default=16,
                        help="passages embedded per call (default: 16)")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract and report without embedding")
    parser.add_argument("--stats", action="store_true",
                        help="describe the existing index and stop")
    args = parser.parse_args(argv)

    root = Path(args.input) if args.input else input_dir()
    target = Path(args.index) if args.index else index_dir()

    if args.stats:
        return stats(target)
    if not root.is_dir():
        print(f"error: {root} does not exist. Put your documents there.",
              file=sys.stderr)
        return 1
    if args.dry_run:
        return dry_run(root)

    from spica.agents.llm import ModelMissing
    from spica.corpus import Embedder

    try:
        print("loading the embedding model...")
        embedder = Embedder(Path(args.model) if args.model else None)
    except ModelMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"  {embedder.label}  dimension {embedder.dimension}\n")

    started = time.time()

    def progress(done: int, total: int, what: str) -> None:
        print(f"\r  {done}/{total}  {what[-56:]:<56}", end="", flush=True)

    index, reports = Index.build(embedder, root=root, batch=args.batch,
                                 progress=progress)
    print()
    index.save(target)

    problems = [r for r in reports if r.problem]
    print(f"\nindexed {len(index):,} passages from {len(index.sources)} documents "
          f"in {time.time() - started:.0f}s -> {target}")
    if problems:
        print(f"{len(problems)} files had problems; `--stats` lists them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
