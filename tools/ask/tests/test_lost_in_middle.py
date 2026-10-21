"""Tests for Lost-in-the-Middle evidence packing (Marathon R2
lane B1).

``evidence_packing.pack_evidence`` rearranges the PACKED list
of a pack of four or more for composition: strongest (by the
existing score / consideration order) at the head and tail,
weakest in the middle. Selection is unchanged; packs of 1-2
(and 3) passages are unchanged.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_lost_in_middle -v
or directly:
    python3 tools/ask/tests/test_lost_in_middle.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence_packing  # noqa: E402


def passage(page, score):
    return {"page": page, "passage": "text-%s" % page, "score": score}


# Six passages, distinct scores, deliberately NOT in score order.
SIX = [
    passage("mid-b", 0.70),
    passage("strongest", 0.95),
    passage("weakest", 0.50),
    passage("second", 0.90),
    passage("mid-a", 0.80),
    passage("weak-second", 0.60),
]
# Consideration order (score desc, ties by input):
#   strongest, second, mid-a, mid-b, weak-second, weakest
# Lost-in-the-Middle arrangement (even ranks, then odd reversed):
EXPECTED_SIX = [
    "strongest", "mid-a", "weak-second", "weakest", "mid-b", "second",
]


class LostInMiddlePackingTests(unittest.TestCase):
    def test_six_passage_arrangement(self):
        result = evidence_packing.pack_evidence(list(SIX), budget=1000)
        packed = result["packed"]
        self.assertEqual([p["page"] for p in packed], EXPECTED_SIX)
        self.assertTrue(result["lost_in_middle_applied"])
        # Strongest at the head, second-strongest at the tail.
        self.assertEqual(packed[0]["page"], "strongest")
        self.assertEqual(packed[-1]["page"], "second")
        # The weakest two meet in the middle.
        middle = {p["page"] for p in packed[2:4]}
        self.assertEqual(middle, {"weakest", "weak-second"})
        # Every score in the middle is <= every score at an end.
        end_scores = [packed[0]["score"], packed[-1]["score"]]
        mid_scores = [p["score"] for p in packed[2:4]]
        self.assertLessEqual(max(mid_scores), min(end_scores))

    def test_arrangement_is_deterministic(self):
        first = evidence_packing.pack_evidence(list(SIX), budget=1000)
        second = evidence_packing.pack_evidence(list(SIX), budget=1000)
        self.assertEqual(first, second)

    def test_selection_and_dropped_order_unchanged(self):
        # Budget fits only the two shortest/strongest by the
        # greedy pass; the rearrangement never resurrects a drop.
        passages = [
            {"page": "a", "passage": "x" * 40, "score": 0.9},
            {"page": "b", "passage": "y" * 40, "score": 0.8},
            {"page": "c", "passage": "z" * 400, "score": 0.7},
            {"page": "d", "passage": "w" * 400, "score": 0.6},
            {"page": "e", "passage": "v" * 400, "score": 0.5},
            {"page": "f", "passage": "u" * 400, "score": 0.4},
        ]
        result = evidence_packing.pack_evidence(passages, budget=100)
        self.assertEqual(
            sorted(p["page"] for p in result["packed"]), ["a", "b"]
        )
        self.assertEqual(
            [p["page"] for p in result["dropped"]],
            ["c", "d", "e", "f"],
        )

    def test_one_and_two_passage_packs_unchanged(self):
        # SIX[:1] is just mid-b; SIX[:2] adds strongest (0.95),
        # whose consideration order is strongest, mid-b. Both
        # packs stand exactly in consideration order.
        for fixture, expected in (
            (SIX[:1], ["mid-b"]),
            (SIX[:2], ["strongest", "mid-b"]),
        ):
            result = evidence_packing.pack_evidence(
                list(fixture), budget=1000
            )
            self.assertEqual(
                [p["page"] for p in result["packed"]], expected
            )
            self.assertNotIn("lost_in_middle_applied", result)

    def test_three_passage_pack_unchanged(self):
        result = evidence_packing.pack_evidence(
            list(SIX[:3]), budget=1000
        )
        self.assertEqual(
            [p["page"] for p in result["packed"]],
            ["strongest", "mid-b", "weakest"],
        )
        self.assertNotIn("lost_in_middle_applied", result)

    def test_arrange_helper_directly(self):
        ranked = ["a", "b", "c", "d", "e", "f"]
        self.assertEqual(
            evidence_packing.arrange_lost_in_middle(ranked),
            ["a", "c", "e", "f", "d", "b"],
        )
        self.assertEqual(ranked, ["a", "b", "c", "d", "e", "f"])
        small = ["a", "b"]
        self.assertIs(
            evidence_packing.arrange_lost_in_middle(small), small
        )

    def test_ties_ranked_by_existing_order(self):
        # Equal scores: the ranking that feeds the arrangement
        # is the caller's original order (stable), so the
        # arrangement is the deterministic one over that order.
        passages = [passage("p%d" % i, 0.5) for i in range(6)]
        result = evidence_packing.pack_evidence(passages, budget=1000)
        self.assertEqual(
            [p["page"] for p in result["packed"]],
            ["p0", "p2", "p4", "p5", "p3", "p1"],
        )


if __name__ == "__main__":
    unittest.main()
