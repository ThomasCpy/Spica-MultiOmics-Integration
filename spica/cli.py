"""Read a record in the terminal, without the window.

    python -m spica.cli PCSK9
    python -m spica.cli PCSK9 --json
    python -m spica.cli PCSK9 --offline     # mirrored sources only
    python -m spica.cli PCSK9 --refresh     # ignore the cache, fetch again
    python -m spica.cli --mirror

Useful while the mirror fills up. It shows what each source gave and what
it could not give, as the report screen does.
"""

from __future__ import annotations

import argparse
import json
import sys

from spica.build import build_record, summarize
from spica.live import Live
from spica.mirror import Mirror
from spica.record import GeneRecord
from spica.schema import FIELDS, SECTIONS


def show_mirror(mirror: Mirror, live: Live) -> int:
    print(f"Mirror: {mirror.root}")
    if not mirror.present:
        print(f"  {mirror.problem}")
        print(f"  Sources not mirrored are "
              f"{'fetched from their API' if live.allowed else 'left empty (offline)'}.")
        return 1
    for entry in mirror.entries.values():
        missing = entry.missing_files()
        state = f"missing {', '.join(missing)}" if missing else "ready"
        print(f"  {entry.label:<22} {entry.version:<12} {entry.retrieved}  {state}")
    return 0


def show_record(record: GeneRecord) -> None:
    print(summarize(record))
    if record.resolution.candidates:
        for candidate in record.resolution.candidates:
            print(f"  {candidate}")
        return

    section = ""
    for spec in FIELDS:
        if spec.section != section:
            section = spec.section
            print(f"\n{SECTIONS[section]}")
        value = record.fields[spec.name]
        if not value.present:
            print(f"  {spec.label:<24} - {value.state.value}: {value.reason}")
            continue
        # A unit belongs beside the label when the value is a map of numbers,
        # and after the number when there is only one.
        label, unit = spec.label, ""
        if spec.unit:
            if isinstance(value.value, dict):
                label = f"{spec.label} ({spec.unit})"
            else:
                unit = f" {spec.unit}"
        # "HGNC 2026-09-01" off the mirror, "Ensembl 116, API" off the wire.
        provenance = value.provenance
        parts = [provenance.source if provenance else ""]
        if provenance and provenance.version and provenance.version != "API":
            parts[0] = f"{parts[0]} {provenance.version}"
        if provenance and provenance.locator.startswith("http"):
            parts.append("API")
        where = ", ".join(part for part in parts if part)
        print(f"  {label:<24} {format_value(value.value)}{unit}   [{where}]")

    fetched = [stamp.label for stamp in record.sources if stamp.status == "fetched"]
    if fetched:
        print(f"\nFetched live from {', '.join(fetched)}, and cached for next time.")
        print(f"Fingerprint {record.fingerprint()[:16]}")
    else:
        print(f"\nFingerprint {record.fingerprint()[:16]}")


def format_value(value: object, width: int = 60) -> str:
    """One value on one line.

    A terminal line abbreviates where a screen expands. The line thus always
    gives the count of hidden entries, and `--json` prints all of them.
    Nothing is dropped silently.
    """
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[1], reverse=True)[:4] \
            if all(isinstance(v, (int, float)) for v in value.values()) \
            else list(value.items())[:4]
        text = ", ".join(f"{k} {v}" for k, v in items)
        if len(value) > 4:
            text += f", +{len(value) - 4} more (--json for all)"
        return text
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value[:8])
        if len(value) > 8:
            text += f", +{len(value) - 8} more (--json for all)"
        return text
    text = str(value)
    return text if len(text) <= width else text[: width - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spica", description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", help="gene symbol or identifier")
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    parser.add_argument("--mirror", action="store_true",
                        help="show what the local mirror holds")
    parser.add_argument("--data-dir", help="read the mirror from here")
    parser.add_argument("--offline", action="store_true",
                        help="mirrored sources only, never the APIs")
    parser.add_argument("--online", action="store_true",
                        help="fill what the mirror lacks from the APIs, whatever Settings say")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and fetch again")
    args = parser.parse_args(argv)

    mirror = Mirror.load(args.data_dir) if args.data_dir else Mirror.load()
    allowed = False if args.offline else True if args.online else None
    live = Live.from_env(mirror.root, allowed=allowed, refresh=args.refresh)
    if args.mirror and not args.target:
        return show_mirror(mirror, live)
    if not args.target:
        parser.print_help()
        return 2

    record = build_record(args.target, mirror, live)
    if args.json:
        print(json.dumps(record.to_dict(), indent=2))
    else:
        show_record(record)
    return 0 if record.resolution.resolved else 1


if __name__ == "__main__":
    sys.exit(main())
