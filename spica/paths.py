"""File locations, for a source run and for the exe.

Two different questions. Bundling separates them.

`bundled()` is for files that ship *with* the program: the built interface.
A PyInstaller one-file build unpacks them into a temporary folder. The exe
deletes that folder on exit, so nothing there is writable.

`data_dir()` is for the mirror and the cache. They outlive each run and can
grow to gigabytes. The location is beside the exe when that is writable (a
portable Spica folder keeps its data with it). Otherwise it is the local app
data of the user, for example under Program Files.

`SPICA_DATA_DIR` overrides it in both cases.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Spica"


def frozen() -> bool:
    """True when running from a built exe rather than from source."""
    return getattr(sys, "frozen", False)


def bundled(*parts: str) -> Path:
    """A file that ships with the program, from wherever it is right now."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root.joinpath(*parts)


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Where the mirror and the fetch cache live."""
    override = os.environ.get("SPICA_DATA_DIR", "").strip()
    if override:
        return Path(override)

    if not frozen():
        return Path(__file__).resolve().parent.parent / "data"

    beside = Path(sys.executable).resolve().parent / "data"
    if _writable(beside):
        return beside

    # Installed somewhere read-only. Fall back to the usual per-user place.
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_NAME / "data"
