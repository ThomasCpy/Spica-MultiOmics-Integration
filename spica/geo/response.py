"""One gene's values inside a GEO series, sample by sample.

From the integrator's `gene_response_from_geo`: many expression series
publish a processed gene-by-sample table (counts, TPM, FPKM, normalised
values) as a supplementary file. Its row for the gene, matched to the
samples it names, sets the samples side by side; grouped by any of their
characteristics (treatment, genotype, cell type), each group gets its mean
and the number of samples behind it.

These are the study's own processed values, read as published: not a
statistical test, and not comparable across series that normalised
differently. The table says which file they came from.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Callable, Iterator

from spica.geo import tracks as geo_tracks
from spica.live import Live, LiveError, OFF

#: Names that suggest a processed expression table, best first.
PREFERRED = ("tpm", "fpkm", "rpkm", "cpm", "norm", "count", "expression", "expr", "matrix", "deseq")
MAX_MATRIX_BYTES = 300 * 1024 * 1024


def matrices(found: dict[str, Any]) -> list[dict[str, Any]]:
    """The series' table files, the likeliest expression table first."""
    files = [f for f in found["files"] if f["kind"] == "matrix"]

    def rank(f: dict[str, Any]) -> tuple[int, str]:
        name = f["name"].lower()
        return next((i for i, word in enumerate(PREFERRED) if word in name), len(PREFERRED)), name

    return sorted(files, key=rank)


def _names(symbol: str, ensembl_id: str, aliases: list[str]) -> set[str]:
    return {n.upper() for n in [symbol, ensembl_id, *aliases] if n}


def find_row(lines: Iterator[str], names: set[str]) -> tuple[list[str], list[str]] | None:
    """The header and the gene's row, or None. The gene is matched in any of
    the first three columns, an Ensembl version suffix ignored."""
    header: list[str] | None = None
    delimiter = "\t"
    for line in lines:
        if not line.strip():
            continue
        if header is None:
            delimiter = "," if line.count(",") > line.count("\t") else "\t"
            header = [c.strip().strip('"') for c in line.split(delimiter)]
            continue
        cells = [c.strip().strip('"') for c in line.split(delimiter)]
        for cell in cells[:3]:
            if cell.upper() in names or cell.split(".")[0].upper() in names:
                return header, cells
    return None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", text.lower())


def abbreviates(short: str, title: str) -> bool:
    """Whether a column name is a short form of a sample title. Each letter
    run is the start of a title word, or the initials of consecutive words.
    Each number is a number of the title, in order. "PT10_C1" is a short
    form of "PT10_Control_1"; "SO2" is a short form of "SFN_OTA_2"."""
    wanted, words = _tokens(short), _tokens(title)
    if not wanted:
        return False

    def walk(i: int, j: int) -> bool:
        if i == len(wanted):
            return True
        token = wanted[i]
        for k in range(j, len(words)):
            word = words[k]
            if token.isdigit():
                if word == token and walk(i + 1, k + 1):
                    return True
                continue
            if word.isalpha() and word.startswith(token) and walk(i + 1, k + 1):
                return True
            # Initials across consecutive words.
            run = words[k:k + len(token)]
            if len(token) > 1 and len(run) == len(token) and all(w.isalpha() for w in run) \
                    and "".join(w[0] for w in run) == token and walk(i + 1, k + len(token)):
                return True
        return False

    return walk(0, 0)


def match_columns(header: list[str], cells: list[str], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each numeric column, with the sample it belongs to when one can be told."""
    width = len(cells)
    # A header one shorter than the row has no name over the gene column.
    names = header if len(header) == width else [""] * (width - len(header)) + header
    by_gsm = {s["accession"]: s for s in samples}
    by_title = {s["title"].lower(): s for s in samples if s["title"]}
    out = []
    for name, cell in zip(names, cells):
        try:
            value = float(cell)
        except ValueError:
            continue
        gsm = re.search(r"GSM\d+", name)
        owner = by_gsm.get(gsm.group(0)) if gsm else by_title.get(name.lower())
        how = "accession" if gsm and owner else "title" if owner else ""
        if owner is None and name:
            # "Ctrl_rep1" against a sample titled "HepG2 Ctrl_rep1".
            close = [s for s in samples if name.lower() in s["title"].lower()]
            if len(close) != 1:
                # "PT10_O1" fits "PT10_OTA_1" and "PT10_SFN_OTA_1": the title
                # with the fewest words to spare is the one it shortens.
                fits = sorted((len(_tokens(s["title"])), s["accession"], s) for s in samples
                              if abbreviates(name, s["title"]))
                close = [fits[0][2]] if fits and (len(fits) == 1 or fits[0][0] < fits[1][0]) else []
            owner = close[0] if len(close) == 1 else None
            how = "abbreviation" if owner else ""
        out.append({"column": name, "value": value, "owner": owner, "how": how})
    if out and len(out) == len(samples):
        # As many columns as samples, and every column whose name told its
        # sample sits where that sample sits in GEO's own order: the table
        # follows the series' order, so the rest are matched by position.
        named = [(i, c) for i, c in enumerate(out) if c["owner"]]
        # No named column, no confirmation: "N1".."T4" against titles
        # "pTRPM1-1".."pNC-4" would pair treated with control.
        if named and all(samples[i] is c["owner"] for i, c in named):
            for i, column in enumerate(out):
                if not column["owner"]:
                    column.update(owner=samples[i], how="order")
    return [{"column": c["column"], "value": c["value"], "matched_by": c["how"],
             "sample": c["owner"]["accession"] if c["owner"] else "",
             "title": c["owner"]["title"] if c["owner"] else "",
             "context": c["owner"]["characteristics"] if c["owner"] else {},
             "arm": c["owner"]["arm"] if c["owner"] else ""} for c in out]


def groups(columns: list[dict[str, Any]], facets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each field that sets samples apart, the gene's mean in each value."""
    out = []
    for facet in facets:
        field = facet["field"]
        bucket: dict[str, list[float]] = {}
        for column in columns:
            value = column["context"].get(field)
            if value:
                bucket.setdefault(value, []).append(column["value"])
        if len(bucket) > 1:
            out.append({"field": field, "groups": [
                {"value": v, "samples": len(xs), "mean": round(statistics.fmean(xs), 4),
                 "values": [round(x, 4) for x in xs]}
                for v, xs in sorted(bucket.items(), key=lambda kv: -statistics.fmean(kv[1]))]})
    return out


def gene(found: dict[str, Any], symbol: str, ensembl_id: str, live: Live, file_url: str = "",
         aliases: list[str] | None = None,
         lines: Callable[[str, int], Iterator[str]] | None = None) -> dict[str, Any]:
    """The gene's row in one of the series' tables, matched to its samples."""
    tables = matrices(found)
    if not tables:
        return {"state": "none", "message": "This series publishes no processed table among its "
                                            "supplementary files; its values are in raw files."}
    chosen = next((t for t in tables if t["url"] == file_url), tables[0]) if file_url else tables[0]
    names = _names(symbol, ensembl_id, aliases or [])
    key = f"geo-gene:{chosen['url']}#{'|'.join(sorted(names))}"

    def produce() -> dict[str, Any]:
        if not live.allowed:
            raise LiveError(OFF)
        try:
            row = find_row((lines or geo_tracks.stream_lines)(chosen["url"], MAX_MATRIX_BYTES), names)
        except (geo_tracks.GeoTrackError, OSError) as exc:
            raise LiveError(str(exc)) from None
        return {"header": row[0], "cells": row[1]} if row else {}

    data = live.remember("geo", key, produce).payload or {}
    base = {"file": chosen["name"], "url": chosen["url"], "tables": [t["name"] for t in tables],
            "table_urls": [t["url"] for t in tables]}
    if not data:
        return {**base, "state": "absent",
                "message": f"{symbol} is not in {chosen['name']} (looked for {', '.join(sorted(names))} in its "
                           "first three columns). Another table of the series may hold it."}
    columns = match_columns(data["header"], data["cells"], found["samples"])
    if not columns:
        return {**base, "state": "absent", "message": f"{symbol} is in {chosen['name']} but its row holds no numbers."}
    matched = sum(1 for c in columns if c["sample"])
    return {**base, "state": "ok", "columns": columns, "matched": matched,
            "groups": groups(columns, found["facets"]),
            "note": "Processed values from the study, as published. Not a statistical test."}
