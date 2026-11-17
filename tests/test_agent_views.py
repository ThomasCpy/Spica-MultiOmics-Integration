"""AI mode reaches what the report reaches.

The parity test is the one that matters most: every view the app serves
has a tool, and a view added without one fails here. The rest run each
tool against the fixture mirror, offline, and check the two rules the
tools keep: nothing is cut without saying how to get the rest, and every
answer can be cited and its numbers checked.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from spica.agents.run import Note
from spica.agents.tools import Compare, Record, default_tools
from spica.agents.verify import verify_answer
from spica.agents.views import (APP_VIEWS, NOT_VIEWS, PAGE, Field, Genetics, Glance, Organs,
                                Where, _page)
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


def offline_builder():
    mirror = Mirror.load(FIXTURE)
    return lambda symbol: build_record(symbol, mirror, Live(mirror.root, allowed=False))


class ParityTest(unittest.TestCase):
    def test_every_view_the_app_serves_has_a_tool(self):
        import app

        methods = {name for name in dir(app.Api)
                   if not name.startswith("_") and callable(getattr(app.Api, name))}
        unmapped = methods - set(APP_VIEWS) - NOT_VIEWS
        self.assertFalse(unmapped, f"app views with no AI tool: {sorted(unmapped)}; "
                                   "add a tool to spica/agents/views.py and map it in APP_VIEWS")
        tools = default_tools()
        for method, key in APP_VIEWS.items():
            self.assertIn(method, methods, f"APP_VIEWS names {method}, which the app lacks")
            self.assertIn(key, tools, f"{method} maps to {key}, which is not a tool")

    def test_every_tool_says_how_to_call_it(self):
        for key, tool in default_tools().items():
            self.assertTrue(tool.usage.startswith(f"{key}("), key)


class PageTest(unittest.TestCase):
    def test_a_short_list_is_shown_whole(self):
        shown, note = _page(list(range(5)), "", 'x("A')
        self.assertEqual((shown, note), (list(range(5)), "all 5"))

    def test_a_long_list_says_how_to_get_the_rest(self):
        items = list(range(PAGE * 2 + 7))
        shown, note = _page(items, "", 'x("A')
        self.assertEqual(len(shown), PAGE)
        self.assertIn(f'x("A {PAGE + 1}-{2 * PAGE}")', note)
        shown, note = _page(items, f"{2 * PAGE + 1}-{3 * PAGE}", 'x("A')
        self.assertEqual(shown, items[2 * PAGE:])
        self.assertNotIn("next page", note)
        shown, _ = _page(items, f"from {PAGE + 1}", 'x("A')
        self.assertEqual(shown[0], PAGE)


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"SPICA_DATA_DIR": str(FIXTURE),
                                                "SPICA_OFFLINE": "1"})
        self.env.start()
        self.build = offline_builder()

    def tearDown(self):
        self.env.stop()

    def test_field_reads_a_whole_map_and_filters_it(self):
        found = Field(self.build).run("PCSK9 gtex_tissue_tpm")
        self.assertEqual(found.citations, ["gtex_tissue_tpm"])
        self.assertIn("Liver: 77.41", found.text)
        self.assertIn("entries all", found.text)
        found = Field(self.build).run("PCSK9 gtex_tissue_tpm brain")
        self.assertIn("Brain Cortex", found.text)
        self.assertNotIn("Liver", found.text.split("\n", 1)[1])

    def test_field_suggests_a_name_it_does_not_know(self):
        found = Field(self.build).run("PCSK9 gtex_tisue_tpm")
        self.assertIn("gtex_tissue_tpm", found.problem)

    def test_field_says_why_a_field_is_empty(self):
        found = Field(self.build).run("ADH1B gtex_tissue_tpm")
        self.assertIn("has no value", found.problem)

    def test_organs_aligns_every_layer(self):
        found = Organs(self.build).run("PCSK9")
        self.assertEqual(found.citations, ["organs:PCSK9"])
        self.assertIn("liver:", found.text)

    def test_glance_gives_weights_and_sources(self):
        found = Glance(self.build).run("PCSK9 function")
        self.assertEqual(found.citations, ["glance:PCSK9"])
        self.assertIn("weight = number of GO terms", found.text)

    def test_where_counts_agreeing_sources(self):
        found = Where(self.build).run("PCSK9")
        self.assertEqual(found.citations, ["where:PCSK9"])
        self.assertIn("sources reporting", found.text)

    def test_genetics_says_what_it_needs(self):
        found = Genetics(self.build).run("PCSK9")
        self.assertIn("update both in Settings", found.problem)

    def test_record_shows_empty_fields_with_reasons(self):
        found = Record(self.build).run("ADH1B")
        self.assertIn("no value (", found.text)

    def test_compare_covers_every_comparable_field_and_every_gene(self):
        genes = ["PCSK9", "ADH1B", "MALAT1", "PCSK9", "ADH1B", "MALAT1", "PCSK9"]  # seven
        found = Compare(self.build).run(", ".join(genes))
        self.assertEqual(found.text.splitlines()[0].count(","), len(genes) - 1)
        self.assertIn("[rna_specificity_tau]", found.text)
        self.assertGreater(len(found.citations), 6)
        self.assertNotIn("[protein_sequence]", found.text)


class NumberCheckTest(unittest.TestCase):
    """An answer may cite a real source and still misquote it."""

    NOTE = Note(tool="organs", tool_label="RNA and protein by organ", text="liver leads",
                fields=["organs:PCSK9"],
                sources="[organs:PCSK9] liver: RNA (GTEx) 26.5 median TPM; RNA (HPA) 47.5 nTPM")

    def test_a_number_the_tool_returned_holds(self):
        verdict = verify_answer("PCSK9 RNA in liver is 47.5 nTPM [organs:PCSK9].", [self.NOTE])
        self.assertEqual(verdict["problems"], [])

    def test_a_rounded_number_holds(self):
        verdict = verify_answer("GTEx puts liver at about 26 TPM [organs:PCSK9].", [self.NOTE])
        self.assertEqual(verdict["problems"], [])

    def test_a_misquoted_number_is_flagged(self):
        verdict = verify_answer("PCSK9 RNA in liver is 74.5 nTPM [organs:PCSK9].", [self.NOTE])
        kinds = [p["kind"] for p in verdict["problems"]]
        self.assertEqual(kinds, ["unsupported_number"])
        self.assertEqual(verdict["problems"][0]["severity"], "warning")

    def test_an_old_note_without_sources_falls_back_to_its_text(self):
        old = Note(tool="organs", tool_label="x", text="liver 26.5", fields=["organs:PCSK9"])
        verdict = verify_answer("Liver is 26.5 TPM [organs:PCSK9].", [old])
        self.assertEqual(verdict["problems"], [])


if __name__ == "__main__":
    unittest.main()
