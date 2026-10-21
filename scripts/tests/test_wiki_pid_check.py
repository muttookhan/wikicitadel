"""Tests for scripts/wiki_pid_check.py (Marathon R8 lane BB;
idutils pattern, Revised BSD - re-implemented, stdlib only).

Pins: DOI/ARK/ORCID/Handle/URN detection + normalisation, ORCID
checksum failure, malformed-scheme errors, unknown scheme,
record-field checking, lockfile scan is read-only.

Run: python3 -m unittest scripts.tests.test_wiki_pid_check
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_pid_check", SCRIPTS / "wiki_pid_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class DetectTests(unittest.TestCase):
    def test_doi_forms(self):
        for raw in ("10.1000/xyz123", "doi:10.1000/xyz123",
                    "https://doi.org/10.1000/xyz123"):
            r = MOD.detect_and_normalise(raw)
            self.assertTrue(r["valid"], raw)
            self.assertEqual(r["scheme"], "doi")
            self.assertEqual(r["normalised"], "doi:10.1000/xyz123")

    def test_doi_malformed(self):
        r = MOD.detect_and_normalise("doi:9.9/nope")
        self.assertFalse(r["valid"])
        self.assertEqual(r["scheme"], "doi")

    def test_orcid_checksum(self):
        r = MOD.detect_and_normalise("0000-0002-1825-0097")
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["scheme"], "orcid")
        bad = MOD.detect_and_normalise("0000-0002-1825-0098")
        self.assertFalse(bad["valid"])

    def test_ark_urn_handle(self):
        r = MOD.detect_and_normalise("ark:/12345/x54xz321")
        self.assertTrue(r["valid"]); self.assertEqual(
            r["normalised"], "ark:/12345/x54xz321")
        r = MOD.detect_and_normalise("URN:ISBN:978-0-13-468599-1")
        self.assertTrue(r["valid"]); self.assertEqual(
            r["normalised"], "urn:isbn:978-0-13-468599-1")
        r = MOD.detect_and_normalise("hdl:1234.5/abc")
        self.assertTrue(r["valid"]); self.assertEqual(
            r["scheme"], "handle")

    def test_unknown_and_empty(self):
        self.assertFalse(MOD.detect_and_normalise(
            "just some words")["valid"])
        self.assertFalse(MOD.detect_and_normalise("")["valid"])

    def test_records_and_scan_readonly(self):
        rows = MOD.check_records(
            [{"id": "c1", "doi": "10.1000/xyz123"},
             {"id": "c2", "note": "no identifier field"}])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["valid"])
        lock = ROOT / "evaluation" / "citation-lockfile.json"
        before = hashlib.sha256(lock.read_bytes()).hexdigest()
        rep = MOD.scan_lockfile(lock)
        self.assertIn("identifiers_found", rep)
        self.assertEqual(
            before, hashlib.sha256(lock.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
