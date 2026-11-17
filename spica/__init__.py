"""Spica data layer: a sourced, deterministic record for one gene.

    from spica import build_record
    record = build_record("PCSK9")
    record.fields["gtex_median_across_tissues"].value
    record.fields["protein_sequence"].state      # a NullState when there is no value

Three layers, as in the roadmap. The mirror keeps the downloads as they are.
`build_record` normalizes them into the record below. The views (report,
table) read only records.
"""

from __future__ import annotations

from spica.build import build_record, summarize
from spica.mirror import Mirror
from spica.record import GeneRecord, NullState, Provenance, Resolution, Value
from spica.schema import FIELDS, SCHEMA_VERSION, schema_to_dict

__all__ = [
    "FIELDS",
    "GeneRecord",
    "Mirror",
    "NullState",
    "Provenance",
    "Resolution",
    "SCHEMA_VERSION",
    "Value",
    "build_record",
    "schema_to_dict",
    "summarize",
]
