"""Whole records, built against the fixture mirror."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica.build import build_record, summarize
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState
from spica.schema import FIELD_NAMES
from spica.sources import SOURCES_BY_KEY

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


def mirror() -> Mirror:
    return Mirror.load(FIXTURE)


# Every test here is about the mirror, so the API fallback is switched off:
# a unit test must never depend on someone else's server being up. The
# fallback has its own tests, against a stub, in test_live.py.
OFFLINE = Live(FIXTURE, allowed=False)


def build(query: str, source: Mirror | None = None):
    return build_record(query, mirror() if source is None else source, OFFLINE)


def edited_manifest(tmp: str, edit) -> Mirror:
    """A mirror whose manifest is the fixture's, put through `edit`.

    The file paths are rewritten to absolute ones into the fixture, so a
    variant manifest needs no copy of the data.
    """
    body = json.loads((FIXTURE / "mirror.json").read_text(encoding="utf-8"))
    for source in body["sources"].values():
        source["files"] = {
            name: str(FIXTURE / relative) for name, relative in source["files"].items()
        }
    edit(body)
    (Path(tmp) / "mirror.json").write_text(json.dumps(body), encoding="utf-8")
    return Mirror.load(tmp)


class TestCompleteRecord(unittest.TestCase):
    """PCSK9 is in every fixture file."""

    @classmethod
    def setUpClass(cls):
        cls.record = build("PCSK9", mirror())

    def test_the_record_has_every_field_in_schema_order(self):
        self.assertEqual(tuple(self.record.fields), FIELD_NAMES)

    def test_identity_comes_from_hgnc(self):
        self.assertTrue(self.record.resolution.resolved)
        self.assertEqual(self.record.resolution.matched_on, "approved symbol")
        self.assertEqual(self.record.value("hgnc_id"), "HGNC:20001")
        self.assertEqual(self.record.value("symbol"), "PCSK9")
        self.assertEqual(self.record.value("aliases"), ["NARC1", "HCHOLA3"])
        self.assertEqual(self.record.value("previous_symbols"), ["NARC1"])
        self.assertEqual(self.record.value("chromosomal_location"), "1p32.3")
        self.assertEqual(self.record.value("ensembl_gene_id"), "ENSG00000169174")
        self.assertEqual(self.record.value("uniprot_accession"), "Q8NBP7")

    def test_every_value_carries_its_release(self):
        provenance = self.record["symbol"].provenance
        self.assertEqual(provenance.source, "HGNC")
        self.assertEqual(provenance.version, "2026-09-01")
        self.assertEqual(provenance.retrieved, "2026-10-20")
        self.assertEqual(provenance.locator, "hgnc/hgnc_complete_set.txt")

    def test_ensembl_gives_biotype_and_a_located_assembly(self):
        self.assertEqual(self.record.value("gene_biotype"), "protein_coding")
        self.assertEqual(
            self.record.value("genomic_location"), "GRCh38.p14 1:55039447-55064852 (+)"
        )

    def test_uniprot_gives_the_reviewed_entry_not_the_fragment(self):
        self.assertEqual(self.record.value("protein_length"), 49)
        self.assertTrue(self.record.value("protein_sequence").startswith("MGTVSSRRSWW"))
        self.assertEqual(
            self.record.value("uniprot_subcellular_locations"),
            ["Secreted", "Endoplasmic reticulum lumen"],
        )

    def test_gtex_values_and_their_median(self):
        tpm = self.record.value("gtex_tissue_tpm")
        self.assertEqual(tpm["Liver"], 77.41)
        self.assertEqual(len(tpm), 5)
        self.assertEqual(self.record.value("gtex_median_across_tissues"), 9.82)

    def test_the_derived_field_names_its_inputs_in_the_provenance(self):
        self.assertEqual(self.record.value("gtex_max_tissue"), "Liver")
        provenance = self.record["gtex_max_tissue"].provenance
        self.assertEqual(provenance.source, "GTEx")
        self.assertEqual(provenance.version, "v11")
        self.assertIn("derived from gtex_tissue_tpm", provenance.locator)

    def test_hpa_takes_the_strongest_staining_in_each_tissue(self):
        levels = self.record.value("hpa_protein_tissue_level")
        self.assertEqual(levels["liver"], "High")  # hepatocytes High, bile duct Low
        self.assertEqual(levels["cerebral cortex"], "Not detected")
        self.assertEqual(self.record.value("hpa_protein_reliability"), "Enhanced")

    def test_hpa_localization_is_split_and_pointed_at_its_own_file(self):
        self.assertEqual(
            self.record.value("hpa_subcellular_main"), ["Golgi apparatus", "Vesicles"]
        )
        self.assertEqual(self.record.value("hpa_subcellular_additional"), ["Nucleoplasm"])
        self.assertEqual(
            self.record["hpa_subcellular_main"].provenance.locator,
            "hpa/subcellular_location.tsv",
        )

    def test_nothing_is_left_unfilled_without_a_reason(self):
        for name, value in self.record.fields.items():
            if not value.present:
                self.assertTrue(value.reason, name)

    def test_the_same_mirror_gives_the_same_record(self):
        self.assertEqual(
            self.record.fingerprint(), build("PCSK9", mirror()).fingerprint()
        )

    def test_the_summary_line(self):
        self.assertIn("PCSK9 (HGNC:20001)", summarize(self.record))


class TestPartialCoverage(unittest.TestCase):
    def test_a_gene_absent_from_a_source_is_not_found_with_the_release_named(self):
        record = build("ADH1B", mirror())  # in HGNC, Ensembl, UniProt only
        # The recommended name only: "[NAD(+)]" is part of it, the EC number
        # that follows in the export is not.
        self.assertEqual(record.value("protein_name"),
                         "All-trans-retinol dehydrogenase [NAD(+)] ADH1B")

        gtex = record["gtex_tissue_tpm"]
        self.assertEqual(gtex.state, NullState.NOT_FOUND)
        self.assertIn("GTEx v11", gtex.reason)
        self.assertEqual(gtex.provenance.version, "v11")

        self.assertEqual(record["hpa_protein_tissue_level"].state, NullState.NOT_FOUND)
        self.assertEqual(record["gtex_max_tissue"].state, NullState.NOT_FOUND)
        self.assertIn("RNA by tissue", record["gtex_max_tissue"].reason)

    def test_a_field_a_source_cannot_cover_is_not_covered(self):
        record = build("MALAT1", mirror())  # long non-coding, no protein
        accession = record["uniprot_accession"]
        self.assertEqual(accession.state, NullState.NOT_COVERED)
        self.assertIn("no protein product", accession.reason)
        self.assertEqual(record.value("gene_biotype"), "lncRNA")
        self.assertEqual(record.value("gtex_max_tissue"), "Brain Cortex")

    def test_an_unrankable_staining_level_is_left_out(self):
        record = build("MALAT1", mirror())  # its only HPA row is "Ascending"
        level = record["hpa_protein_tissue_level"]
        self.assertFalse(level.present)
        # Left with nothing, and MALAT1 makes no protein: not covered, in
        # HGNC's words, rather than a gap in HPA.
        self.assertEqual(level.state, NullState.NOT_COVERED)
        self.assertIn("no protein product", level.reason)

    def test_a_source_missing_from_the_manifest_fails_only_its_own_fields(self):
        def only_identity(body):
            body["sources"] = {
                key: value
                for key, value in body["sources"].items()
                if key in ("hgnc", "ensembl")
            }

        with tempfile.TemporaryDirectory() as tmp:
            record = build("PCSK9", edited_manifest(tmp, only_identity))
        self.assertEqual(record.value("symbol"), "PCSK9")
        self.assertEqual(record.value("gene_biotype"), "protein_coding")

        sequence = record["protein_sequence"]
        self.assertEqual(sequence.state, NullState.FAILED)
        self.assertIn("UniProt is not in the mirror manifest", sequence.reason)
        self.assertIn("API not reached", sequence.reason)
        self.assertEqual(
            [s.status for s in record.sources if s.key == "uniprot"], ["unavailable"]
        )

    def test_half_of_hpa_is_better_than_none(self):
        def drop_localization(body):
            body["sources"]["hpa"]["files"].pop("subcellular_location")

        with tempfile.TemporaryDirectory() as tmp:
            record = build("PCSK9", edited_manifest(tmp, drop_localization))
        self.assertEqual(record.value("hpa_protein_tissue_level")["liver"], "High")
        main = record["hpa_subcellular_main"]
        self.assertEqual(main.state, NullState.FAILED)
        self.assertIn("declares no HPA subcellular_location file", main.reason)


class TestResolution(unittest.TestCase):
    def test_an_alias_resolves_and_says_so(self):
        record = build("NEAT2", mirror())
        self.assertEqual(record.resolution.symbol, "MALAT1")
        self.assertEqual(record.resolution.matched_on, "alias symbol")
        self.assertIn("Matched on alias symbol", summarize(record))

    def test_a_previous_symbol_beats_an_alias_of_the_same_gene(self):
        record = build("NARC1", mirror())  # both for PCSK9
        self.assertEqual(record.resolution.symbol, "PCSK9")
        self.assertEqual(record.resolution.matched_on, "previous symbol")

    def test_identifiers_resolve_in_the_forms_people_paste(self):
        for query, matched_on in (
            ("hgnc:20001", "HGNC ID"),
            ("20001", "HGNC ID"),
            ("ENSG00000169174.11", "Ensembl gene ID"),
            ("q8nbp7", "UniProt accession"),
            ("255738", "Entrez ID"),
            ("  pcsk9  ", "approved symbol"),
        ):
            with self.subTest(query=query):
                record = build(query, mirror())
                self.assertEqual(record.resolution.symbol, "PCSK9")
                self.assertEqual(record.resolution.matched_on, matched_on)

    def test_a_withdrawn_entry_does_not_resolve(self):
        record = build("WITHDRAWNX", mirror())
        self.assertFalse(record.resolution.resolved)

    def test_an_unknown_gene_is_not_found_everywhere_and_asks_nothing_else(self):
        record = build("ZZZZ9", mirror())
        self.assertFalse(record.resolution.resolved)
        self.assertIn("No approved HGNC gene matches ZZZZ9", record.resolution.reason)
        self.assertEqual(
            {value.state for value in record.fields.values()}, {NullState.NOT_FOUND}
        )
        from spica.sources import RESOLVER, SOURCES
        skipped = [s.key for s in record.sources if s.status == "skipped"]
        self.assertEqual(sorted(skipped),
                         sorted(s.key for s in SOURCES if s.key != RESOLVER.key))

    def test_an_ambiguous_alias_is_reported_not_guessed(self):
        header = ("hgnc_id\tsymbol\tname\tlocus_type\tstatus\talias_symbol\n")
        rows = ("HGNC:1\tAAA\tfirst\tgene with protein product\tApproved\tSHARED\n"
                "HGNC:2\tBBB\tsecond\tgene with protein product\tApproved\tSHARED\n")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "hgnc").mkdir()
            (Path(tmp) / "hgnc" / "set.txt").write_text(header + rows, encoding="utf-8")
            body = {"sources": {"hgnc": {"label": "HGNC", "version": "1",
                                         "retrieved": "2026-10-20",
                                         "files": {"complete_set": "hgnc/set.txt"}}}}
            (Path(tmp) / "mirror.json").write_text(json.dumps(body), encoding="utf-8")
            record = build("SHARED", Mirror.load(tmp))

        self.assertFalse(record.resolution.resolved)
        self.assertEqual(record.resolution.candidates, ("AAA (HGNC:1)", "BBB (HGNC:2)"))
        self.assertIn("Gene selection required", record.resolution.reason)

    def test_an_empty_query_asks_for_one(self):
        record = build("   ", mirror())
        self.assertEqual(record.resolution.reason, "No gene entered.")
        self.assertEqual(summarize(record), "No gene entered.")


class TestNoMirror(unittest.TestCase):
    def test_everything_fails_and_the_message_names_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build("PCSK9", Mirror.load(tmp))
        self.assertFalse(record.resolution.resolved)
        self.assertIn("No mirror manifest", record.resolution.reason)
        self.assertIn("HGNC API could not be reached", record.resolution.reason)
        self.assertEqual(
            {value.state for value in record.fields.values()}, {NullState.FAILED}
        )
        self.assertEqual(tuple(record.fields), FIELD_NAMES)


class TestBrokenSource(unittest.TestCase):
    def test_an_adapter_that_raises_costs_only_its_own_fields(self):
        with mock.patch.object(
            SOURCES_BY_KEY["gtex"], "collect", side_effect=RuntimeError("disk gone")
        ):
            record = build("PCSK9", mirror())
        self.assertEqual(record.value("symbol"), "PCSK9")
        self.assertEqual(record["gtex_tissue_tpm"].state, NullState.FAILED)
        self.assertIn("disk gone", record["gtex_tissue_tpm"].reason)
        self.assertEqual([s.status for s in record.sources if s.key == "gtex"], ["failed"])

    def test_a_value_of_the_wrong_type_is_caught_before_it_reaches_the_record(self):
        with mock.patch.object(
            SOURCES_BY_KEY["gtex"], "collect",
            return_value={"gtex_median_across_tissues": "9.82"},
        ):
            record = build("PCSK9", mirror())
        value = record["gtex_median_across_tissues"]
        self.assertEqual(value.state, NullState.FAILED)
        self.assertIn("unusable", value.reason)

    def test_a_derived_field_follows_its_input_into_failure(self):
        with mock.patch.object(
            SOURCES_BY_KEY["gtex"], "collect", side_effect=RuntimeError("disk gone")
        ):
            record = build("PCSK9", mirror())
        self.assertEqual(record["gtex_max_tissue"].state, NullState.FAILED)


if __name__ == "__main__":
    unittest.main()
