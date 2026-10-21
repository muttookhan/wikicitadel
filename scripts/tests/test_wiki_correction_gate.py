#!/usr/bin/env python3
"""Tests for scripts/wiki_correction_gate.py (TB3-4).

Pins: a correction whose DOI resolves in the scholarly
register, with quote + locator, is ACCEPTED; an unknown DOI
is REJECTED; a resolving DOI without quote or locator is
REJECTED; a correction with no scholarly citation is
NOT-SCHOLARLY (ordinary flow); a Crossref seam hit that is
not registered still REJECTS (the register is the
authority; the seam is injectable and off by default).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_correction_gate", SCRIPTS / "wiki_correction_gate.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def fixture():
    root = Path(tempfile.mkdtemp())
    (root / "evaluation").mkdir(parents=True)
    (root / "evaluation" / "scholarly-register.jsonl").write_text(
        json.dumps({"doi": "10.1000/example.1", "title": "T"}) + "\n",
        encoding="utf-8")
    return root


GOOD = {"claim": "c", "correction": "fixed",
        "citation": {"doi": "10.1000/example.1", "quote": "q",
                     "locator": "p. 4"}}


class FakeResolver:
    def resolve(self, doi):
        return {"doi": doi, "title": "from crossref"}


class TestGate(unittest.TestCase):
    def test_accepted(self):
        verdict, _ = M.gate(fixture(), GOOD)
        self.assertEqual(verdict, "accepted")

    def test_unknown_doi_rejected(self):
        bad = dict(GOOD, citation=dict(GOOD["citation"],
                                       doi="10.9999/nope"))
        verdict, _ = M.gate(fixture(), bad)
        self.assertEqual(verdict, "rejected")

    def test_missing_quote_rejected(self):
        bad = dict(GOOD, citation={"doi": "10.1000/example.1",
                                   "locator": "p. 4"})
        verdict, _ = M.gate(fixture(), bad)
        self.assertEqual(verdict, "rejected")

    def test_no_citation_not_scholarly(self):
        verdict, _ = M.gate(fixture(), {"claim": "c",
                                        "correction": "x"})
        self.assertEqual(verdict, "not-scholarly")

    def test_crossref_seam_alone_does_not_accept(self):
        bad = dict(GOOD, citation=dict(GOOD["citation"],
                                       doi="10.5555/seam-only"))
        verdict, reasons = M.gate(fixture(), bad,
                                  resolver=FakeResolver())
        self.assertEqual(verdict, "rejected")
        self.assertTrue(any("Crossref" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
