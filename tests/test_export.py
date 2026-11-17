"""The client report: deterministic, self-contained, and complete.

Built against the fixture mirror with the network off, so every run reads
the same releases and the file can be compared byte for byte.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from spica import export
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"
DAY = date(2026, 10, 27)


def build(queries, project=""):
    mirror = Mirror.load(FIXTURE)
    return export.report(queries, project, mirror, Live(mirror.root, allowed=False), DAY)


class ExportTest(unittest.TestCase):
    def test_the_same_genes_give_the_same_file(self):
        self.assertEqual(build(["PCSK9"], "Lipids")["html"], build(["PCSK9"], "Lipids")["html"])

    def test_cover_carries_project_date_and_versions(self):
        found = build(["PCSK9"], "Lipids")
        page = found["html"]
        self.assertIn("<h1>Lipids</h1>", page)
        self.assertIn("27 October 2026", page)
        self.assertIn("2026-09-01", page)  # the fixture's HGNC release
        self.assertEqual(found["filename"], "Spica PCSK9 2026-10-27.html")

    def test_nothing_is_fetched_when_it_is_opened(self):
        page = build(["PCSK9"])["html"]
        self.assertIn("Content-Security-Policy", page)
        self.assertNotRegex(page, r"<(script|link|img|iframe)[^>]*\b(src|href)=")
        self.assertNotRegex(page, r"url\((?!data:)")
        # Links go to sources' own pages for a reader to follow, nothing more.
        for link in re.findall(r'href="([^"#][^"]*)"', page):
            self.assertTrue(link.startswith("https://"), link)

    def test_house_style(self):
        page = build(["PCSK9"])["html"]
        self.assertNotIn(chr(0x2014), page)  # no em dash in the report
        for section in ("Identity", "Genomics", "Transcriptomics", "Proteomics", "Clinical",
                        "Predictive insights", "Sources and credits"):
            self.assertIn(f">{section}</h3>", page)

    def test_gaps_say_what_they_are_and_the_record_is_named(self):
        mirror = Mirror.load(FIXTURE)
        record = build_record("PCSK9", mirror, Live(mirror.root, allowed=False))
        page = build(["PCSK9"])["html"]
        self.assertIn(record.fingerprint(), page)
        empty = [value for value in record.fields.values() if not value.present]
        self.assertTrue(empty)
        self.assertIn('<span class="null">', page)

    def test_long_lists_are_shortened_never_cut(self):
        rows = [(f"tissue {i:02d}", float(100 - i), str(100 - i)) for i in range(export.FIRST + 5)]
        chart = export.bars(rows, "RNA by tissue")
        self.assertIn("Show the other 5 rows", chart)
        for label, _, _ in rows:
            self.assertIn(f">{label}<", chart)

    def test_several_genes_lead_with_the_comparison(self):
        page = build(["PCSK9", "ADH1B"])["html"]
        self.assertIn("Target comparison", page)
        self.assertLess(page.index("Side by side"), page.index('id="PCSK9"'))
        self.assertIn('id="ADH1B"', page)

    def test_an_unmatched_gene_says_what_to_fix(self):
        found = build(["PCSK9", "NOTAGENE1"])
        self.assertIn("NOTAGENE1", found["error"])
        self.assertNotIn("html", found)


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_saved_and_opened_only_from_this_session(self):
        import app

        api = app.Api()
        mirror = Mirror.load(FIXTURE)
        made = export.report(["PCSK9"], "", mirror, Live(mirror.root, allowed=False), DAY)
        with mock.patch.object(export, "report", return_value=made), \
                mock.patch.object(app, "_save_path", return_value=self.folder / "r.html"):
            saved = api.export_report(["PCSK9"], "")
        self.assertEqual(Path(saved["path"]).read_text(encoding="utf-8"), made["html"])
        stranger = self.folder / "other.html"
        stranger.write_text("x", encoding="utf-8")
        self.assertIn("error", api.open_exported(str(stranger)))

    def test_cancelling_the_dialog_saves_nothing(self):
        import app

        with mock.patch.object(export, "report", return_value={"html": "x", "filename": "r.html",
                                                               "genes": ["PCSK9"]}), \
                mock.patch.object(app, "_save_path", return_value=None):
            self.assertEqual(app.Api().export_report(["PCSK9"], ""), {"cancelled": True})


if __name__ == "__main__":
    unittest.main()
