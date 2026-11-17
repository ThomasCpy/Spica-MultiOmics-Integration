"""From the typed text to the search terms.

The user types a topic as terms separated by commas: `CLDN18.2,
zolbetuximab`. Each term that names a gene gets the HGNC symbol, approved
name, aliases and previous symbols of that gene. Literature and patent
drafting use all of them: a 2014 filing can say only "SFTPJ".

Each term keeps its origin, so the screen can show what was searched and
why. Nothing is added silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Aliases shorter than this match too much to be worth searching: a
#: three-letter alias is as often an abbreviation for something else.
MIN_ALIAS = 4
#: A widened gene contributes at most this many names, so one gene with
#: twenty historical aliases does not drown the user's own terms.
MAX_PER_GENE = 8


@dataclass(frozen=True)
class Term:
    text: str
    origin: str  # "typed", or e.g. "HGNC alias of CLDN18"

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "origin": self.origin}


def split(topic: str) -> list[str]:
    """Terms as typed: commas, semicolons or new lines separate them."""
    seen: list[str] = []
    for part in re.split(r"[,;\n]+", topic or ""):
        text = " ".join(part.split()).strip(" \"'")
        if text and text.lower() not in (t.lower() for t in seen):
            seen.append(text)
    return seen


def widen(typed: list[str], lookup) -> list[Term]:
    """The typed terms, then each gene's names.

    `lookup(term)` returns the resolver's fields for a term that names
    exactly one gene, or None. It is injected so tests never touch HGNC.
    """
    terms = [Term(text, "typed") for text in typed]
    have = {text.lower() for text in typed}

    for text in typed:
        fields = lookup(text)
        if not fields:
            continue
        symbol = str(fields.get("symbol") or "")
        names: list[tuple[str, str]] = [
            (symbol, f"HGNC symbol for {text}"),
            (str(fields.get("name") or ""), f"HGNC name of {symbol}"),
        ]
        names += [(alias, f"HGNC alias of {symbol}")
                  for alias in _as_list(fields.get("aliases"))]
        names += [(old, f"previous symbol of {symbol}")
                  for old in _as_list(fields.get("previous_symbols"))]

        added = 0
        for name, origin in names:
            name = name.strip()
            if not name or name.lower() in have:
                continue
            if origin.startswith(("HGNC alias", "previous")) and len(name) < MIN_ALIAS:
                continue
            terms.append(Term(name, origin))
            have.add(name.lower())
            added += 1
            if added >= MAX_PER_GENE:
                break
    return terms


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return []


def gene_lookup(mirror=None, live=None):
    """A `lookup` backed by the resolver, mirror first and API after."""
    from spica.build import identity

    def lookup(text: str) -> dict[str, Any] | None:
        # Free text is not a gene: only single tokens are worth resolving,
        # and a failed resolution adds no terms.
        if " " in text.strip():
            return None
        try:
            resolution, fields = identity(text, mirror, live)
        except Exception:
            return None
        if not resolution.resolved:
            return None
        return {name: value.value for name, value in fields.items() if value.present}

    return lookup
