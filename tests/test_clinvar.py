"""ClinVar counts: what is counted, what is not, and that both routes agree."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.sources import clinvar
from spica.sources.clinvar import classes_of

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class TestClasses(unittest.TestCase):
    def test_combined_calls_count_under_both(self):
        self.assertEqual(classes_of("Pathogenic/Likely pathogenic"),
                         {"Pathogenic", "Likely pathogenic"})
        self.assertEqual(classes_of("Benign/Likely benign"), {"Benign", "Likely benign"})

    def test_conflicting_is_never_pathogenic(self):
        self.assertEqual(classes_of("Conflicting classifications of pathogenicity"),
                         {"Conflicting"})

    def test_outside_the_standard_classes(self):
        self.assertEqual(classes_of("not provided"), set())
        self.assertEqual(classes_of("drug response"), set())
        self.assertEqual(classes_of("Pathogenic, low penetrance"), {"Pathogenic"})


class TestMirror(unittest.TestCase):
    def test_counts_from_variant_summary(self):
        mirror = Mirror.load(FIXTURE)
        record = build_record("PCSK9", mirror, Live(mirror.root, allowed=False))
        # Five variants of PCSK9 alone on GRCh38: the GRCh37 duplicate and the
        # two-gene deletion are not counted.
        self.assertEqual(record.value("clinvar_variants"), 5)
        self.assertEqual(record.value("clinvar_pathogenic"), 2)
        self.assertEqual(record.value("clinvar_classifications"), {
            "Pathogenic": 2, "Likely pathogenic": 1,
            "Uncertain significance": 1, "Conflicting": 1,
        })
        self.assertEqual(record["clinvar_variants"].provenance.source, "ClinVar")


class Counts:
    """Answers esearch with a count chosen by what the term asks."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, url, headers, timeout, body=None):
        self.asked.append(url)
        term = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("term", [""])[0]
        for fragment, count in self.answers:
            if fragment in term:
                return json.dumps({"esearchresult": {"count": str(count)}}).encode(), {}
        raise urllib.error.HTTPError(url, 500, "unrouted", {}, None)


class TestApi(unittest.TestCase):
    def fetch(self, answers):
        identity = mock.Mock(symbol="PCSK9")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(clinvar, "PACE", 0):
            transport = Counts(answers)
            fetched = clinvar.ClinVar().fetch(identity, Live(tmp, opener=transport))
        return fetched, transport

    ANSWERS = [
        ('OR "clinsig likely pathogenic"', 23),
        ('"clinsig pathogenic"', 14),
        ('"clinsig likely pathogenic"', 9),
        ('"clinsig vus"', 774),
        ('"clinsig likely benign"', 565),
        ('"clinsig benign"', 88),
        ('"clinsig has conflicts"', 168),
        ("single_gene[prop]", 1562),
    ]

    def test_counts_by_filtered_search(self):
        fetched, transport = self.fetch(self.ANSWERS)
        self.assertEqual(fetched.fields["clinvar_variants"], 1562)
        self.assertEqual(fetched.fields["clinvar_pathogenic"], 23)
        self.assertEqual(fetched.fields["clinvar_classifications"]["Uncertain significance"], 774)
        self.assertTrue(all("single_gene" in urllib.parse.unquote_plus(u) for u in transport.asked))

    def test_a_gene_with_no_records_is_not_in_the_source(self):
        from spica.sources.base import GeneNotInSource
        with self.assertRaises(GeneNotInSource):
            self.fetch([("single_gene[prop]", 0)])


if __name__ == "__main__":
    unittest.main()
