"""The promoter scan: matrices, exact p-values, both strands, and the
crossing of motif sites with ChIP-seq peaks."""

import itertools
import unittest
from unittest import mock

import numpy as np

from spica import tfscan
from spica.genome.locus import Locus

JASPAR = """>MA0001.1\tSITE
A  [ 20  0  0  0  0  0 ]
C  [  0 20  0  0 20  0 ]
G  [  0  0 20  0  0  0 ]
T  [  0  0  0 20  0 20 ]
>MA0002.1\tPAL
A  [ 20  0  0  0 ]
C  [  0 20  0  0 ]
G  [  0  0 20  0 ]
T  [  0  0  0 20 ]
>MA0003.1\tMAX::MYC
A  [ 0 10 ]
C  [ 10 0 ]
G  [ 10 0 ]
T  [ 0 10 ]
"""


class MatrixTest(unittest.TestCase):
    def setUp(self):
        self.matrices = tfscan.parse_jaspar(JASPAR)

    def test_the_file_format_is_read(self):
        self.assertEqual([m.id for m in self.matrices], ["MA0001.1", "MA0002.1", "MA0003.1"])
        self.assertEqual(self.matrices[0].length, 6)
        self.assertEqual(tfscan.consensus(self.matrices[0]), "ACGTCT")
        self.assertEqual(tfscan.consensus(self.matrices[2]), "SW")

    def test_a_factor_takes_its_own_matrix_or_a_dimer_it_is_part_of(self):
        own, note = tfscan.pick(self.matrices, "SITE")
        self.assertEqual((own.id, note), ("MA0001.1", ""))
        dimer, note = tfscan.pick(self.matrices, "MYC")
        self.assertEqual(dimer.id, "MA0003.1")
        self.assertIn("MAX::MYC", note)
        none, note = tfscan.pick(self.matrices, "KAT7")
        self.assertIsNone(none)
        self.assertIn("no JASPAR", note)

    def test_the_p_value_is_exact(self):
        # Every one of the 4^n sequences, scored by hand, against the convolution.
        matrix = tfscan.Matrix("x", "x", ((5, 1, 0), (1, 5, 2), (1, 2, 5), (3, 2, 3)))
        table = tfscan.weights(matrix)
        low, chance = tfscan.tail(table)
        scores = [sum(table[i, b] for i, b in enumerate(word))
                  for word in itertools.product(range(4), repeat=matrix.length)]
        for s in sorted(set(scores)):
            expected = sum(1 for x in scores if x >= s) / len(scores)
            self.assertAlmostEqual(chance[s - low], expected, places=12)

    def test_the_cut_off_is_the_lowest_score_inside_the_p_value(self):
        table = tfscan.weights(self.matrices[0])
        cut, low, chance = tfscan.threshold(table, 1e-3)
        self.assertLessEqual(chance[cut - low], 1e-3)
        self.assertGreater(chance[cut - low - 1], 1e-3)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.site, self.pal = tfscan.parse_jaspar(JASPAR)[:2]

    def test_a_site_on_each_strand_is_found_where_it_is(self):
        # ACGTCT forward at 10, and its reverse complement AGACGT at 30.
        sequence = "T" * 10 + "ACGTCT" + "T" * 14 + "AGACGT" + "T" * 10
        hits = tfscan.scan(sequence, self.site, 1e-3)
        self.assertEqual([(h["start"], h["strand"]) for h in hits], [(10, "+"), (30, "-")])
        self.assertTrue(all(h["site"] == "ACGTCT" for h in hits))
        self.assertTrue(all(h["p"] <= 1e-3 for h in hits))

    def test_a_palindrome_is_one_site_not_two(self):
        hits = tfscan.scan("TTTTTACGTTTTTT", self.pal, 0.01)
        self.assertEqual(len(hits), 1)

    def test_a_window_with_an_unknown_base_is_not_scored(self):
        self.assertEqual(tfscan.scan("TTTTACGNCTTTTT", self.site, 1e-3), [])


class AnalyseTest(unittest.TestCase):
    """One gene end to end, with every service stubbed."""

    def test_sites_are_crossed_with_the_factors_own_peaks(self):
        locus = Locus("GENE", "ENSG0", "chr1", 1000, 5000, "+", 10_000_000, 0, 60_000)
        # The promoter from 2,000 upstream to 500 in: TSS at 1000, region 0..1500.
        sequence = ["T"] * 1500
        sequence[700:706] = "ACGTCT"   # inside SITE's peak
        sequence[1200:1206] = "ACGTCT"  # outside it
        regulators = [{"tf": "SITE", "effect": "activates", "level": "A", "references": 4},
                      {"tf": "KAT7", "effect": "activates", "level": "", "references": 1}]
        peaks = [{"name": "SITE", "chromStart": 650, "chromEnd": 760, "sourceCount": 3, "score": 500},
                 {"name": "OTHER", "chromStart": 1190, "chromEnd": 1300, "sourceCount": 2, "score": 300}]
        chip = {"state": "ok", "with_chipseq": ["SITE", "KAT7"],
                "items": [{"target": "SITE"}, {"target": "SITE"}, {"target": "KAT7"}]}
        with mock.patch.object(tfscan.genome_locus, "find", return_value=locus), \
                mock.patch.object(tfscan, "_tss", return_value=(1000, "canonical transcript")), \
                mock.patch.object(tfscan, "_sequence", return_value="".join(sequence)), \
                mock.patch.object(tfscan, "matrices", return_value=tfscan.parse_jaspar(JASPAR)), \
                mock.patch.object(tfscan, "_regulators", return_value=(regulators, "test")), \
                mock.patch.object(tfscan, "ucsc_rows", return_value=peaks), \
                mock.patch.object(tfscan.genome_encode, "for_regulators", return_value=chip):
            found = tfscan.analyse("GENE", "ENSG0", live=None, p_value=1e-3)
        self.assertEqual(found["state"], "ok")
        self.assertEqual(found["region"], {"start": 0, "end": 1500, "upstream": 2000, "downstream": 500})
        site = found["regulators"][0]
        self.assertEqual(site["tf"], "SITE")
        self.assertEqual([(h["offset"], h["in_peak"]) for h in site["hits"]], [(-297, True), (203, False)])
        self.assertEqual(site["supported"], 1)
        self.assertEqual(site["chip"]["experiments"], 2)
        kat7 = found["regulators"][1]
        self.assertIsNone(kat7["motif"])
        self.assertTrue(kat7["chip"]["assayed"])
        self.assertEqual(found["summary"]["supported"], 1)
        self.assertEqual(found["summary"]["bound_here"], 1)
        features = tfscan.features(found, "chr1")
        self.assertEqual([f["color"] for f in features], ["#0077CC", "#5B6B7C"])

    def test_a_region_out_of_bounds_is_refused(self):
        self.assertEqual(tfscan.analyse("G", "E", live=None, upstream=60_000)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
