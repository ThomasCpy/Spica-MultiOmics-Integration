"""Differential expression: what a GEO table is, and the two validated routes."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

import numpy as np

from spica.geo import de
from spica.live import Live, LiveError


def sample(gsm: str, title: str, **context: str) -> dict:
    return {"accession": gsm, "title": title, "characteristics": context, "arm": ""}


SAMPLES = [sample(f"GSM{i}", t, treatment=tr) for i, (t, tr) in enumerate(
    [("Ctrl_1", "DMSO"), ("Ctrl_2", "DMSO"), ("Ctrl_3", "DMSO"),
     ("Drug_1", "drug"), ("Drug_2", "drug"), ("Drug_3", "drug")], start=1)]


def table(header: list[str], rows: list[list]) -> dict:
    return {"sheet": "", "header": header, "rows": rows}


def counts(genes: int = 400, seed: int = 0, up: int = 40) -> tuple[list[str], list[list]]:
    """Negative-binomial counts; the first `up` genes are 4x higher in Drug."""
    rng = np.random.default_rng(seed)
    mean = rng.lognormal(5, 1.2, genes)
    rows = []
    for g in range(genes):
        ctrl = rng.negative_binomial(8, 8 / (8 + mean[g]), 3)
        fold = 4.0 if g < up else 1.0
        drug = rng.negative_binomial(8, 8 / (8 + mean[g] * fold), 3)
        rows.append([f"ENSG{g:011d}", *map(int, ctrl), *map(int, drug)])
    return ["gene_id", "Ctrl_1", "Ctrl_2", "Ctrl_3", "Drug_1", "Drug_2", "Drug_3"], rows


class TestWhatATableIs(unittest.TestCase):
    def test_deseq2_edger_and_limma_results_are_published_results(self):
        for header in (["gene", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"],
                       ["gene", "logFC", "logCPM", "LR", "PValue", "FDR"],
                       ["gene", "logFC", "AveExpr", "t", "P.Value", "adj.P.Val", "B"]):
            prof = de.profile(table(header, [["A", 1.5, 2.0, 0.1, 3.0, 0.001, 0.01]]), SAMPLES)
            self.assertEqual(prof["kind"], "results", header)
            self.assertEqual(prof["routes"], ["published"])
            self.assertTrue(prof["contrasts"][0]["adjusted"], header)

    def test_two_contrasts_in_one_table_pair_by_name(self):
        header = ["gene", "KO_log2FoldChange", "KO_padj", "DKO_log2FoldChange", "DKO_padj"]
        found = de._contrasts(header)
        self.assertEqual([(c["fold"], c["p"]) for c in found],
                         [("KO_log2FoldChange", "KO_padj"), ("DKO_log2FoldChange", "DKO_padj")])

    def test_raw_counts_matched_to_samples_allow_deseq2(self):
        header, rows = counts(50)
        prof = de.profile(table(header + ["gene_length"], [r + [1234] for r in rows]), SAMPLES)
        self.assertEqual(prof["kind"], "counts")
        self.assertEqual(prof["routes"], ["deseq2"])
        self.assertEqual(prof["matched"], 6)
        self.assertNotIn("gene_length", [c["column"] for c in prof["columns"]])

    def test_normalised_values_are_refused_with_the_reason(self):
        header, rows = counts(50)
        rows = [[r[0], *[v * 1.37 + 0.01 for v in r[1:]]] for r in rows]
        prof = de.profile(table(header, rows), SAMPLES)
        self.assertEqual((prof["kind"], prof["routes"]), ("values", []))
        self.assertIn("no validated test", prof["reason"])

    def test_unnamed_count_columns_are_grouped_by_column(self):
        header, rows = counts(50)
        prof = de.profile(table(["gene_id", "N1", "N2", "N3", "T1", "T2", "T3"], rows), SAMPLES)
        self.assertEqual(prof["routes"], ["deseq2"])
        self.assertEqual(prof["matched"], 0)
        self.assertIn("groups by column", prof["reason"])


class TestTitleGroups(unittest.TestCase):
    def test_replicate_numbers_are_dropped(self):
        self.assertEqual(de.title_groups(["shCTR-1", "shCTR-2", "shKD-1", "shKD-2"]),
                         {"shCTR-1": "shCTR", "shCTR-2": "shCTR", "shKD-1": "shKD", "shKD-2": "shKD"})

    def test_numbers_that_are_not_replicates_never_pool(self):
        # Day 3 and Day 10 would pool into "Day": the numbers do not run 1..n.
        self.assertEqual(de.title_groups(["Day 3", "Day 10", "Day 7"]), {})
        self.assertEqual(de.title_groups(["Mock_2", "Mock_4", "Virus_1", "Virus_2"]), {})


class TestRoutes(unittest.TestCase):
    def test_published_results_are_read_as_published(self):
        t = table(["gene_id", "gene_name", "log2FoldChange", "pvalue", "padj"],
                  [["ENSG1", "AAA", "2.5", "1e-8", "1e-6"], ["ENSG2", "BBB", "NA", "NA", "NA"],
                   ["ENSG3", "", "-1.25", "0.2", "0.5"]])
        got = de.published(t, de._contrasts(t["header"])[0])
        self.assertEqual(got["points"], [["AAA", "ENSG1", None, 2.5, 1e-6], ["ENSG3", "ENSG3", None, -1.25, 0.5]])
        self.assertEqual((got["skipped"], got["p_label"]), (1, "adjusted p"))

    def test_deseq2_finds_the_changed_genes(self):
        header, rows = counts(400, up=40)
        t = table(header, rows)
        prof = de.profile(t, SAMPLES)
        got = de.deseq2(t, prof, "treatment", "DMSO", "drug")
        calls = {p[1]: p for p in got["points"]}
        up = [g for g in calls if int(g[4:]) < 40 and calls[g][4] is not None and calls[g][4] < 0.05 and calls[g][3] > 1]
        false = [g for g in calls if int(g[4:]) >= 40 and calls[g][4] is not None and calls[g][4] < 0.05]
        self.assertGreaterEqual(len(up), 30)
        self.assertLessEqual(len(false), 8)  # 5% of 360 is 18; BH keeps it near that or under
        self.assertIn("Wald test", got["method"])
        self.assertEqual(got["groups"]["reference"]["value"], "DMSO")
        self.assertEqual(len(got["groups"]["comparison"]["samples"]), 3)

    def test_one_sample_per_group_is_refused(self):
        header, rows = counts(150)
        t = table(header, rows)
        prof = de.profile(t, SAMPLES)
        with self.assertRaises(de.DeError):
            de.deseq2(t, prof, "", "", "", reference_columns=["Ctrl_1"], comparison_columns=["Drug_1", "Drug_2"])

    def test_a_confounded_covariate_is_refused(self):
        header, rows = counts(150)
        samples = [dict(s, characteristics={**s["characteristics"], "batch": s["characteristics"]["treatment"]})
                   for s in SAMPLES]
        t = table(header, rows)
        prof = de.profile(t, samples)
        with self.assertRaisesRegex(de.DeError, "confounded"):
            de.deseq2(t, prof, "treatment", "DMSO", "drug", covariate="batch")


class TestFiles(unittest.TestCase):
    def test_a_text_table_reads_with_an_unnamed_row_name_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.txt.gz"
            with gzip.open(path, "wt") as out:
                out.write("# featureCounts\nA\tB\nENSG1\t1\t2\nENSG2\t3\t4\n")
            [t] = de.read(path, "x.txt.gz")
        self.assertEqual(t["header"], ["", "A", "B"])
        self.assertEqual(t["rows"][1], ["ENSG2", "3", "4"])

    def test_old_excel_is_refused(self):
        with self.assertRaises(de.DeError):
            de.read(Path("missing.xls"), "missing.xls")

    def test_offline_and_not_cached_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LiveError):
                de.download("https://ftp.ncbi.nlm.nih.gov/geo/x.txt.gz", Live(tmp, allowed=False))


if __name__ == "__main__":
    unittest.main()
