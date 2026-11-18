#!/usr/bin/env python3
"""The stale-context trap bench (lane TA2).

Pins scripts/wiki_stale_bench.py: the retrieval trap (a stale
page outranking the current page in the top-K, or a stale page
present with no current page), the summary trap (the
always-loaded summary carries the stale claim's terms and not
the current claim's — verification suppression), the combined
trap-spring rate per tier, and that the shipped case file loads
with all five tiers represented and every named page present
in the tree (a case pointing at a vanished page is rot).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = load("wiki_stale_bench", "scripts/wiki_stale_bench.py")


class TestTrapRules(unittest.TestCase):
    def test_stale_outranking_current_springs(self):
        ranked = ["wiki/old.md", "wiki/new.md"]
        sprung, _ = bench.retrieval_trap(
            ranked, ["wiki/old.md"], ["wiki/new.md"], 10)
        self.assertTrue(sprung)

    def test_current_first_is_safe(self):
        ranked = ["wiki/new.md", "wiki/old.md"]
        sprung, _ = bench.retrieval_trap(
            ranked, ["wiki/old.md"], ["wiki/new.md"], 10)
        self.assertFalse(sprung)

    def test_stale_without_current_springs(self):
        sprung, _ = bench.retrieval_trap(
            ["wiki/old.md"], ["wiki/old.md"], ["wiki/new.md"], 10)
        self.assertTrue(sprung)

    def test_no_stale_in_window_is_safe(self):
        sprung, _ = bench.retrieval_trap(
            ["wiki/new.md"], ["wiki/old.md"], ["wiki/new.md"], 10)
        self.assertFalse(sprung)

    def test_summary_trap_needs_stale_without_current(self):
        case = {"stale_claim_terms": ["seat is open"],
                "current_claim_terms": ["seat is reserved"]}
        sprung, _ = bench.summary_trap(
            "The seat is open for applications.", case)
        self.assertTrue(sprung)
        safe, _ = bench.summary_trap(
            "The seat is open — no: the seat is reserved.", case)
        self.assertFalse(safe)
        absent, _ = bench.summary_trap("Nothing relevant.", case)
        self.assertFalse(absent)


def fixture_tree(tmp):
    root = Path(tmp)
    (root / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "wiki_search.py",
                root / "scripts" / "wiki_search.py")
    (root / "wiki").mkdir()
    (root / "wiki" / "overview.md").write_text(
        "# Overview\n\nThe harbour fee is five coins.\n",
        encoding="utf-8")
    (root / "wiki" / "old-fees.md").write_text(
        "# Old fees\n\nThe harbour fee is five coins, payable "
        "at the harbour office each morning.\n", encoding="utf-8")
    (root / "wiki" / "current-fees.md").write_text(
        "# Current fees\n\nThe harbour fee is now nine coins.\n",
        encoding="utf-8")
    return root


class TestRunOnFixtureTree(unittest.TestCase):
    def test_trap_springs_end_to_end(self):
        case = {"id": "SCB-T1", "tier": "recency",
                "question": "What is the harbour fee?",
                "stale_pages": ["wiki/old-fees.md"],
                "current_pages": ["wiki/current-fees.md"],
                "stale_claim_terms": ["fee is five coins"],
                "current_claim_terms": ["fee is now nine coins"],
                "summary_page": "wiki/overview.md"}
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_tree(tmp)
            report = bench.run_cases([case], root)
        self.assertEqual(report["cases"], 1)
        row = report["rows"][0]
        # The summary carries the stale claim only: sprung.
        self.assertTrue(row["summary_trap"], row)
        self.assertTrue(row["sprung"], row)
        self.assertEqual(report["by_tier"]["recency"]
                         ["trap_spring_rate"], 1.0)


class TestShippedCases(unittest.TestCase):
    def test_cases_load_all_tiers_pages_exist(self):
        _header, cases = bench.load_cases(bench.DEFAULT_CASES)
        self.assertGreaterEqual(len(cases), 5)
        self.assertEqual({c["tier"] for c in cases},
                         set(bench.TIERS))
        for case in cases:
            for page in (case.get("stale_pages") or []) + \
                        (case.get("current_pages") or []):
                self.assertTrue((ROOT / page).is_file(),
                                f"{case['id']}: {page} missing")


if __name__ == "__main__":
    unittest.main()
