"""The record, rendered for a model to read and for a checker to check.

The `record` and `compare` tools use it, and so does the verifier. The
report screen has its own rendering. This one is for a prompt.

One rendering, used twice. The agents see these lines in their prompt. The
verifier matches claims against the same strings. A number that the model
saw is thus a number that the verifier can find. Two separate formatters
could drift apart; one cannot.

Field names show in brackets because a claim cites its source that way:
`[gtex_max_tissue]`. The names come from the schema, so a citation is
checkable, not decorative.
"""

from __future__ import annotations

from spica.record import GeneRecord, Value
from spica.schema import FIELDS, FIELDS_BY_NAME, SECTIONS, FieldSpec

# Enough of a long map to carry the shape of it without flooding the window.
MAP_ENTRIES = 8
SEQUENCE_HEAD = 60


def render_value(spec: FieldSpec, value: Value) -> str:
    """One field's value as the model will see it, and the verifier will read it."""
    raw = value.value
    if isinstance(raw, dict):
        items = list(raw.items())
        if all(isinstance(v, (int, float)) for v in raw.values()):
            items = sorted(items, key=lambda kv: kv[1], reverse=True)
        shown = ", ".join(f"{key} {item}" for key, item in items[:MAP_ENTRIES])
        if len(items) > MAP_ENTRIES:
            shown += (f", and {len(items) - MAP_ENTRIES} more "
                      f"(field(\"<gene> {spec.name}\") has every one)")
        return shown
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw)
    if spec.type == "sequence" and isinstance(raw, str) and len(raw) > SEQUENCE_HEAD:
        return f"{raw[:SEQUENCE_HEAD]}... ({len(raw)} residues)"
    return str(raw)


def render_field(spec: FieldSpec, value: Value) -> str:
    """One line: what the field says, or why it says nothing."""
    if not value.present:
        return f"  [{spec.name}] {spec.label}: no value ({value.state.value}: {value.reason})"
    unit = f" {spec.unit}" if spec.unit else ""
    source = ""
    if value.provenance:
        source = f"  (from {value.provenance.source} {value.provenance.version})".rstrip()
    return f"  [{spec.name}] {spec.label}: {render_value(spec, value)}{unit}{source}"


def render_record(record: GeneRecord, include_nulls: bool = True) -> str:
    """The whole record, by section, as the agents read it."""
    lines: list[str] = []
    for key, label in SECTIONS.items():
        section = [spec for spec in FIELDS if spec.section == key]
        rendered = [
            render_field(spec, record.fields[spec.name])
            for spec in section
            if include_nulls or record.fields[spec.name].present
        ]
        if rendered:
            lines.append(label)
            lines.extend(rendered)
            lines.append("")
    return "\n".join(lines).strip()


def render_coverage(record: GeneRecord) -> str:
    """What is in the record and what is not, which is what a plan turns on."""
    lines = []
    for key, label in SECTIONS.items():
        section = [spec for spec in FIELDS if spec.section == key]
        present = [spec.name for spec in section if record.fields[spec.name].present]
        missing = [spec.name for spec in section if not record.fields[spec.name].present]
        lines.append(f"{label}: {len(present)} of {len(section)} fields have values")
        if present:
            lines.append(f"  have: {', '.join(present)}")
        if missing:
            lines.append(f"  empty: {', '.join(missing)}")
    return "\n".join(lines)


def present_text(record: GeneRecord) -> dict[str, str]:
    """Field name to its rendered value, for fields with a value.

    The verifier checks citations against this map. A cited field must be
    in it, and a number in the claim must occur in the text of that field.
    """
    out: dict[str, str] = {}
    for spec in FIELDS:
        value = record.fields[spec.name]
        if value.present:
            out[spec.name] = render_value(spec, value)
    return out


def known_fields() -> set[str]:
    return set(FIELDS_BY_NAME)
