"""The digest as the app and AI mode see it: status, latest, search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spica.digest import genes as gene_tags
from spica.digest import search as finder
from spica.digest import speech
from spica.digest.store import Store
from spica.mirror import Mirror
from spica.paths import data_dir

KINDS = {"podcast": "transcripts", "notes": "show notes", "title": "titles only",
         "trial": "trials", "paper": "papers"}


class Digest:
    def __init__(self, root: Path | None = None, mirror: Mirror | None = None) -> None:
        self.root = Path(root or data_dir())
        self.store = Store(self.root)
        self.mirror = mirror if mirror is not None else Mirror.load()

    def watch_runs(self) -> list[dict[str, Any]]:
        """Every check of every watch, for the trials and papers they found."""
        from spica.intel import Watches

        watches = Watches(self.root)
        runs = []
        for path in sorted(watches.folder.glob("*.jsonl")) if watches.folder.exists() else []:
            runs += watches.runs(path.stem)
        return runs

    def watched(self) -> list[str]:
        """The names the watches follow, to prime transcription."""
        names: list[str] = []
        for run in self.watch_runs()[-50:]:
            for term in run.get("terms", []):
                text = term.get("text", "")
                if text and len(text) <= 30 and text not in names:
                    names.append(text)
        return names[:60]

    def vocab(self) -> dict[str, str]:
        return gene_tags.vocabulary(self.mirror)

    def index(self) -> finder.Index:
        runs = self.watch_runs()
        signature = f"{self.store.signature()}|{len(runs)}|{sum(len(str(r.get('at'))) for r in runs)}"
        return finder.index(self.store, runs, self.vocab(), signature)

    def search(self, query: str, kinds: list[str] | None = None, gene: str = "", since: str = "",
               limit: int = 25, offset: int = 0) -> dict[str, Any]:
        from spica.digest import meaning

        found = self.index()
        vectors = None
        if query.strip() and meaning.available():
            try:
                vectors = meaning.scores(found.items, query, self.root)
            except Exception:
                vectors = None  # a model that will not load leaves keyword search
        result = finder.search(found, query, self.vocab(), kinds, gene, since, limit, offset, vectors)
        result["meaning"] = bool(vectors)
        return result

    def embed(self, progress=None) -> int:
        """Vectors for passages that have none, when a model is installed."""
        from spica.digest import meaning

        if not meaning.available():
            return 0
        return meaning.refresh(self.index().items, self.root, progress=progress)

    def status(self) -> dict[str, Any]:
        episodes = self.store.episodes()
        by_feed: dict[str, dict[str, Any]] = {}
        for episode in episodes.values():
            entry = by_feed.setdefault(episode.get("feed", ""), {"episodes": 0, "transcribed": 0,
                                                                 "reserved": "", "latest": ""})
            entry["episodes"] += 1
            entry["transcribed"] += episode.get("status") == "transcribed"
            entry["reserved"] = episode.get("reserved") or entry["reserved"]
            entry["latest"] = max(entry["latest"], episode.get("date", ""))
        feeds = [{**feed.to_dict(), "on": on, **by_feed.get(feed.key, {"episodes": 0, "transcribed": 0,
                                                                         "reserved": "", "latest": ""})}
                 for feed, on in self.store.feeds()]
        from spica.digest import update as digest_update

        return {"feeds": feeds, "speech": speech.status(), "per_feed": self.store.settings()["per_feed"],
                "backlog": digest_update.backlog(self.store),
                "last_update": self.store.last_update(), "episodes": len(episodes),
                "transcribed": sum(1 for e in episodes.values() if e.get("status") == "transcribed")}

    def latest(self, kinds: list[str] | None = None, since: str = "", limit: int = 60,
               offset: int = 0) -> dict[str, Any]:
        """Newest first, with no query: what arrived."""
        found = self.index()
        rows, seen = [], set()
        for passage in found.items:
            if kinds and passage.kind not in kinds:
                continue
            if since and passage.date < since:
                continue
            key = passage.episode or passage.id  # one line per episode, not per minute
            if key in seen:
                continue
            seen.add(key)
            genes = sorted({g for p in found.items if (p.episode or p.id) == key for g in p.genes}) \
                if passage.episode else passage.genes
            rows.append({**passage.to_dict(), "genes": genes,
                         "snippet": finder.snippet(passage.text, [])})
        return {"total": len(rows), "offset": offset, "results": rows[offset:offset + limit]}
