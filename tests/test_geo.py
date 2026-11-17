"""GEO: records read into samples in context, files sorted into tracks,
text tracks read over a window (GRCh37 shifted onto GRCh38), and the table
row of a gene matched to its samples."""

import unittest
from unittest import mock

from spica.genome.locus import Locus
from spica.geo import records, response, search, tracks

SERIES = """^SERIES = GSE1
!Series_title = NRF2 ChIP-seq after sulforaphane
!Series_geo_accession = GSE1
!Series_summary = A summary.
!Series_overall_design = ChIP of NRF2, treated or vehicle.
!Series_type = Genome binding/occupancy profiling by high throughput sequencing
!Series_pubmed_id = 123
!Series_contact_email = someone@example.org
!Series_contact_name = Some,,One
!Series_sample_id = GSM1
!Series_sample_id = GSM2
!Series_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE1nnn/GSE1/suppl/GSE1_counts.txt.gz
!Series_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE1nnn/GSE1/suppl/GSM2_vehicle_hg19.bw
"""

SAMPLES = """^SAMPLE = GSM1
!Sample_title = HepG2 NRF2 SFN rep1
!Sample_geo_accession = GSM1
!Sample_source_name_ch1 = HepG2
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = cell line: HepG2
!Sample_characteristics_ch1 = treatment: sulforaphane
!Sample_library_strategy = ChIP-Seq
!Sample_data_processing = Reads aligned to hg38 with bowtie2.
!Sample_supplementary_file_1 = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM1nnn/GSM1/suppl/GSM1_peaks.narrowPeak.gz
!Sample_supplementary_file_2 = NONE
!Sample_contact_phone = 555
^SAMPLE = GSM2
!Sample_title = HepG2 NRF2 vehicle rep1
!Sample_geo_accession = GSM2
!Sample_source_name_ch1 = HepG2
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = cell line: HepG2
!Sample_characteristics_ch1 = treatment: vehicle
!Sample_library_strategy = ChIP-Seq
!Sample_data_processing = Genome_build: hg19
"""


class FakeLive:
    def __init__(self, texts):
        self.texts, self.allowed = texts, True

    def get_text(self, source, url):
        for marker, text in self.texts.items():
            if marker in url:
                return mock.Mock(payload=text)
        raise AssertionError(url)


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.found = records.read("GSE1", FakeLive({"targ=self": SERIES, "targ=gsm": SAMPLES}))

    def test_people_are_never_read_in(self):
        flat = repr(self.found)
        self.assertNotIn("someone@example.org", flat)
        self.assertNotIn("555", flat)

    def test_samples_carry_their_context(self):
        first, second = self.found["samples"]
        self.assertEqual(first["characteristics"], {"cell line": "HepG2", "treatment": "sulforaphane"})
        self.assertEqual((first["assembly"], second["assembly"]), ("GRCh38", "GRCh37"))
        self.assertEqual(second["arm"], "control")
        self.assertEqual(first["arm"], "")

    def test_files_are_sorted_into_what_can_be_drawn(self):
        peaks = self.found["samples"][0]["files"][0]
        self.assertEqual((peaks["kind"], peaks["assembly"], peaks["track"]), ("peaks", "GRCh38", True))
        self.assertTrue(peaks["url"].startswith("https://ftp.ncbi.nlm.nih.gov/geo/samples/"))
        table, bigwig = self.found["files"]
        self.assertEqual((table["kind"], table["track"]), ("matrix", False))
        self.assertEqual((bigwig["sample"], bigwig["assembly"]), ("GSM2", "GRCh37"))
        self.assertEqual(self.found["counts"], {"samples": 2, "human": 2, "files": 3, "tracks": 2, "matrices": 1,
                                                    "sheets": 0})

    def test_only_fields_that_differ_are_facets(self):
        self.assertEqual([f["field"] for f in self.found["facets"]], ["treatment"])

    def test_an_accession_that_is_not_a_series_is_refused(self):
        with self.assertRaises(ValueError):
            records.read("GSM1", FakeLive({}))

    def test_builds_as_people_write_them(self):
        self.assertEqual(records.build("x_hg19.bw"), "GRCh37")
        self.assertEqual(records.build("aligned to GRCh38.p13"), "GRCh38")
        self.assertEqual(records.build("mm10 peaks"), "mouse")
        self.assertEqual(records.build("no build here"), "")


class TextTrackTest(unittest.TestCase):
    def test_bed_and_wig_lines_inside_the_window_shifted_onto_grch38(self):
        wanted = [("chr1", 1000, 2000, 500)]  # GRCh37 1000..2000 is GRCh38 1500..2500
        bed = ["track name=x", "chr1\t900\t1100\tpeak1\t10", "1\t1500\t1600\tpeak2", "chr2\t1500\t1600\tother"]
        shape, rows = tracks.parse_text(iter(bed), "bed", wanted)
        self.assertEqual(shape, "bed")
        self.assertEqual([(s, e, r[0]) for s, e, r in rows], [(1500, 1600, "peak1"), (2000, 2100, "peak2")])
        wig = ["variableStep chrom=chr1 span=10", "1201 3.5", "fixedStep chrom=chr1 start=1301 step=100 span=50", "1", "2"]
        shape, rows = tracks.parse_text(iter(wig), "wig", wanted)
        self.assertEqual(shape, "wig")
        self.assertEqual(rows, [(1700, 1710, 3.5), (1800, 1850, 1.0), (1900, 1950, 2.0)])

    def test_grch38_needs_no_mapping_and_hg18_is_refused(self):
        locus = Locus("G", "E", "chr1", 100, 200, "+", 1000, 0, 1000)
        self.assertEqual(tracks.blocks(locus, "GRCh38", live=None), [("chr1", 0, 1000, 0)])
        with self.assertRaises(tracks.GeoTrackError):
            tracks.blocks(locus, "NCBI36", live=None)

    def test_grch37_is_mapped_through_ensembl(self):
        locus = Locus("G", "E", "chr1", 100, 200, "+", 10_000, 1000, 3000)
        live = mock.Mock()
        live.get_json.return_value.payload = {"mappings": [{
            "original": {"seq_region_name": "1", "start": 1001, "end": 3000, "strand": 1},
            "mapped": {"seq_region_name": "1", "start": 801, "end": 2800, "strand": 1}}]}
        self.assertEqual(tracks.blocks(locus, "GRCh37", live), [("chr1", 800, 2800, 200)])


class ResponseTest(unittest.TestCase):
    SAMPLES = [{"accession": f"GSM{i}", "title": t, "characteristics": {"treatment": tr}, "arm": ""}
               for i, (t, tr) in enumerate([("PT10_Control_1", "Control"), ("PT10_10uM_OTA_1", "OTA"),
                                             ("PT10_20uM_SFN2_1", "SFN"), ("PT10_10uM_OTA+20uM_SFN2_1", "OTA+SFN")])]

    def test_shortened_column_names_find_their_samples(self):
        self.assertTrue(response.abbreviates("PT10_C1", "PT10_Control_1"))
        self.assertTrue(response.abbreviates("SO2", "SFN_OTA_2"))
        self.assertFalse(response.abbreviates("PT10_C1", "PT10_10uM_OTA_1"))

    def test_the_shortest_fitting_title_wins_and_order_fills_the_rest(self):
        header = ["gene", "PT10_C1", "PT10_O1", "PT10_S1", "PT10_SO1"]
        cells = ["ALB", "10", "12", "20", "18"]
        columns = response.match_columns(header, cells, self.SAMPLES)
        self.assertEqual([c["sample"] for c in columns], ["GSM0", "GSM1", "GSM2", "GSM3"])
        self.assertEqual(columns[0]["matched_by"], "abbreviation")
        self.assertIn(columns[3]["matched_by"], ("abbreviation", "order"))

    def test_order_is_not_trusted_when_a_named_column_contradicts_it(self):
        header = ["gene", "PT10_O1", "PT10_C1", "x", "y"]
        columns = response.match_columns(header, ["ALB", "1", "2", "3", "4"], self.SAMPLES)
        self.assertEqual(columns[0]["sample"], "GSM1")
        self.assertEqual(columns[2]["sample"], "")

    def test_the_row_is_found_by_any_name_and_grouped(self):
        lines = iter(["id\tsymbol\ta\tb", "ENSG00000163631.17\tALB\t5\t7", "ENSG1\tOTHER\t1\t1"])
        header, cells = response.find_row(lines, {"ALB", "ENSG00000163631"})
        self.assertEqual(cells[1], "ALB")
        columns = [{"value": 1.0, "context": {"treatment": "A"}}, {"value": 3.0, "context": {"treatment": "A"}},
                   {"value": 10.0, "context": {"treatment": "B"}}]
        grouped = response.groups(columns, [{"field": "treatment"}])
        self.assertEqual([(g["value"], g["mean"], g["samples"]) for g in grouped[0]["groups"]],
                         [("B", 10.0, 1), ("A", 2.0, 2)])


class SearchTest(unittest.TestCase):
    def test_the_expression_keeps_to_series_and_the_filters(self):
        text = search.query(["NFE2L2", "NRF2", "NFE2 like bZIP", "NRF2 ChIP-seq"], human=True, tracks=True,
                            phrases={"NFE2 like bZIP"})
        self.assertIn('(NFE2L2 OR NRF2 OR "NFE2 like bZIP" OR (NRF2 ChIP-seq)) AND gse[Entry Type]', text)
        self.assertIn('"Homo sapiens"[Organism]', text)
        self.assertIn("bw[Supplementary Files]", text)


    def test_a_gene_inside_a_typed_phrase_is_widened(self):
        live = mock.Mock()
        live.get_json.return_value.payload = {"esearchresult": {"count": "0", "idlist": []}}
        lookup = lambda text: {"symbol": "NFE2L2", "aliases": ["NRF2"]} if text == "NFE2L2" else None
        found = search.search("NFE2L2 ChIP-seq", live, lookup=lookup)
        self.assertEqual(found["terms"], ["NFE2L2 ChIP-seq", "NRF2 ChIP-seq"])
        self.assertIn("(NFE2L2 ChIP-seq) OR (NRF2 ChIP-seq)", found["expression"])



class TestOrderNeedsAWitness(unittest.TestCase):
    def test_no_named_column_means_no_order_matching(self):
        from spica.geo.response import match_columns

        samples = [{"accession": f"GSM{i}", "title": t, "characteristics": {}, "arm": ""}
                   for i, t in enumerate(["pTRPM1-1", "pTRPM1-2", "pNC-1", "pNC-2"])]
        columns = match_columns(["N1", "N2", "T1", "T2"], ["1", "2", "3", "4"], samples)
        self.assertEqual([c["sample"] for c in columns], ["", "", "", ""])


if __name__ == "__main__":
    unittest.main()
