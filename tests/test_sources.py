"""The file reading and the per-source parsing, away from a whole build."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spica.sources.base import SourceError, read_tsv, split_list
from spica.record import NullState
from spica.sources.base import Absent
from spica.sources.hpa import (RELIABILITY_RANK, ms_profile, split_locations,
                               stain_profiles, strongest)
from spica.sources.uniprot import parse_locations


def write(tmp: str, name: str, text: str) -> Path:
    path = Path(tmp) / name
    path.write_text(text, encoding="utf-8")
    return path


class TestReadTsv(unittest.TestCase):
    def test_rows_are_keyed_by_column_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", "b\ta\nsecond\tfirst\n")
            rows = list(read_tsv(path, ("a",)))
        self.assertEqual(rows, [{"a": "first", "b": "second"}])

    def test_a_missing_required_column_is_an_error_not_a_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", "b\tc\n1\t2\n")
            with self.assertRaises(SourceError) as caught:
                list(read_tsv(path, ("a",)))
        self.assertIn("no a column", str(caught.exception))

    def test_an_empty_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", "")
            with self.assertRaises(SourceError):
                list(read_tsv(path))

    def test_short_rows_are_padded_and_blank_lines_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", "a\tb\tc\n1\t2\n\n3\t4\t5\n")
            rows = list(read_tsv(path))
        self.assertEqual(rows[0], {"a": "1", "b": "2", "c": ""})
        self.assertEqual(len(rows), 2)

    def test_a_byte_order_mark_does_not_rename_the_first_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", "﻿Gene\tLevel\nPCSK9\tHigh\n")
            rows = list(read_tsv(path, ("Gene",)))
        self.assertEqual(rows[0]["Gene"], "PCSK9")

    def test_quotes_in_a_cell_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.tsv", 'a\tb\n"quoted" name\t2\n')
            rows = list(read_tsv(path))
        self.assertEqual(rows[0]["a"], '"quoted" name')

    def test_split_list_keeps_order_and_drops_blanks(self):
        self.assertEqual(split_list("NARC1| HCHOLA3 ||"), ["NARC1", "HCHOLA3"])


class TestUniProtLocations(unittest.TestCase):
    def test_evidence_tags_and_notes_are_dropped(self):
        cell = ("SUBCELLULAR LOCATION: Secreted {ECO:0000269|PubMed:14703719}; "
                "Endoplasmic reticulum lumen. Note=Autocatalytic cleavage is required.")
        self.assertEqual(parse_locations(cell), ["Secreted", "Endoplasmic reticulum lumen"])

    def test_topology_is_kept(self):
        cell = "SUBCELLULAR LOCATION: Cell membrane; Single-pass type I membrane protein."
        self.assertEqual(
            parse_locations(cell), ["Cell membrane", "Single-pass type I membrane protein"]
        )

    def test_isoform_markers_are_dropped_and_repeats_collapse(self):
        cell = ("SUBCELLULAR LOCATION: [Isoform 1]: Nucleus. "
                "SUBCELLULAR LOCATION: [Isoform 2]: Nucleus. Cytoplasm.")
        self.assertEqual(parse_locations(cell), ["Nucleus", "Cytoplasm"])

    def test_an_empty_cell_gives_nothing(self):
        self.assertEqual(parse_locations(""), [])


class TestHpaHelpers(unittest.TestCase):
    def test_locations_split_on_either_separator(self):
        self.assertEqual(
            split_locations("Golgi apparatus;Vesicles"), ["Golgi apparatus", "Vesicles"]
        )
        self.assertEqual(
            split_locations("Nucleoplasm, Cytosol"), ["Nucleoplasm", "Cytosol"]
        )

    def test_strongest_keeps_the_releases_spelling(self):
        self.assertEqual(
            strongest(["Approved", "Enhanced", "Uncertain"], RELIABILITY_RANK), "Enhanced"
        )

    def test_strongest_of_nothing_rankable_is_empty(self):
        self.assertEqual(strongest(["", "Unknown"], RELIABILITY_RANK), "")


class TestHpaProfiles(unittest.TestCase):
    """Download-API rows, shaped as HPA answered them for CLDN18."""

    ROW = {
        "Tissue Annotation (IH) - liver": "not detected",
        "Tissue Annotation (IH) - lung": "medium",
        "Tissue Annotation (IH) - stomach": "high",
        "Tissue Annotation (IH) - kidney": None,
        "Tissue Cell type Annotation (IH) - lung - alveolar cells type I": "low",
        "Tissue Cell type Annotation (IH) - lung - alveolar cells type II": "medium",
        "Tissue Cell type Annotation (IH) - lung - alveolar cells": None,
        "Tissue Cell type Annotation (IH) - stomach 1 - glandular cells": "high",
        "Tissue protein MS - lung [Intensity]": "7482438.2",
        "Tissue protein MS - Stomach [Intensity]": "120.5",
        "Tissue protein MS - liver [Intensity]": None,
    }

    def test_staining_keeps_not_detected_and_drops_unstained(self):
        out = stain_profiles(self.ROW)
        self.assertEqual(out["hpa_protein_tissue_level"],
                         {"liver": "Not detected", "lung": "Medium", "stomach": "High"})
        # Levels as the release files write them, so both routes agree.
        self.assertEqual(out["hpa_protein_cell_type_level"], {
            "lung / alveolar cells type I": "Low",
            "lung / alveolar cells type II": "Medium",
            "stomach 1 / glandular cells": "High",
        })

    def test_no_staining_at_all_is_not_found(self):
        out = stain_profiles({"Tissue Annotation (IH) - liver": None})
        self.assertIsInstance(out["hpa_protein_tissue_level"], Absent)
        self.assertEqual(out["hpa_protein_tissue_level"].state, NullState.NOT_FOUND)

    def test_mass_spec_records_not_detected_as_zero(self):
        out = ms_profile(self.ROW)["hpa_protein_tissue_intensity"]
        self.assertEqual(out, {"lung": 7482438.2, "stomach": 120.5, "liver": 0.0})

    def test_mass_spec_detected_nowhere_is_not_found(self):
        out = ms_profile({"Tissue protein MS - liver [Intensity]": None})
        self.assertEqual(out["hpa_protein_tissue_intensity"].state, NullState.NOT_FOUND)
        self.assertEqual(ms_profile({"unrelated": 1}), {})


if __name__ == "__main__":
    unittest.main()
