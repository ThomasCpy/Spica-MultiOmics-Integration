"""The real mirror: the byte index over large files, and the HPA 25 formats.

The tests force the index on small files (`SMALL` patched to 0). Each path
of a 1.5 GB file thus runs on a few lines. HPA 25 renamed some columns and
dropped others. A mirror built today has those files, and the fixtures have
the older shape, so both are tested.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.sources import hpa as hpa_module
from spica.sources import index as index_module
from spica.sources.base import SourceError
from spica.sources.gtex import readable
from spica.sources.index import lines_for, rows_for
from spica.sources.uniprot import pdb_xrefs, segments, structures

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"

TSV = (
    "﻿Gene\tTissue\tValue\n"
    "G1\tliver\t1\n"
    "G1\tlung\t2\n"
    "G2\tliver\t3\n"
    "G3\tbrain\t4\n"
    "G1\tskin\t5\n"  # G1 again, out of its group: two ranges
    "G4\tliver\n"  # a short row, padded
)


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(index_module, "SMALL", 0),
                        mock.patch.dict(os.environ, {"SPICA_DATA_DIR": str(self.folder / "data")})]
        for patch in self.patches:
            patch.start()
        index_module._memory.clear()
        self.path = self.folder / "table.tsv"
        self.path.write_bytes(TSV.encode("utf-8"))

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        index_module._memory.clear()

    def test_rows_of_one_key_including_a_split_group(self):
        rows = list(rows_for(self.path, "Gene", "G1", ("Gene", "Tissue", "Value")))
        self.assertEqual([row["Tissue"] for row in rows], ["liver", "lung", "skin"])
        self.assertEqual(rows[0]["Value"], "1")

    def test_same_answer_as_a_scan(self):
        with mock.patch.object(index_module, "SMALL", 10 ** 9):
            scanned = {key: list(rows_for(self.path, "Gene", key)) for key in ("G1", "G2", "G4")}
        for key, rows in scanned.items():
            self.assertEqual(list(rows_for(self.path, "Gene", key)), rows)

    def test_a_short_row_is_padded_and_an_absent_key_is_empty(self):
        self.assertEqual(list(rows_for(self.path, "Gene", "G4")),
                         [{"Gene": "G4", "Tissue": "liver", "Value": ""}])
        self.assertEqual(list(rows_for(self.path, "Gene", "G9")), [])

    def test_a_missing_column_is_an_error_not_an_empty_answer(self):
        with self.assertRaisesRegex(SourceError, "nTPM"):
            list(rows_for(self.path, "Gene", "G1", ("Gene", "nTPM")))

    def test_the_index_is_kept_and_rebuilt_when_the_file_changes(self):
        list(rows_for(self.path, "Gene", "G1"))
        stored = list((self.folder / "data" / "cache" / "index").glob("table-*.json"))
        self.assertEqual(len(stored), 1)
        index_module._memory.clear()
        self.path.write_bytes((TSV + "G5\tlung\t9\n").encode("utf-8"))
        self.assertEqual(len(list(rows_for(self.path, "Gene", "G5"))), 1)
        self.assertEqual(len(list((self.folder / "data" / "cache" / "index").glob("*.json"))), 2)

    def test_json_lines_by_field(self):
        path = self.folder / "targets.jsonl"
        lines = [{"accession": "P1", "n": 1}, {"accession": "P2", "n": 2},
                 {"n": 3, "accession": "P3"}]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        found = [json.loads(line) for line in lines_for(path, "accession", "P3")]
        self.assertEqual(found, [{"n": 3, "accession": "P3"}])
        self.assertEqual(list(lines_for(path, "accession", "P9")), [])

    def test_a_gzipped_file_is_scanned(self):
        path = self.folder / "table.tsv.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(TSV)
        self.assertFalse(index_module.indexable(path))
        self.assertEqual(len(list(rows_for(path, "Gene", "G1"))), 3)


class Hpa25Test(unittest.TestCase):
    """A mirror built from HPA 25: nCPM for single cell, the interaction file
    with IDs only, and the mass-spectrometry file listing detections."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        hpa = self.root / "hpa"
        for name in ("rna_single_cell_type.tsv", "rna_single_cell_type_tissue.tsv"):
            text = (hpa / name).read_text(encoding="utf-8")
            (hpa / name).write_text(text.replace("\tnTPM\n", "\tnCPM\n", 1), encoding="utf-8")
        (hpa / "interaction_consensus.tsv").write_text(
            "ensembl_gene_id_1\tensembl_gene_id_2\tdatasets\n"
            "ENSG00000169174\tENSG00000130164\tintact_biogrid\n"
            "ENSG00000073060\tENSG00000169174\tbiogrid\n", encoding="utf-8")
        consensus = (hpa / "rna_tissue_consensus.tsv").read_text(encoding="utf-8")
        (hpa / "rna_tissue_consensus.tsv").write_text(
            consensus + "ENSG00000130164\tLDLR\tliver\t80.0\n"
                        "ENSG00000073060\tSCARB1\tliver\t60.0\n", encoding="utf-8")
        (hpa / "ms_tissue.tsv").write_text(
            "Gene\tGene name\tTissue\tIntensity\n"
            "ENSG00000000003\tTSPAN6\tkidney\t1500\n"
            "ENSG00000000003\tTSPAN6\tblood vessel\t\n"
            "ENSG00000169174\tPCSK9\tliver\t250000\n", encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["hpa"]["version"] = "25.1"
        manifest["sources"]["hpa"]["files"]["ms_tissue"] = "hpa/ms_tissue.tsv"
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        hpa_module._CACHE.clear()

    def tearDown(self):
        hpa_module._CACHE.clear()

    def record(self):
        mirror = Mirror.load(self.root)
        return build_record("PCSK9", mirror, Live(mirror.root, allowed=False))

    def test_single_cell_reads_ncpm(self):
        self.assertEqual(hpa_module._unit_column(self.root / "hpa" / "rna_single_cell_type.tsv"),
                         "nCPM")
        record = self.record()
        self.assertEqual(record.value("hpa_single_cell_ncpm")["hepatocytes"], 120.4)
        self.assertEqual(record.value("hpa_single_cell_tissue")["liver / hepatocytes"], 131.5)

    def test_partners_are_named_from_the_consensus_file(self):
        record = self.record()
        self.assertEqual(sorted(record.value("hpa_interactors")), ["LDLR", "SCARB1"])
        self.assertEqual(record.value("hpa_interactions"), 2)

    def test_tissues_without_a_detection_read_zero(self):
        profile = self.record().value("hpa_protein_tissue_intensity")
        self.assertEqual(profile["liver"], 250000.0)
        self.assertEqual(profile["kidney"], 0.0)  # assayed for another protein
        self.assertEqual(profile["blood vessel"], 0.0)


class GtexNamesTest(unittest.TestCase):
    LABELS = {"Liver": "Liver", "Colon_Transverse": "Colon - Transverse",
              "Small_Intestine_Terminal_Ileum": "Small Intestine - Terminal Ileum",
              "Cells_Cultured_fibroblasts": "Cells - Cultured fibroblasts"}

    def test_named_sites_take_the_gtex_name(self):
        self.assertEqual(readable("Cells_Cultured_fibroblasts", self.LABELS),
                         "Cells - Cultured fibroblasts")

    def test_microdissected_samples_take_their_site_name(self):
        self.assertEqual(readable("Liver_Hepatocyte", self.LABELS), "Liver (Hepatocyte)")
        self.assertEqual(readable("Colon_Transverse_Mucosa", self.LABELS),
                         "Colon - Transverse (Mucosa)")
        self.assertEqual(readable("Small_Intestine_Terminal_Ileum_Lymphode_Aggregate", self.LABELS),
                         "Small Intestine - Terminal Ileum (Lymphode Aggregate)")

    def test_without_a_list_the_id_is_spaced(self):
        self.assertEqual(readable("Adipose_Subcutaneous"), "Adipose Subcutaneous")

    def test_the_mirror_list_is_used_and_nothing_else(self):
        root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, root)
        (root / "gtex" / "tissues.tsv").write_text(
            "tissueSiteDetailId\ttissueSiteDetail\nLiver\tLiver\n"
            "Kidney_Cortex\tKidney - Cortex\n", encoding="utf-8")
        manifest = json.loads((root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["gtex"]["files"]["tissues"] = "gtex/tissues.tsv"
        (root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        mirror = Mirror.load(root)
        tissues = build_record("PCSK9", mirror, Live(root, allowed=False)).value("gtex_tissue_tpm")
        self.assertIn("Kidney - Cortex", tissues)
        self.assertIn("Brain Cortex", tissues)  # not in the list: spaced, not guessed


class PdbColumnTest(unittest.TestCase):
    CELL = ('"2P4E; X-ray; 1.98 A; A/P=1-692.";"2PMW; X-ray; 2.30 A; A=31-152, B=153-692.";'
            '"6U26; EM; -; A=1-100.";')

    def test_full_column_parses_like_the_api(self):
        xrefs = pdb_xrefs(self.CELL)
        self.assertEqual([x["id"] for x in xrefs], ["2P4E", "2PMW", "6U26"])
        summary = structures(xrefs, 692)
        self.assertEqual(summary, {"pdb_structures": 3, "pdb_best_resolution": 1.98,
                                   "pdb_coverage": 100.0})
        self.assertEqual(segments(xrefs)[1]["ranges"], [[31, 152], [153, 692]])
        self.assertIsNone(segments(xrefs)[2]["resolution"])

    def test_an_ids_only_column_gives_nothing_to_parse(self):
        self.assertEqual(pdb_xrefs("2P4E;2PMW;"), [])


if __name__ == "__main__":
    unittest.main()
