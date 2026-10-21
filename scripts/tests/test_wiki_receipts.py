#!/usr/bin/env python3
"""Tests for scripts/wiki_receipts.py (TB3-7).

Pins the in-toto-pattern contract on fixtures: receipts for
two steps of one run sign and verify (artefact hashes, the
per-run receipt chain, the register chain, the HMAC with a
TEST-ONLY local key); an artefact changed after its receipt
fails verify; a wrong key fails verify; a receipt line
altered in the register fails verify.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_receipts", SCRIPTS / "wiki_receipts.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def fixture():
    root = Path(tempfile.mkdtemp())
    (root / "evaluation").mkdir(parents=True)
    (root / "a.txt").write_text("artefact A", encoding="utf-8")
    (root / "b.txt").write_text("artefact B", encoding="utf-8")
    key = root / "test-key.bin"
    assert M.cmd_init_key(key) == 0
    assert M.cmd_sign(root, key, "run-1", "ingest", ["a.txt"]) == 0
    assert M.cmd_sign(root, key, "run-1", "compile", ["b.txt"]) == 0
    return root, key


class TestReceipts(unittest.TestCase):
    def test_sign_and_verify(self):
        root, key = fixture()
        ok, problems = M.verify(root, key.read_bytes())
        self.assertTrue(ok, problems)

    def test_changed_artefact_fails(self):
        root, key = fixture()
        (root / "a.txt").write_text("artefact A — edited",
                                    encoding="utf-8")
        ok, problems = M.verify(root, key.read_bytes())
        self.assertFalse(ok)
        self.assertTrue(any("artefact changed" in p for p in problems))

    def test_wrong_key_fails(self):
        root, key = fixture()
        ok, problems = M.verify(root, b"\x00" * 32)
        self.assertFalse(ok)
        self.assertTrue(any("HMAC" in p for p in problems))

    def test_tampered_register_line_fails(self):
        root, key = fixture()
        reg = root / "evaluation" / "pipeline-receipts.jsonl"
        text = reg.read_text(encoding="utf-8")
        reg.write_text(text.replace('"compile"', '"Compile"'),
                       encoding="utf-8")
        ok, problems = M.verify(root, key.read_bytes())
        self.assertFalse(ok)
        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
