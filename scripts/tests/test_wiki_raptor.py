#!/usr/bin/env python3
"""RAPTOR recursive summary trees (Marathon Round 3, lane TB7, row 3).

Pins on fixture pages: leaf passages at level 0; cluster
summaries above them; a single root; summaries are EXTRACTIVE
(every summary sentence appears verbatim in a child); the
summariser is a named slot with the extractive default and an
unknown name is refused; retrieval answers from a CHOSEN level
(the root for a broad query, a leaf for a specific one);
building twice gives the identical tree (determinism).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_raptor", ROOT / "scripts" / "wiki_raptor.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

PAGES = [
    {"path": "wiki/concepts/orchard.md", "title": "Orchard",
     "text": "---\ntitle: Orchard\n---\n# Orchard\n\n"
             "The orchard grows apples and pears. Apple trees need "
             "winter chill hours.\n\n"
             "Pear trees in the orchard are grafted by hand. "
             "Grafting joins two cultivars.\n"},
    {"path": "wiki/concepts/cider.md", "title": "Cider",
     "text": "---\ntitle: Cider\n---\n# Cider\n\n"
             "Cider is pressed from apples in autumn. The press "
             "crushes apples into pomace.\n\n"
             "Fermentation turns cider sweet to dry. Yeast drives "
             "the fermentation of cider.\n"},
    {"path": "wiki/concepts/granite.md", "title": "Granite",
     "text": "---\ntitle: Granite\n---\n# Granite\n\n"
             "Granite is an igneous rock of quartz and feldspar. "
             "Quarries cut granite blocks.\n"},
]


class RaptorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = R.build_tree(PAGES)

    def test_levels_and_root(self):
        kinds = {}
        for n in self.tree["nodes"]:
            kinds.setdefault(n["level"], []).append(n)
        self.assertIn(0, kinds)
        roots = [n for n in self.tree["nodes"] if n["kind"] == "root"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["level"], self.tree["levels"] - 1)
        # every page contributes leaf passages
        leaf_paths = {p for n in kinds[0] for p in n["paths"]}
        self.assertEqual(leaf_paths, {p["path"] for p in PAGES})

    def test_summaries_are_extractive(self):
        child_text = {}
        for n in self.tree["nodes"]:
            child_text[n["id"]] = n["text"]
        for n in self.tree["nodes"]:
            if n["level"] == 0:
                continue
            joined = " ".join(child_text[c] for c in n["children"])
            for sent in R.split_sentences(n["text"]):
                self.assertIn(sent, joined)

    def test_deterministic(self):
        self.assertEqual(R.build_tree(PAGES), self.tree)

    def test_query_from_any_level(self):
        root_hits = R.query_tree(self.tree, "orchard apples cider",
                                 level=self.tree["levels"] - 1)
        self.assertTrue(root_hits)
        self.assertEqual(root_hits[0]["kind"], "root")
        leaf_hits = R.query_tree(self.tree, "quartz feldspar", level=0)
        self.assertTrue(leaf_hits)
        self.assertEqual(leaf_hits[0]["paths"],
                         ["wiki/concepts/granite.md"])
        all_hits = R.query_tree(self.tree, "grafting cultivars")
        self.assertTrue(all_hits)
        self.assertTrue(any(h["level"] == 0 for h in all_hits))

    def test_summarizer_slot(self):
        self.assertIs(R.get_summarizer("extractive"),
                      R.SUMMARIZERS["extractive"])
        with self.assertRaises(ValueError):
            R.get_summarizer("some-model")
        s = R.ExtractiveSummarizer(max_sentences=1).summarize(
            ["Cats sleep all day. Dogs bark loudly. Cats sleep."])
        self.assertEqual(len(R.split_sentences(s)), 1)


if __name__ == "__main__":
    unittest.main()
