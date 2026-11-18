#!/usr/bin/env python3
"""Tests for scripts/wiki_web_expand.py (SearXNG pattern, TB8 row 4).

Pins: confidence at/above threshold does nothing; below threshold
proposes queries deterministically; fetching is DEFAULT OFF (no
fetcher call, no files) even below threshold; enabled-without-
fetcher still makes no call; with an injected FAKE fetcher,
results land as UNFILED candidates with provenance under the out
dir only — never in wiki/, never marked compiled. No network:
the only fetcher in this suite is the fake.

Run:  python3 -m unittest discover -s scripts/tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_web_expand  # noqa: E402


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def __call__(self, query):
        self.calls.append(query)
        return [{"title": "A Result", "url": "https://example.org/a",
                 "snippet": "snippet text"},
                {"title": "B Result", "url": "https://example.org/b",
                 "snippet": "more"}]


class TestExpand(unittest.TestCase):
    def test_high_confidence_no_expansion(self):
        r = wiki_web_expand.run_expansion("q", 0.9)
        self.assertFalse(r["expanded"])
        self.assertEqual(r["proposed_queries"], [])
        self.assertFalse(r["fetched"])

    def test_threshold_boundary(self):
        r = wiki_web_expand.run_expansion("q", 0.5, threshold=0.5)
        self.assertFalse(r["expanded"])

    def test_low_confidence_proposes_but_default_off(self):
        fake = FakeFetcher()
        with tempfile.TemporaryDirectory() as td:
            r = wiki_web_expand.run_expansion(
                "multi word query", 0.2, fetcher=fake,
                out_dir=Path(td) / "cands")
            self.assertTrue(r["expanded"])
            self.assertIn('"multi word query"',
                          r["proposed_queries"])
            self.assertEqual(fake.calls, [])  # never called
            self.assertFalse(r["fetched"])
            self.assertFalse((Path(td) / "cands").exists())

    def test_enabled_without_fetcher_makes_no_call(self):
        with tempfile.TemporaryDirectory() as td:
            r = wiki_web_expand.run_expansion(
                "q", 0.1, enabled=True, fetcher=None,
                out_dir=Path(td) / "cands")
            self.assertFalse(r["fetched"])
            self.assertIn("no fetcher", r["reason"])

    def test_fake_fetcher_lands_unfiled_with_provenance(self):
        fake = FakeFetcher()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cands"
            r = wiki_web_expand.run_expansion(
                "obscure topic", 0.1, enabled=True, fetcher=fake,
                out_dir=out)
            self.assertTrue(r["fetched"])
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(len(r["candidates"]), 2)
            for cand in r["candidates"]:
                self.assertEqual(cand["status"], "unfiled")
                self.assertFalse(cand["compiled"])
                text = Path(cand["path"]).read_text(
                    encoding="utf-8")
                self.assertIn("status: unfiled", text)
                self.assertIn("compiled: false", text)
                self.assertIn("origin_url: https://example.org/",
                              text)
                self.assertIn("retrieval_confidence: 0.1", text)
                self.assertIn("NOT been ingested", text)
                self.assertTrue(
                    Path(cand["path"]).is_relative_to(out))

    def test_bad_confidence_rejected(self):
        with self.assertRaises(ValueError):
            wiki_web_expand.run_expansion("q", 1.5)


if __name__ == "__main__":
    unittest.main()
