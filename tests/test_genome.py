"""The backend of the genome view, with no network.

The bigBed/bigWig reader runs on files that this module builds byte by
byte, to the UCSC format documentation. Each offset that the reader follows
is thus one that this file wrote. The track converters get rows in the
shape of the real answers (UCSC, ENCORI). The live layer gets a stub
transport.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path

from spica.genome import locus as genome_locus
from spica.genome import tracks
from spica.genome.bigfile import (BIGBED_MAGIC, BIGWIG_MAGIC, CHROM_TREE_MAGIC, RTREE_MAGIC,
                                  BigFile, BigFileError, Ranged)
from spica.genome.locus import Locus
from spica.live import Live, LiveError


# -- a tiny bigBed / bigWig writer ------------------------------------------------


def _chrom_tree(chroms: list[tuple[str, int]], key_size: int = 8) -> bytes:
    head = struct.pack("<IIIIQQ", CHROM_TREE_MAGIC, len(chroms), key_size, 8, len(chroms), 0)
    node = struct.pack("<BBH", 1, 0, len(chroms))
    for index, (name, size) in enumerate(chroms):
        node += name.encode().ljust(key_size, b"\x00") + struct.pack("<II", index, size)
    return head + node


def _rtree(items: list[tuple[int, int, int, int, int, int]]) -> bytes:
    """One leaf: (startChrom, startBase, endChrom, endBase, offset, size)."""
    head = struct.pack("<IIQIIIIQII", RTREE_MAGIC, max(1, len(items)), len(items),
                       0, 0, 0, 0, 0, 1, 0)
    node = struct.pack("<BBH", 1, 0, len(items))
    for sc, sb, ec, eb, offset, size in items:
        node += struct.pack("<IIIIQQ", sc, sb, ec, eb, offset, size)
    return head + node


def build(kind: str, blocks: list[tuple[int, int, int, bytes]], compress: bool,
          zoom: tuple[int, bytes, tuple[int, int, int]] | None = None) -> bytes:
    """A whole file. `blocks` are (chrom, start, end, raw block bytes)."""
    magic = BIGBED_MAGIC if kind == "bigbed" else BIGWIG_MAGIC
    chroms = _chrom_tree([("chr3", 200_000_000), ("chr7", 160_000_000)])
    pack = (lambda b: zlib.compress(b)) if compress else (lambda b: b)
    zoom_count = 1 if zoom else 0
    offset = 64 + 24 * zoom_count
    tree_at = offset
    offset += len(chroms)
    data = b""
    data_at = offset
    leaves = []
    for chrom, start, end, raw in blocks:
        packed = pack(raw)
        leaves.append((chrom, start, chrom, end, data_at + len(data), len(packed)))
        data += packed
    offset = data_at + len(data)
    index_at = offset
    index = _rtree(leaves)
    offset += len(index)
    zoom_header = b""
    tail = b""
    if zoom:
        reduction, raw, (chrom, start, end) = zoom
        packed = pack(raw)
        zoom_data_at = offset
        zoom_index_at = zoom_data_at + len(packed)
        tail = packed + _rtree([(chrom, start, chrom, end, zoom_data_at, len(packed))])
        zoom_header = struct.pack("<IIQQ", reduction, 0, zoom_data_at, zoom_index_at)
    uncompress = max((len(raw) for *_, raw in blocks), default=0) if compress else 0
    header = struct.pack("<IHHQQQHHQQIQ", magic, 4, zoom_count, tree_at, data_at, index_at,
                         3, 3, 0, 0, uncompress, 0)
    return header + zoom_header + chroms + data + index + tail


def bed_block(records: list[tuple[int, int, int, str]]) -> bytes:
    return b"".join(struct.pack("<III", c, s, e) + rest.encode() + b"\x00"
                    for c, s, e, rest in records)


def bedgraph_block(chrom: int, records: list[tuple[int, int, float]]) -> bytes:
    start, end = records[0][0], records[-1][1]
    head = struct.pack("<IIIIIBBH", chrom, start, end, 0, 0, 1, 0, len(records))
    return head + b"".join(struct.pack("<IIf", s, e, v) for s, e, v in records)


def opened(data: bytes) -> BigFile:
    return BigFile(Ranged("memory://file", fetch=lambda url, o, n: data[o:o + n]))


class TestBigBed(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            (0, 100, 900, bed_block([(0, 100, 200, "peakA\t500\t+"),
                                     (0, 400, 900, "peakB\t300\t-")])),
            (1, 50, 60, bed_block([(1, 50, 60, "elsewhere\t1\t+")])),
        ]

    def test_region_query_both_compressions(self):
        for compress in (False, True):
            big = opened(build("bigbed", self.blocks, compress))
            self.assertEqual(big.kind, "bigbed")
            rows = big.bed("chr3", 150, 450)
            self.assertEqual([(s, e, f[0]) for s, e, f in rows],
                             [(100, 200, "peakA"), (400, 900, "peakB")])
            self.assertEqual(rows[1][2], ["peakB", "300", "-"])

    def test_edges_are_half_open(self):
        big = opened(build("bigbed", self.blocks, False))
        self.assertEqual(big.bed("chr3", 200, 400), [])  # touches both, overlaps neither
        self.assertEqual(len(big.bed("chr3", 199, 401)), 2)

    def test_chromosome_names_with_or_without_chr(self):
        big = opened(build("bigbed", self.blocks, False))
        self.assertEqual(big.bed("7", 0, 100)[0][2][0], "elsewhere")
        self.assertEqual(big.bed("chr9", 0, 100), [])

    def test_not_a_big_file(self):
        with self.assertRaises(BigFileError):
            opened(b"\x00" * 128)


class TestBigWig(unittest.TestCase):
    def test_full_resolution_mean_per_bin(self):
        block = bedgraph_block(0, [(0, 10, 1.0), (10, 20, 3.0)])
        big = opened(build("bigwig", [(0, 0, 20, block)], compress=True))
        self.assertEqual(big.kind, "bigwig")
        rows = big.wig("chr3", 0, 20, bins=2)
        self.assertEqual([(s, e, round(v, 6)) for s, e, v in rows], [(0, 10, 1.0), (10, 20, 3.0)])
        # One bin over both halves is the base-weighted mean.
        self.assertAlmostEqual(big.wig("chr3", 0, 20, bins=1)[0][2], 2.0)

    def test_gaps_are_left_out_not_zero(self):
        block = bedgraph_block(0, [(0, 10, 1.0)])
        big = opened(build("bigwig", [(0, 0, 10, block)], compress=False))
        rows = big.wig("chr3", 0, 40, bins=4)
        self.assertEqual(len(rows), 1)

    def test_zoom_level_used_only_when_coarse_enough(self):
        full = bedgraph_block(0, [(0, 1000, 1.0)])
        # The zoom record disagrees on purpose: it says the mean is 5.
        zoom = struct.pack("<IIIIffff", 0, 0, 1000, 1000, 0.0, 9.0, 5000.0, 0.0)
        big = opened(build("bigwig", [(0, 0, 1000, full)], compress=True,
                           zoom=(100, zoom, (0, 0, 1000))))
        self.assertAlmostEqual(big.wig("chr3", 0, 1000, bins=2)[0][2], 5.0)    # 500 bp bins
        self.assertAlmostEqual(big.wig("chr3", 0, 1000, bins=100)[0][2], 1.0)  # 10 bp bins


class TestRanged(unittest.TestCase):
    def test_prefetch_merges_near_ranges_into_one_request(self):
        calls = []
        data = bytes(range(256)) * 1024

        def fetch(url, offset, size):
            calls.append((offset, size))
            return data[offset:offset + size]

        source = Ranged("memory://x", fetch=fetch)
        source.prefetch([(1000, 10), (1100, 10), (200_000, 10)])
        self.assertEqual(len(calls), 2)  # 1000 and 1100 share a request
        source.read(1100, 10)
        source.read(1005, 3)
        self.assertEqual(len(calls), 2)  # served from what was fetched


# -- converters -----------------------------------------------------------------

CHROM = "chr3"


class TestConverters(unittest.TestCase):
    def test_gene_model_marks_utrs_like_igv(self):
        row = {"chromStart": 1000, "chromEnd": 2000, "strand": "+", "name": "ENST1.1",
               "geneName": "CLDN18", "transcriptType": "protein_coding", "tag": "basic,CCDS",
               "thickStart": 1150, "thickEnd": 1900, "blockSizes": "200,100,150,",
               "chromStarts": "0,400,850,"}
        feature = tracks.gene_features([row], CHROM)[0]
        exons = feature["exons"]
        self.assertEqual([(e["start"], e["end"]) for e in exons],
                         [(1000, 1200), (1400, 1500), (1850, 2000)])
        self.assertEqual(exons[0]["cdStart"], 1150)
        self.assertNotIn("utr", exons[1])
        self.assertEqual(exons[2]["cdEnd"], 1900)
        self.assertEqual(feature["name"], "CLDN18")

    def test_noncoding_transcript_is_all_utr(self):
        row = {"chromStart": 0, "chromEnd": 100, "thickStart": 50, "thickEnd": 50,
               "blockSizes": "100", "chromStarts": "0", "name": "ENST2"}
        feature = tracks.gene_features([row], CHROM)[0]
        self.assertTrue(all(e.get("utr") for e in feature["exons"]))
        self.assertNotIn("cdStart", feature)

    def test_clinvar_strips_html_and_colours_by_significance(self):
        row = {"chromStart": 10, "chromEnd": 11, "name": "VCV1",
               "origName": "1|VCV1 : NM_1(CLDN18):c.107A>C (p.Tyr36Ser)",
               "clinSign": "Pathogenic",
               "reviewStatus": "&#9733;&#9733;&#9734;&#9734;&nbsp;<small>based on: x</small>",
               "phenotypeList": "<script>alert(1)</script>Gastric cancer",
               "molConseq": "missense variant", "type": "single nucleotide variant", "snpId": "rs1"}
        feature = tracks.clinvar_features([row], CHROM)[0]
        self.assertEqual(feature["name"], "p.Tyr36Ser")
        self.assertTrue(feature["review"].startswith("2 of 4 stars"))
        self.assertNotIn("<", feature["condition"])  # popups are HTML: nothing gets through
        self.assertEqual(feature["color"], tracks.ORANGE)
        benign = tracks.clinvar_features([{**row, "clinSign": "Benign"}], CHROM)[0]
        conflicting = tracks.clinvar_features(
            [{**row, "clinSign": "Conflicting classifications of pathogenicity"}], CHROM)[0]
        self.assertEqual(benign["color"], tracks.AZURE_DEEP)
        self.assertEqual(conflicting["color"], tracks.SLATE)

    def test_eqtls_keep_only_this_gene(self):
        rows = [{"chromStart": 5, "thickStart": 7, "geneName": "CLDN18", "eqtlName": "rs1",
                 "tissue": "Stomach", "pip": "0.9"},
                {"chromStart": 5, "thickStart": 9, "geneName": "DZIP1L", "eqtlName": "rs2",
                 "tissue": "Lung", "pip": "0.5"}]
        features = tracks.eqtl_features(rows, CHROM, "cldn18")
        self.assertEqual([(f["name"], f["start"]) for f in features], [("rs1", 7)])

    def test_jaspar_keeps_regulators_above_threshold(self):
        rows = [{"chromStart": 1, "chromEnd": 9, "TFName": "HNF4A", "score": 500, "name": "MA1"},
                {"chromStart": 1, "chromEnd": 9, "TFName": "HNF4A", "score": 399, "name": "MA1"},
                {"chromStart": 1, "chromEnd": 9, "TFName": "CREB1", "score": 900, "name": "MA2"},
                {"chromStart": 1, "chromEnd": 9, "TFName": "FOS::JUN", "score": 600, "name": "MA3"}]
        names = [f["name"] for f in tracks.jaspar_features(rows, CHROM, {"HNF4A", "JUN"})]
        self.assertEqual(names, ["HNF4A", "FOS::JUN"])

    def test_encori_table_and_evidence(self):
        table = ("# citation line\n"
                 "miRNAname\tnarrowStart\tnarrowEnd\tstrand\tclipExpNum\tdegraExpNum\n"
                 "hsa-miR-1\t100\t106\t+\t3\t1\n"
                 "hsa-miR-2\t200\t206\t-\t2\t0\n"
                 "hsa-miR-3\t300\t306\t+\t0\t0\n")
        features = tracks.encori_features(table, CHROM)
        self.assertEqual([f["evidence"] for f in features],
                         ["cleavage (degradome)", "AGO-CLIP", "predicted"])
        self.assertEqual(features[1]["strand"], "-")

    def test_binned_weights_by_bases_and_skips_gaps(self):
        rows = [(0, 10, 2.0), (10, 30, 4.0)]
        out = tracks.binned(rows, 0, 40, bins=2)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0][2], (10 * 2 + 10 * 4) / 20)
        self.assertAlmostEqual(out[1][2], 4.0)  # only the covered half counts
        self.assertEqual(tracks.binned([], 0, 40, bins=4), [])

    def test_tissue_hint_from_the_gene_peak(self):
        hint = tracks.tissue_hint("Stomach")
        self.assertEqual((hint["dnase"], hint["gtex_coverage"], hint["encode"]),
                         ("Stomach", "Stomach", "stomach"))
        self.assertEqual(tracks.tissue_hint("nowhere"), {})

    def test_every_catalog_track_states_source_and_terms(self):
        for track in tracks.CATALOG:
            self.assertTrue(track.source and track.licence, track.id)
            if not track.verified:
                self.assertFalse(track.default, f"{track.id} has unverified terms but is on")


# -- the live side, stubbed -------------------------------------------------------

LOCUS = Locus(symbol="CLDN18", ensembl_id="ENSG00000066405", chrom="chr3",
              start=1_000, end=2_000, strand="+", length=10_000,
              window_start=0, window_end=3_000)


class Transport:
    def __init__(self, routes):
        self.routes = routes
        self.asked = []

    def __call__(self, url, headers, timeout, body=None):
        self.asked.append(url)
        for fragment, answer in self.routes.items():
            if fragment in url:
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(url, answer, "", {}, None)
                text = answer if isinstance(answer, str) else json.dumps(answer)
                return text.encode(), {}
        raise urllib.error.HTTPError(url, 500, "unrouted", {}, None)


class TestLoad(unittest.TestCase):
    def test_a_track_loads_with_its_config(self):
        rows = {"encodeCcreCombined": [{"chromStart": 5, "chromEnd": 50, "ccre": "PLS",
                                        "name": "EH1", "description": "d", "zScore": 1}]}
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"track=encodeCcreCombined": rows}))
            out = tracks.load("ccre", LOCUS, live)
        self.assertEqual(out["state"], "ok")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["config"]["type"], "annotation")
        # Coloured features: the track colour must not override them.
        self.assertNotIn("color", out["config"])

    def test_offline_unknown_and_missing_tissue(self):
        with tempfile.TemporaryDirectory() as tmp:
            offline = Live(tmp, allowed=False)
            self.assertEqual(tracks.load("ccre", LOCUS, offline)["state"], "offline")
            self.assertEqual(tracks.load("nope", LOCUS, offline)["state"], "failed")
            self.assertIn("no tissue", tracks.load("dnase:Moon", LOCUS, offline)["reason"])

    def test_signal_is_binned_before_caching(self):
        points = {"wgEncodeReg4DnaseAllStomach": [
            {"start": s, "end": s + 1, "value": 1.0} for s in range(0, 3_000)]}
        with tempfile.TemporaryDirectory() as tmp:
            transport = Transport({"track=wgEncodeReg4DnaseAllStomach": points})
            out = tracks.load("dnase:Stomach", LOCUS, Live(tmp, opener=transport))
            again = tracks.load("dnase:Stomach", LOCUS, Live(tmp, allowed=False))
            cached = " ".join(p.read_text() for p in Path(tmp).rglob("*.json"))
        self.assertEqual(out["state"], "ok")
        self.assertLessEqual(out["count"], tracks.WIG_BINS)
        self.assertEqual(again["count"], out["count"])  # offline, from the cache
        self.assertLess(len(cached), 400_000)  # the bins, not three thousand raw points


class TestLocus(unittest.TestCase):
    def test_reference_header_places_the_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"getData/sequence": {"dna": "ACGT" * 750}}))
            ref = genome_locus.reference(LOCUS, live)
        header, *lines = ref["fasta"].splitlines()
        # igv.js only offsets a slice when the length token is present.
        self.assertEqual(header, ">chr3:1-3000 @len=10000")
        self.assertEqual(len("".join(lines)), 3000)
        self.assertEqual(ref["source"], "UCSC")

    def test_reference_falls_back_to_ensembl(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"getData/sequence": 500,
                                               "sequence/region": {"seq": "A" * 3000}}))
            self.assertEqual(genome_locus.reference(LOCUS, live)["source"], "Ensembl")

    def test_window_is_the_gene_plus_flanks(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({
                "lookup/id": {"seq_region_name": "3", "start": 137998735, "end": 138033655, "strand": 1},
                "info/assembly": {"length": 198295559}}))
            found = genome_locus.find("CLDN18", "ENSG00000066405", live)
        self.assertEqual((found.chrom, found.start, found.end), ("chr3", 137998734, 138033655))
        self.assertEqual(found.window_start, 137998734 - genome_locus.FLANK)
        self.assertEqual(found.view, "chr3:137988735-138043655")

    def test_a_mirrored_gene_is_placed_without_asking_ensembl(self):
        from spica.mirror import Mirror

        mirror = Mirror.load(Path(__file__).parent / "fixtures" / "mirror")
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, allowed=False)  # any request would raise
            found = genome_locus.find("PCSK9", "ENSG00000169174", live, mirror)
        self.assertEqual((found.chrom, found.start, found.end, found.strand),
                         ("chr1", 55039446, 55064852, "+"))
        self.assertEqual(found.length, genome_locus.LENGTHS["1"])


class TestLiveAdditions(unittest.TestCase):
    def test_remember_runs_once_and_then_reads_offline(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp)
            first = live.remember("x", "key", lambda: calls.append(1) or {"v": 1}).payload
            second = Live(tmp, allowed=False).remember("x", "key", lambda: calls.append(1)).payload
            with self.assertRaises(LiveError):
                Live(tmp, allowed=False).remember("x", "other", lambda: 1)
        self.assertEqual((first, second, len(calls)), ({"v": 1}, {"v": 1}, 1))

    def test_get_text_caches_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"encori": "a\tb\n1\t2\n"}))
            live.get_text("encori", "https://encori/x")
            again = Live(tmp, allowed=False).get_text("encori", "https://encori/x")
        self.assertEqual(again.payload, "a\tb\n1\t2\n")


if __name__ == "__main__":
    unittest.main()
