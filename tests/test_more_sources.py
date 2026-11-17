"""The sources added from the integrator's list: structure, druggability,
single-cell, interactions. Mirror routes against the fixture, parsers on
answers shaped like the live ones."""

from __future__ import annotations

import unittest
from pathlib import Path

from spica.build import build_record
from spica.dogma import align
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState
from spica.sources.alphafold import missense, per_residue_missense
from spica.sources.chembl import summarise
from spica.sources.uniprot import clean_text, segments, structures

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


def record(symbol: str = "PCSK9"):
    mirror = Mirror.load(FIXTURE)
    return build_record(symbol, mirror, Live(mirror.root, allowed=False))


class TestUniProt(unittest.TestCase):
    def test_mirror_columns(self):
        r = record()
        self.assertEqual(r.value("uniprot_function"),
                         "Crucial player in the regulation of plasma cholesterol homeostasis.")
        self.assertEqual(r.value("go_process"),
                         ["cholesterol homeostasis", "lipoprotein metabolic process"])
        self.assertEqual(r.value("uniprot_isoforms"), 2)
        self.assertEqual(r.value("pdb_structures"), 3)
        # IDs only in the export: resolution and coverage say where they come from.
        self.assertEqual(r["pdb_best_resolution"].state, NullState.NOT_COVERED)

    def test_coverage_is_the_union_of_chain_ranges(self):
        xrefs = [
            {"database": "PDB", "id": "1AAA", "properties": [
                {"key": "Method", "value": "X-ray"}, {"key": "Resolution", "value": "2.10 A"},
                {"key": "Chains", "value": "A=1-50"}]},
            {"database": "PDB", "id": "2BBB", "properties": [
                {"key": "Method", "value": "EM"}, {"key": "Resolution", "value": "3.4 A"},
                {"key": "Chains", "value": "A/B=41-80, C=91-100"}]},
            {"database": "GO", "id": "GO:1"},
        ]
        out = structures(xrefs, 100)
        self.assertEqual(out["pdb_structures"], 2)
        self.assertEqual(out["pdb_best_resolution"], 2.1)
        self.assertEqual(out["pdb_coverage"], 90.0)  # 1-80 and 91-100
        self.assertEqual(segments(xrefs)[1]["ranges"], [[41, 80], [91, 100]])
        self.assertEqual(structures([], 100), {})

    def test_clean_text_drops_evidence(self):
        self.assertEqual(clean_text("FUNCTION: Binds LDLR {ECO:0000269|PubMed:1} (PubMed:2)."),
                         "Binds LDLR.")


class TestAlphaFold(unittest.TestCase):
    TABLE = ("protein_variant,am_pathogenicity,am_class\n"
             "M1A,0.2,LBen\nM1C,0.4,Amb\nK2A,0.9,LPath\nK2E,0.7,LPath\n")

    def test_missense_summary(self):
        self.assertEqual(missense(self.TABLE),
                         {"alphamissense_mean": 0.55, "alphamissense_pathogenic_share": 50.0})
        self.assertEqual(missense("header only\n"), {})

    def test_per_residue_mean(self):
        self.assertEqual(per_residue_missense(self.TABLE), {1: 0.3, 2: 0.8})

    def test_mirror_summary(self):
        r = record()
        self.assertEqual(r.value("alphafold_mean_plddt"), 85.19)
        self.assertEqual(r.value("alphafold_confidence_bands")["very high (90 and above)"], 66.9)
        self.assertEqual(r.value("alphamissense_mean"), 0.376)

    def test_a_model_without_missense_scores_says_so(self):
        r = record("ADH1B")
        self.assertEqual(r["alphamissense_mean"].state, NullState.NOT_FOUND)


class TestChEMBL(unittest.TestCase):
    def test_furthest_phase_first_and_max_phase(self):
        r = record()
        self.assertEqual(r.value("chembl_drugs"), [
            "ALIROCUMAB (approved, inhibitor)", "EVOLOCUMAB (approved, inhibitor)",
            "BOCOCIZUMAB (phase 3, inhibitor)"])
        self.assertEqual(r.value("chembl_max_phase"), 4.0)
        self.assertEqual(r.value("chembl_activities"), 2460)

    def test_no_drugs_is_not_found_not_zero(self):
        fields = summarise("CHEMBL1", 12, [])
        self.assertEqual(fields["chembl_activities"], 12)
        self.assertEqual(fields["chembl_max_phase"].state, NullState.NOT_FOUND)


class TestHpaFiles(unittest.TestCase):
    def test_single_cell_and_its_tau(self):
        r = record()
        self.assertEqual(r.value("hpa_single_cell_ncpm")["hepatocytes"], 120.4)
        tau = r.value("single_cell_tau")
        self.assertGreater(tau, 0.8)  # hepatocytes dominate five cell types

    def test_cell_types_by_tissue_take_the_highest_cluster(self):
        r = record()
        self.assertEqual(r.value("hpa_single_cell_tissue")["liver / hepatocytes"], 131.5)

    def test_partners_from_either_column(self):
        r = record()
        self.assertEqual(r.value("hpa_interactors"), ["LDLR", "SCARB1"])
        self.assertEqual(r.value("hpa_interactions"), 2)

    def test_the_organ_view_gains_a_single_cell_layer(self):
        dogma = align(record())
        keys = [layer["key"] for layer in dogma["layers"]]
        self.assertIn("hpa_sc", keys)
        liver = next(row for row in dogma["rows"] if row["organ"] == "liver")
        members = [m["tissue"] for m in liver["cells"]["hpa_sc"]["members"]]
        self.assertEqual(members, ["liver / hepatocytes", "liver / Kupffer cells"])


if __name__ == "__main__":
    unittest.main()
