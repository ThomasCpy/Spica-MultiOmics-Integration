"""Milestone 3: gene lists, the ranked table, the benchmark.

The tests use the fixture mirror and hand-made records, so each rule is
readable in its test. The rules: how an entry maps, that the score of a
gene never depends on the other genes, that missing data is left out or
counts as zero on request, and that the benchmark arithmetic is correct.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica import benchmark, genelist, ranking
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.record import GeneRecord, NullState, Provenance, Resolution, Value
from spica.sources.hgnc import Hgnc

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class ParseTest(unittest.TestCase):
    def test_a_column_title_is_not_a_gene(self):
        self.assertEqual(genelist.parse("Gene\nPCSK9\nADH1B\n"), ["PCSK9", "ADH1B"])

    def test_separators_and_spreadsheet_rows(self):
        self.assertEqual(genelist.parse("PCSK9, ADH1B; MALAT1  TP53"), ["PCSK9", "ADH1B", "MALAT1", "TP53"])
        self.assertEqual(genelist.parse("PCSK9\t0.91\nADH1B\t0.40"), ["PCSK9", "ADH1B"])

    def test_repeats_are_kept_so_the_mapping_can_say_so(self):
        self.assertEqual(genelist.parse("PCSK9\nPCSK9"), ["PCSK9", "PCSK9"])


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.mirror = Mirror.load(FIXTURE)
        self.live = Live(self.mirror.root, allowed=False)

    def test_every_kind_of_match(self):
        mapped = genelist.map_entries(["HCHOLA3", "ADH2", "pcsk9", "ENSG00000169174", "NOTAGENE",
                                       "125"], self.mirror, self.live)
        status = [row["status"] for row in mapped["rows"]]
        # A second entry for a gene is a duplicate first, whatever it matched as.
        self.assertEqual(status, ["alias", "renamed", "duplicate", "duplicate", "not_found",
                                  "duplicate"])
        self.assertEqual(mapped["rows"][0]["symbol"], "PCSK9")
        self.assertEqual(mapped["rows"][1]["symbol"], "ADH1B")
        self.assertIn("now ADH1B", mapped["rows"][1]["note"])
        self.assertIn("entry 1", mapped["rows"][3]["note"])
        self.assertEqual(mapped["genes"], 2)
        self.assertEqual(mapped["needs_review"], 1)

    def test_confirm_needs_a_choice_for_every_ambiguous_entry(self):
        rows = [{"input": "X", "position": 0, "status": "ambiguous", "symbol": "", "hgnc_id": "",
                 "candidates": [{"symbol": "A", "hgnc_id": "HGNC:1", "name": ""},
                                {"symbol": "B", "hgnc_id": "HGNC:2", "name": ""}]},
                {"input": "PCSK9", "position": 1, "status": "exact", "symbol": "PCSK9",
                 "hgnc_id": "HGNC:20001", "candidates": []},
                {"input": "Q", "position": 2, "status": "not_found", "symbol": "", "hgnc_id": "",
                 "candidates": []}]
        self.assertIn("Gene selection required: X", genelist.confirm(rows, {})["error"])
        genes = genelist.confirm(rows, {"0": "HGNC:2"})["genes"]
        self.assertEqual([g["symbol"] for g in genes], ["B", "PCSK9"])
        self.assertEqual([g["symbol"] for g in genelist.confirm(rows, {"0": "drop"})["genes"]],
                         ["PCSK9"])

    def test_saved_lists_round_trip(self):
        folder = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(genelist, "folder", return_value=folder):
                saved = genelist.save("Lipid targets", ["PCSK9"], {"rows": []},
                                      [{"input": "PCSK9", "symbol": "PCSK9", "hgnc_id": "HGNC:20001"}],
                                      {}, {"surface": 2.0}, "antibody", "cholesterol")
                self.assertEqual(saved["slug"], "lipid-targets")
                self.assertEqual(genelist.saved()[0]["genes"], 1)
                self.assertEqual(genelist.load("lipid-targets")["indication"], "cholesterol")
                self.assertTrue(genelist.delete("lipid-targets"))
                self.assertEqual(genelist.saved(), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class NumberTest(unittest.TestCase):
    def test_a_number_that_is_both_an_hgnc_number_and_an_entrez_id_is_asked_about(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "hgnc").mkdir()
            (root / "hgnc" / "complete_set.txt").write_text(
                "hgnc_id\tsymbol\tstatus\tentrez_id\n"
                "HGNC:1956\tCHRNA2\tApproved\t1135\n"
                "HGNC:3236\tEGFR\tApproved\t1956\n", encoding="utf-8")
            entry = mock.Mock()
            entry.path.return_value = root / "hgnc" / "complete_set.txt"
            found = Hgnc().resolve("1956", entry)
            self.assertFalse(found.resolved)
            self.assertEqual(found.candidates, ("CHRNA2 (HGNC:1956)", "EGFR (HGNC:3236)"))
            self.assertEqual(Hgnc().resolve("HGNC:1956", entry).symbol, "CHRNA2")
        finally:
            shutil.rmtree(root, ignore_errors=True)


def record(symbol: str, **fields) -> GeneRecord:
    """A record with only the fields a test names; every other field missing."""
    values = {}
    for spec_name, value in fields.items():
        values[spec_name] = (Value.missing(NullState.NOT_FOUND, "none") if value is None
                             else Value.found(value, Provenance("Test", "1", "2026-10-28")))
    return GeneRecord(query=symbol, resolution=Resolution(query=symbol, resolved=True,
                                                          symbol=symbol, hgnc_id=f"HGNC:{symbol}"),
                      fields=values)


class RankingTest(unittest.TestCase):
    def test_a_score_never_depends_on_the_other_genes(self):
        mirror = Mirror.load(FIXTURE)
        live = Live(mirror.root, allowed=False)
        pcsk9, adh1b = (build_record(g, mirror, live) for g in ("PCSK9", "ADH1B"))
        weights = ranking.weights_for("antibody")
        alone = ranking.rank([pcsk9], weights, mirror=mirror)["rows"][0]
        together = {r["symbol"]: r for r in ranking.rank([pcsk9, adh1b], weights, mirror=mirror)["rows"]}
        self.assertEqual(alone["score"], together["PCSK9"]["score"])

    def test_weighted_mean_and_missing_data(self):
        a = record("A", rna_specificity_tau=0.9, cyno_protein_identity=50.0)
        b = record("B", rna_specificity_tau=0.5)  # no ortholog field at all: missing
        weights = {key: 0.0 for key in ranking.BY_KEY}
        weights.update(specificity=1.0, cyno=1.0)
        skip = {r["symbol"]: r for r in ranking.rank([a, b], weights)["rows"]}
        self.assertAlmostEqual(skip["A"]["score"], (0.9 + 0.5) / 2)
        self.assertAlmostEqual(skip["B"]["score"], 0.5)  # scored on what it has
        self.assertEqual(skip["B"]["coverage"], 0.5)
        zero = {r["symbol"]: r for r in ranking.rank([a, b], weights, missing="zero")["rows"]}
        self.assertAlmostEqual(zero["B"]["score"], 0.25)
        self.assertAlmostEqual(sum(p["contribution"] for p in skip["A"]["parts"].values()),
                               skip["A"]["score"], places=3)

    def test_no_ortholog_is_an_answer_not_a_gap(self):
        row = ranking.score(record("C", cyno_protein_identity=None), {"cyno": 1.0}, ranking.Context())
        self.assertEqual(row["parts"]["cyno"]["score"], 0.0)

    def test_selective_means_needed_in_one_lineage_and_spared_in_the_rest(self):
        broad = record("D", depmap_common_essential="no", depmap_dependent_share=60.0,
                       depmap_lineage_dependency={"Liver, 24 lines": 90.0})
        narrow = record("E", depmap_common_essential="no", depmap_dependent_share=5.0,
                        depmap_lineage_dependency={"Skin, 70 lines": 60.0, "Eye, 3 lines": 100.0})
        context = ranking.Context()
        self.assertAlmostEqual(ranking.BY_KEY["selective"].measure(broad, context)[0], 0.36)
        self.assertAlmostEqual(ranking.BY_KEY["selective"].measure(narrow, context)[0], 0.57)

    def test_presets_cover_every_criterion(self):
        for key in ranking.PRESETS:
            weights = ranking.weights_for(key)
            self.assertEqual(set(weights), set(ranking.BY_KEY))
            self.assertTrue(any(weights.values()))

    def test_weights_run_0_to_10_and_old_lists_keep_their_ratios(self):
        for key in ranking.PRESETS:
            self.assertLessEqual(max(ranking.weights_for(key).values()), ranking.SCALE)
        old = {"name": "x", "weights": {"surface": 3, "cyno": 0.5}}
        new = ranking.upgraded(old)
        self.assertEqual(new["weights"], {"surface": 9.0, "cyno": 1.5})
        self.assertEqual(new["scale"], ranking.SCALE)
        self.assertEqual(ranking.upgraded(new), new)  # once only


class BenchmarkTest(unittest.TestCase):
    def test_auc_by_hand(self):
        self.assertEqual(benchmark.auc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(benchmark.auc([0.1], [0.9]), 0.0)
        self.assertEqual(benchmark.auc([0.5], [0.5]), 0.5)  # a tie counts half
        self.assertEqual(benchmark.auc([0.9, 0.3], [0.5, 0.1]), 0.75)
        self.assertIsNone(benchmark.auc([], [0.1]))

    def test_roc_runs_from_the_corner_to_the_corner(self):
        points = benchmark.roc([(0.9, True), (0.8, False), (0.7, True), (0.1, False)])
        self.assertEqual(points[0], [0.0, 0.0])
        self.assertEqual(points[-1], [1.0, 1.0])
        self.assertEqual(points[1], [0.0, 0.5])

    def test_a_run_weighed_only_on_the_label_is_refused(self):
        weights = {key: 0.0 for key in ranking.BY_KEY}
        weights["precedent"] = 3.0
        with mock.patch.object(benchmark, "sets", return_value={"positives": [], "decoys": []}):
            found = benchmark.run("antibody", weights, Mirror.load(FIXTURE))
        self.assertIn("carries the label", found["error"])

    def test_decoys_are_the_same_every_run(self):
        targets = {f"ENSG{i:011d}": {"symbol": f"G{i}", "buckets": {}} for i in range(40)}
        targets["ENSG00000000001"]["buckets"] = {"AB": ["Approved Drug"]}
        targets["ENSG00000000002"]["buckets"] = {"SM": ["Phase 1 Clinical"]}
        with mock.patch.object(benchmark, "tractability", return_value=targets), \
                mock.patch.object(benchmark, "_protein_coding", return_value=set(targets)):
            first = benchmark.sets("antibody", None)
            second = benchmark.sets("antibody", None)
        self.assertEqual(first, second)
        self.assertEqual(first["positives"], ["ENSG00000000001"])
        self.assertEqual(len(first["decoys"]), benchmark.RATIO)
        # A gene with a drug of any modality in the clinic is never a decoy.
        self.assertNotIn("ENSG00000000002", first["decoys"])
        self.assertNotIn("ENSG00000000001", first["decoys"])


if __name__ == "__main__":
    unittest.main()


class JobsTest(unittest.TestCase):
    def test_a_job_reports_progress_then_its_result_or_its_error(self):
        import time

        import app

        jobs = app.Jobs()

        def work(progress):
            progress(1, 2)
            return {"rows": [1]}

        first = jobs.start("rank", 2, work)
        failing = jobs.start("rank", 0, lambda progress: {"error": "nothing to rank"})
        broken = jobs.start("rank", 0, lambda progress: 1 / 0)
        for _ in range(100):
            if all(jobs.status(job)["state"] != "running" for job in (first, failing, broken)):
                break
            time.sleep(0.02)
        self.assertEqual(jobs.status(first)["state"], "done")
        self.assertEqual(jobs.status(first)["result"], {"rows": [1]})
        self.assertEqual(jobs.status(failing)["error"], "nothing to rank")
        self.assertIn("ZeroDivisionError", jobs.status(broken)["error"])
        self.assertEqual(jobs.status("nope")["state"], "unknown")
