#!/usr/bin/env python3
"""Repeat/loop detector over eval outputs (lane TA2).

Pins scripts/wiki_repeat_check.py: a degenerately looping
answer (high repeated n-gram ratio, repeated sentences) is
flagged; a normal varied answer is not; identical answers to
different questions cluster — EXCEPT declared abstentions,
whose repetition is correct behaviour; empty answers are
skipped, not flagged. The checker is report-only by contract
(its main returns 0 on a completed scan).

Run:  python3 -m unittest discover -s scripts/tests
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


rc = load("wiki_repeat_check", "scripts/wiki_repeat_check.py")

LOOP = ("The fee is five coins and the fee is five coins and "
        "the fee is five coins and the fee is five coins and "
        "the fee is five coins and the fee is five coins.")
NORMAL = ("The harbour fee is nine coins since the spring "
          "ruling, payable at the office on Market Street "
          "before noon each working day.")


class TestRepetition(unittest.TestCase):
    def test_ratio_loop_vs_normal(self):
        self.assertGreater(
            rc.ngram_repeat_ratio(rc.tokens(LOOP), 4), 0.3)
        self.assertLess(
            rc.ngram_repeat_ratio(rc.tokens(NORMAL), 4), 0.3)

    def test_analyse_flags_loop_only(self):
        report = rc.analyse([
            {"id": "A", "answer": LOOP},
            {"id": "B", "answer": NORMAL},
        ])
        self.assertEqual(report["flagged_repetition"], ["A"])


class TestIdenticalClusters(unittest.TestCase):
    def test_identical_answers_cluster(self):
        report = rc.analyse([
            {"id": "A", "answer": NORMAL},
            {"id": "B", "answer": NORMAL},
            {"id": "C", "answer": "A different answer entirely, "
                                  "about tides and ledgers."},
        ])
        self.assertEqual(len(report["identical_clusters"]), 1)
        self.assertEqual(set(report["identical_answer_ids"]),
                         {"A", "B"})

    def test_abstentions_do_not_cluster(self):
        report = rc.analyse([
            {"id": "A", "answer": "Not recorded.",
             "abstained": True},
            {"id": "B", "answer": "Not recorded.",
             "abstained": True},
        ])
        self.assertEqual(report["identical_clusters"], [])

    def test_empty_answers_skipped(self):
        report = rc.analyse([{"id": "A", "answer": ""}])
        self.assertEqual(report["answers_scanned"], 0)
        self.assertEqual(report["flagged_repetition"], [])


if __name__ == "__main__":
    unittest.main()
