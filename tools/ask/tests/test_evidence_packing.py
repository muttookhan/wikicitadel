"""Tests for token-budget evidence packing (batch 2.1).

Covers ``tools/ask/evidence_packing.py``: the budget is respected,
selection follows relevance order, ties are stable, and dropped
passages are reported with their reason.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_evidence_packing -v
or directly:
    python3 tools/ask/tests/test_evidence_packing.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence_packing  # noqa: E402


def passage(page, text, score=None):
    entry = {"page": page, "passage": text}
    if score is not None:
        entry["score"] = score
    return entry


class EstimateTokensTests(unittest.TestCase):
    def test_documented_approximation(self):
        self.assertEqual(evidence_packing.estimate_tokens(""), 0)
        self.assertEqual(evidence_packing.estimate_tokens("abcd"), 1)
        self.assertEqual(evidence_packing.estimate_tokens("abcde"), 2)
        self.assertEqual(evidence_packing.estimate_tokens("a" * 400), 100)


class PackEvidenceTests(unittest.TestCase):
    def test_budget_is_respected(self):
        passages = [
            passage("a", "x" * 400, 0.9),   # 100 tokens
            passage("b", "y" * 400, 0.8),   # 100 tokens
            passage("c", "z" * 400, 0.7),   # 100 tokens
        ]
        result = evidence_packing.pack_evidence(passages, budget=250)
        self.assertLessEqual(result["tokens_used"], 250)
        self.assertEqual(result["tokens_used"], 200)
        self.assertEqual(
            [p["page"] for p in result["packed"]], ["a", "b"]
        )

    def test_relevance_order_and_drops_reported(self):
        passages = [
            passage("low", "l" * 40, 0.2),
            passage("high", "h" * 40, 0.95),
            passage("mid", "m" * 40, 0.5),
        ]
        result = evidence_packing.pack_evidence(passages, budget=20)
        self.assertEqual(
            [p["page"] for p in result["packed"]], ["high", "mid"]
        )
        self.assertEqual(len(result["dropped"]), 1)
        self.assertEqual(result["dropped"][0]["page"], "low")
        self.assertEqual(result["dropped"][0]["reason"], "over-budget")

    def test_ties_keep_input_order(self):
        passages = [
            passage("first", "a" * 40, 0.5),
            passage("second", "b" * 40, 0.5),
            passage("third", "c" * 40, 0.5),
        ]
        result = evidence_packing.pack_evidence(passages, budget=1000)
        self.assertEqual(
            [p["page"] for p in result["packed"]],
            ["first", "second", "third"],
        )

    def test_smaller_later_passage_can_still_fit(self):
        passages = [
            passage("big", "b" * 400, 0.9),    # 100 tokens, dropped
            passage("small", "s" * 40, 0.8),   # 10 tokens, fits
        ]
        result = evidence_packing.pack_evidence(passages, budget=50)
        self.assertEqual(
            [p["page"] for p in result["packed"]], ["small"]
        )
        self.assertEqual(
            [p["page"] for p in result["dropped"]], ["big"]
        )

    def test_missing_score_counts_as_zero(self):
        passages = [
            passage("unscored", "u" * 40),
            passage("scored", "s" * 40, 0.1),
        ]
        result = evidence_packing.pack_evidence(passages, budget=1000)
        self.assertEqual(
            [p["page"] for p in result["packed"]],
            ["scored", "unscored"],
        )

    def test_empty_input(self):
        result = evidence_packing.pack_evidence([], budget=100)
        self.assertEqual(result["packed"], [])
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["tokens_used"], 0)
        self.assertEqual(result["budget"], 100)

    def test_zero_budget_drops_everything(self):
        result = evidence_packing.pack_evidence(
            [passage("a", "text", 0.9)], budget=0
        )
        self.assertEqual(result["packed"], [])
        self.assertEqual(len(result["dropped"]), 1)

    def test_input_passages_are_not_mutated(self):
        original = passage("a", "x" * 40, 0.9)
        evidence_packing.pack_evidence([original], budget=100)
        self.assertNotIn("tokens", original)


if __name__ == "__main__":
    unittest.main()
