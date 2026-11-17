"""The regulators of the compared genes, shared and between them.

From the shared-regulators and directed-link pipelines of the integrator,
as one Compare panel. Two questions:

- **Transcription factors shared by two or more of the genes.** A shared
  regulator is only interesting when it is selective. A hub with thousands
  of targets is shared by almost any pair. Each shared regulator thus
  carries its target count, and the most selective ones come first.
- **Direct regulation between the genes.** Directed edges between the
  compared genes, with their type and their number of references.

OmniPath, with its `license=commercial` filter, so only records cleared for
commercial use are read. The data comes from the local mirror when it holds
OmniPath (`spica/omnipath.py`). Otherwise it comes from the service through
the live layer and its cache.
"""

from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream, OFF

OMNIPATH = "https://omnipathdb.org/interactions"
TF_DATASETS = "dorothea,collectri,tf_target"


def _rows(live: Live, **query: Any) -> list[dict[str, Any]]:
    params = {"genesymbols": 1, "license": "commercial", "format": "json", **query}
    try:
        payload = live.get_json("omnipath", f"{OMNIPATH}?{urllib.parse.urlencode(params)}").payload
    except NotFoundUpstream:
        return []
    return [row for row in payload or [] if isinstance(row, dict)]


def _effect(row: dict[str, Any]) -> str:
    up, down = row.get("is_stimulation"), row.get("is_inhibition")
    if up and down:
        return "both"
    return "activates" if up else "represses" if down else "unsigned"


class _Reader:
    """OmniPath's answers from the local copy when there is one, else the
    service: the same three questions either way."""

    def __init__(self, live: Live, mirror=None) -> None:
        from spica import omnipath

        self.live, self.mirror = live, mirror
        self.local = mirror is not None and omnipath.available(mirror)

    def regulating(self, symbol: str) -> list[dict[str, Any]]:
        from spica import omnipath

        if self.local:
            return omnipath.regulators_of(symbol, self.mirror)
        return _rows(self.live, targets=symbol, datasets=TF_DATASETS)

    def regulated(self, tf: str) -> list[dict[str, Any]]:
        from spica import omnipath

        if self.local:
            return omnipath.regulated_by(tf, self.mirror)
        return _rows(self.live, sources=tf, datasets=TF_DATASETS)

    def between(self, symbols: list[str]) -> list[dict[str, Any]]:
        from spica import omnipath

        if self.local:
            return [row for symbol in symbols
                    for row in omnipath.interactions_of(symbol, self.mirror)
                    + omnipath.regulated_by(symbol, self.mirror)
                    if row["source_genesymbol"] == symbol and row["target_genesymbol"] in symbols]
        return _rows(self.live, sources=",".join(symbols), targets=",".join(symbols),
                     fields="sources,references,type")

    @property
    def source(self) -> str:
        from spica import omnipath

        where = f"{omnipath.version(self.mirror)}, local copy" if self.local else "OmniPath"
        return f"{where}, records cleared for commercial use"


def single(symbol: str, live: Live, mirror=None) -> dict[str, Any]:
    """One gene's regulators, and the genes it regulates if it is a factor."""
    reader = _Reader(live, mirror)
    try:
        regulators = {str(r.get("source_genesymbol")): _effect(r) for r in reader.regulating(symbol)
                      if r.get("source_genesymbol")}
        targets = {str(r.get("target_genesymbol")): _effect(r) for r in reader.regulated(symbol)
                   if r.get("target_genesymbol")}
    except LiveError as exc:
        state = "offline" if OFF in str(exc) else "failed"
        return {"state": state, "error": f"OmniPath: {exc}"}
    return {"state": "ok", "gene": symbol,
            "regulators": dict(sorted(regulators.items())),
            "targets": dict(sorted(targets.items())), "source": reader.source}


def compare(symbols: list[str], live: Live, mirror=None) -> dict[str, Any]:
    symbols = [s for s in dict.fromkeys(s.strip() for s in symbols) if s]
    if len(symbols) < 2:
        return {"error": "Shared regulation needs at least two genes."}
    reader = _Reader(live, mirror)
    regulating, regulated = reader.regulating, reader.regulated

    try:
        per_gene: dict[str, dict[str, str]] = {}
        for symbol in symbols:
            regulators: dict[str, str] = {}
            for row in regulating(symbol):
                tf = str(row.get("source_genesymbol") or "")
                if tf:
                    regulators.setdefault(tf, _effect(row))
            per_gene[symbol] = regulators

        shared_names = sorted({tf for regs in per_gene.values() for tf in regs
                               if sum(tf in r for r in per_gene.values()) >= 2})

        def targets(tf: str) -> tuple[str, int]:
            rows = regulated(tf.split("_")[0])
            return tf, len({str(r.get("target_genesymbol")) for r in rows})

        with ThreadPoolExecutor(max_workers=6) as pool:
            reach = dict(pool.map(targets, shared_names))

        shared = [{"tf": tf, "targets": reach.get(tf, 0),
                   "genes": {s: per_gene[s][tf] for s in symbols if tf in per_gene[s]}}
                  for tf in shared_names]
        shared.sort(key=lambda item: (item["targets"] or 10**9, item["tf"]))

        links = []
        for row in reader.between(symbols):
            source, target = row.get("source_genesymbol"), row.get("target_genesymbol")
            if source == target or source not in symbols or target not in symbols:
                continue
            refs = row.get("references") or []
            refs = refs if isinstance(refs, list) else str(refs).split(";")
            references = {str(r).split(":")[-1] for r in refs if r}
            databases = row.get("sources") or []
            databases = databases if isinstance(databases, list) else str(databases).split(";")
            links.append({"source": source, "target": target, "effect": _effect(row),
                          "type": str(row.get("type") or "").replace("_", " "),
                          "references": len(references),
                          "databases": ", ".join(sorted({str(d) for d in databases if d}))})
    except LiveError as exc:
        state = "offline" if OFF in str(exc) else "failed"
        return {"state": state, "error": f"OmniPath: {exc}"}
    return {
        "state": "ok",
        "genes": symbols,
        "regulators": {s: sorted(per_gene[s]) for s in symbols},
        "shared": shared,
        "links": links,
        "source": reader.source,
    }
