#!/usr/bin/env python3
"""Retrieval severance in the Lens mirror (item 20, part b).

tools/lens/lenslib.py's PostingsIndex.hybrid_rank mirrors
scripts/wiki_search.py's hybrid_rank, severance stage included:
given the same severance list, both exclude the same results.
These tests run the fixture corpus through both implementations
and pin the agreement — including doc keys given as filesystem
paths, the form the Lens build passes.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wiki_search", ROOT / "scripts" / "wiki_search.py")
L = _load("lenslib", ROOT / "tools" / "lens" / "lenslib.py")

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

DOC_A = ("# Seat record\n\nGalen's seat stays RESERVED, the "
         "original form said. Notes on the galen seat question.\n")
DOC_B = ("# Decisions record\n\nThe galen seat question and the "
         "decisions record. Reserved parking is elsewhere "
         "entirely.\n")


class LensSeveranceParityTests(unittest.TestCase):
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

    def test_mirror_excludes_identically(self):
        terms = ws.tokenize("galen seat reserved")
        ref = ws.hybrid_rank(terms, self.docs, self.adj,
                             severance=SEV_FORM)
        ref_paths = [str(p.relative_to(self.root))
                     for _s, p, _t, _d in ref]
        # Keys as the Lens build passes them: filesystem paths.
        idx = L.PostingsIndex(
            [{"key": str(p), "text": t} for p, t in self.docs],
            severance=SEV_FORM)
        mine = idx.hybrid_rank(terms, self.adj)
        my_paths = [L._sev_relpath(idx.docs[i]["key"])
                    for _s, i, _d in mine]
        self.assertEqual(ref_paths, my_paths)
        self.assertNotIn("wiki/severed-home.md", my_paths)
        self.assertEqual(idx.last_severance["excluded"],
                         ws.LAST_SEVERANCE["excluded"])

    def test_mirror_without_list_is_unchanged(self):
        terms = ws.tokenize("galen seat reserved")
        idx = L.PostingsIndex(
            [{"key": str(p), "text": t} for p, t in self.docs])
        mine = idx.hybrid_rank(terms, self.adj)
        paths = [L._sev_relpath(idx.docs[i]["key"])
                 for _s, i, _d in mine]
        self.assertIn("wiki/severed-home.md", paths)
        self.assertEqual(idx.last_severance["excluded"], [])
        self.assertFalse(idx.last_severance["applied"])

    def test_relpath_recovery(self):
        self.assertEqual(L._sev_relpath("wiki/a/b.md"), "wiki/a/b.md")
        self.assertEqual(
            L._sev_relpath("/home/x/llm-wiki/wiki/a/b.md"),
            "wiki/a/b.md")
        self.assertEqual(
            L._sev_relpath("/home/x/llm-wiki/raw/f.md"), "raw/f.md")


if __name__ == "__main__":
    unittest.main()
