#!/usr/bin/env python3
"""Rosenthal threat-and-disclosure register (Marathon R8).

Pins scripts/wiki_threat_register.py and the seeded register
evaluation/threat-register.jsonl: every Rosenthal class has
exactly one row; mapped rows name evidence that exists in the
tree; the two classes with no stated strategy (economic /
organisational failure) stay blank as GAP findings — they are
reported, never papered over and never auto-remediated.
Run: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tr = load("wiki_threat_register", "scripts/wiki_threat_register.py")


class TestSeededRegister(unittest.TestCase):
    def setUp(self):
        self.header, self.rows = tr.load_register(tr.REGISTER)

    def test_header_and_one_row_per_class(self):
        self.assertIsNotNone(self.header)
        self.assertEqual({r["threat"] for r in self.rows},
                         set(tr.THREAT_CLASSES))
        self.assertEqual(len(self.rows), len(tr.THREAT_CLASSES))

    def test_mapped_rows_are_evidenced_in_this_tree(self):
        _u, unevidenced, structural = tr.findings(self.rows)
        self.assertEqual(unevidenced, [])
        self.assertEqual(structural, [])

    def test_gaps_stay_blank_as_findings(self):
        unmapped, _e, _s = tr.findings(self.rows)
        self.assertEqual(set(unmapped),
                         {"economic-failure", "organisational-failure"})
        for row in self.rows:
            if row["status"] == "gap":
                self.assertEqual(row["strategy"], "")
                self.assertEqual(row["evidence"], [])


class TestFindingsLogic(unittest.TestCase):
    def test_missing_class_and_missing_evidence_surface(self):
        rows = [{"threat": "attack", "strategy": "signed",
                 "evidence": ["no/such/path.py"], "status": "mapped"}]
        unmapped, unevidenced, _s = tr.findings(rows)
        self.assertTrue(any("attack" in u for u in unevidenced))
        self.assertEqual(len(unmapped), len(tr.THREAT_CLASSES) - 1)

    def test_mapped_without_strategy_is_structural(self):
        rows = [{"threat": "attack", "strategy": "",
                 "evidence": ["scripts/wiki_validate.py"],
                 "status": "mapped"}]
        _u, _e, structural = tr.findings(rows)
        self.assertTrue(structural)


if __name__ == "__main__":
    unittest.main()
