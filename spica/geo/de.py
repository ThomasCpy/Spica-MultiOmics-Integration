"""Differential expression in a GEO series, for a volcano plot.

Two routes, both validated:

- *Published results.* A supplementary table with the fold changes and
  p-values of the authors. DESeq2, edgeR and limma name their columns in
  fixed ways. The table is plotted as published, never recalculated.
- *DESeq2 on raw counts.* A gene-by-sample table of integer read counts,
  matched to the samples of the series, in two groups by one sample
  variable. The test is PyDESeq2, a port of DESeq2 checked against the R
  package (Muzellec et al., Bioinformatics 2023), with the DESeq2 defaults:
  Wald test, Benjamini-Hochberg adjustment, Cook's distance and independent
  filtering.

A table of TPM, FPKM or other normalised values has no validated test, so
Spica refuses it and gives the reason. It also refuses a table whose
columns do not match the samples, because the groups would be guesses.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from spica.geo import response as geo_response
from spica.live import OFF, USER_AGENT, Live, LiveError

MAX_BYTES = 300 * 1024 * 1024
#: Rows read to tell what a table is.
SAMPLE_ROWS = 2000
#: Columns that hold annotation, not samples (featureCounts, RSEM, Ensembl exports).
ANNOTATION = re.compile(r"^(gene[_ ]?)?(chr|chrom|chromosome|start|end|stop|strand|length|"
                        r"effective_?length|width|gc|gc_?content|biotype|type|id|entrez(_?id)?)$|^geneid$", re.I)
SYMBOL = re.compile(r"^(gene_?name|gene_?symbol|symbol|external_?gene_?name|hgnc_?symbol|gene name|name)$", re.I)
#: Result columns besides fold change and p (DESeq2, edgeR, limma), by _key.
STATISTICS = {"basemean", "lfcse", "stat", "aveexpr", "logcpm", "t", "b", "lr", "f", "foldchange"}
#: Names that suggest published results, then counts, best first.
HINTS = ("deseq", "edger", "limma", "differential", "_vs_", "-vs-", ".vs.", "deg", "result",
         "count", "readcount")
MIN_PER_GROUP = 2
#: Part of every cached result's key: raised when a result's content changes,
#: so an older result is computed again rather than shown.
RESULT_VERSION = 2


class DeError(Exception):
    pass


#: A replicate number: at the end of a title, or of one of its comma-separated parts.
REPLICATE = re.compile(r"[-_\s.]+(?:rep(?:licate)?[-_\s.]*)?(\d{1,2})(?=\s*(?:[,;]|$))", re.I)


def title_groups(titles: list[str]) -> dict[str, str]:
    """Each title's group, the title without its replicate number, or {} when
    the titles do not read as groups of numbered replicates.

    "Mock_2" -> "Mock", "shCTR1-1" -> "shCTR1". Within a group the numbers
    must run 1..n (or 0..n-1), so "Day 3" and "Day 10" never pool into "Day".
    """
    groups: dict[str, list[int]] = {}
    out = {}
    for title in titles:
        found = list(REPLICATE.finditer(title))
        if not found:
            return {}
        last = found[-1]
        group = re.sub(r"\s+", " ", title[:last.start()] + title[last.end():]).strip(" ,;_-")
        groups.setdefault(group, []).append(int(last.group(1)))
        out[title] = group
    for numbers in groups.values():
        low = min(numbers)
        if low not in (0, 1) or sorted(numbers) != list(range(low, low + len(numbers))):
            return {}
    return out if len(groups) > 1 else {}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _fold(name: str) -> bool:
    k = _key(name)
    return "log2foldchange" in k or "log2fc" in k or k.endswith("logfc") or k.startswith("logfc") \
        or k in ("lfc", "log2ratio", "log2fold")


def _adjusted(name: str) -> bool:
    k = _key(name)
    return "padj" in k or "adjp" in k or "pvaladj" in k or "pvalueadj" in k or "fdr" in k \
        or "qval" in k or k in ("bh", "qvalue")


def _raw_p(name: str) -> bool:
    k = _key(name)
    return not _adjusted(name) and (k in ("p", "pval", "pvalue", "pvalues") or k.endswith("pvalue")
                                    or k.endswith("pval") or k.startswith("pvalue") or k.startswith("pval"))


def _number(cell: Any) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    text = str(cell).strip()
    if text.upper() in ("", "NA", "NAN", "N/A", "NULL", "-", "INF", "-INF"):
        return math.nan if text else None
    try:
        return float(text)
    except ValueError:
        return None


# -- files ---------------------------------------------------------------------------


def tables(found: dict[str, Any]) -> list[dict[str, Any]]:
    """The series' text and Excel tables, likeliest results or counts first."""
    files = [f for f in found["files"] if f["kind"] in ("matrix", "sheet")]

    def rank(f: dict[str, Any]) -> tuple[int, str]:
        name = f["name"].lower()
        return next((i for i, word in enumerate(HINTS) if word in name), len(HINTS)), name

    return sorted(files, key=rank)


def _cache_dir(live: Live, folder: str) -> Path:
    path = live.root / "cache" / folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def download(url: str, live: Live) -> Path:
    """The file, from the cache when it is there. Fetched whole, once."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", url.rsplit("/", 1)[-1])[-80:]
    path = _cache_dir(live, "geo-files") / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}-{name}"
    if path.exists():
        return path
    if not live.allowed:
        raise LiveError(OFF)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            size = int(response.headers.get("Content-Length") or 0)
            if size > MAX_BYTES:
                raise DeError(f"{name}: {size / 1e6:,.0f} MB; maximum {MAX_BYTES / 1e6:,.0f} MB")
            got = 0
            with open(temporary, "wb") as out:
                while chunk := response.read(1 << 20):
                    got += len(chunk)
                    if got > MAX_BYTES:
                        raise DeError(f"{name}: more than {MAX_BYTES / 1e6:,.0f} MB")
                    out.write(chunk)
        os.replace(temporary, path)
    except OSError as exc:
        raise LiveError(f"{name} not read: {exc}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read(path: Path, name: str) -> list[dict[str, Any]]:
    """Every table in the file: one for a text file, one per sheet for Excel.
    Each is {"sheet", "header", "rows"}, the header as wide as the rows."""
    lower = name.lower()
    if lower.endswith(".xls"):
        raise DeError(f"{name}: old Excel format (.xls) not read")
    if lower.endswith((".xlsx", ".xlsx.gz")):
        import openpyxl

        data = path.read_bytes()
        if lower.endswith(".gz"):
            data = gzip.decompress(data)
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for sheet in book.worksheets:
            rows = [list(r) for r in sheet.iter_rows(values_only=True)]
            rows = [r for r in rows if any(c not in (None, "") for c in r)]
            if len(rows) > 1:
                out.append(_shaped(sheet.title, rows))
        return out
    opener = gzip.open if lower.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith(("#", "!"))]
    if not lines:
        return []
    head = lines[0]
    delimiter = "," if head.count(",") > head.count("\t") else "\t"
    rows = list(csv.reader(lines, delimiter=delimiter))
    return [_shaped("", rows)]


def _shaped(sheet: str, rows: list[list[Any]]) -> dict[str, Any]:
    header = ["" if c is None else str(c).strip() for c in rows[0]]
    body = rows[1:]
    width = max((len(r) for r in body[:200]), default=len(header))
    if len(header) < width:
        # R's write.table leaves the row-name column unnamed.
        header = [""] * (width - len(header)) + header
    return {"sheet": sheet, "header": header, "rows": body}


# -- what a table is -------------------------------------------------------------------


def _numeric_columns(header: list[str], rows: list[list[Any]]) -> list[int]:
    out = []
    for i in range(len(header)):
        cells = [r[i] for r in rows if i < len(r)]
        values = [_number(c) for c in cells]
        given = [v for v in values if v is not None]
        if cells and len(given) >= 0.95 * len(cells) and any(not math.isnan(v) for v in given):
            out.append(i)
    return out


def _gene_column(header: list[str], rows: list[list[Any]], numeric: list[int]) -> int:
    for i in range(len(header)):
        if i not in numeric:
            return i
    return 0


def _symbol_column(header: list[str], gene: int) -> int | None:
    for i, name in enumerate(header):
        if i != gene and SYMBOL.match(name.strip()):
            return i
    return None


def _contrasts(header: list[str]) -> list[dict[str, Any]]:
    """Each fold-change column with its adjusted and raw p-value columns."""
    folds = [i for i, n in enumerate(header) if _fold(n)]
    adjusted = [i for i, n in enumerate(header) if _adjusted(n)]
    raw = [i for i, n in enumerate(header) if _raw_p(n)]

    def stem(name: str) -> str:
        k = _key(name)
        for token in ("log2foldchange", "log2fc", "logfc", "padj", "adjpval", "adjpvalue", "pvaladj",
                      "fdr", "qvalue", "qval", "pvalue", "pval"):
            k = k.replace(token, "")
        return k

    def partner(i: int, pool: list[int]) -> int | None:
        same = [j for j in pool if stem(header[j]) == stem(header[i])]
        if same:
            return same[0]
        after = [j for j in pool if j > i]
        return after[0] if len(folds) > 1 and after else (pool[0] if pool and len(folds) == 1 else None)

    out = []
    for i in folds:
        p_adj, p_raw = partner(i, adjusted), partner(i, raw)
        if p_adj is None and p_raw is None:
            continue
        label = re.sub(r"[_.\s]*(log2\s*fold\s*change|log2\s*fc|log\s*fc)[_.\s]*", " ", header[i], flags=re.I).strip()
        out.append({"label": label or header[i], "fold": header[i],
                    "p": header[p_adj] if p_adj is not None else header[p_raw],
                    "adjusted": p_adj is not None})
    return out


def profile(table: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """What the table is and which routes it allows."""
    header, rows = table["header"], table["rows"][:SAMPLE_ROWS]
    if not rows:
        return {"kind": "other", "reason": "No data rows."}
    contrasts = _contrasts(header)
    numeric = _numeric_columns(header, rows)
    gene = _gene_column(header, rows, numeric)
    out: dict[str, Any] = {"rows": len(table["rows"]), "gene_column": header[gene] or "(unnamed)",
                           "contrasts": contrasts}
    # Columns matched to samples, read off the first row as the gene view does.
    # Statistics are not samples: a p-value column whose first rows underflow
    # to 0 would otherwise read as integer counts.
    candidates = [i for i in numeric if not ANNOTATION.match(header[i].strip())
                  and not (_fold(header[i]) or _adjusted(header[i]) or _raw_p(header[i]))
                  and _key(header[i]) not in STATISTICS]
    first = rows[0]
    matched = geo_response.match_columns([header[i] for i in candidates],
                                         [str(first[i]) if i < len(first) else "" for i in candidates], samples)
    columns = []
    for i, m in zip(candidates, matched):
        values = [_number(r[i]) if i < len(r) else None for r in rows]
        given = [v for v in values if v is not None and not math.isnan(v)]
        integer = bool(given) and all(v >= 0 and abs(v - round(v)) < 1e-9 for v in given)
        context = dict(m["context"])
        columns.append({"index": i, "column": header[i], "sample": m["sample"], "title": m["title"],
                        "matched_by": m["matched_by"], "context": context, "integer": integer})
    by_title = title_groups(sorted({c["title"] for c in columns if c["title"]}))
    for c in columns:
        if c["title"] in by_title:
            c["context"]["sample group (title)"] = by_title[c["title"]]
    counts = [c for c in columns if c["integer"]]
    out["columns"] = [{k: v for k, v in c.items() if k != "integer"} for c in counts]
    out["matched"] = sum(1 for c in counts if c["sample"])
    out["other_numeric"] = [c["column"] for c in columns if not c["integer"]]
    routes = []
    if contrasts:
        routes.append("published")
    if len(counts) >= 2 * MIN_PER_GROUP:
        routes.append("deseq2")
    out["routes"] = routes
    if contrasts:
        out["kind"] = "results"
    elif routes:
        out["kind"] = "counts"
        if out["matched"] < len(counts):
            out["reason"] = (f"{len(counts) - out['matched']} of {len(counts)} count columns not matched to "
                             "samples: groups by column.")
    elif counts:
        out["kind"] = "counts"
        out["reason"] = f"{len(counts)} count columns; DESeq2 needs {2 * MIN_PER_GROUP} or more."
    elif columns:
        out["kind"] = "values"
        out["reason"] = "Values not integer read counts (TPM, FPKM or normalised): no validated test."
    else:
        out["kind"] = "other"
        out["reason"] = "No fold-change, p-value or sample columns."
    return out


# -- gene labels -------------------------------------------------------------------------

_SYMBOLS: dict[str, dict[str, str]] = {}


def _symbols(mirror) -> dict[str, str]:
    """Ensembl gene ID to HGNC symbol, from the local HGNC set."""
    entry = mirror.entry("hgnc") if mirror is not None else None
    if entry is None:
        return {}
    path = str(entry.path("complete_set"))
    if path not in _SYMBOLS:
        from spica.sources.base import read_tsv

        found: dict[str, str] = {}
        try:
            for row in read_tsv(entry.path("complete_set"), ("symbol",)):
                ensembl = (row.get("ensembl_gene_id") or "").strip()
                if ensembl:
                    found[ensembl] = row["symbol"].strip()
        except Exception:
            pass
        _SYMBOLS[path] = found
    return _SYMBOLS[path]


def _label(gene_id: str, symbol: str, symbols: dict[str, str]) -> str:
    if symbol:
        return symbol
    bare = gene_id.split(".")[0] if gene_id.upper().startswith("ENSG") else gene_id
    return symbols.get(bare, gene_id)


def _sig(x: float | None, digits: int = 3) -> float | None:
    if x is None or math.isnan(x) or math.isinf(x):
        return None
    return float(f"{x:.{digits}g}")


# -- routes ------------------------------------------------------------------------------


def published(table: dict[str, Any], contrast: dict[str, Any], mirror=None) -> dict[str, Any]:
    """The authors' fold changes and p-values, as published."""
    header, rows = table["header"], table["rows"]
    numeric = _numeric_columns(header, rows[:SAMPLE_ROWS])
    gene = _gene_column(header, rows[:SAMPLE_ROWS], numeric)
    symbol = _symbol_column(header, gene)
    fold, p = header.index(contrast["fold"]), header.index(contrast["p"])
    mean = next((i for i, n in enumerate(header) if _key(n) in ("basemean", "aveexpr", "logcpm")), None)
    symbols = _symbols(mirror)
    points, skipped = [], 0
    for r in rows:
        f = _number(r[fold]) if fold < len(r) else None
        q = _number(r[p]) if p < len(r) else None
        if f is None or q is None or math.isnan(f) or math.isnan(q):
            skipped += 1
            continue
        gid = str(r[gene]).strip() if gene < len(r) and r[gene] is not None else ""
        sym = str(r[symbol]).strip() if symbol is not None and symbol < len(r) and r[symbol] is not None else ""
        m = _number(r[mean]) if mean is not None and mean < len(r) else None
        points.append([_label(gid, sym, symbols), gid, _sig(m, 4), round(f, 4), _sig(q)])
    return {"route": "published", "points": points, "skipped": skipped,
            "p_label": "adjusted p" if contrast["adjusted"] else "p, not adjusted",
            "mean_label": header[mean] if mean is not None else "",
            "method": f"Published results: {contrast['fold']}, {contrast['p']}. Not recomputed."}


def deseq2(table: dict[str, Any], prof: dict[str, Any], field: str, reference: str, comparison: str,
           covariate: str = "", mirror=None, reference_columns: list[str] | None = None,
           comparison_columns: list[str] | None = None) -> dict[str, Any]:
    """DESeq2 on the table's raw counts: comparison against reference.

    Groups come from a sample variable (field, two of its values), or, when
    the columns name no sample, from the columns chosen for each group."""
    import numpy as np

    columns = prof["columns"]
    if reference_columns or comparison_columns:
        ref = [c for c in columns if c["column"] in (reference_columns or [])]
        comp = [c for c in columns if c["column"] in (comparison_columns or [])]
        if {c["column"] for c in ref} & {c["column"] for c in comp}:
            raise DeError("A column in both groups.")
        field, covariate = "columns", ""
        reference = reference or ", ".join(c["column"] for c in ref)
        comparison = comparison or ", ".join(c["column"] for c in comp)
    else:
        ref = [c for c in columns if c["context"].get(field) == reference]
        comp = [c for c in columns if c["context"].get(field) == comparison]
    if len(ref) < MIN_PER_GROUP or len(comp) < MIN_PER_GROUP:
        raise DeError(f"{MIN_PER_GROUP} samples minimum per group: {reference} {len(ref)}, "
                      f"{comparison} {len(comp)}.")
    chosen = ref + comp
    levels = ["reference"] * len(ref) + ["comparison"] * len(comp)
    meta: dict[str, list[str]] = {"condition": levels}
    design, shown = "~condition", "~condition"
    if covariate:
        values = [c["context"].get(covariate, "") for c in chosen]
        if not all(values):
            raise DeError(f"{covariate}: not given for every sample.")
        codes = {v: f"c{i}" for i, v in enumerate(sorted(set(values)))}
        meta["covariate"] = [codes[v] for v in values]
        design, shown = "~covariate + condition", f"~{covariate} + condition"
        dummies = np.array([[1.0] + [float(meta["covariate"][k] == code) for code in sorted(codes.values())[1:]]
                            + [float(levels[k] == "comparison")] for k in range(len(chosen))])
        if np.linalg.matrix_rank(dummies) < dummies.shape[1]:
            raise DeError(f"{covariate} confounded with the groups: design not estimable.")
        if len(chosen) <= dummies.shape[1]:
            raise DeError("No residual degrees of freedom: more samples required.")

    header, rows = table["header"], table["rows"]
    gene = _gene_column(header, rows[:SAMPLE_ROWS], [c["index"] for c in columns])
    symbol = _symbol_column(header, gene)
    # Every gene goes in, all-zero ones too: DESeq2's independent filtering
    # takes its thresholds over all of them, so dropping any shifts padj.
    ids, syms, matrix, dropped, seen = [], [], [], 0, {}
    for r in rows:
        values = [_number(r[c["index"]]) if c["index"] < len(r) else None for c in chosen]
        if any(v is None or math.isnan(v) or v < 0 for v in values):
            dropped += 1
            continue
        gid = str(r[gene]).strip() if gene < len(r) and r[gene] is not None else ""
        n = seen.get(gid, 0)
        seen[gid] = n + 1
        ids.append(gid if n == 0 else f"{gid}#{n + 1}")
        syms.append(str(r[symbol]).strip() if symbol is not None and symbol < len(r) and r[symbol] else "")
        matrix.append([int(round(v)) for v in values])
    if len(matrix) < 100:
        raise DeError(f"{len(matrix)} genes with complete counts: too few for DESeq2.")

    import warnings

    import pandas as pd
    import pydeseq2
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.default_inference import DefaultInference
    from pydeseq2.ds import DeseqStats

    names = [c["sample"] or c["column"] for c in chosen]
    counts = pd.DataFrame(np.array(matrix, dtype=np.int64).T, index=names, columns=[f"g{i}" for i in range(len(ids))])
    metadata = pd.DataFrame(meta, index=names)
    # One worker: joblib then runs in this process and starts none, which
    # the packaged app (one window process) needs.
    inference = DefaultInference(n_cpus=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dds = DeseqDataSet(counts=counts, metadata=metadata, design=design, inference=inference, quiet=True)
        dds.deseq2()
        stats = DeseqStats(dds, contrast=["condition", "comparison", "reference"], inference=inference, quiet=True)
        stats.summary()
    result = stats.results_df
    symbols = _symbols(mirror)
    points, filtered = [], 0
    for i, (base, lfc, se, p, q) in enumerate(zip(result["baseMean"], result["log2FoldChange"], result["lfcSE"],
                                                  result["pvalue"], result["padj"])):
        if q is None or (isinstance(q, float) and math.isnan(q)) or lfc is None or math.isnan(lfc):
            filtered += 1
            continue
        points.append([_label(ids[i], syms[i], symbols), ids[i], _sig(float(base), 4), round(float(lfc), 4),
                       _sig(float(q)), _sig(float(se)), _sig(float(p))])
    return {"route": "deseq2", "points": points, "filtered": filtered, "dropped": dropped,
            "duplicates": sum(n - 1 for n in seen.values() if n > 1),
            "p_label": "adjusted p", "mean_label": "baseMean",
            "groups": {"field": field,
                       "reference": {"value": reference, "samples": [[c["sample"], c["title"] or c["column"]] for c in ref]},
                       "comparison": {"value": comparison, "samples": [[c["sample"], c["title"] or c["column"]] for c in comp]}},
            "design": shown,
            "method": (f"DESeq2 (PyDESeq2 {pydeseq2.__version__}): Wald test, Benjamini-Hochberg adjustment, "
                       f"Cook's distance and independent filtering, DESeq2 defaults. Design {shown}. "
                       f"log2 fold change: {comparison} over {reference}.")}


def run(found: dict[str, Any], url: str, sheet: str, live: Live, mirror=None, route: str = "",
        contrast: str = "", field: str = "", reference: str = "", comparison: str = "",
        covariate: str = "", reference_columns: list[str] | None = None,
        comparison_columns: list[str] | None = None) -> dict[str, Any]:
    """Volcano data for one table, by one route; cached by its inputs."""
    from importlib.metadata import version

    chosen = next((t for t in tables(found) if t["url"] == url), None)
    if chosen is None:
        raise DeError("Table not in this series.")
    key = json.dumps([RESULT_VERSION, url, sheet, route, contrast, field, reference, comparison, covariate,
                      sorted(reference_columns or []), sorted(comparison_columns or []),
                      version("pydeseq2") if route == "deseq2" else ""])
    store = _cache_dir(live, "geo-de") / f"{hashlib.sha1(key.encode()).hexdigest()[:20]}.json"
    if store.exists():
        try:
            return json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    path = download(url, live)
    table = next((t for t in read(path, chosen["name"]) if t["sheet"] == sheet), None)
    if table is None:
        raise DeError(f"No sheet {sheet} in {chosen['name']}.")
    prof = profile(table, found["samples"])
    if route == "published":
        picked = next((c for c in prof["contrasts"] if c["fold"] == contrast), None)
        if picked is None:
            raise DeError("No fold-change column of that name.")
        result = published(table, picked, mirror)
    elif route == "deseq2":
        if "deseq2" not in prof["routes"]:
            raise DeError(prof.get("reason") or "Not a raw count table.")
        result = deseq2(table, prof, field, reference, comparison, covariate, mirror,
                        reference_columns, comparison_columns)
    else:
        raise DeError(f"No route {route}.")
    result.update(file=chosen["name"], url=url, sheet=sheet, accession=found.get("accession", ""))
    temporary = store.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    os.replace(temporary, store)
    return result


def inspect(found: dict[str, Any], url: str, live: Live) -> dict[str, Any]:
    """Every table in one file, profiled."""
    chosen = next((t for t in tables(found) if t["url"] == url), None)
    if chosen is None:
        raise DeError("Table not in this series.")
    path = download(url, live)
    out = []
    for table in read(path, chosen["name"]):
        prof = profile(table, found["samples"])
        out.append({"sheet": table["sheet"], **prof})
    return {"file": chosen["name"], "url": url, "tables": out}
