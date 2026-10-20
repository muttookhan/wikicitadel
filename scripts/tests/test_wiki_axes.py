#!/usr/bin/env python3
"""Phase-2 harvest item 7: two-axis status/confidence discipline.
The conflation check is pure: lifecycle words on the confidence
axis (and the reverse) are flagged; correct pairings — including
status 'verified', which is OUR lifecycle state — are not.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
wv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wv)


class TestAxisConflation(unittest.TestCase):
    def test_confidence_value_on_status_axis(self):
        hits = wv.axis_conflation({"status": "high"})
        self.assertEqual(len(hits), 1)
        self.assertIn("CONFIDENCE", hits[0])

    def test_lifecycle_value_on_confidence_axis(self):
        hits = wv.axis_conflation({"confidence": "published"})
        self.assertEqual(len(hits), 1)
        self.assertIn("LIFECYCLE", hits[0])

    def test_correct_pairings_pass(self):
        self.assertEqual(wv.axis_conflation(
            {"status": "verified", "confidence": "medium"}), [])
        self.assertEqual(wv.axis_conflation({"status": "draft"}), [])
        self.assertEqual(wv.axis_conflation({"confidence": "high"}), [])
        self.assertEqual(wv.axis_conflation({}), [])

    def test_vocabulary_listing_is_not_a_claim(self):
        # A page documenting the states in one line is not flagged:
        # only exact single-value matches count.
        self.assertEqual(wv.axis_conflation(
            {"status": "proposed | decided | superseded"}), [])


if __name__ == "__main__":
    unittest.main()
