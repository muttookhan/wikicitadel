#!/usr/bin/env python3
"""HyDE-style lexical query expansion (W3, 2026-10-22):
scripts/wiki_hyde_expand.py + the stage-0 hook in
scripts/wiki_search.py hybrid_rank.

Pins:
  - the draft: seeds are the query's own top BM25 hits, the
    record carries the original terms, every expansion term
    with its weight (< the originals' 1.0) and its draft
    evidence (draft_tf / df / idf), and the seed paths;
  - vocabulary mismatch: a page sharing NO term with the
    query is unretrievable by default and retrieved with
    expansion on, its detail stamped with the expansion
    contribution;
  - the default path is untouched: same-process A/B —
    hybrid_rank without the argument vs expansion=None —
    produces identical (score, path, detail) rankings on the
    fixture corpus;
  - the merged recall arithmetic: a document matching only
    expansion terms scores exactly weight x its raw BM25
    score for those terms;
  - governance composition (W1.5): an expansion built
    WITHOUT exclusions — its draft seeded by the withheld
    page itself, its terms pointing straight at it — still
    cannot resurrect the withheld page; stage 6 withholds
    it with its reasons, and LAST_GOVERNANCE records it;
  - severance composition (item 20): page-level and
    claim-text-match exclusions still remove pages the
    expansion boosts;
  - honesty edges: a query with no BM25 hits drafts nothing
    and expands to nothing; excluded paths never seed a
    draft; two builds of one expansion are byte-identical
    records.

Fixture corpora are in-memory (Path, text) pairs on fake
absolute paths — no disk, no tempfile.

Run:  python3 -m unittest scripts.tests.test_wiki_hyde_expand
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hyde = _load("wiki_hyde_expand", ROOT / "scripts" / "wiki_hyde_expand.py")
ws = _load("wiki_search_for_hyde_tests", ROOT / "scripts" / "wiki_search.py")


def doc(name, text):
    return (Path("/fix") / name, text)


# A vocabulary-mismatch corpus: the guide page speaks only the
# corpus's own words (westwind / lamp / beacon); the query
# speaks the visitor's (zephyr / lantern). Two harbour pages
# use both vocabularies — they are the draft the expansion is
# extracted from.
MISMATCH_DOCS = [
    doc("regatta.md",
        "zephyr lantern regatta notes. The zephyr lantern fleet "
        "answers the westwind lamp and the beacon lamp before "
        "the mast signal. westwind lamp westwind beacon."),
    doc("fair.md",
        "zephyr lantern fair. A zephyr lantern over the harbour, "
        "the westwind lamp lit, the beacon turning."),
    doc("beacon-guide.md",
        "westwind lamp beacon guide. The westwind lamp and the "
        "beacon lamp: how the lamp keeper reads the westwind "
        "and trims the beacon."),
    doc("orchard.md",
        "orchard ledger apples pears cider press harvest "
        "orchard ledger apples."),
    doc("quarry.md",
        "quarry stone granite slab quarry ledger stone dust."),
    doc("bakery.md",
        "bakery flour yeast oven loaf bakery ledger flour."),
    doc("ferry.md",
        "ferry tide timetable harbour ferry crossing tide."),
    doc("school.md",
        "school primer slate lesson school ledger primer."),
]

QUERY = ["zephyr", "lantern"]


def paths(ranked):
    return [str(p) for _s, p, _t, _d in ranked]


class DraftAndRecordTests(unittest.TestCase):
    def test_record_shape_and_weights(self):
        rec = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        self.assertEqual(rec["kind"], "hyde-lexical-expansion")
        self.assertEqual(rec["original_terms"], QUERY)
        self.assertEqual(set(rec["draft"]["seed_paths"]),
                         {"/fix/regatta.md", "/fix/fair.md"})
        terms = {e["term"]: e for e in rec["expansion_terms"]}
        self.assertTrue(terms, "draft must contribute vocabulary")
        for bridge in ("westwind", "lamp"):
            self.assertIn(bridge, terms)
        for e in rec["expansion_terms"]:
            self.assertEqual(e["weight"], hyde.DEFAULT_WEIGHT)
            self.assertLess(e["weight"], 1.0)
            self.assertGreaterEqual(e["draft_tf"], 1)
            self.assertGreaterEqual(e["df"], 1)
            self.assertIn("idf", e)
            self.assertIn("score", e)
        # query terms are never re-added as expansion terms
        self.assertFalse(set(terms) & set(QUERY))

    def test_deterministic(self):
        a = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        b = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        self.assertEqual(a, b)

    def test_excluded_paths_never_seed(self):
        rec = hyde.build_expansion(
            ws, QUERY, MISMATCH_DOCS,
            exclude_paths={"/fix/regatta.md"})
        self.assertEqual(rec["draft"]["seed_paths"], ["/fix/fair.md"])

    def test_no_hits_no_draft(self):
        rec = hyde.build_expansion(ws, ["qqzzx"], MISMATCH_DOCS)
        self.assertEqual(rec["expansion_terms"], [])
        self.assertEqual(rec["draft"]["seed_paths"], [])
        ranked = ws.hybrid_rank(["qqzzx"], MISMATCH_DOCS,
                                severance=False, governance=False,
                                expansion=rec)
        self.assertEqual(ranked, [])
        self.assertFalse(ws.LAST_EXPANSION["applied"])


class RetrievalEffectTests(unittest.TestCase):
    def test_mismatch_page_retrieved_only_with_expansion(self):
        off = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                             severance=False, governance=False)
        self.assertNotIn("/fix/beacon-guide.md", paths(off))
        rec = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        on = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                            severance=False, governance=False,
                            expansion=rec)
        self.assertIn("/fix/beacon-guide.md", paths(on))
        self.assertTrue(ws.LAST_EXPANSION["applied"])
        self.assertEqual(ws.LAST_EXPANSION["record"], rec)
        detail = {str(p): d for _s, p, _t, d in on}
        self.assertGreater(
            detail["/fix/beacon-guide.md"]["expansion_bm25"], 0.0)

    def test_default_path_byte_identical(self):
        a = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                           severance=False, governance=False)
        b = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                           severance=False, governance=False,
                           expansion=None)
        self.assertEqual(
            [(s, str(p), d) for s, p, _t, d in a],
            [(s, str(p), d) for s, p, _t, d in b])
        self.assertFalse(ws.LAST_EXPANSION["applied"])
        for _s, _p, _t, d in a:
            self.assertNotIn("expansion_bm25", d)

    def test_expansion_contribution_is_weighted_bm25(self):
        rec = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        on = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                            severance=False, governance=False,
                            expansion=rec)
        detail = {str(p): d for _s, p, _t, d in on}
        guide = detail["/fix/beacon-guide.md"]
        # the guide matches ONLY expansion terms, so its whole
        # recall score is weight x its raw BM25 for those terms
        terms = [t for t, _w in hyde.expansion_terms_of(rec)]
        raw = {str(p): s for s, p, _t
               in ws.bm25_rank(terms, MISMATCH_DOCS)}
        self.assertAlmostEqual(
            guide["expansion_bm25"],
            round(hyde.DEFAULT_WEIGHT * raw["/fix/beacon-guide.md"], 4),
            places=3)
        self.assertAlmostEqual(guide["bm25"], guide["expansion_bm25"],
                               places=3)


class GovernanceCompositionTests(unittest.TestCase):
    GOV = {"kind": "retrieval-governance",
           "pages": {"/fix/regatta.md": {
               "state": "withheld",
               "reasons": ["superseded by the current harbour "
                           "rules page"]}},
           "chains": {}}

    def test_expansion_cannot_resurrect_withheld_page(self):
        # built WITHOUT exclusions: the withheld page is the
        # draft's own first seed, and its vocabulary dominates
        # the expansion terms — the strongest form of the attack
        rec = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        self.assertIn("/fix/regatta.md", rec["draft"]["seed_paths"])
        on = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                            severance=False, governance=self.GOV,
                            expansion=rec)
        self.assertNotIn("/fix/regatta.md", paths(on))
        self.assertEqual(
            ws.LAST_GOVERNANCE["withheld"],
            [{"path": "/fix/regatta.md",
              "reasons": ["superseded by the current harbour "
                          "rules page"]}])
        # the expansion still works for live pages
        self.assertIn("/fix/beacon-guide.md", paths(on))

    def test_withheld_without_expansion_too(self):
        off = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                             severance=False, governance=self.GOV)
        self.assertNotIn("/fix/regatta.md", paths(off))


class SeveranceCompositionTests(unittest.TestCase):
    def test_page_level_severance_still_excludes(self):
        sev = {"entries": [{"id": "sev-t1", "kind": "page",
                            "page": "/fix/beacon-guide.md"}]}
        rec = hyde.build_expansion(ws, QUERY, MISMATCH_DOCS)
        on = ws.hybrid_rank(QUERY, MISMATCH_DOCS,
                            severance=sev, governance=False,
                            expansion=rec)
        self.assertNotIn("/fix/beacon-guide.md", paths(on))
        self.assertEqual(
            ws.LAST_SEVERANCE["excluded"],
            [{"path": "/fix/beacon-guide.md", "entries": ["sev-t1"]}])

    def test_claim_text_match_still_excludes(self):
        docs = MISMATCH_DOCS + [
            doc("old-form.md",
                "zephyr lantern bulletin. The dead form of the "
                "harbour rule, lantern zephyr dead form."),
        ]
        sev = {"entries": [{
            "id": "sev-t2", "kind": "claim",
            "cues": {"phrases": [["dead", "form"]],
                     "terms": ["dead", "form", "harbour", "rule"]}}]}
        query = ["zephyr", "lantern", "dead", "form"]
        rec = hyde.build_expansion(ws, query, docs)
        on = ws.hybrid_rank(query, docs, severance=sev,
                            governance=False, expansion=rec)
        self.assertNotIn("/fix/old-form.md", paths(on))
        excluded = {e["path"] for e in ws.LAST_SEVERANCE["excluded"]}
        self.assertIn("/fix/old-form.md", excluded)


if __name__ == "__main__":
    unittest.main()
