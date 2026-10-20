"""Tests for freshness attachment in evidence packing
(consolidated-queue item 46).

``evidence_packing.pack_evidence(..., freshness=...)`` attaches
the per-page freshness record (scripts/wiki_search.py's
``freshness_record`` shape) to each packed/dropped entry whose
page carries a signal — the annotation travels with the
evidence at the moment of use. Signal-less pages gain no key.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_freshness_packing -v
or directly:
    python3 tools/ask/tests/test_freshness_packing.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence_packing  # noqa: E402


def record(line, **kw):
    base = {"verified_until": None, "overdue": False,
            "superseded": False, "superseded_by": None,
            "standing": None, "line": line}
    base.update(kw)
    return base


DUE = record("⚠ re-verification due 2026-10-20", overdue=True)
SILENT = record(None)


def passage(page, text, score=None):
    entry = {"page": page, "passage": text}
    if score is not None:
        entry["score"] = score
    return entry


class FreshnessPackingTests(unittest.TestCase):
    def test_mapping_form_page_id_matches_repo_path_key(self):
        result = evidence_packing.pack_evidence(
            [passage("overview", "x" * 40, 1.0)],
            budget=100, freshness={"wiki/overview.md": DUE})
        self.assertTrue(result["freshness_applied"])
        self.assertEqual(result["packed"][0]["freshness"], DUE)

    def test_silent_record_attaches_nothing(self):
        result = evidence_packing.pack_evidence(
            [passage("overview", "x" * 40, 1.0)],
            budget=100, freshness={"overview": SILENT})
        self.assertTrue(result["freshness_applied"])
        self.assertNotIn("freshness", result["packed"][0])

    def test_unmapped_page_attaches_nothing(self):
        result = evidence_packing.pack_evidence(
            [passage("other", "x" * 40, 1.0)],
            budget=100, freshness={"wiki/overview.md": DUE})
        self.assertNotIn("freshness", result["packed"][0])

    def test_callable_form(self):
        result = evidence_packing.pack_evidence(
            [passage("overview", "x" * 40, 1.0),
             passage("other", "y" * 40, 0.5)],
            budget=100,
            freshness=lambda page: DUE if page == "overview"
            else None)
        self.assertEqual(result["packed"][0]["freshness"], DUE)
        self.assertNotIn("freshness", result["packed"][1])

    def test_dropped_entries_carry_freshness_too(self):
        result = evidence_packing.pack_evidence(
            [passage("a", "x" * 400, 0.9),
             passage("overview", "y" * 400, 0.8)],
            budget=100, freshness={"wiki/overview.md": DUE})
        self.assertEqual(len(result["dropped"]), 1)
        self.assertEqual(result["dropped"][0]["page"], "overview")
        self.assertEqual(result["dropped"][0]["freshness"], DUE)

    def test_no_freshness_no_flag_no_keys(self):
        result = evidence_packing.pack_evidence(
            [passage("overview", "x" * 40, 1.0)], budget=100)
        self.assertNotIn("freshness_applied", result)
        self.assertNotIn("freshness", result["packed"][0])


if __name__ == "__main__":
    unittest.main()
