"""The user's choices, kept between runs.

A small JSON file beside the mirror. Only choices live here (the model,
other model folders, the sources that the agents can read), never derived
data. A deleted file thus loses preferences and nothing else.

Writes are atomic: the file is replaced, not edited in place. An
interrupted save thus cannot leave a half-written settings file that stops
the app at start.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from spica.paths import data_dir

FILENAME = "settings.json"

DEFAULTS: dict[str, Any] = {
    # Absolute path to a .gguf. Empty means "use the best one found".
    "model": "",
    # Extra directories to look for models in, so a 22 GB file kept on
    # another drive never has to be copied into the mirror.
    "model_dirs": [],
    # Source keys the agents may read. Empty means all of them.
    "tools": [],
    # The embedding model used to index the user's documents.
    "embed_model": "",
    # The user's own EPO Open Patent Services credentials, for the patent
    # side of competitive intelligence. Free to register; never sent
    # anywhere but ops.epo.org, and never handed back to the interface.
    "epo_key": "",
    "epo_secret": "",
    # Whether Spica may use the network on its own: fill what the mirror
    # lacks from the sources' public APIs, draw the views beside the record,
    # check competitive intelligence. Off by default: a client's Spica reads
    # its mirror and nothing else until someone decides otherwise. Updating
    # the mirror is a separate, explicit action and does not depend on it.
    "online": False,
    # Appearance: "light", "dark", or "system" to follow Windows.
    "theme": "light",
    # AI mode: let the model reason before it plans and writes (slower,
    # usually better), or answer straight away. The Ask screen switches it.
    "thinking": True,
    # The main menu: "sidebar" (the default) or "cards", the floating cards
    # on a home screen with a slim bar inside each screen.
    "menu": "sidebar",
}


def path() -> Path:
    return data_dir() / FILENAME


def load() -> dict[str, Any]:
    """The saved settings, with defaults filled in. Never raises."""
    settings = dict(DEFAULTS)
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in settings and isinstance(value, type(settings[key])):
                settings[key] = value
    return settings


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """Merge `changes` into the saved settings and write them out."""
    settings = load()
    for key, value in changes.items():
        if key in DEFAULTS:
            settings[key] = value

    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(settings, indent=1), encoding="utf-8")
        os.replace(temporary, target)  # atomic: no half-written settings file
    except OSError:
        pass  # a preference that cannot be saved is not worth failing over
    return settings
