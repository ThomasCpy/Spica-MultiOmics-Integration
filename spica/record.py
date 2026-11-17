"""The gene record: typed values, provenance, and explicit nulls.

A record is a fixed set of fields (see `schema.py`). All fields are always
present. A field holds a value with its provenance, or a null state that
gives the cause of the absence. There is no third case and no silent
blank: `Value` accepts no other form.

Null states, from the roadmap:

    not_found    the source was queried and has nothing for this gene or field
    not_covered  the source does not cover this field at all
    failed       the query could not run (mirror missing, parse error, ...)

Records are deterministic: the same gene against the same mirror versions
gives the same `fingerprint()`. Nothing that varies between runs (clock,
file paths, machine) goes into it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NullState(str, Enum):
    """Why a field has no value. Subclasses str so it serializes as itself."""

    NOT_FOUND = "not_found"
    NOT_COVERED = "not_covered"
    FAILED = "failed"


@dataclass(frozen=True)
class Provenance:
    """Where one value came from, in enough detail to go and check it."""

    source: str  # display name of the source, e.g. "HGNC"
    version: str  # the source's own release label, e.g. "2026-09-01"
    retrieved: str  # ISO date the local mirror was downloaded
    locator: str = ""  # file or accession within the mirror

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "version": self.version,
            "retrieved": self.retrieved,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class Value:
    """One field of a record: either a value with provenance, or a null state.

    Build it with `Value.found(...)` or `Value.missing(...)` rather than
    directly; the constructor only exists to enforce that one of the two
    shapes holds.
    """

    value: Any = None
    state: NullState | None = None
    reason: str = ""
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if self.state is None:
            if self.value is None:
                raise ValueError("a present value needs a value; use Value.missing()")
            if self.provenance is None:
                raise ValueError("a present value needs provenance")
        elif not self.reason:
            raise ValueError(f"a {self.state.value} value needs a reason")

    @property
    def present(self) -> bool:
        return self.state is None

    @classmethod
    def found(cls, value: Any, provenance: Provenance) -> "Value":
        return cls(value=value, provenance=provenance)

    @classmethod
    def missing(
        cls, state: NullState, reason: str, provenance: Provenance | None = None
    ) -> "Value":
        # Provenance is kept on a null where the queried release is known:
        # "GTEx v11 has no row for this gene" is a stronger statement than
        # "GTEx has nothing", and the report says which one it is.
        return cls(state=state, reason=reason, provenance=provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "state": self.state.value if self.state else None,
            "reason": self.reason,
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }


@dataclass(frozen=True)
class Resolution:
    """The result of the query resolution.

    `matched_on` gives the kind of identifier that matched ("approved
    symbol", "alias symbol", ...). A match through an alias is a fact that
    the user must see before trusting the rest of the record.
    """

    query: str
    resolved: bool
    matched_on: str = ""
    hgnc_id: str = ""
    symbol: str = ""
    ensembl_gene_id: str = ""
    uniprot_accession: str = ""
    reason: str = ""
    candidates: tuple[str, ...] = ()  # populated when the query is ambiguous

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "resolved": self.resolved,
            "matched_on": self.matched_on,
            "hgnc_id": self.hgnc_id,
            "symbol": self.symbol,
            "ensembl_gene_id": self.ensembl_gene_id,
            "uniprot_accession": self.uniprot_accession,
            "reason": self.reason,
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class SourceStamp:
    """One source's contribution to a record: which release, and whether it ran."""

    key: str
    label: str
    status: str  # "read" | "unavailable" | "failed" | "skipped"
    version: str = ""
    retrieved: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "version": self.version,
            "retrieved": self.retrieved,
            "note": self.note,
        }


@dataclass
class GeneRecord:
    """Every field of the schema for one gene, plus how it was built."""

    query: str
    resolution: Resolution
    fields: dict[str, Value] = field(default_factory=dict)
    sources: tuple[SourceStamp, ...] = ()
    schema_version: str = ""

    def __getitem__(self, name: str) -> Value:
        return self.fields[name]

    def value(self, name: str) -> Any:
        """The value of a field, or None if it is null. For callers that only
        want the data and will check `fields[name].state` themselves."""
        return self.fields[name].value

    def present_fields(self) -> list[str]:
        return [name for name, value in self.fields.items() if value.present]

    def fingerprint(self) -> str:
        """A hash of what the record says and which releases it says it from.

        Deliberately excludes build time, file paths, and whether a source
        was read, fetched or served from the cache: none of those change
        what the record says. Rebuilding the same gene against the same
        releases is then verifiably the same record.
        """
        payload = {
            "schema_version": self.schema_version,
            "resolution": self.resolution.to_dict(),
            "sources": [
                {"key": stamp.key, "version": stamp.version}
                for stamp in self.sources
            ],
            "fields": {
                name: {
                    "value": value.value,
                    "state": value.state.value if value.state else None,
                }
                for name, value in self.fields.items()
            },
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "schema_version": self.schema_version,
            "resolution": self.resolution.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
            "fields": {name: value.to_dict() for name, value in self.fields.items()},
            "fingerprint": self.fingerprint(),
        }
