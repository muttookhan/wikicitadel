#!/usr/bin/env python3
"""Tests for scripts/wiki_corrections.py — the corrections
ledger's classification + repetition counter (consolidated
queue item 19, 2030-10-20).

The counter's whole point is the Bottomless-Pinocchio
lesson: an error kind that recurs after its first entry set
a rule against it is a different fact from a first error,
and must surface as a recurrence — not pass as a fresh,
unrelated entry.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_corrections_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_corrections_under_test", SCRIPTS / "wiki_corrections.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wc = load_corrections_module()

FIXTURE = """# Corrections ledger (fixture)

## Entries

### 2030-01-01 — The first overstatement

- **What was wrong:** a count was delivered unchecked.

### 2030-01-02 — A date stated wrongly

- **What was wrong:** the deadline was a day out.

### 2030-01-03 — The same overstatement again

- **What was wrong:** another count, delivered unchecked.

### 2030-01-04 — An entry nobody classified

- **What was wrong:** filed without a classification row.

## Classification

| Entry | Class | Error kind | Standing rule |
|---|---|---|---|
| 2030-01-01 — The first overstatement | correction | overstated-claim | check-the-count |
| 2030-01-02 — A date stated wrongly | correction | wrong-date | check-the-date |
| 2030-01-03 — The same overstatement again | correction | overstated-claim | check-the-count |
| 2030-01-05 — A row with no entry | correction | conduct | ghost-row |
"""


class FixtureReportTest(unittest.TestCase):
    def setUp(self):
        self.rep = wc.build_report(FIXTURE)

    def test_counts(self):
        self.assertEqual(self.rep["entries"], 4)
        self.assertEqual(self.rep["classified"], 3)
        self.assertEqual(self.rep["by_kind"]["overstated-claim"], 2)
        self.assertEqual(self.rep["by_kind"]["wrong-date"], 1)
        self.assertEqual(self.rep["by_class"]["correction"], 3)
        self.assertEqual(self.rep["by_rule"]["check-the-count"], 2)

    def test_recurrence_detected_in_ledger_order(self):
        rep = self.rep["repeated_since_ruled"]
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0]["date"], "2030-01-03")
        self.assertEqual(rep[0]["kind"], "overstated-claim")
        self.assertEqual(rep[0]["first_ruled"]["date"], "2030-01-01")
        self.assertEqual(rep[0]["first_ruled"]["rule"],
                         "check-the-count")
        self.assertEqual(
            self.rep["recurrences_by_kind"], {"overstated-claim": 1})

    def test_unclassified_and_orphan_rows_surface(self):
        self.assertEqual([e["date"] for e in self.rep["unclassified"]],
                         ["2030-01-04"])
        self.assertEqual(len(self.rep["orphan_classification_rows"]), 1)
        self.assertIn("2030-01-05", self.rep["orphan_classification_rows"][0])

    def test_no_recurrence_when_kinds_are_distinct(self):
        text = FIXTURE.replace("The same overstatement again",
                               "A different failure entirely").replace(
            "| 2030-01-03 — A different failure entirely | correction | overstated-claim | check-the-count |",
            "| 2030-01-03 — A different failure entirely | verdict-change | conduct | ask-first |")
        rep = wc.build_report(text)
        self.assertEqual(rep["repeated_since_ruled"], [])
        self.assertEqual(rep["by_class"]["verdict-change"], 1)


if __name__ == "__main__":
    unittest.main()
