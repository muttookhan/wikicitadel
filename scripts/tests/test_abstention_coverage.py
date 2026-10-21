#!/usr/bin/env python3
"""Coverage-at-accuracy reporting for the abstention battery
(Marathon R8, Kamath et al., ACL 2020).

REPORTING ONLY: pins scripts/wiki_abstention_check.py's
coverage_report() on synthetic result rows — the answered /
abstained split, coverage, and accuracy-on-answered beside
the per-case pass/fail it summarises. No threshold, case or
decision-rule behaviour is touched (the battery file itself
is pinned elsewhere and stays byte-identical).
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


check = load("wiki_abstention_check_cov",
             "scripts/wiki_abstention_check.py")


def row(observed, ok):
    return {"id": "X", "kind": "k", "expected": observed,
            "observed": observed, "pass": ok, "detail": ""}


class TestCoverageReport(unittest.TestCase):
    def test_split_and_accuracy_on_answered(self):
        results = [row("answer", True), row("answer", False),
                   row("abstain", True), row("abstain", True),
                   row("hold", True)]
        cov = check.coverage_report(results)
        self.assertEqual(cov["total"], 5)
        self.assertEqual(cov["answered"], 2)
        self.assertEqual(cov["abstained"], 2)
        self.assertEqual(cov["other_verdicts"], 1)
        self.assertAlmostEqual(cov["coverage"], 0.4)
        self.assertAlmostEqual(cov["accuracy_on_answered"], 0.5)
        self.assertAlmostEqual(cov["accuracy_on_abstained"], 1.0)

    def test_no_answered_cases_accuracy_is_none_not_zero(self):
        cov = check.coverage_report([row("abstain", True)])
        self.assertEqual(cov["answered"], 0)
        self.assertIsNone(cov["accuracy_on_answered"])
        self.assertEqual(cov["coverage"], 0.0)

    def test_empty_results(self):
        cov = check.coverage_report([])
        self.assertEqual(cov["total"], 0)
        self.assertIsNone(cov["coverage"])


if __name__ == "__main__":
    unittest.main()
