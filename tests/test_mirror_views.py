"""The views that left the APIs: per transcript, per residue, per brain region.

Each is pinned on small files written the way the mirror builder writes
them, and each must answer without the network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica import isoforms, structure
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror
from spica.record import NullState

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"
TAB, NL = chr(9), chr(10)


def tsv(rows):
    return NL.join(TAB.join(row) for row in rows) + NL


class MirrorViewsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "mirror"
        shutil.copytree(FIXTURE, self.root)
        manifest = json.loads((self.root / "mirror.json").read_text(encoding="utf-8"))
        sources = manifest["sources"]
        (self.root / "hpa" / "rna_brain_region_hpa.tsv").write_text(tsv([
            ["Gene", "Gene name", "Brain region", "TPM", "pTPM", "nTPM"],
            ["ENSG00000169174", "PCSK9", "cerebellum", "20.1", "22.0", "21.3"],
            ["ENSG00000169174", "PCSK9", "amygdala", "0.4", "0.5", "0.5"]]), encoding="utf-8")
        (self.root / "hpa" / "transcript_tissue_median.tsv").write_text(tsv([
            ["ensgid", "enstid", "liver", "lung"],
            ["ENSG00000169174", "ENST00000302118", "40.00", "2.00"],
            ["ENSG00000169174", "ENST00000543384", "1.00", "6.00"]]), encoding="utf-8")
        (self.root / "ensembl" / "transcripts.tsv").write_text(tsv([
            ["Gene stable ID", "Transcript stable ID", "Transcript name", "Transcript type",
             "Ensembl Canonical"],
            ["ENSG00000169174", "ENST00000302118", "PCSK9-201", "protein_coding", "1"],
            ["ENSG00000169174", "ENST00000543384", "PCSK9-202", "protein_coding", ""]]),
            encoding="utf-8")
        (self.root / "alphafold").mkdir(exist_ok=True)
        (self.root / "alphafold" / "plddt_residues.tsv").write_text(tsv([
            ["accession", "start", "plddt"], ["Q8NBP7", "1", "50.5,70.0,91.2"]]), encoding="utf-8")
        (self.root / "alphafold" / "missense_residues.tsv").write_text(tsv([
            ["accession", "means"], ["Q8NBP7", "0.100,,0.800"]]), encoding="utf-8")
        # The fixture's UniProt row lists PDB IDs without chains, which sends
        # the structure view to the API for segments; a protein with no
        # structure keeps this test offline.
        entries = self.root / "uniprot" / "entries.tsv"
        lines = entries.read_text(encoding="utf-8").split(NL)
        head = lines[0].split(TAB)
        at = head.index("PDB")
        lines = [lines[0]] + [TAB.join(cells[:at] + [""] + cells[at + 1:])
                              for cells in (line.split(TAB) for line in lines[1:] if line)]
        entries.write_text(NL.join(lines) + NL, encoding="utf-8")
        sources["hpa"]["files"].update({"brain_region": "hpa/rna_brain_region_hpa.tsv",
                                        "transcripts": "hpa/transcript_tissue_median.tsv"})
        sources["ensembl"]["files"]["transcripts"] = "ensembl/transcripts.tsv"
        sources["alphafold"]["files"].update({"plddt_residues": "alphafold/plddt_residues.tsv",
                                              "missense_residues": "alphafold/missense_residues.tsv"})
        (self.root / "mirror.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.mirror = Mirror.load(self.root)

        def refuse(url, headers, timeout, body=None):
            raise AssertionError(f"a mirrored view asked the network for {url}")

        self.live = Live(self.root, opener=refuse)

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def test_brain_regions_come_from_hpa(self):
        record = build_record("PCSK9", self.mirror, self.live)
        self.assertEqual(record.value("hpa_brain_region_ntpm"), {"cerebellum": 21.3, "amygdala": 0.5})

    def test_without_the_brain_file_it_says_which_file(self):
        record = build_record("PCSK9", Mirror.load(FIXTURE), Live(FIXTURE, allowed=False))
        value = record.fields["hpa_brain_region_ntpm"]
        self.assertIs(value.state, NullState.NOT_COVERED)
        self.assertIn("brain_region", value.reason)

    def test_isoforms_from_hpa_with_ensembl_names(self):
        table = isoforms.table("PCSK9", "ENSG00000169174", self.live, self.mirror)
        self.assertEqual([t["name"] for t in table["transcripts"]], ["PCSK9-201", "PCSK9-202"])
        self.assertTrue(table["transcripts"][0]["canonical"])
        self.assertEqual(table["dominant"]["lung"], {"transcript": "ENST00000543384", "share": 75.0})
        self.assertIn("HPA", table["dataset"])

    def test_residues_from_the_mirror(self):
        found = structure.profile("Q8NBP7", self.live, self.mirror)
        self.assertEqual(found["plddt"], [[1, 50.5], [2, 70.0], [3, 91.2]])
        self.assertEqual(found["missense"], [[1, 0.1], [3, 0.8]])  # a gap stays a gap
        self.assertIn("local copy", found["source"])


class SigningTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("build_exe", ROOT / "tools" / "build_exe.py")
        self.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.build)

    def test_unsigned_unless_a_certificate_is_named(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("SPICA_SIGN_PFX", "SPICA_SIGN_THUMBPRINT"):
                os.environ.pop(key, None)
            self.assertIsNone(self.build.sign(Path("Spica.exe")))

    def test_a_named_certificate_without_signtool_fails_loudly(self):
        with mock.patch.dict(os.environ, {"SPICA_SIGN_THUMBPRINT": "abc"}), \
                mock.patch.object(self.build, "signtool", return_value=None):
            self.assertFalse(self.build.sign(Path("Spica.exe")))


if __name__ == "__main__":
    unittest.main()
