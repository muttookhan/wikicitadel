"""Tests for strongest-source-first packing (item 33).

Covers ``tools/ask/standing.py`` (the fold of the treatment and
source-grades registers into per-page standings) and the
standing-aware ordering in ``evidence_packing.pack_evidence``:
the strongest standing packs first within the token budget,
negatively-treated passages are labelled (not hidden), and
packing without standings is exactly the pre-item-33 order.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_standing_packing -v
or directly:
    python3 tools/ask/tests/test_standing_packing.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence_packing  # noqa: E402
import standing  # noqa: E402


def treatment(page, claim, grade, tid="treat-0001"):
    # The register's real row shape: the subject nests page+claim.
    return {"kind": "treatment", "id": tid, "date": "2026-10-20",
            "subject": {"page": "wiki/%s.md" % page, "claim": claim},
            "grade": grade, "treated_by": {"source": "test"}}


def grade(source, axis, value, line=1):
    # The register's real row shape: source is a wiki/….md path.
    return {"kind": "grade", "source": "wiki/%s.md" % source,
            "axis": axis, "grade": value,
            "basis_event": {"detail": "test"}, "source_line": line}


class TestFold(unittest.TestCase):
    def test_negative_treatment_is_tier3_and_flagged(self):
        s = standing.fold_standings(
            [treatment("sources/x", "a dead claim", "negative")], [])
        entry = s["sources/x"]
        self.assertEqual(entry["tier"], 3)
        self.assertTrue(entry["negative"])
        self.assertIn("negative", entry["label"])

    def test_strongest_grade_makes_tier0(self):
        s = standing.fold_standings(
            [treatment("sources/x", "a claim", "followed")], [])
        self.assertEqual(s["sources/x"]["tier"], 0)

    def test_strongest_claim_governs_the_page(self):
        # Page-level fold (wiki_treatment's own rule): one
        # negative subject governs the page's packing order even
        # beside a followed one.
        s = standing.fold_standings([
            treatment("sources/x", "claim a", "followed"),
            treatment("sources/x", "claim b", "negative"),
        ], [])
        self.assertEqual(s["sources/x"]["tier"], 3)

    def test_source_axes_not_merged_weakest_axis_governs(self):
        s = standing.fold_standings([], [
            grade("sources/y", "integrity", "established"),
            grade("sources/y", "precision", "loose"),
        ])
        entry = s["sources/y"]
        self.assertEqual(entry["tier"], 2)
        self.assertIn("precision", entry["label"])

    def test_latest_grade_per_axis_wins(self):
        s = standing.fold_standings([], [
            grade("sources/y", "integrity", "questioned", line=1),
            grade("sources/y", "integrity", "established", line=2),
        ])
        self.assertEqual(s["sources/y"]["tier"], 0)

    def test_compromised_is_negative(self):
        s = standing.fold_standings(
            [], [grade("sources/y", "integrity", "compromised")])
        self.assertEqual(s["sources/y"]["tier"], 3)
        self.assertTrue(s["sources/y"]["negative"])

    def test_ungraded_page_is_neutral(self):
        s = standing.fold_standings([], [])
        entry = standing.standing_for(s, "sources/anything")
        self.assertEqual(entry["tier"], 1)
        self.assertEqual(entry["label"],
                         "neutral — no standing on record")
        self.assertFalse(entry["negative"])


class TestPackingOrder(unittest.TestCase):
    def setUp(self):
        self.standings = standing.fold_standings([
            treatment("sources/dead", "a dead claim", "negative"),
            treatment("sources/strong", "a claim", "followed"),
            grade("sources/loose", "precision", "loose"),
        ], [
            grade("sources/loose", "precision", "loose"),
        ])

    def test_strongest_packs_first_despite_lower_score(self):
        passages = [
            {"page": "sources/dead", "passage": "dead evidence",
             "score": 0.99},
            {"page": "sources/plain", "passage": "plain evidence",
             "score": 0.80},
            {"page": "sources/strong", "passage": "strong evidence",
             "score": 0.50},
        ]
        result = evidence_packing.pack_evidence(
            passages, standings=self.standings)
        order = [e["page"] for e in result["packed"]]
        self.assertEqual(
            order,
            ["sources/strong", "sources/plain", "sources/dead"])
        self.assertTrue(result["standing_applied"])

    def test_negative_passage_is_labelled_not_hidden(self):
        passages = [
            {"page": "sources/dead", "passage": "the only evidence",
             "score": 0.9},
        ]
        result = evidence_packing.pack_evidence(
            passages, standings=self.standings)
        self.assertEqual(len(result["packed"]), 1)
        entry = result["packed"][0]
        self.assertTrue(entry["standing"]["negative"])
        self.assertEqual(entry["standing"]["tier"], 3)
        self.assertIn("negative", entry["standing"]["label"])

    def test_weakened_packs_between_neutral_and_negative(self):
        passages = [
            {"page": "sources/dead", "passage": "d", "score": 0.9},
            {"page": "sources/loose", "passage": "l", "score": 0.9},
            {"page": "sources/plain", "passage": "p", "score": 0.9},
        ]
        result = evidence_packing.pack_evidence(
            passages, standings=self.standings)
        self.assertEqual(
            [e["page"] for e in result["packed"]],
            ["sources/plain", "sources/loose", "sources/dead"])

    def test_without_standings_legacy_order_and_no_labels(self):
        passages = [
            {"page": "sources/dead", "passage": "dead evidence",
             "score": 0.99},
            {"page": "sources/strong", "passage": "strong evidence",
             "score": 0.50},
        ]
        result = evidence_packing.pack_evidence(passages)
        self.assertEqual(
            [e["page"] for e in result["packed"]],
            ["sources/dead", "sources/strong"])
        self.assertNotIn("standing", result["packed"][0])
        self.assertNotIn("standing_applied", result)

    def test_dropped_entries_carry_standing_too(self):
        passages = [
            {"page": "sources/strong", "passage": "x" * 100,
             "score": 0.9},
            {"page": "sources/dead", "passage": "y" * 100,
             "score": 0.8},
        ]
        result = evidence_packing.pack_evidence(
            passages, budget=30, standings=self.standings)
        self.assertEqual(len(result["dropped"]), 1)
        self.assertIn("standing", result["dropped"][0])


if __name__ == "__main__":
    unittest.main()
