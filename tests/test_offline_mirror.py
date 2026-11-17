"""Offline by default, and the mirror kept up to date from inside the app.

No test here reaches the network: the release probes are replaced, and the
build steps are stand-ins that write files the way the real ones do.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from spica import mirrorbuild, settings
from spica.live import Live, network_allowed


def clean_env():
    return mock.patch.dict(os.environ, {"SPICA_OFFLINE": "", "SPICA_ONLINE": ""})


class OnlineSettingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SPICA_DATA_DIR": self.folder,
                                                "SPICA_OFFLINE": "", "SPICA_ONLINE": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_off_by_default(self):
        self.assertFalse(settings.load()["online"])
        self.assertFalse(network_allowed())
        self.assertFalse(Live.from_env(self.folder).allowed)

    def test_the_setting_turns_it_on(self):
        settings.save({"online": True})
        self.assertTrue(network_allowed())
        self.assertTrue(Live.from_env(self.folder).allowed)

    def test_the_environment_overrules_the_setting(self):
        settings.save({"online": True})
        with mock.patch.dict(os.environ, {"SPICA_OFFLINE": "1"}):
            self.assertFalse(network_allowed())
        settings.save({"online": False})
        with mock.patch.dict(os.environ, {"SPICA_ONLINE": "1"}):
            self.assertTrue(network_allowed())

    def test_an_explicit_choice_overrules_both(self):
        with mock.patch.dict(os.environ, {"SPICA_ONLINE": "1"}):
            self.assertFalse(Live.from_env(self.folder, allowed=False).allowed)

    def test_the_app_reports_and_changes_it(self):
        import app

        api = app.Api()
        self.assertEqual(api.settings_status()["online"], False)
        self.assertTrue(api.set_online(True)["online_effective"])
        self.assertFalse(api.set_online(False)["online_effective"])


class BuilderTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.saved = (mirrorbuild.DATA, mirrorbuild.MANIFEST, mirrorbuild.STATUS,
                      mirrorbuild.LOG, mirrorbuild.LATEST)
        mirrorbuild.use(self.folder)

    def tearDown(self):
        (mirrorbuild.DATA, mirrorbuild.MANIFEST, mirrorbuild.STATUS,
         mirrorbuild.LOG, mirrorbuild.LATEST) = self.saved

    def test_files_are_swapped_in_whole(self):
        dest = self.folder / "x.tsv"
        mirrorbuild.write_atomic(dest, "a\tb\n")
        self.assertEqual(dest.read_text(encoding="utf-8"), "a\tb\n")
        self.assertFalse(dest.with_suffix(".tsv.part").exists())
        archive = self.folder / "y.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("y.tsv", "Gene\tLevel\n")
        mirrorbuild.unzip_one(archive, self.folder / "y.tsv")
        self.assertEqual((self.folder / "y.tsv").read_text(encoding="utf-8"), "Gene\tLevel\n")
        self.assertFalse((self.folder / "y.tsv.part").exists())

    def test_a_build_reports_each_source_and_survives_a_failure(self):
        def good(refresh):
            mirrorbuild.record("good", {"label": "Good", "version": "2", "retrieved": "today",
                                        "files": {}})

        def bad(refresh):
            raise RuntimeError("upstream is down")

        with mock.patch.dict(mirrorbuild.STEPS, {"good": good, "bad": bad}, clear=True), \
                mock.patch("sys.stdout", None):
            code = mirrorbuild.build(["bad", "good"], refresh=True)
        self.assertEqual(code, 1)
        status = json.loads(mirrorbuild.STATUS.read_text(encoding="utf-8"))
        self.assertFalse(status["running"])
        self.assertEqual(status["done"], ["good"])
        self.assertIn("upstream is down", status["failed"]["bad"])
        self.assertTrue(status["finished"])
        manifest = json.loads(mirrorbuild.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sources"]["good"]["version"], "2")
        self.assertIn("good: done", mirrorbuild.LOG.read_text(encoding="utf-8"))

    def test_latest_asks_every_source_and_keeps_the_answer(self):
        probes = {"hgnc": lambda: "2026-11-01", "gtex": lambda: (_ for _ in ()).throw(
            OSError("bucket unreachable"))}
        with mock.patch.dict(mirrorbuild.PROBES, probes, clear=True):
            result = mirrorbuild.latest()
        self.assertEqual(result["sources"]["hgnc"], {"version": "2026-11-01", "error": ""})
        self.assertIn("bucket unreachable", result["sources"]["gtex"]["error"])
        kept = json.loads(mirrorbuild.LATEST.read_text(encoding="utf-8"))
        self.assertEqual(kept["sources"]["hgnc"]["version"], "2026-11-01")

    def test_every_step_has_a_probe(self):
        self.assertEqual(set(mirrorbuild.STEPS), set(mirrorbuild.PROBES))


class StatusTest(unittest.TestCase):
    """What the app shows: local against upstream, and a build that died."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"SPICA_DATA_DIR": str(self.folder)})
        self.env.start()
        self.saved = (mirrorbuild.DATA, mirrorbuild.MANIFEST, mirrorbuild.STATUS,
                      mirrorbuild.LOG, mirrorbuild.LATEST)
        mirrorbuild.use(self.folder)
        (self.folder / "gtex").mkdir()
        (self.folder / "gtex" / "median_tpm.gct").write_text("x" * 100, encoding="utf-8")
        (self.folder / "mirror.json").write_text(json.dumps({"mirror_version": "1", "sources": {
            "gtex": {"label": "GTEx", "version": "v10", "retrieved": "2026-01-01",
                     "files": {"median_tpm": "gtex/median_tpm.gct"}}}}), encoding="utf-8")
        mirrorbuild.LATEST.write_text(json.dumps({"checked": "2026-10-26", "sources": {
            "gtex": {"version": "v11", "error": ""}}}), encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        (mirrorbuild.DATA, mirrorbuild.MANIFEST, mirrorbuild.STATUS,
         mirrorbuild.LOG, mirrorbuild.LATEST) = self.saved

    def test_a_newer_release_is_flagged(self):
        import app

        status = app.Api().mirror_status()
        gtex = next(row for row in status["rows"] if row["key"] == "gtex")
        self.assertEqual((gtex["version"], gtex["latest"], gtex["newer"]), ("v10", "v11", True))
        self.assertEqual(gtex["bytes"], 100)
        hgnc = next(row for row in status["rows"] if row["key"] == "hgnc")
        self.assertEqual(hgnc["version"], "")  # not built
        self.assertEqual(status["checked"], "2026-10-26")

    def test_a_build_that_stopped_beating_is_not_running(self):
        import app

        mirrorbuild.STATUS.write_text(json.dumps({"running": True, "beat": 0, "started": "x",
                                                  "finished": ""}), encoding="utf-8")
        job = app.Api().mirror_status()["job"]
        self.assertFalse(job["running"])
        self.assertTrue(job["interrupted"])

    def test_an_update_needs_a_source(self):
        import app

        self.assertIn("No source selected", app.Api().mirror_update([], True)["error"])


if __name__ == "__main__":
    unittest.main()
