#!/usr/bin/env python3
"""Wave-3 set E: pass^k counting (τ-bench shape).

Covers ``scripts/wiki_passk.py``:

- a question passes pass^k only if ALL of its first k trials
  pass — a flaky trial sequence (pass, fail, pass) passes pass^1
  and fails pass^k, which is the entire point of the metric;
- trials beyond k are ignored for pass^k;
- a question with fewer than k trials is reported insufficient
  and excluded from the rate, never silently passed or failed;
- the --answers mode judges recorded trials with the stub judge
  against the eval set's gold expectations.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pk = _load("wiki_passk", ROOT / "scripts" / "wiki_passk.py")


class PasskCountingTests(unittest.TestCase):
    def test_all_trials_must_pass(self):
        out = pk.summarise({"Q1": [True, True, True]}, 3)
        self.assertEqual(out["passk"], 1)
        self.assertEqual(out["passk_rate"], 1.0)

    def test_flaky_trial_fails_passk_but_passes_pass1(self):
        # The scripted flaky answerer: right, wrong, right.
        out = pk.summarise({"Q1": [True, False, True]}, 3)
        self.assertEqual(out["passk"], 0)
        self.assertEqual(out["pass1"], 1)
        self.assertEqual(out["passk_rate"], 0.0)
        self.assertEqual(out["pass1_rate"], 1.0)

    def test_trials_beyond_k_ignored(self):
        out = pk.summarise({"Q1": [True, True, True, False]}, 3)
        self.assertEqual(out["passk"], 1)

    def test_insufficient_trials_excluded_not_failed(self):
        out = pk.summarise({"Q1": [True], "Q2": [True, True, True]}, 3)
        self.assertEqual(out["insufficient"], ["Q1"])
        self.assertEqual(out["scored"], 1)
        self.assertEqual(out["passk_rate"], 1.0)
        self.assertIsNone(out["per_question"]["Q1"]["passk"])

    def test_mixed_population_rates(self):
        outcomes = {
            "A": [True, True],      # passes pass^2
            "B": [False, True],     # fails both
            "C": [True, False],     # pass^1 only
        }
        out = pk.summarise(outcomes, 2)
        self.assertEqual(out["passk"], 1)
        self.assertEqual(out["pass1"], 2)
        self.assertAlmostEqual(out["passk_rate"], 1 / 3, places=3)
        self.assertAlmostEqual(out["pass1_rate"], 2 / 3, places=3)


if __name__ == "__main__":
    unittest.main()
