"""DepMap: the summary the mirror builds, the record it gives, the sentence.

The summary is pinned on two tiny matrices with known answers, so every
figure the record shows can be checked by hand.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica import metrics, mirrorbuild
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"

MODELS = ("ModelID,CellLineName,OncotreeLineage\n"
          "ACH-1,LINE1,Lung\nACH-2,LINE2,Lung\nACH-3,LINE3,Blood\nACH-4,LINE4,Blood\n")
# PCSK9 needed by the two blood lines only; ADH1B by none; ESS1 by all.
EFFECT = (",PCSK9 (255738),ADH1B (125),ESS1 (99999)\n"
          "ACH-1,0.05,0.1,-1.5\nACH-2,-0.1,0.0,-1.2\nACH-3,-1.2,,-2.0\nACH-4,-0.9,0.2,-3.4\n")
# Rows in another order than the effect matrix: matched by ModelID.
DEPENDENCY = (",ADH1B (125),PCSK9 (255738),ESS1 (99999)\n"
              "ACH-4,0.01,0.80,1.0\nACH-3,,0.95,1.0\nACH-2,0.0,0.10,0.99\nACH-1,0.02,0.02,0.97\n")


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        raw = self.data / "depmap" / "raw"
        raw.mkdir(parents=True)
        (raw / "Model.csv").write_text(MODELS, encoding="utf-8")
        (raw / "CRISPRInferredCommonEssentials.csv").write_text("Essentials\nESS1 (99999)\n",
                                                                 encoding="utf-8")
        (raw / "CRISPRGeneEffect.csv").write_text(EFFECT, encoding="utf-8")
        (raw / "CRISPRGeneDependency.csv").write_text(DEPENDENCY, encoding="utf-8")
        shutil.copytree(FIXTURE / "hgnc", self.data / "hgnc")
        with mock.patch.object(mirrorbuild, "DATA", self.data):
            mirrorbuild._depmap_summary(raw, self.data / "depmap" / "genes.tsv")
        lines = (self.data / "depmap" / "genes.tsv").read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        self.rows = {row["depmap_symbol"]: row for row in
                     (dict(zip(head, line.split("\t"))) for line in lines[1:])}

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def test_figures_by_hand(self):
        pcsk9 = self.rows["PCSK9"]
        self.assertEqual(pcsk9["hgnc_id"], "HGNC:20001")  # through Entrez, not the name
        self.assertEqual(pcsk9["lines"], "4")
        self.assertAlmostEqual(float(pcsk9["mean_effect"]), (0.05 - 0.1 - 1.2 - 0.9) / 4, places=3)
        self.assertEqual((pcsk9["dependent"], pcsk9["dependent_share"]), ("2", "50.00"))
        self.assertEqual(json.loads(pcsk9["lineages"])["Blood"][:2], [2, 2])
        self.assertEqual(json.loads(pcsk9["lineages"])["Lung"][:2], [2, 0])
        # Most dependent first.
        self.assertEqual(pcsk9["dependent_lines"], "ACH-3:-1.200|ACH-4:-0.900")

    def test_a_missing_cell_is_not_a_zero(self):
        self.assertEqual(self.rows["ADH1B"]["lines"], "3")
        self.assertEqual(self.rows["ADH1B"]["dependent"], "0")

    def test_every_line_lands_in_a_bin(self):
        ess = self.rows["ESS1"]
        self.assertEqual(ess["common_essential"], "1")
        self.assertEqual(sum(int(c) for c in ess["histogram"].split(",")), 4)
        self.assertEqual(ess["hgnc_id"], "")  # not an HGNC gene in the fixture: kept anyway


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        (self.root / "depmap").mkdir(exist_ok=True)
        (self.root / "depmap" / "Model.csv").write_text(MODELS, encoding="utf-8")
        bins = ["0"] * 40
        bins[18], bins[30], bins[31] = "1", "2", "1"
        lineages = json.dumps({"Blood": [12, 9, -1.05], "Lung": [30, 1, -0.1]})
        head = ["hgnc_id", "symbol", "entrez", "depmap_symbol", "lines", "mean_effect",
                "median_effect", "min_effect", "dependent", "dependent_share", "common_essential",
                "lineages", "histogram", "dependent_lines"]
        rows = [["HGNC:20001", "PCSK9", "255738", "PCSK9", "42", "-0.3812", "-0.2", "-1.2", "10",
                 "23.81", "0", lineages, ",".join(bins), "ACH-3:-1.200|ACH-4:-0.900"],
                ["HGNC:250", "ADH1B", "125", "ADH1B", "42", "0.0500", "0.04", "-0.2", "0",
                 "0.00", "0", json.dumps({"Lung": [42, 0, 0.05]}), ",".join(bins), ""]]
        (self.root / "depmap" / "genes.tsv").write_text(
            "\n".join("\t".join(row) for row in [head] + rows) + "\n", encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["depmap"] = {
            "label": "DepMap", "version": "24Q4", "retrieved": "2026-10-28",
            "files": {"genes": "depmap/genes.tsv", "models": "depmap/Model.csv"}}
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.mirror = Mirror.load(self.root)

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def record(self, symbol):
        return build_record(symbol, self.mirror, Live(self.root, allowed=False))

    def test_the_record_reads_the_summary(self):
        record = self.record("PCSK9")
        self.assertEqual(record.value("depmap_dependent_share"), 23.8)
        self.assertEqual(record.value("depmap_lineage_dependency"),
                         {"Blood, 12 lines": 75.0, "Lung, 30 lines": 3.3})
        self.assertEqual(record.value("depmap_dependent_lines"),
                         ["LINE3 (Blood) -1.200", "LINE4 (Blood) -0.900"])
        self.assertEqual(record.value("depmap_effect_distribution")["-1.2"], 1)
        self.assertEqual(record.value("dependency_profile"),
                         "Selective: 23.8% of lines depend on it, most in Blood (75% of 12 lines).")

    def test_no_dependent_line_says_so(self):
        record = self.record("ADH1B")
        self.assertIs(record.fields["depmap_dependent_lines"].state, NullState.NOT_FOUND)
        self.assertEqual(record.value("dependency_profile"), "Rarely a dependency: 0% of lines.")

    def test_without_depmap_it_says_there_is_no_api(self):
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        del manifest["sources"]["depmap"]
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        mirror = Mirror.load(self.root)
        record = build_record("PCSK9", mirror, Live(mirror.root, allowed=True))
        value = record.fields["depmap_mean_effect"]
        self.assertIs(value.state, NullState.FAILED)
        self.assertIn("no API", value.reason)


class ProfileTest(unittest.TestCase):
    def test_the_three_readings(self):
        self.assertTrue(metrics.dependency_profile(97.0, True, {}).startswith("Common essential"))
        self.assertEqual(metrics.dependency_profile(0.4, False, {}),
                         "Rarely a dependency: 0.4% of lines.")
        # A lineage of three lines never names where it gathers.
        self.assertEqual(metrics.dependency_profile(5.0, False, {"Eye, 3 lines": 66.7}),
                         "A dependency in 5% of lines, spread across lineages.")


if __name__ == "__main__":
    unittest.main()
