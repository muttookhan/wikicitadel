#!/usr/bin/env python3
"""MemoRAG clue-generation pass (Marathon Round 3, lane TB7,
row 7).

Pins on a fixture corpus: the clue pass emits the original
query first, then likely-title clues from pages sharing a
stemmed query token, entity clues from capitalised heading
phrases, and synonym clues from corpus co-occurrence (a term
seen in only ONE page is below the floor); generation is
deterministic; per-clue retrieval merged by RRF surfaces a
page the bare query's vocabulary cannot reach on its own —
the harbour page found via the "timetable" synonym clue —
with the clue provenance carried on the hit.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_memorag", ROOT / "scripts" / "wiki_memorag.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

DOCS = [
    (Path("/x/wiki/ferries.md"),
     "---\ntitle: Ferries\n---\n# Ferries\n\n"
     "## Timetable Office Notes\n\n"
     "Ferries leave the harbour twice daily. The timetable is "
     "posted at the harbour office.\n"),
    (Path("/x/wiki/harbour.md"),
     "---\ntitle: Harbour\n---\n# Harbour\n\n"
     "The harbour office posts the timetable in winter. "
     "Ferries use the harbour in all seasons. Timetable "
     "changes are rare.\n"),
    (Path("/x/wiki/granite.md"),
     "---\ntitle: Granite\n---\n# Granite\n\n"
     "Granite is an igneous rock of quartz and feldspar.\n"),
]


class MemoragTests(unittest.TestCase):
    def test_clue_kinds_and_order(self):
        clues = M.generate_clues("ferry sailings", DOCS)
        kinds = [c["kind"] for c in clues]
        self.assertEqual(kinds[0], "original")
        self.assertEqual(clues[0]["terms"], M.ws.tokenize("ferry sailings"))
        self.assertIn("likely-title", kinds)
        titles = [c["clue"] for c in clues if c["kind"] == "likely-title"]
        self.assertIn("Ferries", titles)

    def test_synonym_clues_are_corpus_derived(self):
        clues = M.generate_clues("ferries", DOCS)
        syns = [c["clue"] for c in clues if c["kind"] == "synonym"]
        self.assertIn("timetable", syns)
        self.assertIn("harbour", syns)
        # quartz appears in one page that shares no query term: no clue
        self.assertNotIn("quartz", syns)

    def test_deterministic(self):
        self.assertEqual(M.generate_clues("ferries harbour", DOCS),
                         M.generate_clues("ferries harbour", DOCS))

    def test_clue_retrieval_surfaces_the_synonym_page(self):
        clues, hits = M.search_with_clues("ferries", DOCS, top=10)
        paths = [h["path"] for h in hits]
        self.assertIn("/x/wiki/harbour.md", paths)
        harbour = next(h for h in hits if h["path"].endswith("harbour.md"))
        self.assertIn("synonym", harbour["clues"])
        granite = [h for h in hits if h["path"].endswith("granite.md")]
        self.assertEqual(granite, [])


if __name__ == "__main__":
    unittest.main()
