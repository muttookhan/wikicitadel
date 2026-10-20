#!/usr/bin/env python3
"""Phase-2 harvest item 9: talk-page dispute surfacing in the
Lens insights. dispute_items() is pure: open talk pages become
items in path order, resolved ones do not, and `about` resolves
to a real node id through the route table.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "build_lens", ROOT / "tools" / "lens" / "build_lens.py")
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)

PAGES = [
    {"path": "wiki/concepts/alpha.md", "id": "alpha", "title": "Alpha",
     "fm": {"title": "Alpha"}},
    {"path": "wiki/talk/alpha.md", "id": "query-alpha",
     "title": "Dispute: Alpha",
     "fm": {"about": "wiki/concepts/alpha.md", "dispute_status": "open"}},
    {"path": "wiki/talk/beta.md", "id": "query-beta",
     "title": "Dispute: Beta",
     "fm": {"about": "wiki/concepts/beta.md",
            "dispute_status": "resolved"}},
    {"path": "wiki/talk/gamma.md", "id": "query-gamma",
     "title": "Dispute: Gamma (about a missing page)",
     "fm": {"about": "wiki/concepts/gamma.md", "dispute_status": "open"}},
]
ROUTES = {"wiki/concepts/alpha": "alpha", "alpha": "alpha"}
BY_ID = {"alpha": PAGES[0]}


class TestDisputeItems(unittest.TestCase):
    def test_open_only_deterministic(self):
        items = bl.dispute_items(PAGES, ROUTES, BY_ID)
        self.assertEqual(len(items), 2)  # resolved beta excluded
        self.assertEqual(items[0]["pages"], ["alpha"])
        self.assertIn("Alpha", items[0]["text"])
        # Missing about-target: still surfaced, no dangling reference.
        self.assertEqual(items[1]["pages"], [])
        self.assertIn("Gamma", items[1]["text"])
        again = bl.dispute_items(PAGES, ROUTES, BY_ID)
        self.assertEqual(items, again)


if __name__ == "__main__":
    unittest.main()
