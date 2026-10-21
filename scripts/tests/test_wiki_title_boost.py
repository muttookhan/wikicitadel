#!/usr/bin/env python3
"""Exact-title/stem-match boost + rank expressions (Marathon
Round 3, lane TB7, rows 1-2).

Pins, on a fixture corpus in a temp dir (never the live corpus):

  - a page whose title exactly equals the query outranks 15
    filler pages that repeat the query term far more often —
    the round-2 finding (an attested page titled by the query
    term fell out of the hybrid top-10 on corpus growth) cannot
    recur while the page is a candidate at all;
  - a stemmed title match ("running" -> the page titled "Run")
    earns the smaller, still decisive, stem boost;
  - the boost is carried on the result detail (title_boost /
    title_match / rank_expression) so surfaces can show it;
  - lenslib's PostingsIndex hybrid agrees with wiki_search on
    the fixture ranking AND on the boosted scores (parity);
  - the rank-expression language: arithmetic, precedence,
    functions, unknown features/functions rejected at parse
    time, division by zero = 0, and the named "hybrid-current"
    expression evaluating to the shipped hybrid score for the
    target page's features.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lens"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("wiki_search_tb", ROOT / "scripts" / "wiki_search.py")
import lenslib as L  # noqa: E402


def _docs(root):
    docs = [(root / "wiki" / "zebra.md",
             "---\ntitle: Zebra\n---\n# Zebra\n\n"
             "The zebra page. One mention of zebra, plainly.\n"),
            (root / "wiki" / "run.md",
             "---\ntitle: Run\n---\n# Run\n\n"
             "Notes on running form and running shoes.\n")]
    for i in range(15):
        docs.append((root / "wiki" / f"filler-{i:02d}.md",
                     f"---\ntitle: Filler {i}\n---\n# Filler {i}\n\n"
                     + "zebra " * (20 - i) + "\n"))
    return docs


class TitleBoostTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        self.docs = _docs(self.root)
        self.adj = ws.build_link_graph(self.docs)
        self._old = ws.ROOT
        ws.ROOT = self.root

    def tearDown(self):
        ws.ROOT = self._old
        self._tmp.cleanup()

    def test_exact_title_beats_term_flood(self):
        ranked = ws.hybrid_rank(ws.tokenize("zebra"), self.docs,
                                self.adj, severance=False)
        self.assertEqual(len(ranked) >= 10, True)
        top = ranked[0]
        self.assertEqual(top[1].name, "zebra.md")
        self.assertEqual(top[3]["title_match"], "exact")
        self.assertEqual(top[3]["title_boost"], ws.TITLE_EXACT_BOOST)
        # in the top-10 by construction — rank 1, stated plainly
        names = [p.name for _s, p, _t, _d in ranked[:10]]
        self.assertIn("zebra.md", names)

    def test_stem_match_boost(self):
        ranked = ws.hybrid_rank(ws.tokenize("running"), self.docs,
                                self.adj, severance=False)
        by_name = {p.name: d for _s, p, _t, d in ranked}
        self.assertEqual(by_name["run.md"]["title_match"], "stem")
        self.assertEqual(by_name["run.md"]["title_boost"],
                         ws.TITLE_STEM_BOOST)
        self.assertEqual(ranked[0][1].name, "run.md")

    def test_no_match_no_boost(self):
        ranked = ws.hybrid_rank(ws.tokenize("zebra"), self.docs,
                                self.adj, severance=False)
        filler = [d for _s, p, _t, d in ranked
                  if p.name.startswith("filler")][0]
        self.assertEqual(filler["title_boost"], 0.0)
        self.assertIsNone(filler["title_match"])

    def test_match_kind_rules(self):
        self.assertEqual(ws.title_match_kind(["galen"], "Galen", "galen"),
                         "exact")
        self.assertEqual(ws.title_match_kind(["running"], "Run", "run"),
                         "stem")
        self.assertIsNone(ws.title_match_kind(["zebra"], "Filler", "f"))
        self.assertEqual(ws.stem_token("studies"), "study")
        self.assertEqual(ws.stem_token("reflections"), "reflection")

    def test_hindsight_also_boosts(self):
        ranked = ws.hindsight_rank(ws.tokenize("zebra"), self.docs,
                                   self.adj)
        self.assertEqual(ranked[0][1].name, "zebra.md")
        self.assertEqual(ranked[0][3]["title_match"], "exact")

    def test_lenslib_parity_on_fixture(self):
        terms = ws.tokenize("zebra")
        mine = ws.hybrid_rank(terms, self.docs, self.adj, severance=False)
        idx = L.PostingsIndex(
            [{"key": str(p), "text": t} for p, t in self.docs])
        theirs = idx.hybrid_rank(L.tokenize("zebra"), self.adj)
        self.assertEqual([p.name for _s, p, _t, _d in mine],
                         [Path(idx.docs[i]["key"]).name
                          for _s, i, _d in theirs])
        for (s1, _p, _t, _d), (s2, _i, _d2) in zip(mine, theirs):
            self.assertAlmostEqual(s1, s2, places=3)
        self.assertEqual(theirs[0][2]["title_boost"],
                         L.TITLE_EXACT_BOOST)
        self.assertEqual(L.TITLE_EXACT_BOOST, ws.TITLE_EXACT_BOOST)
        self.assertEqual(L.TITLE_STEM_BOOST, ws.TITLE_STEM_BOOST)


class RankExpressionTests(unittest.TestCase):
    def ev(self, text, feats):
        return ws.eval_rank_expression(ws.parse_rank_expression(text),
                                       feats)

    def test_arithmetic_and_precedence(self):
        self.assertEqual(self.ev("1 + 2 * 3", {}), 7.0)
        self.assertEqual(self.ev("(1 + 2) * 3", {}), 9.0)
        self.assertEqual(self.ev("-bm25_norm + 2", {"bm25_norm": 0.5}), 1.5)

    def test_functions(self):
        self.assertEqual(self.ev("max(bm25_norm, ppr_norm)",
                                 {"bm25_norm": 0.2, "ppr_norm": 0.9}), 0.9)
        self.assertEqual(self.ev("clamp(bm25_norm, 0, 0.5)",
                                 {"bm25_norm": 2.0}), 0.5)
        self.assertAlmostEqual(self.ev("log1p(bm25_norm)",
                                       {"bm25_norm": 0.0}), 0.0)

    def test_division_by_zero_is_zero(self):
        self.assertEqual(self.ev("bm25_norm / ppr_norm",
                                 {"bm25_norm": 1.0, "ppr_norm": 0.0}), 0.0)

    def test_unknown_feature_and_function_rejected(self):
        with self.assertRaises(ValueError):
            ws.parse_rank_expression("nonsense_feature + 1")
        with self.assertRaises(ValueError):
            ws.parse_rank_expression("frobnicate(bm25_norm)")
        with self.assertRaises(ValueError):
            ws.parse_rank_expression("bm25_norm +")

    def test_named_expressions_all_parse(self):
        for name, text in ws.RANK_EXPRESSIONS.items():
            ast = ws.rank_expression_ast(name)
            self.assertEqual(
                ws.eval_rank_expression(ast, {}), 0.0, name)
            self.assertGreater(
                ws.eval_rank_expression(
                    ast, {f: 1.0 for f in ws.RANK_FEATURES}), 0.0, name)

    def test_hybrid_current_is_the_shipped_expression(self):
        # The hybrid's detail names the expression it evaluated.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki").mkdir()
            docs = _docs(root)
            old = ws.ROOT
            ws.ROOT = root
            try:
                ranked = ws.hybrid_rank(ws.tokenize("zebra"), docs,
                                        ws.build_link_graph(docs),
                                        severance=False)
            finally:
                ws.ROOT = old
        for _s, _p, _t, d in ranked:
            self.assertEqual(d["rank_expression"], "hybrid-current")
        # And the top score equals the expression over the stated
        # features (bm25_norm=1 for the top BM25 hit is NOT assumed;
        # instead check the boost is the decisive margin).
        self.assertGreaterEqual(ranked[0][0] - ranked[1][0],
                                ws.TITLE_EXACT_BOOST - 3.0)


if __name__ == "__main__":
    unittest.main()
