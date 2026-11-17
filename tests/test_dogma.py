"""The central dogma view: organs, merging, and never mixing scales."""

from __future__ import annotations

import unittest
from pathlib import Path

from spica import metrics
from spica.build import build_record
from spica.dogma import align, align_many, project, readable
from spica.live import Live
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


def record(symbol="PCSK9"):
    mirror = Mirror.load(FIXTURE)
    return build_record(symbol, mirror, Live(mirror.root, allowed=False))


class TestProject(unittest.TestCase):
    def test_regions_fold_into_one_organ_at_their_maximum(self):
        cells, stray = project({
            "Brain - Cerebellum": 21.7,
            "Brain - Cortex": 0.14,
            "Liver": 77.4,
            "Unlabelled specimen 7": 3.0,
        }, "number")
        brain = cells["brain"].to_dict()
        self.assertEqual(brain["value"], 21.7)
        self.assertEqual(brain["merged"], 2)
        self.assertEqual(brain["peak_tissue"], "Brain - Cerebellum")
        self.assertEqual([m["tissue"] for m in brain["members"]],
                         ["Brain - Cerebellum", "Brain - Cortex"])
        # Measured but not an organ: reported, not dropped.
        self.assertEqual(stray, ["Unlabelled specimen 7"])

    def test_cell_types_fold_by_their_tissue_and_stay_openable(self):
        cells, stray = project({
            "lung / alveolar cells type II": "medium",
            "lung / endothelial cells": "not detected",
            "bronchus / respiratory epithelial cells": "low",
            "soft tissue 1 / fibroblasts": "low",
        }, "level")
        lung = cells["lung"].to_dict()
        self.assertEqual(lung["display"], "medium")
        self.assertEqual(lung["merged"], 3)
        self.assertEqual(lung["members"][0]["tissue"], "lung / alveolar cells type II")
        # Placed by the tissue part only: "endothelial" does not make it a vessel.
        self.assertNotIn("vessel", cells)
        self.assertEqual(stray, ["soft tissue 1 / fibroblasts"])

    def test_staining_levels_rank_weakest_first(self):
        cells, _ = project({"liver": "High", "kidney": "Low", "lung": "Not detected"},
                           "level")
        self.assertEqual(cells["liver"].value, 3.0)
        self.assertEqual(cells["lung"].value, 0.0)
        self.assertEqual(cells["kidney"].display, "Low")

    def test_every_vocabulary_trap_stays_shut(self):
        self.assertEqual(set(metrics.organs("parathyroid gland")), {"parathyroid"})
        self.assertEqual(set(metrics.organs("thyroid gland")), {"thyroid"})
        self.assertEqual(set(metrics.organs("adrenal gland")), {"adrenal"})

    def test_compound_labels_land_in_one_organ(self):
        # Each of these used to be counted in two organs, or the wrong one.
        self.assertEqual(set(metrics.organs("heart muscle")), {"heart"})
        self.assertEqual(set(metrics.organs("blood vessel")), {"vessel"})
        self.assertEqual(set(metrics.organs("Nerve - Tibial")), {"nerve"})
        self.assertEqual(set(metrics.organs("Cells - EBV-transformed lymphocytes")),
                         {"cultured cells"})
        self.assertEqual(set(metrics.organs("Muscle - Skeletal")), {"muscle"})


class TestReadable(unittest.TestCase):
    def test_numbers_read_without_scientific_notation(self):
        self.assertEqual(readable(7482438.2), "7.48M")
        self.assertEqual(readable(10905.9), "10,906")
        self.assertEqual(readable(427.67), "428")
        self.assertEqual(readable(28.31), "28.3")
        self.assertEqual(readable(0.07), "0.07")
        self.assertEqual(readable(0.0), "0")


class TestAlign(unittest.TestCase):
    def test_each_layer_is_scaled_against_its_own_peak(self):
        dogma = align(record())
        liver = next(row for row in dogma["rows"] if row["organ"] == "liver")
        for cell in liver["cells"].values():
            self.assertEqual(cell["share"], 1.0)  # liver is the peak of every layer
        self.assertEqual(liver["reading"], "Both high")

    def test_layers_report_their_coverage(self):
        layers = {layer["key"]: layer for layer in align(record())["layers"]}
        self.assertEqual(layers["gtex"]["organs"], 5)
        self.assertFalse(layers["gtex"]["sparse"])
        self.assertTrue(layers["hpa_ihc"]["sparse"])

    def test_a_missing_layer_says_why(self):
        missing = {m["key"]: m["reason"] for m in align(record())["missing"]}
        self.assertIn("hpa_ms", missing)
        self.assertTrue(missing["hpa_ms"])

    def test_an_organ_no_protein_layer_covers_is_not_called_silent(self):
        rows = {row["organ"]: row for row in align(record())["rows"]}
        self.assertEqual(rows["intestine"]["reading"], "No protein measured here")


class TestAlignMany(unittest.TestCase):
    def test_one_layer_per_column_for_the_whole_column(self):
        many = align_many([record(), record()])
        for gene in many["genes"]:
            # GTEx covers five organs here, HPA RNA three: GTEx draws the column.
            self.assertEqual(gene["layers"]["transcript"]["label"], "RNA (GTEx)")
            self.assertEqual(gene["layers"]["protein"]["label"], "Protein (antibody)")
        for row in many["rows"]:
            for cell in row["cells"]:
                if cell["transcript"]:
                    self.assertEqual(cell["transcript"]["layer"], "RNA (GTEx)")

    def test_rows_share_one_organ_axis(self):
        many = align_many([record(), record()])
        self.assertTrue(all(len(row["cells"]) == 2 for row in many["rows"]))
        self.assertEqual(many["rows"][0]["organ"], "liver")
        self.assertIn("own peak", many["summary"])


if __name__ == "__main__":
    unittest.main()
