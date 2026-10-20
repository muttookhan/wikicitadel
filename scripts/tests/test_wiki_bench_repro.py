#!/usr/bin/env python3
"""Tests for wiki_bench_repro.compare + wiki_scale_bench.synthetic_docs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_bench_repro  # noqa: E402
import wiki_scale_bench  # noqa: E402


def pack(coverage, mrr, hit=1.0):
    return {"results": {"bm25": {
        "citation_coverage": {"@1": 0.0, "@3": 0.0, "@5": 0.0, "@10": coverage},
        "mrr_must_cite": mrr, "hit_rate_topk": hit}}}


class TestCompare(unittest.TestCase):
    def test_regression_detected(self):
        reg, _ = wiki_bench_repro.compare(pack(0.9, 0.7), pack(0.8, 0.7))
        self.assertTrue(any("coverage@10" in r for r in reg))

    def test_improvement_not_regression(self):
        reg, imp = wiki_bench_repro.compare(pack(0.8, 0.6), pack(0.9, 0.6))
        self.assertEqual(reg, [])
        self.assertTrue(imp)

    def test_equal_is_neither(self):
        reg, imp = wiki_bench_repro.compare(pack(0.9, 0.7), pack(0.9, 0.7))
        self.assertEqual((reg, imp), ([], []))


class TestSynthetic(unittest.TestCase):
    def test_deterministic_and_sized(self):
        a = wiki_scale_bench.synthetic_docs(50)
        b = wiki_scale_bench.synthetic_docs(50)
        self.assertEqual(len(a), 50)
        self.assertEqual([t for _p, t in a], [t for _p, t in b])

    def test_probe_vocabulary_planted(self):
        docs = wiki_scale_bench.synthetic_docs(26)
        self.assertIn("alpha", docs[0][1])
        self.assertIn("alpha", docs[25][1])


if __name__ == "__main__":
    unittest.main()
