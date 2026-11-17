"""The benchmark: rank of known targets against undrugged genes under the weights.

For one modality, the positives are the targets with an approved drug of
that modality (Open Targets tractability, "Approved Drug"). The decoys are
protein-coding genes with no drug of any modality in the clinic. Both get
scores from the user's weights. The benchmark measures how well the score
separates them: the area under the ROC curve (0.5 is chance, 1 is perfect),
the curve, the positives at the top of the list, and each criterion alone.

Two rules keep it honest:

- Criteria that encode the label are excluded. Clinical precedent is the
  label, and the Open Targets association score counts drug evidence. Each
  such criterion has a flag (`leaks` in `spica/ranking.py`), and the result
  names what was dropped.
- A fixed hash selects the decoys, not a random draw, so a run repeats
  exactly. The result gives data coverage per group: approved targets have
  more studies, and a criterion that only rewards study count shows it.

The benchmark reads the mirror only. The gene sets come from the Open
Targets targets file, read once per release and kept in the cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from spica import ranking
from spica.metrics import _ranks
from spica.mirror import Mirror
from spica.paths import data_dir

MODALITIES = {"antibody": ("AB", "Antibody"), "small_molecule": ("SM", "Small molecule")}
CLINICAL = ("Approved Drug", "Advanced Clinical", "Phase 1 Clinical")
#: Decoys per positive, and the most positives a run takes (sampled by the
#: same hash when there are more).
RATIO = 3
MOST = 200
SEED = "spica-benchmark-1"


def _folder() -> Path:
    return data_dir() / "benchmarks"


def tractability(mirror: Mirror) -> dict[str, dict[str, Any]]:
    """Ensembl ID to symbol and the tractability buckets that are true, by
    modality, for every target in the Open Targets mirror. One pass over the
    file per release; the answer is kept in the cache."""
    entry = mirror.entry("opentargets")
    if entry is None or entry.missing_files():
        raise ValueError("The benchmark needs Open Targets in the local data: update it in "
                         "Settings.")
    store = data_dir() / "cache" / "benchmark" / f"tractability-{entry.version}.json"
    try:
        return json.loads(store.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    found: dict[str, dict[str, Any]] = {}
    gene = re.compile(r'"ensemblId"\s*:\s*"([^"]+)"')
    symbol = re.compile(r'"approvedSymbol"\s*:\s*"([^"]*)"')
    with open(entry.path("targets"), encoding="utf-8") as handle:
        for line in handle:
            at = line.find('"tractability"')
            matched = gene.search(line, 0, 300)
            if not matched:
                continue
            buckets: dict[str, list[str]] = {}
            if at >= 0:
                start = line.find("[", at)
                depth, end = 0, start
                for end in range(start, len(line)):
                    if line[end] == "[":
                        depth += 1
                    elif line[end] == "]":
                        depth -= 1
                        if depth == 0:
                            break
                try:
                    for item in json.loads(line[start:end + 1]):
                        if item.get("value"):
                            buckets.setdefault(item["modality"], []).append(item["label"])
                except (ValueError, TypeError, KeyError):
                    pass
            name = symbol.search(line, 0, 400)
            found[matched.group(1)] = {"symbol": name.group(1) if name else "", "buckets": buckets}
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(found), encoding="utf-8")
    return found


def _order(key: str) -> str:
    return hashlib.sha1(f"{SEED}:{key}".encode()).hexdigest()


def sets(modality: str, mirror: Mirror) -> dict[str, list[str]]:
    """Positives and decoys as Ensembl IDs, the same every run."""
    code, _ = MODALITIES[modality]
    targets = tractability(mirror)
    coding = _protein_coding(mirror)
    positives = sorted((g for g, t in targets.items()
                        if "Approved Drug" in t["buckets"].get(code, []) and g in coding),
                       key=_order)[:MOST]
    clinical = {g for g, t in targets.items()
                if any(label in CLINICAL for labels in t["buckets"].values() for label in labels)}
    pool = sorted((g for g in targets if g in coding and g not in clinical), key=_order)
    return {"positives": positives, "decoys": pool[:RATIO * len(positives)]}


def _protein_coding(mirror: Mirror) -> set[str]:
    from spica.sources.hgnc import PROTEIN_CODING, table

    entry = mirror.entry("hgnc")
    if entry is None or entry.missing_files():
        raise ValueError("The benchmark needs HGNC in the local data.")
    return {row["ensembl_gene_id"] for row in table(entry.path("complete_set"))["rows"]
            if row["locus_type"] == PROTEIN_CODING and row["ensembl_gene_id"]}


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Area under the ROC curve, as the Mann-Whitney statistic, ties halved."""
    if not positives or not negatives:
        return None
    ranks = _ranks(positives + negatives)
    total = sum(ranks[:len(positives)])
    n_pos, n_neg = len(positives), len(negatives)
    return round((total - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


def roc(scored: list[tuple[float, bool]]) -> list[list[float]]:
    """(false positive rate, true positive rate) at each distinct threshold."""
    positives = sum(1 for _, label in scored if label)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return []
    points, tp, fp = [[0.0, 0.0]], 0, 0
    ordered = sorted(scored, key=lambda item: -item[0])
    for index, (value, label) in enumerate(ordered):
        tp += label
        fp += not label
        if index + 1 == len(ordered) or ordered[index + 1][0] != value:
            points.append([round(fp / negatives, 4), round(tp / positives, 4)])
    return points


def run(modality: str, weights: dict[str, float], mirror: Mirror | None = None,
        progress: Callable[[int, int], None] | None = None,
        missing: str = "skip") -> dict[str, Any]:
    from spica.build import build_record
    from spica.live import Live

    if modality not in MODALITIES:
        return {"error": f"No benchmark for {modality}: antibody or small_molecule."}
    mirror = Mirror.load() if mirror is None else mirror
    live = Live(mirror.root, allowed=False)  # the benchmark never reaches the network
    try:
        chosen = sets(modality, mirror)
    except ValueError as exc:
        return {"error": str(exc)}
    dropped = [c.key for c in ranking.CRITERIA if modality in c.leaks and weights.get(c.key)]
    used = {key: (0.0 if key in dropped else float(value)) for key, value in weights.items()}
    if not any(used.values()):
        return {"error": "Every weighted criterion carries the label for this modality; weigh "
                         "at least one other criterion."}
    genes = [(g, True) for g in chosen["positives"]] + [(g, False) for g in chosen["decoys"]]
    context = ranking.Context(mirror=mirror)
    rows, started = [], time.time()
    for done, (ensembl_id, label) in enumerate(genes, start=1):
        record = build_record(ensembl_id, mirror, live)
        if record.resolution.resolved:
            row = ranking.score(record, used, context, missing)
            row["positive"] = label
            rows.append(row)
        if progress:
            progress(done, len(genes))
    scored = [row for row in rows if row["score"] is not None]
    scored.sort(key=lambda row: (-row["score"], row["symbol"]))
    for position, row in enumerate(scored, start=1):
        row["rank"] = position
    pos = [row["score"] for row in scored if row["positive"]]
    neg = [row["score"] for row in scored if not row["positive"]]
    top = scored[:len(pos)]
    per_criterion = []
    for criterion in ranking.CRITERIA:
        p = [row["parts"][criterion.key]["score"] for row in rows if row["positive"]
             and row["parts"][criterion.key]["score"] is not None]
        n = [row["parts"][criterion.key]["score"] for row in rows if not row["positive"]
             and row["parts"][criterion.key]["score"] is not None]
        per_criterion.append({"key": criterion.key, "label": criterion.label,
                              "auc": auc(p, n), "positives": len(p), "decoys": len(n),
                              "weight": used.get(criterion.key, 0.0),
                              "dropped": criterion.key in dropped,
                              "leaks": modality in criterion.leaks})

    def coverage(label: bool) -> float | None:
        values = [row["coverage"] for row in rows if row["positive"] == label and row["coverage"] is not None]
        return round(sum(values) / len(values), 3) if values else None

    result = {
        "modality": modality, "label": MODALITIES[modality][1],
        "when": time.strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - started, 1),
        "weights": used, "scale": ranking.SCALE, "dropped": dropped, "missing": missing,
        "positives": len(pos), "decoys": len(neg),
        "auc": auc(pos, neg),
        "roc": roc([(row["score"], row["positive"]) for row in scored]),
        "top": {"size": len(top), "positives": sum(row["positive"] for row in top)},
        "coverage": {"positives": coverage(True), "decoys": coverage(False)},
        "criteria": per_criterion,
        "rows": [{"rank": row["rank"], "symbol": row["symbol"], "score": row["score"],
                  "coverage": row["coverage"], "positive": row["positive"]} for row in scored],
        "versions": {key: f"{entry.label} {entry.version}" for key, entry in mirror.entries.items()},
        "sets": "Positives: targets with an approved " + MODALITIES[modality][1].lower()
                + " drug (Open Targets tractability). Decoys: protein-coding genes with no drug "
                  "of any modality in the clinic, drawn by a fixed hash, "
                + f"{RATIO} per positive.",
    }
    _folder().mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (_folder() / f"{modality}-{stamp}.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def latest(modality: str = "") -> dict[str, Any] | None:
    """The newest saved result, for one modality or any."""
    if not _folder().exists():
        return None
    found = sorted(_folder().glob(f"{modality or '*'}-*.json"))
    if not found:
        return None
    try:
        return ranking.upgraded(json.loads(found[-1].read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
