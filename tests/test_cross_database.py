"""Comparisons across databases: each rule tested on small, known inputs.

Agreement between sources (log-scale correlation). Protein location (three
vocabularies onto ten compartments). Disease against genetics (Open Targets
joined to ClinVar on identifiers, never on names). Interaction partners
(HPA experiments against OmniPath curation).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spica import genetics, interactions, metrics, regulators
from spica.build import build_record
from spica.dogma import align
from spica.live import Live
from spica.locations import COMPARTMENTS, compartments, place
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"


class CorrelationTest(unittest.TestCase):
    def test_log_correlation_follows_where_the_expression_is(self):
        # Two atlases that agree on the two organs that matter and differ in
        # the noise near zero: ranks read them as barely related, the log
        # scale as close.
        first = [700, 240, 0.4, 0.1, 0.3, 0.0, 0.2, 0.5]
        second = [680, 230, 0.1, 0.5, 0.0, 0.4, 0.3, 0.2]
        self.assertGreater(metrics.log_correlation(first, second), 0.95)
        self.assertLess(metrics.spearman(first, second), 0.6)

    def test_too_few_or_flat_means_no_figure(self):
        self.assertIsNone(metrics.log_correlation([1, 2, 3], [1, 2, 3]))
        self.assertIsNone(metrics.log_correlation([5] * 6, [1, 2, 3, 4, 5, 6]))
        self.assertIsNone(metrics.spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]))

    def test_spearman_shares_ranks_between_ties(self):
        self.assertEqual(metrics._ranks([3, 1, 3, 2]), [3.5, 1.0, 3.5, 2.0])

    def test_the_organ_alignment_reports_every_pair(self):
        mirror = Mirror.load(FIXTURE)
        aligned = align(build_record("PCSK9", mirror, Live(mirror.root, allowed=False)))
        keys = [layer["key"] for layer in aligned["layers"]]
        pairs = {(p["a"], p["b"]) for p in aligned["agreement"]}
        self.assertEqual(len(pairs), len(keys) * (len(keys) - 1) // 2)
        for pair in aligned["agreement"]:
            self.assertTrue(pair["rho"] is None or -1 <= pair["rho"] <= 1)


class LocationsTest(unittest.TestCase):
    def test_specific_organelles_before_the_word_membrane(self):
        cases = {
            "Nucleus membrane": "Nucleus", "Endosome membrane": "Vesicles",
            "mitochondrial inner membrane": "Mitochondria", "Cell membrane": "Plasma membrane",
            "Golgi apparatus membrane": "Golgi apparatus",
            "endoplasmic reticulum lumen": "Endoplasmic reticulum",
            "perinuclear region of cytoplasm": "Cytosol", "Secreted": "Extracellular",
            "chylomicron": "Extracellular", "Cell junction, tight junction": "Plasma membrane",
            "Basal body": "Cytoskeleton", "Nucleoplasm": "Nucleus", "Cytosol": "Cytosol",
        }
        for term, expected in cases.items():
            self.assertEqual(place(term), expected, term)

    def test_a_complex_is_not_a_compartment(self):
        self.assertIsNone(place("PCSK9-LDLR complex"))

    def test_every_compartment_is_reported_and_topology_kept_aside(self):
        mirror = Mirror.load(FIXTURE)
        found = compartments(build_record("PCSK9", mirror, Live(mirror.root, allowed=False)))
        self.assertEqual([row["name"] for row in found["compartments"]], list(COMPARTMENTS))
        for row in found["compartments"]:
            self.assertEqual(row["count"], len(row["sources"]))
        self.assertTrue(all("membrane protein" not in term.lower()
                            for row in found["compartments"]
                            for terms in row["sources"].values() for term in terms))


class GeneticsTest(unittest.TestCase):
    def test_one_spelling_per_identifier(self):
        for raw, expected in {"MONDO_0005439": "MONDO:0005439",
                              "MONDO:MONDO:0005439": "MONDO:0005439",
                              "MedGen:C0020445": "CUI:C0020445", "UMLS:C0020445": "CUI:C0020445",
                              "Orphanet_406": "ORPHANET:406",
                              "Human Phenotype Ontology:HP:0003124": "HP:0003124"}.items():
            self.assertEqual(genetics.normal(raw), expected, raw)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        target = {"ensemblId": "ENSG00000169174", "approvedSymbol": "PCSK9",
                  "associatedDiseases": {"count": 3, "rows": [
                      {"score": 0.86, "disease": {"id": "MONDO_0005439",
                                                  "name": "familial hypercholesterolemia"}},
                      {"score": 0.5, "disease": {"id": "EFO_0001645",
                                                 "name": "coronary artery disease"}},
                      {"score": 0.2, "disease": {"id": "EFO_0000400", "name": "diabetes"}}]}}
        (self.root / "opentargets").mkdir(exist_ok=True)
        (self.root / "opentargets" / "targets.jsonl").write_text(json.dumps(target) + "\n",
                                                                  encoding="utf-8")
        (self.root / "opentargets" / "disease_xrefs.tsv").write_text(
            "id\tname\txrefs\n"
            "EFO_0001645\tcoronary artery disease\tUMLS:C1956346|MeSH:D003324\n"
            "MONDO_0005439\tfamilial hypercholesterolemia\tOMIM:143890\n", encoding="utf-8")
        (self.root / "clinvar" / "conditions.tsv").write_text(
            "GeneSymbol\tCondition\tIDs\tPathogenic\tRecords\n"
            "PCSK9\tHypercholesterolemia, familial, 1\tMONDO:MONDO:0005439,OMIM:143890\t30\t90\n"
            "PCSK9\tCoronary artery disease\tMedGen:C1956346\t0\t4\n"
            "PCSK9\tLow density lipoprotein cholesterol level quantitative trait locus 1\t"
            "OMIM:603776\t5\t6\n", encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["opentargets"] = {
            "label": "Open Targets", "version": "26.09", "retrieved": "2026-10-26",
            "files": {"targets": "opentargets/targets.jsonl",
                      "disease_xrefs": "opentargets/disease_xrefs.tsv"}}
        manifest["sources"]["clinvar"]["files"]["conditions"] = "clinvar/conditions.tsv"
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        genetics._XREFS.clear()

    def test_diseases_and_conditions_meet_on_identifiers(self):
        found = genetics.evidence("PCSK9", "ENSG00000169174", Mirror.load(self.root))
        rows = {row["disease"]: row for row in found["rows"]}
        self.assertEqual(rows["familial hypercholesterolemia"]["pathogenic"], 30)
        self.assertEqual(rows["familial hypercholesterolemia"]["conditions"],
                         ["Hypercholesterolemia, familial, 1"])
        # Matched through a UMLS cross-reference, with no pathogenic records.
        self.assertEqual((rows["coronary artery disease"]["pathogenic"],
                          rows["coronary artery disease"]["records"]), (0, 4))
        self.assertEqual(rows["diabetes"]["records"], 0)
        self.assertEqual([c["condition"] for c in found["clinvar_only"]],
                         ["Low density lipoprotein cholesterol level quantitative trait locus 1"])
        self.assertEqual(found["summary"]["with_pathogenic"], 1)
        # Common variants too: the GWAS trait meets the disease on its MONDO or
        # EFO term; the measurement matches no disease and is kept apart.
        self.assertEqual(rows["familial hypercholesterolemia"]["gwas"], 45.2)
        self.assertEqual(rows["coronary artery disease"]["gwas"], 6.0)
        self.assertEqual(rows["diabetes"]["gwas"], 0.0)
        self.assertEqual([t["trait"] for t in found["gwas_only"]],
                         ["low density lipoprotein cholesterol measurement"])
        self.assertEqual([row["disease"] for row in found["rows"]][0],
                         "familial hypercholesterolemia")  # strongest association first

    def test_without_the_identifier_files_it_says_what_to_do(self):
        found = genetics.evidence("PCSK9", "ENSG00000169174", Mirror.load(FIXTURE))
        self.assertIn("update both in Settings", found["error"])


class InteractionsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        with open(self.root / "hgnc" / "hgnc_complete_set.txt", "a", encoding="utf-8") as handle:
            handle.write('HGNC:6547\tLDLR\tlow density lipoprotein receptor\tprotein-coding gene\tgene with protein product\tApproved\t19p13.2\t\t\t3949\tENSG00000130164\tP01130\nHGNC:1664\tSCARB1\tscavenger receptor class B member 1\tprotein-coding gene\tgene with protein product\tApproved\t12q24.31\t\t\t949\tENSG00000073060\tQ8WTV0\nHGNC:8568\tFURIN\tfurin, paired basic amino acid cleaving enzyme\tprotein-coding gene\tgene with protein product\tApproved\t15q26.1\t\t\t5045\tENSG00000140564\tP09958\n')
        (self.root / "omnipath").mkdir()
        (self.root / "omnipath" / "interactions.tsv").write_text('source\ttarget\tsource_genesymbol\ttarget_genesymbol\tis_directed\tis_stimulation\tis_inhibition\tconsensus_direction\tconsensus_stimulation\tconsensus_inhibition\tsources\treferences\ttype\tcuration_effort\nQ8NBP7\tP01130\tPCSK9\tLDLR\tTrue\tFalse\tTrue\tTrue\tFalse\tTrue\tSIGNOR;HPRD\tSIGNOR:111;HPRD:111;HPRD:222\tpost_translational\t3\nP09958\tQ8NBP7\tFURIN\tPCSK9\tTrue\tFalse\tTrue\tTrue\tFalse\tTrue\tSIGNOR\tSIGNOR:333\tpost_translational\t1\nCOMPLEX:Q8NBP7_P01130\tP04114\tPCSK9_LDLR\tAPOB\tTrue\tTrue\tFalse\tTrue\tTrue\tFalse\tSIGNOR\tSIGNOR:444\tpost_translational\t1\nQ8NBP7\tQ8NBP7\tPCSK9\tPCSK9\tTrue\tTrue\tFalse\tTrue\tTrue\tFalse\tPhosphoSite\tPhosphoSite:555\tpost_translational\t1\n', encoding="utf-8")
        (self.root / "omnipath" / "regulation.tsv").write_text('source\ttarget\tsource_genesymbol\ttarget_genesymbol\tis_directed\tis_stimulation\tis_inhibition\tconsensus_direction\tconsensus_stimulation\tconsensus_inhibition\tsources\treferences\ttype\tcuration_effort\nQ12772\tQ8NBP7\tSREBF2\tPCSK9\tTrue\tTrue\tFalse\tTrue\tTrue\tFalse\tCollecTRI\tCollecTRI:666\ttranscriptional\t1\n', encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["omnipath"] = {
            "label": "OmniPath", "version": "2026-10-27", "retrieved": "2026-10-27",
            "files": {"interactions": "omnipath/interactions.tsv",
                      "regulation": "omnipath/regulation.tsv"}}
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.mirror = Mirror.load(self.root)

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def test_partners_meet_on_identifiers(self):
        found = interactions.compare("PCSK9", "ENSG00000169174", self.mirror)
        rows = {row["symbol"]: row for row in found["partners"]}
        self.assertEqual(set(rows), {"LDLR", "SCARB1", "FURIN", "APOB", "PCSK9"})
        # In both, so first; HPA's older file names no dataset, the pair is
        # still there; OmniPath's references are counted once per paper.
        self.assertEqual(found["partners"][0]["symbol"], "LDLR")
        self.assertEqual(rows["LDLR"]["hpa"], ["consensus"])
        self.assertEqual(rows["LDLR"]["omnipath"]["references"], 2)
        self.assertEqual(rows["LDLR"]["omnipath"]["links"],
                         [{"direction": "out", "sign": "inhibits", "from": "PCSK9", "to": "LDLR"}])
        self.assertIsNone(rows["SCARB1"]["omnipath"])
        self.assertIsNone(rows["FURIN"]["hpa"])
        self.assertEqual(rows["FURIN"]["omnipath"]["links"][0]["direction"], "in")
        summary = {key: found["summary"][key] for key in (
            "hpa", "omnipath", "both", "union", "jaccard", "omnipath_in_hpa", "hpa_in_omnipath",
            "via_complex_only")}
        self.assertEqual(summary, {
            "hpa": 2, "omnipath": 4, "both": 1, "union": 5, "jaccard": 0.2,
            "omnipath_in_hpa": 0.25, "hpa_in_omnipath": 0.5, "via_complex_only": 1})
        # Without STRING mirrored, two networks and nothing pretended.
        self.assertEqual(found["summary"]["networks"], ["hpa", "omnipath"])
        self.assertIsNone(found["summary"]["string"])
        self.assertEqual(sum(c["count"] for c in found["summary"]["combinations"]), 5)

    def test_a_complex_acts_as_one_and_its_members_are_not_partners(self):
        found = interactions.compare("PCSK9", "ENSG00000169174", self.mirror)
        rows = {row["symbol"]: row for row in found["partners"]}
        apob = rows["APOB"]["omnipath"]
        self.assertFalse(apob["direct"])
        self.assertEqual(apob["links"][0]["from"], "complex PCSK9/LDLR")
        # Not in HGNC: kept by accession, never dropped.
        self.assertEqual(rows["APOB"]["ensembl_id"], "")
        # LDLR is PCSK9's partner through its own row, not through sharing
        # the complex; the gene acting on itself alone is recorded.
        self.assertTrue(rows["LDLR"]["omnipath"]["direct"])
        self.assertTrue(rows["PCSK9"]["omnipath"]["direct"])

    def test_string_joins_on_genes_and_a_weak_link_alone_is_not_a_partner(self):
        (self.root / "string").mkdir()
        (self.root / "string" / "physical.tsv").write_text(
            "gene_a\tgene_b\texperimental\tdatabase\ttextmining\tcombined_score\n"
            "ENSG00000169174\tENSG00000073060\t150\t0\t100\t250\n"   # SCARB1, weak
            "ENSG00000169174\tENSG00000130164\t900\t900\t800\t999\n"  # LDLR
            "ENSG00000169174\tENSG00000999999\t0\t0\t300\t300\n"     # weak, alone
            "ENSG00000169174\tENSG00000888888\t500\t0\t0\t500\n",    # medium, alone
            encoding="utf-8")
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        manifest["sources"]["string"] = {"label": "STRING", "version": "12.5",
                                         "retrieved": "2026-10-28",
                                         "files": {"physical": "string/physical.tsv"}}
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        found = interactions.compare("PCSK9", "ENSG00000169174", Mirror.load(self.root))
        rows = {row["ensembl_id"]: row for row in found["partners"]}
        self.assertNotIn("ENSG00000999999", rows)
        self.assertEqual(rows["ENSG00000888888"]["networks"], ["string"])
        # SCARB1 keeps its weak score for reading, but is not counted in STRING.
        self.assertEqual(rows["ENSG00000073060"]["string"]["score"], 0.25)
        self.assertEqual(rows["ENSG00000073060"]["networks"], ["hpa"])
        self.assertEqual(found["partners"][0]["symbol"], "LDLR")  # in all three
        self.assertEqual(found["partners"][0]["networks"], ["hpa", "omnipath", "string"])
        self.assertEqual(found["summary"]["string"], 2)

    def test_regulators_read_the_local_copy(self):
        one = regulators.single("PCSK9", Live(self.root, allowed=False), self.mirror)
        self.assertEqual(one["state"], "ok")
        self.assertEqual(one["regulators"], {"SREBF2": "activates"})
        self.assertIn("local copy", one["source"])

    def test_without_omnipath_it_says_what_to_do(self):
        found = interactions.compare("PCSK9", "ENSG00000169174", Mirror.load(FIXTURE))
        self.assertIn("update them in Settings", found["error"])


if __name__ == "__main__":
    unittest.main()
