"""A watch: a topic, checked again and again, with each check kept.

Each check is one line appended to `data/intel/<slug>.jsonl`. Nothing is
rewritten, so the file is the history: what was found on which day, with
which terms, from which source, and what was unreachable. "New" comes from
that history: an item is new if no earlier check of the same watch saw it.
A reader can verify this definition.

The first check of a watch marks nothing as new. All items are new the
first time, and that is the same as no new items.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from spica.intel import literature, patents, trials
from spica.intel.terms import Term, split, widen
from spica.live import Live

DIRNAME = "intel"
WINDOWS = (30, 90, 365, 1825)  # days; the screen offers these
DEFAULT_WINDOW = 90
#: What a check gathers; a check made before trials were added has none.
KINDS = ("papers", "patents", "trials")


def slug(topic: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return text[:60] or "watch"


@dataclass
class Watches:
    """The watches kept under one data directory."""

    root: Path

    @property
    def folder(self) -> Path:
        return Path(self.root) / DIRNAME

    def path(self, name: str) -> Path:
        return self.folder / f"{slug(name)}.jsonl"

    def runs(self, name: str) -> list[dict[str, Any]]:
        """Every check of a watch, oldest first. A torn last line is skipped."""
        path = self.path(name)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # an interrupted append costs that check, not the file
        return out

    def append(self, name: str, run: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.path(name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run, ensure_ascii=False) + "\n")

    def list(self) -> list[dict[str, Any]]:
        """Saved watches, most recently checked first."""
        if not self.folder.exists():
            return []
        out = []
        for path in self.folder.glob("*.jsonl"):
            runs = self.runs(path.stem)
            if not runs:
                continue
            last = view(runs)
            out.append({
                "slug": path.stem,
                "topic": last.get("topic", path.stem),
                "checked": last.get("at", ""),
                "checks": len(runs),
                "papers": (last.get("papers") or {}).get("total", 0),
                "patents": (last.get("patents") or {}).get("total", 0),
                "patents_state": (last.get("patents") or {}).get("state", ""),
                "trials": (last.get("trials") or {}).get("total", 0),
                "new": last["new"],
            })
        out.sort(key=lambda w: w["checked"], reverse=True)
        return out

    def latest(self, name: str) -> dict[str, Any] | None:
        runs = self.runs(name)
        return view(runs) if runs else None


def view(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The last check, with every item marked new or not against the rest."""
    last = dict(runs[-1])
    earlier: set[str] = set()
    for run in runs[:-1]:
        for kind in KINDS:
            earlier.update(item.get("id", "") for item in
                           (run.get(kind) or {}).get("items", []))
    first = len(runs) == 1
    counts = {}
    for kind in KINDS:
        block = dict(last.get(kind) or {})
        # A source a watch had never asked before (trials, for checks made
        # before they were added) is on its first check too: nothing new.
        fresh = first or not any(kind in run for run in runs[:-1])
        items = [dict(item, new=(not fresh and item.get("id") not in earlier))
                 for item in block.get("items", [])]
        block["items"] = items
        counts[kind] = sum(1 for item in items if item["new"])
        last[kind] = block
    last["first_check"] = first
    last["new"] = counts
    last["checks"] = len(runs)
    last["previous"] = runs[-2].get("at", "") if len(runs) > 1 else ""
    # New means "no earlier check saw it". If the terms or the window
    # changed, part of the new items comes from a wider search, not from new
    # publications. The screen must say so.
    if len(runs) > 1:
        before, now = runs[-2], runs[-1]
        texts = lambda run: sorted(t.get("text", "").lower() for t in run.get("terms", []))
        # The queries sent count too: when Spica learns to search better
        # (trials' isoform names), what is newly found is not newly done.
        last["search_changed"] = (texts(before) != texts(now)
                                  or (before.get("window") or {}).get("days")
                                  != (now.get("window") or {}).get("days")
                                  or before.get("queries") != now.get("queries"))
    else:
        last["search_changed"] = False
    return last


def run_watch(
    topic: str,
    live: Live,
    watches: Watches,
    credentials: patents.Credentials,
    days: int = DEFAULT_WINDOW,
    expand: bool = True,
    lookup: Callable[[str], dict[str, Any] | None] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Check a topic now, append the check, and return it marked up."""
    typed = split(topic)
    if not typed:
        return {"error": "No terms entered."}

    today = today or date.today()
    days = int(days) if int(days) > 0 else DEFAULT_WINDOW
    since = today - timedelta(days=days)
    terms: list[Term] = widen(typed, lookup) if (expand and lookup) else \
        [Term(text, "typed") for text in typed]
    texts = [term.text for term in terms]
    stamp = today.isoformat()

    papers = literature.search(live, texts, since, today, stamp)
    filed = patents.search(live, credentials, texts, since, today, stamp)
    registered = trials.search(live, texts, since, today, stamp)

    name = ", ".join(typed)
    run = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "topic": name,
        "terms": [term.to_dict() for term in terms],
        "window": {"days": days, "from": since.isoformat(), "to": today.isoformat()},
        "papers": {**papers.to_dict(), "label": literature.LABEL,
                   "facets": literature.facets(papers.items)},
        "patents": {**filed.to_dict(), "label": patents.LABEL,
                    "facets": patents.facets(filed.items)},
        "trials": {**registered.to_dict(), "label": trials.LABEL, "credit": trials.CREDIT,
                   "facets": trials.facets(registered.items)},
        "queries": {"trials": trials.expression(texts)},
    }
    watches.append(name, run)
    result = view(watches.runs(name))
    result["slug"] = slug(name)
    return result
