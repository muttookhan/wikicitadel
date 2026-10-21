"""Tests for CJK search-mode segmentation (Marathon Round 4,
lane B, item 2 -- the Kagome pattern: index compounds both
whole and segmented, so CJK pages retrieve on either form).

Pins, on both mirrors (scripts/wiki_search.py and
tools/lens/lenslib.py, which must agree exactly):
  - tokenize emits the whole CJK run AND its character bigrams,
    in order; a lone CJK character indexes as itself; Korean
    (hangul) and kana runs segment the same way;
  - non-CJK tokenisation is byte-for-byte the historical rule
    ([a-z0-9]+ tokens of length >= 2, in order);
  - bm25 retrieval (wiki_search.bm25_rank and the Lens
    PostingsIndex) finds a CJK page on the WHOLE compound and
    on a PARTIAL compound (a 2+ character substring surfacing
    as query bigrams / a whole-run partial query);
  - the two tokenizers produce identical streams on mixed text,
    and make_snippet windows around a CJK hit in a long line
    instead of returning the line head.

Run:  python3 -m unittest discover -s scripts/tests
In-memory fixtures only; the live corpus is never touched.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name,
                                                  ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


ws = load("wiki_search_cjk", "scripts/wiki_search.py")
lens = load("lenslib_cjk", "tools/lens/lenslib.py")

COMPOUND = "東京都の検索エンジン"  # Tokyo + search engine, one run


def docs():
    from pathlib import Path as P
    return [
        (P("wiki/concepts/cjk.md"),
         f"# 検索\n\n{COMPOUND}は速い。日本語の情報を探す。\n"),
        (P("wiki/concepts/plain.md"),
         "# Plain\n\nAn English page about search engines "
         "and ranking signals.\n"),
        (P("wiki/concepts/other-cjk.md"),
         "# 料理\n\n大阪の料理は美味しい。寿司と味噌汁。\n"),
    ]


class TokenizeTests(unittest.TestCase):
    def test_whole_and_bigrams_both_mirrors(self):
        for m in (ws, lens):
            toks = m.tokenize(COMPOUND)
            self.assertEqual(toks[0], COMPOUND)          # whole
            for bg in ("東京", "京都", "都の", "の検", "検索",
                       "索エ", "エン", "ンジ", "ジン"):
                self.assertIn(bg, toks)                  # segmented
            self.assertEqual(len(toks), 1 + len(COMPOUND) - 1)

    def test_mirrors_agree_on_mixed_text(self):
        sample = ("Hello 東京都の検索 world, 猫と犬 42 x "
                  "한국어검색 テストです")
        self.assertEqual(ws.tokenize(sample), lens.tokenize(sample))

    def test_single_cjk_char_indexes_as_itself(self):
        self.assertEqual(ws.tokenize("猫"), ["猫"])
        self.assertEqual(lens.tokenize("猫"), ["猫"])

    def test_non_cjk_behaviour_unchanged(self):
        self.assertEqual(ws.tokenize("Hello, WORLD! a b 42 x9"),
                         ["hello", "world", "42", "x9"])
        self.assertEqual(lens.tokenize("Hello, WORLD! a b 42 x9"),
                         ["hello", "world", "42", "x9"])

    def test_hangul_and_kana_segment(self):
        toks = ws.tokenize("한국어검색")
        self.assertEqual(toks[0], "한국어검색")
        self.assertIn("한국", toks)
        self.assertIn("검색", toks)


class RetrievalTests(unittest.TestCase):
    def test_bm25_whole_compound(self):
        hits = ws.bm25_rank(ws.tokenize(COMPOUND), docs())
        self.assertTrue(hits)
        self.assertEqual(hits[0][1].name, "cjk.md")

    def test_bm25_partial_compound(self):
        # A substring of the compound: its bigrams are indexed.
        for query in ("検索", "京都の検", "索エン"):
            hits = ws.bm25_rank(ws.tokenize(query), docs())
            self.assertTrue(hits, query)
            self.assertEqual(hits[0][1].name, "cjk.md", query)

    def test_bm25_unrelated_cjk_does_not_hit(self):
        hits = ws.bm25_rank(ws.tokenize("寿司"), docs())
        names = [p.name for _s, p, _t in hits]
        self.assertNotIn("cjk.md", names)
        self.assertIn("other-cjk.md", names)

    def test_lens_index_whole_and_partial(self):
        idx = lens.PostingsIndex(
            [{"key": str(p), "text": t} for p, t in docs()])
        for query in (COMPOUND, "検索", "京都の検"):
            ranked = idx.rank(lens.tokenize(query))
            self.assertTrue(ranked, query)
            top = idx.docs[ranked[0][1]]["key"]
            self.assertTrue(top.endswith("cjk.md"), (query, top))
            self.assertFalse(top.endswith("other-cjk.md"))


class SnippetTests(unittest.TestCase):
    def test_snippet_windows_around_cjk_hit(self):
        line = "あ" * 120 + "検索" + "い" * 120
        for m in (ws, lens):
            snip = m.make_snippet(line, m.tokenize("検索"))
            self.assertIn("検索", snip)
            self.assertTrue(snip.startswith("…"), snip[:10])


if __name__ == "__main__":
    unittest.main()
