"""Tests for scripts/wiki_judge_ppi.py (Marathon R8 lane BB;
ARES/PPI reporting pattern, Apache-2.0).

Pins: labelled-n zero -> plain statement, NO interval, NO
accuracy; labelled-n > 0 -> PPI estimate + interval + accuracy;
report certifies nothing; register report states labelled-n
honestly for the shipped register.

Run: python3 -m unittest scripts.tests.test_wiki_judge_ppi
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_judge_ppi", SCRIPTS / "wiki_judge_ppi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class PpiReportTests(unittest.TestCase):
    def test_zero_labelled_n_no_interval(self):
        rep = MOD.ppi_report([0.9, 0.8, 1.0], [])
        self.assertEqual(rep["labelled_n"], 0)
        self.assertIsNone(rep["confidence_interval"])
        self.assertIsNone(
            rep["judge_accuracy_on_human_labels"])
        self.assertIn("labelled-n is zero", rep["statement"])
        self.assertFalse(rep["certifies"])

    def test_labelled_report(self):
        scores = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
        pairs = [(1.0, 1.0), (0.0, 0.0), (1.0, 0.0), (0.0, 0.0)]
        rep = MOD.ppi_report(scores, pairs)
        self.assertEqual(rep["labelled_n"], 4)
        self.assertIsNotNone(rep["confidence_interval"])
        lo, hi = rep["confidence_interval"]
        self.assertLessEqual(lo, rep["estimate"])
        self.assertLessEqual(rep["estimate"], hi)
        # judge mean 4/6 + rectifier mean(-0.25) = 0.4167
        self.assertAlmostEqual(rep["estimate"], 0.4167, places=3)
        self.assertAlmostEqual(
            rep["judge_accuracy_on_human_labels"], 0.75)

    def test_register_report_honest(self):
        rep = MOD.register_report()
        self.assertIn("labelled_n", rep)
        self.assertFalse(rep["certifies"])
        if rep["labelled_n"] == 0:
            self.assertIn("labelled-n is zero", rep["statement"])


if __name__ == "__main__":
    unittest.main()
