"""GWAS Catalog in the record: counts, the trait chart, the lead variants."""

from __future__ import annotations

import unittest
from pathlib import Path

from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class GwasRecordTest(unittest.TestCase):
    def setUp(self):
        mirror = Mirror.load(FIXTURE)
        self.live = Live(mirror.root, allowed=False)
        self.mirror = mirror
        self.record = build_record("PCSK9", mirror, self.live)

    def test_counts_and_genome_wide_traits(self):
        self.assertEqual(self.record.value("gwas_associations"), 14)
        # 120 and 45.2 pass 7.3; the nearest-gene hit at 6.0 does not.
        self.assertEqual(self.record.value("gwas_genome_wide_traits"), 2)

    def test_every_trait_strongest_first_with_where_the_variant_is(self):
        self.assertEqual(list(self.record.value("gwas_traits")),
                         ["low density lipoprotein cholesterol measurement",
                          "familial hypercholesterolemia", "coronary artery disease"])
        lead = self.record.value("gwas_lead_variants")
        self.assertTrue(lead[0].startswith("low density lipoprotein cholesterol measurement: "
                                           "rs11591147-T, p 1E-120"))
        self.assertIn("nearest gene", lead[2])

    def test_a_gene_with_no_association_says_so(self):
        record = build_record("ADH1B", self.mirror, self.live)
        self.assertIs(record.fields["gwas_traits"].state, NullState.NOT_FOUND)
        self.assertIn("maps no association", record.fields["gwas_traits"].reason)


if __name__ == "__main__":
    unittest.main()
