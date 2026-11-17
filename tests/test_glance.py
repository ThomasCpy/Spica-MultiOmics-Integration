"""The gene at a glance: the words that its terms repeat.

The rules are small, and this file tests each one: what counts as a word,
which words are dropped, when two words become one phrase, how a word is
written, how disease scores weigh, and that measurements stay out.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from spica.build import build_record
from spica.glance import DISEASE_STOP, GO_STOP, MEASUREMENT, glance, tokens, word_map
from spica.live import Live
from spica.mirror import Mirror
from spica.record import GeneRecord, NullState, Value

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


def terms(*names: str) -> list[tuple[str, float]]:
    return [(name, 1.0) for name in names]


def by_word(words: list[dict]) -> dict[str, dict]:
    return {w["word"]: w for w in words}


class TokenTest(unittest.TestCase):
    def test_compounds_stay_whole(self):
        self.assertEqual(tokens("very-low-density lipoprotein particle"),
                         ["very-low-density", "lipoprotein", "particle"])
        self.assertEqual(tokens("FEV/FVC ratio"), ["FEV/FVC", "ratio"])

    def test_other_slashes_separate(self):
        self.assertEqual(tokens("phosphatidylinositol 3-kinase/protein kinase B"),
                         ["phosphatidylinositol", "3-kinase", "protein", "kinase", "B"])


class FunctionWordsTest(unittest.TestCase):
    def test_weight_is_the_number_of_terms_using_the_word(self):
        words = by_word(word_map(terms(
            "low-density lipoprotein particle receptor binding",
            "negative regulation of receptor internalization",
            "receptor-mediated endocytosis",
        ), GO_STOP, weighted=False))
        self.assertEqual(words["receptor"]["weight"], 2)
        self.assertEqual(words["receptor"]["from"], [
            "low-density lipoprotein particle receptor binding",
            "negative regulation of receptor internalization"])
        for dropped in ("negative", "regulation", "binding", "particle", "of"):
            self.assertNotIn(dropped, words)

    def test_words_that_travel_together_become_one_phrase(self):
        words = by_word(word_map(terms(
            "endoplasmic reticulum", "endoplasmic reticulum lumen", "plasma membrane",
            "lysosomal membrane", "plasma membrane raft",
        ), GO_STOP, weighted=False))
        self.assertEqual(words["endoplasmic reticulum"]["weight"], 2)
        self.assertEqual(words["plasma membrane"]["weight"], 2)
        self.assertEqual(words["membrane"]["weight"], 1)  # the lysosomal one
        self.assertNotIn("endoplasmic", words)

    def test_a_pair_seen_once_stays_apart(self):
        words = by_word(word_map(terms("lung alveolus development"), GO_STOP, weighted=False))
        self.assertEqual(set(words), {"lung", "alveolus", "development"})

    def test_plurals_fold_into_the_singular(self):
        words = by_word(word_map(terms("receptor clustering", "receptors recycling"),
                                 GO_STOP, weighted=False))
        self.assertEqual(words["receptor"]["weight"], 2)
        self.assertNotIn("receptors", words)

    def test_casing_that_means_something_is_kept(self):
        words = by_word(word_map(terms(
            "Golgi apparatus", "COPII-coated ER to Golgi transport vesicle", "LDL clearance",
        ), GO_STOP, weighted=False))
        for kept in ("Golgi", "COPII-coated", "ER", "LDL"):
            self.assertTrue(any(kept in word.split(" ") for word in words), kept)

    def test_order_is_heaviest_first_then_alphabetical(self):
        words = word_map(terms("zeta alpha", "zeta beta", "gamma"), GO_STOP, weighted=False)
        self.assertEqual([w["word"] for w in words], ["zeta", "alpha", "beta", "gamma"])


class DiseaseWordsTest(unittest.TestCase):
    def test_scores_are_squared_then_summed(self):
        faint = [(f"rare congenital condition {i}", 0.02) for i in range(50)]
        words = by_word(word_map([("lung carcinoma", 0.8), ("lung adenocarcinoma", 0.6)] + faint,
                                 DISEASE_STOP, weighted=True, sentence_case=True))
        self.assertEqual(words["lung"]["weight"], round(0.8 ** 2 + 0.6 ** 2, 3))
        # Fifty faint associations, always worded alike: one phrase, and light.
        self.assertEqual(words["congenital condition"]["weight"], round(50 * 0.02 ** 2, 3))
        self.assertGreater(words["lung"]["weight"], words["congenital condition"]["weight"])
        self.assertEqual(words["lung"]["from"][0], ["lung carcinoma", 0.8])

    def test_a_sentence_case_capital_is_not_a_name(self):
        words = by_word(word_map([("Hypercholesterolemia", 0.8),
                                  ("familial hypercholesterolemia", 0.9)],
                                 DISEASE_STOP, weighted=True, sentence_case=True))
        self.assertIn("hypercholesterolemia", words)
        self.assertEqual(words["hypercholesterolemia"]["count"], 2)

    def test_a_capital_kept_mid_name_is_a_name(self):
        words = by_word(word_map([("nephroblastoma, Wilms type", 0.5), ("Wilms tumor", 0.4)],
                                 DISEASE_STOP, weighted=True, sentence_case=True))
        self.assertIn("Wilms", words)

    def test_measurements_are_recognised(self):
        for name in ("total cholesterol measurement", "FEV/FVC ratio", "total lipids in small VLDL",
                     "cholesterol in large LDL", "VLDL particle size", "mean corpuscular volume",
                     "LDL cholesterol levels", "heart rate", "sleep duration",
                     "body mass index", "bone mineral density"):
            self.assertTrue(MEASUREMENT.search(name), name)
        for name in ("familial hypercholesterolemia", "non-small cell lung carcinoma",
                     "cerebral small vessel disease", "diffuse large B-cell lymphoma",
                     "heart failure"):
            self.assertFalse(MEASUREMENT.search(name), name)


class RecordTest(unittest.TestCase):
    def setUp(self):
        mirror = Mirror.load(FIXTURE)
        self.record = build_record("PCSK9", mirror, Live(mirror.root, allowed=False))

    def test_both_maps_from_a_record(self):
        result = glance(self.record)
        self.assertTrue(result["function"]["words"])
        self.assertTrue(result["function"]["source"].startswith("Gene Ontology, via UniProt"))
        self.assertEqual(result["function"]["reason"], "")
        self.assertIn("words", result["disease"])

    def test_the_same_record_gives_the_same_map(self):
        self.assertEqual(glance(self.record), glance(self.record))

    def test_a_gene_without_terms_says_why(self):
        missing = Value.missing(NullState.NOT_FOUND, "UniProt has no GO terms for this gene")
        fields = dict(self.record.fields)
        for name in ("go_process", "go_function", "go_component", "disease_associations"):
            fields[name] = missing
        record = GeneRecord(query=self.record.query, schema_version=self.record.schema_version,
                            resolution=self.record.resolution, sources=self.record.sources,
                            fields=fields)
        result = glance(record)
        self.assertEqual(result["function"]["words"], [])
        self.assertEqual(result["function"]["reason"], "UniProt has no GO terms for this gene")
        self.assertEqual(result["disease"]["reason"], "UniProt has no GO terms for this gene")


if __name__ == "__main__":
    unittest.main()
