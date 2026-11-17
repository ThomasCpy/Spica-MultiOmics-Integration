"""A value is either sourced or explained, and a record hashes to its content."""

from __future__ import annotations

import unittest

from spica.record import (
    GeneRecord,
    NullState,
    Provenance,
    Resolution,
    SourceStamp,
    Value,
)

PROV = Provenance("HGNC", "2026-09-01", "2026-10-20", "hgnc/hgnc_complete_set.txt")


class TestValue(unittest.TestCase):
    def test_a_present_value_needs_provenance(self):
        with self.assertRaises(ValueError):
            Value(value="PCSK9")

    def test_a_present_value_needs_a_value(self):
        with self.assertRaises(ValueError):
            Value(provenance=PROV)

    def test_a_null_needs_a_reason(self):
        with self.assertRaises(ValueError):
            Value(state=NullState.NOT_FOUND)

    def test_found_and_missing(self):
        found = Value.found("PCSK9", PROV)
        self.assertTrue(found.present)
        self.assertIsNone(found.state)

        missing = Value.missing(NullState.NOT_COVERED, "no protein product")
        self.assertFalse(missing.present)
        self.assertIsNone(missing.value)
        self.assertEqual(missing.state, NullState.NOT_COVERED)

    def test_serializes_the_state_as_its_name(self):
        payload = Value.missing(NullState.FAILED, "mirror unreadable").to_dict()
        self.assertEqual(payload["state"], "failed")
        self.assertEqual(payload["reason"], "mirror unreadable")


def record(symbol: str = "PCSK9", tpm: float = 77.41) -> GeneRecord:
    return GeneRecord(
        query=symbol,
        resolution=Resolution(query=symbol, resolved=True, matched_on="approved symbol",
                              hgnc_id="HGNC:20001", symbol=symbol),
        fields={
            "symbol": Value.found(symbol, PROV),
            "gtex_median_across_tissues": Value.found(tpm, PROV),
            "protein_sequence": Value.missing(NullState.NOT_FOUND, "no entry"),
        },
        sources=(SourceStamp("hgnc", "HGNC", "read", "2026-09-01", "2026-10-20"),),
        schema_version="1",
    )


class TestFingerprint(unittest.TestCase):
    def test_same_content_same_fingerprint(self):
        self.assertEqual(record().fingerprint(), record().fingerprint())

    def test_a_changed_value_changes_the_fingerprint(self):
        self.assertNotEqual(record().fingerprint(), record(tpm=77.42).fingerprint())

    def test_a_changed_null_state_changes_the_fingerprint(self):
        other = record()
        other.fields["protein_sequence"] = Value.missing(
            NullState.NOT_COVERED, "no entry"
        )
        self.assertNotEqual(record().fingerprint(), other.fingerprint())

    def test_the_locator_does_not_change_the_fingerprint(self):
        # Where a file sits on this machine is not part of what the record says.
        other = record()
        other.fields["symbol"] = Value.found(
            "PCSK9", Provenance("HGNC", "2026-09-01", "2026-10-20", "elsewhere.txt")
        )
        self.assertEqual(record().fingerprint(), other.fingerprint())

    def test_how_a_value_was_obtained_does_not_change_the_fingerprint(self):
        # Read from the mirror or served from the API cache: same record.
        other = record()
        other.sources = (
            SourceStamp("hgnc", "HGNC", "cached", "2026-09-01", "2026-10-20"),
        )
        self.assertEqual(record().fingerprint(), other.fingerprint())

    def test_a_changed_release_changes_the_fingerprint(self):
        other = record()
        other.sources = (SourceStamp("hgnc", "HGNC", "read", "2026-10-01", "2026-10-20"),)
        self.assertNotEqual(record().fingerprint(), other.fingerprint())

    def test_to_dict_is_json_shaped(self):
        import json

        payload = record().to_dict()
        self.assertEqual(json.loads(json.dumps(payload))["query"], "PCSK9")


if __name__ == "__main__":
    unittest.main()
