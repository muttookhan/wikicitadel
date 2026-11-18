#!/usr/bin/env python3
"""GraphRAG community-summary map-reduce (Marathon Round 3,
lane TB7, row 4).

Pins on a fixture graph dict + fixture page texts (no live
corpus): the MAP step produces one summary per member page; the
REDUCE step produces one record per community with a summary
drawn from the member summaries, top terms and member titles;
consult() routes a query to the community whose summary owns
its terms and returns nothing for an unrelated query.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_graphrag", ROOT / "scripts" / "wiki_graphrag.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

GRAPH = {
    "nodes": [
        {"id": "wiki/a.md", "title": "Harbour", "out_degree": 1,
         "in_degree": 1},
        {"id": "wiki/b.md", "title": "Ferries", "out_degree": 1,
         "in_degree": 1},
        {"id": "wiki/c.md", "title": "Granite", "out_degree": 0,
         "in_degree": 0},
    ],
    "edges": [{"source": "wiki/a.md", "target": "wiki/b.md",
               "relation": "mentions", "kind": "wikilink"}],
    "communities": [
        {"id": "C1", "label": "wiki/a.md", "size": 2,
         "members": ["wiki/a.md", "wiki/b.md"],
         "top_pages": [{"id": "wiki/a.md", "title": "Harbour",
                        "degree": 2}]},
        {"id": "C2", "label": "wiki/c.md", "size": 1,
         "members": ["wiki/c.md"],
         "top_pages": [{"id": "wiki/c.md", "title": "Granite",
                        "degree": 0}]},
    ],
}

TEXTS = {
    "wiki/a.md": "---\ntitle: Harbour\n---\n# Harbour\n\n"
                 "The harbour shelters ferries in winter storms. "
                 "Harbour lights guide ferries home.\n",
    "wiki/b.md": "---\ntitle: Ferries\n---\n# Ferries\n\n"
                 "Ferries cross to the island twice daily. The "
                 "ferry timetable changes in winter.\n",
    "wiki/c.md": "---\ntitle: Granite\n---\n# Granite\n\n"
                 "Granite is an igneous rock of quartz and "
                 "feldspar.\n",
}


class GraphRagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            cls.records = G.build_summaries(Path(td), graph=GRAPH,
                                            page_texts=TEXTS)

    def test_map_reduce_shape(self):
        self.assertEqual(self.records["kind"], "community-summaries")
        self.assertEqual(self.records["counts"],
                         {"communities": 2, "pages": 3})
        c1 = self.records["communities"][0]
        self.assertEqual(set(c1["member_summaries"]),
                         {"wiki/a.md", "wiki/b.md"})
        for summary in c1["member_summaries"].values():
            self.assertTrue(summary)
        self.assertTrue(c1["summary"])
        self.assertIn("ferries", c1["top_terms"])
        self.assertEqual(c1["member_titles"], ["Harbour", "Ferries"])

    def test_reduce_summary_comes_from_member_summaries(self):
        c1 = self.records["communities"][0]
        joined = " ".join(c1["member_summaries"].values())
        for sent in c1["summary"].split(". "):
            sent = sent.strip().rstrip(".")
            if sent:
                self.assertIn(sent, joined)

    def test_consult_routes_queries(self):
        hits = G.consult(self.records, "winter ferries timetable")
        self.assertEqual(hits[0]["id"], "C1")
        hits = G.consult(self.records, "quartz feldspar igneous")
        self.assertEqual(hits[0]["id"], "C2")
        self.assertEqual(G.consult(self.records, "photosynthesis"), [])


if __name__ == "__main__":
    unittest.main()
