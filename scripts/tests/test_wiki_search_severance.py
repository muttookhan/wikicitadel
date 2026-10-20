#!/usr/bin/env python3
"""Retrieval severance in the search engine (item 20, part b).

scripts/wiki_search.py's hybrid_rank excludes, after every
ranking stage: results on a severed page, and results whose text
carries a severed claim the query itself hunts (the cue path is
cut; the page stays findable by other queries). These tests pin
that behaviour on a fixture corpus, including the off switch and
the LAST_SEVERANCE record the CLI / evidence pack report.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_search", ROOT / "scripts" / "wiki_search.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)

SEV_FORM = {
    "kind": "retrieval-severance", "version": 1,
    "entries": [{
        "id": "sev-0001", "kind": "decision-form",
        "page": "wiki/severed-home.md",
        "claim": "Galen's seat stays RESERVED",
        "cues": {"phrases": [["seat", "stays", "reserved"],
                             ["seat", "reserved"],
                             ["galen", "reserved"]],
                 "terms": ["galen", "reserved", "seat", "stays"]},
        "source": {"register": "evaluation/decisions-register.jsonl",
                   "line": 2, "record_id": "d1-old",
                   "signal": "superseded form"},
    }],
}

SEV_PAGE = {
    "kind": "retrieval-severance", "version": 1,
    "entries": [{
        "id": "sev-0001", "kind": "page",
        "page": "wiki/control.md", "claim": None,
        "cues": {"phrases": [], "terms": ["chapter", "record"]},
        "source": {"register": "wiki/ frontmatter",
                   "line": None, "record_id": "wiki/control.md",
                   "signal": "status: superseded"},
    }],
}

DOC_A = ("# Seat record\n\nGalen's seat stays RESERVED, the "
         "original form said. Notes on the galen seat question.\n")
DOC_B = ("# Chapter record\n\nThe galen seat question and the "
         "chapter 7 decisions. Reserved parking is elsewhere "
         "entirely.\n")


class HybridSeveranceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        self.docs = [
            (self.root / "wiki" / "severed-home.md", DOC_A),
            (self.root / "wiki" / "control.md", DOC_B),
        ]
        self.adj = ws.build_link_graph(self.docs)
        self._old_root = ws.ROOT
        ws.ROOT = self.root

    def tearDown(self):
        ws.ROOT = self._old_root
        self._tmp.cleanup()

    def paths(self, ranked):
        return [str(p.relative_to(self.root)) for _s, p, _t, _d in ranked]

    def test_cue_query_excludes_the_carrier(self):
        ranked = ws.hybrid_rank(ws.tokenize("galen seat reserved"),
                                self.docs, self.adj, severance=SEV_FORM)
        self.assertNotIn("wiki/severed-home.md", self.paths(ranked))
        self.assertEqual(
            ws.LAST_SEVERANCE["excluded"],
            [{"path": "wiki/severed-home.md",
              "entries": ["sev-0001"]}])
        self.assertTrue(ws.LAST_SEVERANCE["applied"])

    def test_other_queries_still_find_the_record(self):
        # The cue path is cut, not the page: a query that does not
        # hunt the dead form is not severed.
        ranked = ws.hybrid_rank(ws.tokenize("seat question notes"),
                                self.docs, self.adj, severance=SEV_FORM)
        self.assertIn("wiki/severed-home.md", self.paths(ranked))
        self.assertEqual(ws.LAST_SEVERANCE["excluded"], [])

    def test_severance_off_restores_the_carrier(self):
        ranked = ws.hybrid_rank(ws.tokenize("galen seat reserved"),
                                self.docs, self.adj, severance=False)
        self.assertIn("wiki/severed-home.md", self.paths(ranked))
        self.assertFalse(ws.LAST_SEVERANCE["applied"])

    def test_page_entry_severs_for_any_query(self):
        ranked = ws.hybrid_rank(ws.tokenize("chapter decisions"),
                                self.docs, self.adj, severance=SEV_PAGE)
        self.assertNotIn("wiki/control.md", self.paths(ranked))
        self.assertEqual(
            ws.LAST_SEVERANCE["excluded"],
            [{"path": "wiki/control.md", "entries": ["sev-0001"]}])

    def test_absent_list_changes_nothing(self):
        ranked = ws.hybrid_rank(ws.tokenize("galen seat reserved"),
                                self.docs, self.adj,
                                severance={"kind": "retrieval-severance",
                                           "entries": []})
        self.assertIn("wiki/severed-home.md", self.paths(ranked))


if __name__ == "__main__":
    unittest.main()
