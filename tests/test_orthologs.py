"""Orthologs in mouse and cynomolgus, from Ensembl Compara: both routes.

The identity figure is the share of the human protein identical in the
ortholog. BioMart and the REST API label it differently, so each route is
pinned to the column it must read, with numbers taken from Ensembl 116.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState
from spica.sources.ensembl import Ensembl
from tests.test_live import Stub

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"
TAB, NL = chr(9), chr(10)


def biomart(title: str, rows: list[list[str]]) -> str:
    head = ["Gene stable ID", f"{title} gene stable ID", f"{title} gene name",
            f"{title} homology type", f"%id. target {title} gene identical to query gene",
            f"%id. query gene identical to target {title} gene",
            f"{title} Gene-order conservation score", f"{title} Whole-genome alignment coverage",
            f"{title} orthology confidence [0 low, 1 high]"]
    return NL.join(TAB.join(row) for row in [head] + rows) + NL


class MirrorRouteTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        (self.root / "ensembl" / "orthologs_mouse.tsv").write_text(biomart("Mouse", [
            ["ENSG00000169174", "ENSMUSG00000044254", "Pcsk9", "ortholog_one2one", "76.7341",
             "76.513", "100", "100.00", "1"],
            # Two mouse genes for one human: the closer one leads.
            ["ENSG00000196616", "ENSMUSG00000000001", "Adh1a", "ortholog_one2many", "61.2",
             "60.0", "50", "90.00", "0"],
            ["ENSG00000196616", "ENSMUSG00000000002", "Adh1c", "ortholog_one2many", "70.4",
             "69.0", "50", "90.00", "0"],
            ["ENSG00000251562", "", "", "", "", "", "", "", ""],
        ]), encoding="utf-8")
        (self.root / "ensembl" / "orthologs_cyno.tsv").write_text(biomart("Crab-eating macaque", [
            ["ENSG00000169174", "ENSMFAG00000000310", "PCSK9", "ortholog_one2one", "96.3873",
             "82.2441", "100", "100.00", "1"],
        ]), encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["ensembl"]["files"].update({
            "orthologs_mouse": "ensembl/orthologs_mouse.tsv",
            "orthologs_cyno": "ensembl/orthologs_cyno.tsv"})
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.mirror = Mirror.load(self.root)

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def record(self, symbol):
        return build_record(symbol, self.mirror, Live(self.root, allowed=False))

    def test_identity_is_the_share_of_the_human_protein(self):
        record = self.record("PCSK9")
        self.assertEqual(record.value("mouse_orthologs"), ["Pcsk9 ENSMUSG00000044254"])
        self.assertEqual(record.value("mouse_orthology"), "one-to-one, high confidence")
        self.assertEqual(record.value("mouse_protein_identity"), 76.7)
        # Not the 82.2 of the other column: the cynomolgus protein is longer.
        self.assertEqual(record.value("cyno_protein_identity"), 96.4)
        self.assertEqual(record.fields["cyno_orthologs"].provenance.locator,
                         "ensembl/orthologs_cyno.tsv")

    def test_the_closest_of_several_leads(self):
        record = self.record("ADH1B")
        self.assertEqual(record.value("mouse_orthologs"),
                         ["Adh1c ENSMUSG00000000002", "Adh1a ENSMUSG00000000001"])
        self.assertEqual(record.value("mouse_protein_identity"), 70.4)
        self.assertEqual(record.value("mouse_orthology"), "one-to-many, low confidence")

    def test_no_ortholog_is_an_answer(self):
        record = self.record("ADH1B")
        self.assertIs(record.fields["cyno_orthology"].state, NullState.NOT_FOUND)
        self.assertIn("no cynomolgus ortholog", record.fields["cyno_orthology"].reason)
        self.assertIs(self.record("MALAT1").fields["mouse_orthologs"].state, NullState.NOT_FOUND)


class OlderMirrorTest(unittest.TestCase):
    def test_a_mirror_without_the_files_says_how_to_get_them(self):
        mirror = Mirror.load(FIXTURE)
        record = build_record("PCSK9", mirror, Live(mirror.root, allowed=False))
        value = record.fields["mouse_protein_identity"]
        self.assertIs(value.state, NullState.FAILED)
        self.assertIn("Ensembl update required", value.reason)
        self.assertTrue(record.fields["genomic_location"].present)  # the rest still reads


class ApiRouteTest(unittest.TestCase):
    def test_rest_identity_is_the_source_side(self):
        homology = {"data": [{"id": "ENSG00000169174", "homologies": [
            {"type": "ortholog_one2one",
             "source": {"id": "ENSG00000169174", "perc_id": 96.3873, "species": "homo_sapiens"},
             "target": {"id": "ENSMFAG00000000310", "perc_id": 82.2441,
                        "species": "macaca_fascicularis"}},
            {"type": "ortholog_one2one",
             "source": {"id": "ENSG00000169174", "perc_id": 76.7341, "species": "homo_sapiens"},
             "target": {"id": "ENSMUSG00000044254", "perc_id": 76.513, "species": "mus_musculus"}},
        ]}]}
        stub = Stub({"homology/id/human/ENSG00000169174": homology,
                     "lookup/id/ENSMUSG00000044254": {"display_name": "Pcsk9"},
                     "lookup/id/ENSMFAG00000000310": {"display_name": "PCSK9"}})
        with tempfile.TemporaryDirectory() as tmp:
            fields = Ensembl()._orthologs_live("ENSG00000169174", Live(tmp, opener=stub), "116")
        self.assertEqual(fields["cyno_protein_identity"], 96.4)
        self.assertEqual(fields["mouse_orthologs"], ["Pcsk9 ENSMUSG00000044254"])
        self.assertEqual(fields["mouse_orthology"], "one-to-one")  # no confidence over REST

    def test_a_gene_without_homologies(self):
        with tempfile.TemporaryDirectory() as tmp:
            fields = Ensembl()._orthologs_live("ENSG00000251562", Live(tmp, opener=Stub({})), "116")
        self.assertIs(fields["mouse_orthology"].state, NullState.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
