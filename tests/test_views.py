"""The views beside the record: isoforms, structure, the regulation atlas,
co-expression, shared regulation and the recent-reports list. No network:
a stub transport answers in the shapes the live services were checked to use."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from spica import coexpression, isoforms, recent, regulators, structure
from spica.genome import atlas
from spica.genome.locus import Locus
from spica.live import Live
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class Transport:
    def __init__(self, routes):
        self.routes = routes
        self.asked = []

    def __call__(self, url, headers, timeout, body=None):
        self.asked.append(url)
        for fragment, answer in self.routes:
            if fragment in url:
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(url, answer, "", {}, None)
                text = answer if isinstance(answer, str) else json.dumps(answer)
                return text.encode(), {}
        raise urllib.error.HTTPError(url, 404, "unrouted", {}, None)


class TestIsoforms(unittest.TestCase):
    def test_every_transcript_and_tissue_with_names(self):
        rows = [{"transcriptId": t, "tissueSiteDetailId": tissue, "median": v}
                for t, tissue, v in [("ENST1.5", "Liver", 14.1), ("ENST1.5", "Lung", 0.2),
                                     ("ENST2.1", "Liver", 1.5), ("ENST2.1", "Lung", 3.0)]]
        routes = [
            ("reference/gene", {"data": [{"gencodeId": "ENSG1.11"}]}),
            ("medianTranscriptExpression", {"data": rows}),
            ("tissueSiteDetail", {"data": [{"tissueSiteDetailId": "Liver", "tissueSiteDetail": "Liver"},
                                           {"tissueSiteDetailId": "Lung", "tissueSiteDetail": "Lung"}]}),
            ("lookup/id", {"Transcript": [
                {"id": "ENST1", "display_name": "G-201", "biotype": "protein_coding", "is_canonical": 1},
                {"id": "ENST2", "display_name": "G-202", "biotype": "retained_intron", "is_canonical": 0}]}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transport = Transport(routes)
            out = isoforms.table("G", "ENSG1", Live(tmp, opener=transport))
        # The request asks for every row: GTEx pages at 250 otherwise.
        self.assertTrue(any("itemsPerPage=100000" in u for u in transport.asked))
        self.assertEqual([t["name"] for t in out["transcripts"]], ["G-201", "G-202"])
        self.assertTrue(out["transcripts"][0]["canonical"])
        self.assertEqual(out["dominant"]["Lung"], {"transcript": "ENST2.1", "share": 93.8})


class TestStructure(unittest.TestCase):
    def test_profile_combines_three_sources(self):
        routes = [
            ("uniprotkb/P1.json", {"sequence": {"length": 4}, "uniProtKBCrossReferences": [
                {"database": "PDB", "id": "1ABC", "properties": [
                    {"key": "Method", "value": "X-ray"}, {"key": "Resolution", "value": "2.0 A"},
                    {"key": "Chains", "value": "A=1-2"}]}]}),
            ("api/prediction/P1", [{"uniprotAccession": "P1", "uniprotStart": 1, "uniprotEnd": 4,
                                    "latestVersion": 6, "plddtDocUrl": "https://af/conf.json",
                                    "amAnnotationsUrl": "https://af/am.csv"}]),
            ("af/conf.json", {"residueNumber": [1, 2, 3, 4], "confidenceScore": [90, 80, 40, 30]}),
            ("af/am.csv", "protein_variant,am_pathogenicity,am_class\nM1A,0.2,LBen\nM1C,0.4,Amb\n"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = structure.profile("p1", Live(tmp, opener=Transport(routes)))
        self.assertEqual(out["length"], 4)
        self.assertEqual(out["plddt"][2], [3, 40.0])
        self.assertEqual(out["missense"], [[1, 0.3]])
        self.assertEqual(out["pdb"][0]["ranges"], [[1, 2]])


LOCUS = Locus(symbol="G", ensembl_id="ENSG1", chrom="chr3", start=1000, end=2000, strand="+",
              length=10000, window_start=0, window_end=2400)


class TestAtlas(unittest.TestCase):
    def test_every_tissue_one_row_shared_scale(self):
        def points(value):
            return {"start": 0, "end": 2400, "value": value}

        with mock.patch.object(atlas, "FAMILIES", {"dnase": ("pre", ("Liver", "Lung", "Moon"),
                                                              "Open", "signal")}):
            routes = [("track=preLiver", {"preLiver": [points(2.0)]}),
                      ("track=preLung", {"preLung": [points(0.5)]}),
                      ("track=preMoon", 500)]
            with tempfile.TemporaryDirectory() as tmp:
                out = atlas.atlas("dnase", LOCUS, Live(tmp, opener=Transport(routes)))
        self.assertEqual([r["tissue"] for r in out["rows"]], ["Liver", "Lung"])
        self.assertEqual(out["max"], 2.0)
        self.assertEqual(len(out["rows"][0]["values"]), atlas.ATLAS_BINS)
        # A tissue that could not be read is listed, not silently missing.
        self.assertEqual([f["tissue"] for f in out["failed"]], ["Moon"])

    def test_unknown_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("error", atlas.atlas("nope", LOCUS, Live(tmp)))


class TestCoexpression(unittest.TestCase):
    def test_ranks_against_every_gene_in_the_matrix(self):
        out = coexpression.correlated("PCSK9", "ENSG00000169174", Mirror.load(FIXTURE))
        self.assertEqual([g["symbol"] for g in out["genes"]], ["MALAT1"])
        self.assertTrue(-1 <= out["genes"][0]["r"] <= 1)

    def test_without_the_mirror_it_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = coexpression.correlated("PCSK9", "ENSG00000169174", Mirror.load(tmp))
        self.assertIn("mirror", out["error"])

    def test_pearson(self):
        self.assertAlmostEqual(coexpression._pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(coexpression._pearson([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(coexpression._pearson([1, 1, 1], [1, 2, 3]))


class TestSharedRegulation(unittest.TestCase):
    def test_shared_ranked_by_selectivity_and_links(self):
        def edge(source, target, up=True):
            return {"source_genesymbol": source, "target_genesymbol": target,
                    "is_stimulation": up, "is_inhibition": not up}

        routes = [
            ("targets=A&", [edge("TF1", "A"), edge("HUB", "A")]),
            ("targets=B&", [edge("TF1", "B", False), edge("HUB", "B")]),
            ("sources=TF1&", [edge("TF1", t) for t in ("A", "B", "C")]),
            ("sources=HUB&", [edge("HUB", f"G{i}") for i in range(50)]),
            ("sources=A%2CB", [{**edge("A", "B"), "type": "post_translational",
                                "references": ["X:1", "Y:1", "Y:2"], "sources": ["IntAct", "HPRD"]}]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transport = Transport(routes)
            out = regulators.compare(["A", "B"], Live(tmp, opener=transport))
        self.assertTrue(all("license=commercial" in u for u in transport.asked))
        self.assertEqual([s["tf"] for s in out["shared"]], ["TF1", "HUB"])  # selective first
        self.assertEqual(out["shared"][0]["genes"], {"A": "activates", "B": "represses"})
        self.assertEqual(out["links"][0]["references"], 2)
        self.assertEqual(out["links"][0]["databases"], "HPRD, IntAct")

    def test_needs_two_genes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("error", regulators.compare(["A"], Live(tmp)))


class TestRecent(unittest.TestCase):
    def test_most_recent_first_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("spica.recent.data_dir",
                                                              return_value=Path(tmp)):
            recent.add("PCSK9")
            recent.add("CLDN18")
            recent.add("PCSK9")
            self.assertEqual([e["symbol"] for e in recent.load()], ["PCSK9", "CLDN18"])


if __name__ == "__main__":
    unittest.main()
