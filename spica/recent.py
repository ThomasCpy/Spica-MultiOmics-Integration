"""The reports built on this machine, most recent first, for the sidebar.

A navigation aid, not data: it remembers which genes were looked at and
when, so the sidebar can offer them again. Kept beside the mirror like the
settings, written atomically, and capped, because it is a history list and
not a record of anything.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from spica.paths import data_dir

FILENAME = "recent.json"
KEEP = 50


def load() -> list[dict[str, Any]]:
    try:
        stored = json.loads((data_dir() / FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in stored if isinstance(item, dict) and item.get("symbol")] \
        if isinstance(stored, list) else []


def add(symbol: str, when: date | None = None) -> list[dict[str, Any]]:
    """Put a gene at the top, once."""
    entries = [item for item in load() if item.get("symbol") != symbol]
    entries.insert(0, {"symbol": symbol, "date": (when or date.today()).isoformat()})
    entries = entries[:KEEP]
    target = data_dir() / FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass  # a history that cannot be saved is not worth failing a report over
    return entries
