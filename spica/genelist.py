"""Gene lists: the pasted entries, mapped to genes, confirmed before use.

A list comes in any form: a column from a spreadsheet, a comma list in an
email, a file. Each entry goes through HGNC, as the query of a single
report does. The result is a mapping report that gives the match of each
entry, row by row:

- exact: an approved symbol, or an HGNC, Ensembl, UniProt or Entrez ID;
- renamed: a previous symbol, now another one; check it;
- alias: another name of the gene; check it, because lists often fail here;
- ambiguous: the name of several genes; the user selects one, never Spica;
- not found: no match; the user corrects or drops it;
- duplicate: a second entry for a gene already in the list.

Nothing is ranked until the user confirms the mapping. A confirmed list is
saved under `data/lists/` with its mapping, so the next session starts from
the same genes.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from spica import ranking
from spica.live import Live
from spica.mirror import Mirror
from spica.paths import data_dir

#: How an HGNC match is reported, by `Resolution.matched_on`.
STATUS = {"HGNC ID": "exact", "approved symbol": "exact", "Ensembl gene ID": "exact",
          "UniProt accession": "exact", "Entrez ID": "exact",
          "previous symbol": "renamed", "alias symbol": "alias"}

#: First cells that are a column title, not a gene.
HEADERS = {"gene", "genes", "symbol", "symbols", "gene symbol", "gene_symbol", "gene name",
           "genename", "id", "ids", "name", "target", "targets", "hgnc", "ensembl", "uniprot"}

SPLIT = re.compile(r"[\s,;|]+")


def parse(text: str) -> list[str]:
    """Entries in the order given. A line with tabs is a spreadsheet row, and
    its first cell is the gene; otherwise commas, semicolons and spaces all
    separate. A column title on the first line is dropped; exact repeats are
    kept, so the mapping can say they are repeats."""
    entries: list[str] = []
    lines = [line for line in text.replace("\r", "").split("\n") if line.strip()]
    for number, line in enumerate(lines):
        cells = [line.split("\t")[0]] if "\t" in line else SPLIT.split(line)
        for cell in cells:
            cell = cell.strip().strip('"').strip("'").strip()
            if not cell:
                continue
            if number == 0 and not entries and cell.lower() in HEADERS:
                continue
            entries.append(cell)
    return entries


def read_file(path: str) -> str:
    """The text of a list file: .txt, .csv, .tsv, or the first column of an
    .xlsx's first sheet when the spreadsheet reader is installed."""
    file = Path(path)
    if file.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Reading .xlsx needs the document readers; save the list as .csv "
                             "or paste it.") from None
        sheet = load_workbook(file, read_only=True, data_only=True).worksheets[0]
        return "\n".join(str(row[0]) for row in sheet.iter_rows(values_only=True)
                         if row and row[0] is not None)
    text = file.read_text(encoding="utf-8-sig", errors="replace")
    if file.suffix.lower() == ".csv":
        # A CSV's first column, like a spreadsheet's.
        return "\n".join(line.split(",")[0] for line in text.splitlines())
    return text


def _names(mirror: Mirror) -> dict[str, dict[str, str]]:
    """HGNC ID to symbol and name, from the resolver's own index."""
    from spica.sources.hgnc import table

    entry = mirror.entry("hgnc")
    if entry is None or entry.missing_files():
        return {}
    found = table(entry.path("complete_set"))
    return {row["hgnc_id"]: {"symbol": row["symbol"], "name": row["name"]}
            for row in found["rows"]}


def map_entries(entries: list[str], mirror: Mirror | None = None,
                live: Live | None = None) -> dict[str, Any]:
    """The mapping report for `entries`, one row each, in order."""
    from spica.build import _resolve

    mirror = Mirror.load() if mirror is None else mirror
    live = Live.from_env(mirror.root) if live is None else live
    names = _names(mirror)
    rows: list[dict[str, Any]] = []
    first: dict[str, int] = {}
    for position, entry in enumerate(entries):
        resolution, _ = _resolve(entry, mirror, live)
        row: dict[str, Any] = {"input": entry, "position": position, "symbol": "", "hgnc_id": "",
                               "name": "", "matched_on": resolution.matched_on,
                               "candidates": [], "note": ""}
        if resolution.resolved:
            row.update(symbol=resolution.symbol, hgnc_id=resolution.hgnc_id,
                       name=names.get(resolution.hgnc_id, {}).get("name", ""),
                       status=STATUS.get(resolution.matched_on, "exact"))
            if row["status"] == "renamed":
                row["note"] = f"{entry} is a previous symbol; the gene is now {resolution.symbol}"
            elif row["status"] == "alias":
                row["note"] = f"{entry} is an alias of {resolution.symbol}"
            if resolution.hgnc_id in first:
                row["status"] = "duplicate"
                row["note"] = (f"the same gene as entry {first[resolution.hgnc_id] + 1} "
                               f"({rows[first[resolution.hgnc_id]]['input']})")
            else:
                first[resolution.hgnc_id] = position
        elif resolution.candidates:
            row["status"] = "ambiguous"
            row["note"] = resolution.reason
            for candidate in resolution.candidates:
                found = re.match(r"^(.*) \((HGNC:\d+)\)$", candidate)
                symbol, hgnc_id = (found.group(1), found.group(2)) if found else (candidate, "")
                row["candidates"].append({"symbol": symbol, "hgnc_id": hgnc_id,
                                          "name": names.get(hgnc_id, {}).get("name", "")})
        else:
            row["status"] = "not_found"
            row["note"] = resolution.reason
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    review = counts.get("ambiguous", 0) + counts.get("not_found", 0)
    return {"rows": rows, "counts": counts, "genes": len(first),
            "needs_review": review,
            "message": (f"{review} {'entry' if review == 1 else 'entries'} to review." if review else
                        f"All entries mapped: {len(first)} genes.")}


def confirm(rows: list[dict[str, Any]], choices: dict[str, str]) -> dict[str, Any]:
    """The confirmed genes, in list order. Each resolved row gives its gene
    once. Each ambiguous row gives the HGNC ID that the user chose for it (by
    position). Dropped and unfound rows give nothing. An ambiguous row with
    no choice is an error that names the row."""
    genes, seen, missing = [], set(), []
    for row in rows:
        choice = choices.get(str(row["position"]), "")
        if choice == "drop":
            continue
        if row["status"] == "ambiguous":
            picked = next((c for c in row["candidates"] if c["hgnc_id"] == choice), None)
            if picked is None:
                missing.append(row["input"])
                continue
            symbol, hgnc_id = picked["symbol"], picked["hgnc_id"]
        elif row["status"] == "not_found" or not row.get("hgnc_id"):
            continue
        else:
            symbol, hgnc_id = row["symbol"], row["hgnc_id"]
        if hgnc_id not in seen:
            seen.add(hgnc_id)
            genes.append({"input": row["input"], "symbol": symbol, "hgnc_id": hgnc_id})
    if missing:
        return {"error": f"Gene selection required: {', '.join(missing)}."}
    if not genes:
        return {"error": "No gene left in the list."}
    return {"genes": genes}


# -- saved lists --------------------------------------------------------------------------------


def folder() -> Path:
    return data_dir() / "lists"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "list"


def save(name: str, entries: list[str], mapping: dict[str, Any], genes: list[dict[str, str]],
         choices: dict[str, str], weights: dict[str, float] | None = None,
         preset: str = "", indication: str = "") -> dict[str, Any]:
    name = name.strip() or "Untitled list"
    path = folder() / f"{slug(name)}.json"
    created = time.strftime("%Y-%m-%d %H:%M")
    if path.exists():
        try:
            created = json.loads(path.read_text(encoding="utf-8")).get("created", created)
        except (OSError, json.JSONDecodeError):
            pass
    record = {"name": name, "created": created, "updated": time.strftime("%Y-%m-%d %H:%M"),
              "entries": entries, "mapping": mapping, "choices": choices, "genes": genes,
              "weights": weights or {}, "scale": ranking.SCALE, "preset": preset,
              "indication": indication}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=1), encoding="utf-8")
    temporary.replace(path)
    return {"slug": path.stem, **{k: record[k] for k in ("name", "created", "updated")},
            "genes": len(genes)}


def saved() -> list[dict[str, Any]]:
    out = []
    for path in sorted(folder().glob("*.json")) if folder().exists() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"slug": path.stem, "name": record.get("name", path.stem),
                    "updated": record.get("updated", ""), "genes": len(record.get("genes", [])),
                    "preset": record.get("preset", "")})
    return sorted(out, key=lambda item: item["updated"], reverse=True)


def load(list_slug: str) -> dict[str, Any] | None:
    path = folder() / f"{slug(list_slug)}.json"
    try:
        return ranking.upgraded(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def delete(list_slug: str) -> bool:
    path = folder() / f"{slug(list_slug)}.json"
    if path.exists():
        path.unlink()
        return True
    return False
