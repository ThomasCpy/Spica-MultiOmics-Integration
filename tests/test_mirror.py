"""The manifest is the only statement of what is mirrored, so it is read strictly."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class TestLoading(unittest.TestCase):
    def test_a_missing_manifest_is_a_state_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = Mirror.load(tmp)
        self.assertFalse(mirror.present)
        self.assertIn("No mirror manifest", mirror.problem)
        self.assertEqual(mirror.entries, {})

    def test_unreadable_json_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.json").write_text("{not json", encoding="utf-8")
            mirror = Mirror.load(tmp)
        self.assertFalse(mirror.present)
        self.assertIn("not read", mirror.problem)

    def test_a_manifest_without_sources_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.json").write_text('{"mirror_version": "1"}',
                                                   encoding="utf-8")
            mirror = Mirror.load(tmp)
        self.assertIn("no sources object", mirror.problem)

    def test_a_source_without_a_version_is_dropped(self):
        # A value whose provenance cannot name a release is not a sourced value.
        body = {"sources": {"hgnc": {"retrieved": "2026-10-20", "files": {}},
                            "gtex": {"version": "v11", "retrieved": "2026-10-21"}}}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.json").write_text(json.dumps(body), encoding="utf-8")
            mirror = Mirror.load(tmp)
        self.assertIsNone(mirror.entry("hgnc"))
        self.assertIsNotNone(mirror.entry("gtex"))


class TestEntries(unittest.TestCase):
    def setUp(self):
        self.mirror = Mirror.load(FIXTURE)

    def test_the_fixture_mirror_reads(self):
        self.assertTrue(self.mirror.present, self.mirror.problem)
        from spica.sources import SOURCES
        self.assertEqual(sorted(self.mirror.entries),
                         sorted(source.key for source in SOURCES))

    def test_provenance_comes_from_the_manifest(self):
        provenance = self.mirror.entry("gtex").provenance("gtex/median_tpm.gct.gz")
        self.assertEqual(provenance.source, "GTEx")
        self.assertEqual(provenance.version, "v11")
        self.assertEqual(provenance.retrieved, "2026-10-21")
        self.assertEqual(provenance.locator, "gtex/median_tpm.gct.gz")

    def test_unreserved_keys_reach_the_adapter(self):
        self.assertEqual(self.mirror.entry("ensembl").extra["assembly"], "GRCh38.p14")

    def test_declared_files_are_all_present(self):
        for entry in self.mirror.entries.values():
            self.assertEqual(entry.missing_files(), [], entry.key)

    def test_missing_files_are_named_as_the_manifest_writes_them(self):
        body = {"sources": {"hgnc": {"version": "1", "retrieved": "2026-10-20",
                                     "files": {"complete_set": "hgnc/nope.txt"}}}}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.json").write_text(json.dumps(body), encoding="utf-8")
            entry = Mirror.load(tmp).entry("hgnc")
            self.assertEqual(entry.missing_files(), ["hgnc/nope.txt"])


if __name__ == "__main__":
    unittest.main()
