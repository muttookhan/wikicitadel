"""Tests for scripts/wiki_review_diff.py (Marathon R8 lane BB;
Difftastic adoption, MIT - external tool, never embedded).

Pins: difft absent -> stated fallback message + unified diff +
no failure; difft present (fake executable) -> difftastic driver
used; identical files -> changed False. No network.

Run: python3 -m unittest scripts.tests.test_wiki_review_diff
"""
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_review_diff", SCRIPTS / "wiki_review_diff.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class ReviewDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.a = self.dir / "a.json"
        self.b = self.dir / "b.json"
        self.a.write_text('{"x": 1}\n', encoding="utf-8")
        self.b.write_text('{"x": 2}\n', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_falls_back_with_stated_message(self):
        rep = MOD.review_diff(self.a, self.b,
                              which=lambda name: None)
        self.assertEqual(rep["driver"], "unified-diff")
        self.assertFalse(rep["difft_available"])
        self.assertIn("not on PATH", rep["message"])
        self.assertTrue(rep["changed"])
        self.assertIn('"x": 2', rep["diff"])

    def test_present_uses_difftastic(self):
        fake = self.dir / "difft"
        fake.write_text("#!/bin/sh\necho FAKE-DIFFT-OUTPUT\n"
                        "exit 1\n", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        rep = MOD.review_diff(
            self.a, self.b,
            which=lambda name: str(fake))
        self.assertEqual(rep["driver"], "difftastic")
        self.assertIn("FAKE-DIFFT-OUTPUT", rep["diff"])
        self.assertTrue(rep["changed"])

    def test_identical_files_unchanged(self):
        rep = MOD.review_diff(self.a, self.a,
                              which=lambda name: None)
        self.assertFalse(rep["changed"])

    def test_cli_absent_still_exit_0(self):
        env = dict(os.environ, PATH="/nonexistent-dir")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "wiki_review_diff.py"),
             str(self.a), str(self.b)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not on PATH", proc.stdout)


if __name__ == "__main__":
    unittest.main()
