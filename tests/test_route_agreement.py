"""What the debug pass found: places where the mirror and the API said
different things about the same gene, or where a file was read wrongly.

Each test pins one rule, so a release that changes its format again shows
up here rather than in a client's report.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spica.build import build_record, phrase, unprefixed
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState
from spica.sources.base import read_tsv, unwrap
from spica.sources.gtex import readable, site_of
from spica.sources.hpa import consensus_name, stain_level, stain_profiles
from spica.sources.uniprot import (function_statements, join_statements, parse_locations,
                                   recommended_name)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class QuotedCellsTest(unittest.TestCase):
    """HGNC's newer files wrap multi-value cells in quotes."""

    def test_a_cell_quoted_at_both_ends_is_unwrapped(self):
        self.assertEqual(unwrap('"p53|LFS1"'), "p53|LFS1")
        self.assertEqual(unwrap('"say ""hi"""'), 'say "hi"')

    def test_a_stray_quote_survives(self):
        self.assertEqual(unwrap('"Hairy" protein'), '"Hairy" protein')
        self.assertEqual(unwrap('"'), '"')

    def test_read_tsv_unwraps(self):
        path = Path(tempfile.mkdtemp()) / "genes.txt"
        path.write_text('symbol\talias_symbol\nTP53\t"p53|LFS1"\n', encoding="utf-8")
        row = next(read_tsv(path))
        self.assertEqual(row["alias_symbol"], "p53|LFS1")


class UniProtTextTest(unittest.TestCase):
    def test_the_recommended_name_alone(self):
        self.assertEqual(recommended_name(
            "Titin (EC 2.7.11.1) (Connectin) (Rhabdomyosarcoma antigen MU-RMS-40.14)"), "Titin")
        self.assertEqual(recommended_name(
            "Insulin [Cleaved into: Insulin B chain; Insulin A chain]"), "Insulin")
        self.assertEqual(recommended_name(
            "Ribosyldihydronicotinamide dehydrogenase [quinone] (EC 1.10.5.1)"),
            "Ribosyldihydronicotinamide dehydrogenase [quinone]")
        self.assertEqual(recommended_name(
            "Gamma-aminobutyric acid receptor subunit alpha-1 (GABA(A) receptor subunit alpha-1)"),
            "Gamma-aminobutyric acid receptor subunit alpha-1")
        self.assertEqual(recommended_name("ATP synthase F(0) complex subunit B1, mitochondrial"),
                         "ATP synthase F(0) complex subunit B1, mitochondrial")

    def test_function_statements_read_the_same_from_either_route(self):
        export = ("FUNCTION: Binds EGF (By similarity). {ECO:0000250}.; FUNCTION: [Isoform 2]: "
                  "May act as an antagonist of EGF action.; FUNCTION: (Microbial infection) "
                  "Acts as a receptor for HCV.")
        api = ["Binds EGF (By similarity).", "May act as an antagonist of EGF action",
               "(Microbial infection) Acts as a receptor for HCV."]
        expected = ("Binds EGF (By similarity). May act as an antagonist of EGF action. "
                    "(Microbial infection) Acts as a receptor for HCV.")
        self.assertEqual(join_statements(function_statements(export)), expected)
        self.assertEqual(join_statements(api), expected)

    def test_a_location_note_is_dropped_whole(self):
        cell = ("SUBCELLULAR LOCATION: Cell membrane; Single-pass type I membrane protein. "
                "Nucleus. Note=In response to EGF, translocated to the nucleus. Endocytosed "
                "upon activation by ligand. Colocalized with GPER1. SUBCELLULAR LOCATION: "
                "[Isoform 2]: Secreted.")
        self.assertEqual(parse_locations(cell), [
            "Cell membrane", "Single-pass type I membrane protein", "Nucleus", "Secreted"])


class HpaNamesTest(unittest.TestCase):
    def test_consensus_tissues_lose_the_sampling_suffix(self):
        self.assertEqual(consensus_name("skin 1"), "skin")
        self.assertEqual(consensus_name("Stomach 1"), "stomach")
        self.assertEqual(consensus_name("heart muscle"), "heart muscle")

    def test_levels_as_the_release_files_write_them(self):
        self.assertEqual(stain_level("not detected"), "Not detected")
        self.assertEqual(stain_level(" high "), "High")

    def test_a_tissue_is_its_strongest_cell_type_on_the_api_route_too(self):
        row = {"Tissue expression cluster": "x",
               "Tissue RNA - skin [nTPM]": "1",
               "Tissue Annotation (IH) - skin": "medium",
               "Tissue Cell type Annotation (IH) - skin 1 - fibrohistiocytic cells": "high",
               "Tissue Cell type Annotation (IH) - skin 2 - melanocytes": "low"}
        out = stain_profiles(row)
        self.assertEqual(out["hpa_protein_tissue_level"]["skin"], "High")
        self.assertEqual(out["hpa_protein_cell_type_level"]["skin 1 / fibrohistiocytic cells"],
                         "High")


class GtexPartsTest(unittest.TestCase):
    LABELS = {"Liver": "Liver", "Colon_Transverse": "Colon - Transverse"}

    def test_a_microdissected_sample_belongs_to_its_site(self):
        self.assertEqual(site_of("Liver_Hepatocyte", self.LABELS), "Liver")
        self.assertEqual(site_of("Colon_Transverse_Mucosa", self.LABELS), "Colon_Transverse")
        self.assertEqual(site_of("Liver", self.LABELS), "")
        self.assertEqual(site_of("Brain_Cortex", self.LABELS), "")  # unlisted, not a part

    def test_parts_are_kept_apart_from_the_profile(self):
        root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, root)
        gct = root / "gtex" / "median_tpm.gct.gz"
        import gzip
        with gzip.open(gct, "rt", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        lines[2] += "\tLiver_Hepatocyte"
        lines[3:] = [line + "\t99.5" for line in lines[3:]]
        with gzip.open(gct, "wt", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        (root / "gtex" / "tissues.tsv").write_text(
            "tissueSiteDetailId\ttissueSiteDetail\nLiver\tLiver\n", encoding="utf-8")
        manifest = json.loads((root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["gtex"]["files"]["tissues"] = "gtex/tissues.tsv"
        (root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        mirror = Mirror.load(root)
        record = build_record("PCSK9", mirror, Live(root, allowed=False))
        self.assertNotIn("Liver (Hepatocyte)", record.value("gtex_tissue_tpm"))
        self.assertEqual(record.value("gtex_microdissected_tpm"), {"Liver (Hepatocyte)": 99.5})
        self.assertEqual(readable("Liver_Hepatocyte", {"Liver": "Liver"}), "Liver (Hepatocyte)")


class WordingTest(unittest.TestCase):
    def test_a_label_in_a_sentence_keeps_its_acronyms(self):
        self.assertEqual(phrase("HPA additional locations"), "HPA additional locations")
        self.assertEqual(phrase("Single-cell RNA, every cell type"),
                         "single-cell RNA, every cell type")
        self.assertEqual(phrase("RNA by tissue"), "RNA by tissue")
        self.assertEqual(phrase("Protein by tissue (antibody)"), "protein by tissue (antibody)")

    def test_a_sentence_naming_the_source_does_not_name_it_twice(self):
        self.assertEqual(phrase(unprefixed("HPA additional locations")), "additional locations")
        self.assertEqual(unprefixed("RNA by tissue"), "RNA by tissue")


class NonCodingTest(unittest.TestCase):
    def test_protein_fields_are_not_covered_for_a_gene_without_a_protein(self):
        from spica import build
        from spica.record import Value
        fields = {"uniprot_accession": Value.missing(
                      NullState.NOT_COVERED, "RNA, long non-coding has no protein product"),
                  "protein_name": Value.missing(NullState.NOT_FOUND, "MALAT1 is not in UniProt"),
                  "chembl_target": Value.missing(NullState.FAILED, "ChEMBL could not be read")}
        build._no_protein(fields)
        self.assertEqual(fields["protein_name"].state, NullState.NOT_COVERED)
        self.assertEqual(fields["protein_name"].reason,
                         "RNA, long non-coding has no protein product")
        self.assertEqual(fields["chembl_target"].state, NullState.FAILED)  # a failure stays one


if __name__ == "__main__":
    unittest.main()
