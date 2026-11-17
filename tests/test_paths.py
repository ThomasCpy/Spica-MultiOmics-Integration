"""The location of the mirror, which differs between a checkout and the exe.

An error here is expensive, and tests are cheap. A one-file build unpacks
itself into a temporary folder that the exe deletes on exit. A mirror there
would lose gigabytes of downloads at each exit.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica import paths


class TestDataDir(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        os.environ.pop("SPICA_DATA_DIR", None)

    def tearDown(self):
        self.environment.stop()

    def test_from_source_it_sits_in_the_checkout(self):
        self.assertEqual(paths.data_dir(), Path(paths.__file__).parent.parent / "data")

    def test_the_environment_variable_wins(self):
        os.environ["SPICA_DATA_DIR"] = r"X:\elsewhere"
        self.assertEqual(paths.data_dir(), Path(r"X:\elsewhere"))

    def test_frozen_it_sits_beside_the_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "Spica.exe"
            executable.write_text("", encoding="utf-8")
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", str(executable)):
                self.assertEqual(paths.data_dir(), Path(tmp) / "data")

    def test_frozen_somewhere_read_only_it_falls_back_to_the_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "Spica.exe"
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", str(executable)), \
                 mock.patch.object(paths, "_writable", return_value=False):
                landed = paths.data_dir()
        self.assertNotEqual(landed, Path(tmp) / "data")
        self.assertEqual(landed.name, "data")
        self.assertEqual(landed.parent.name, paths.APP_NAME)


class TestBundled(unittest.TestCase):
    def test_from_source_it_is_the_repository(self):
        self.assertTrue(paths.bundled("app.py").exists())

    def test_frozen_it_is_the_unpacked_bundle(self):
        with mock.patch.object(sys, "_MEIPASS", r"X:\unpacked", create=True):
            self.assertEqual(
                paths.bundled("frontend", "dist", "index.html"),
                Path(r"X:\unpacked") / "frontend" / "dist" / "index.html",
            )


if __name__ == "__main__":
    unittest.main()
