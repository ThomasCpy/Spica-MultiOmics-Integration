"""The local mirror: the releases on this machine, and their location.

Spica never fetches at report time, so a record is only as good as its
mirror. `data/mirror.json` states what the mirror holds:

    {
      "mirror_version": "1",
      "sources": {
        "hgnc": {
          "label": "HGNC",
          "version": "2026-09-01",
          "retrieved": "2026-10-20",
          "license": "CC0 1.0",
          "files": {"complete_set": "hgnc/hgnc_complete_set.txt"}
        }
      }
    }

`version` and `retrieved` go into the provenance of each value, so they are
required. A mirror without its release cannot give a sourced record. The
sources that depend on it then report `failed`; they do not guess.

Mirrors are large and often live on another drive. The SPICA_DATA_DIR
environment variable moves the location. `spica/paths.py` gives the default
location, which differs between a source checkout and the built exe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from spica.paths import data_dir
from spica.record import Provenance

MANIFEST_NAME = "mirror.json"


@dataclass(frozen=True)
class MirrorEntry:
    """One source's presence in the mirror."""

    key: str
    label: str
    version: str
    retrieved: str
    root: Path
    files: dict[str, str] = field(default_factory=dict)
    license: str = ""
    extra: dict[str, str] = field(default_factory=dict)  # source-specific keys

    def path(self, name: str) -> Path:
        """Absolute path of a declared file. Raises KeyError if the manifest
        never mentioned it, which is a manifest bug, not missing data."""
        return self.root / self.files[name]

    def missing_files(self) -> list[str]:
        """Declared files absent from disk, as written in the
        manifest so the message points at something the user can go and fix."""
        return sorted(
            relative
            for relative in self.files.values()
            if not (self.root / relative).exists()
        )

    def provenance(self, locator: str = "") -> Provenance:
        return Provenance(
            source=self.label,
            version=self.version,
            retrieved=self.retrieved,
            locator=locator,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "version": self.version,
            "retrieved": self.retrieved,
            "license": self.license,
        }


@dataclass(frozen=True)
class Mirror:
    """What `data/mirror.json` says, or why it could not be read."""

    root: Path
    entries: dict[str, MirrorEntry] = field(default_factory=dict)
    problem: str = ""

    @property
    def present(self) -> bool:
        return not self.problem

    def entry(self, key: str) -> MirrorEntry | None:
        return self.entries.get(key)

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "present": self.present,
            "problem": self.problem,
            "sources": [entry.to_dict() for entry in self.entries.values()],
        }

    @classmethod
    def load(cls, root: Path | str | None = None) -> "Mirror":
        """Read the manifest. Never raises: a mirror that cannot be read is a
        state the record reports, not an error that stops a build."""
        root = data_dir() if root is None else Path(root)
        manifest = root / MANIFEST_NAME

        if not manifest.exists():
            return cls(root=root, problem=f"No mirror manifest at {manifest}")
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return cls(root=root, problem=f"{manifest} not read: {exc}")

        if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
            return cls(root=root, problem=f"{manifest} has no sources object")

        entries: dict[str, MirrorEntry] = {}
        for key, body in sorted(raw["sources"].items()):
            if not isinstance(body, dict):
                continue
            version = str(body.get("version", "")).strip()
            retrieved = str(body.get("retrieved", "")).strip()
            if not version or not retrieved:
                # Deliberately dropped rather than defaulted: a value whose
                # provenance says "version unknown" is not a sourced value.
                continue
            files = {
                str(name): str(relative)
                for name, relative in (body.get("files") or {}).items()
            }
            reserved = {"label", "version", "retrieved", "files", "license"}
            entries[key] = MirrorEntry(
                key=key,
                label=str(body.get("label", key.upper())),
                version=version,
                retrieved=retrieved,
                root=root,
                files=files,
                license=str(body.get("license", "")),
                # Anything else the adapter needs to read its own files, such
                # as the assembly an Ensembl export was taken against.
                extra={
                    str(name): str(value)
                    for name, value in body.items()
                    if name not in reserved
                },
            )
        return cls(root=root, entries=entries)
