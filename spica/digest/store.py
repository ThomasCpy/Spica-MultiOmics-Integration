"""What the digest has gathered, kept the way watches are kept: appended.

`data/digest/events.jsonl` is the history, one line per event, never
rewritten: an episode seen (with everything its feed said about it), a
transcript made, an episode skipped and why, an update run. The state of
any episode is those lines folded in order, so the file can always say
what was known on which day. Transcripts are files of their own, written
once, under `data/digest/transcripts/`; audio is never kept.

Which feeds are on, and the feeds the user added, are settings, kept in
`data/digest/sources.json`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from spica.digest.catalogue import BY_KEY, CATALOGUE, Feed
from spica.paths import data_dir

#: How many of each feed's newest episodes an update transcribes, unless set.
PER_FEED = 3


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.folder = Path(root or data_dir()) / "digest"

    # -- sources ---------------------------------------------------------------------------

    def _sources_path(self) -> Path:
        return self.folder / "sources.json"

    def settings(self) -> dict[str, Any]:
        try:
            found = json.loads(self._sources_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            found = {}
        return {"enabled": found.get("enabled", {}), "added": found.get("added", []),
                "per_feed": int(found.get("per_feed", PER_FEED))}

    def save_settings(self, chosen: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self._sources_path().with_suffix(".tmp")
        temporary.write_text(json.dumps(chosen, indent=1), encoding="utf-8")
        os.replace(temporary, self._sources_path())

    def feeds(self) -> list[tuple[Feed, bool]]:
        """Every feed, catalogue first, with whether it is on (catalogue
        feeds are on until turned off)."""
        chosen = self.settings()
        added = [Feed(**{**feed, "added": True}) for feed in chosen["added"]]
        return [(feed, bool(chosen["enabled"].get(feed.key, True))) for feed in (*CATALOGUE, *added)]

    def feed(self, key: str) -> Feed | None:
        return next((feed for feed, _ in self.feeds() if feed.key == key), BY_KEY.get(key))

    # -- events ----------------------------------------------------------------------------

    def _events_path(self) -> Path:
        return self.folder / "events.jsonl"

    def append(self, event: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        event = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
        with self._events_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self._events_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line costs that event, not the file
        return out

    def episodes(self) -> dict[str, dict[str, Any]]:
        """Every episode's current state, folded from the events."""
        state: dict[str, dict[str, Any]] = {}
        for event in self.events():
            kind, ident = event.get("event"), event.get("id")
            if kind == "seen" and ident:
                state.setdefault(ident, {}).update(
                    {k: v for k, v in event.items() if k not in ("event", "at")},
                    first_seen=state.get(ident, {}).get("first_seen", event.get("at", "")))
            elif kind in ("transcribed", "skipped") and ident in state:
                state[ident]["status"] = kind
                state[ident]["status_note"] = event.get("engine") or event.get("reason", "")
                state[ident]["status_at"] = event.get("at", "")
                state[ident]["permanent"] = bool(event.get("permanent"))
        return state

    def last_update(self) -> dict[str, Any] | None:
        updates = [event for event in self.events() if event.get("event") == "update"]
        return updates[-1] if updates else None

    # -- transcripts -----------------------------------------------------------------------

    def transcript_path(self, ident: str) -> Path:
        return self.folder / "transcripts" / f"{ident}.json"

    def write_transcript(self, ident: str, segments: list[list], engine: str) -> None:
        path = self.transcript_path(ident)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"id": ident, "engine": engine, "segments": segments}),
                             encoding="utf-8")
        os.replace(temporary, path)

    def transcript(self, ident: str) -> dict[str, Any] | None:
        try:
            return json.loads(self.transcript_path(ident).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def signature(self) -> str:
        """Changes whenever anything searchable changes."""
        parts = []
        for path in (self._events_path(), self.folder / "transcripts"):
            try:
                stat = path.stat()
                parts.append(f"{stat.st_size}:{stat.st_mtime_ns}")
            except OSError:
                parts.append("-")
        return "|".join(parts)
