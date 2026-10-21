#!/usr/bin/env python3
"""Script unification for multilingual retrieval (IndicTrans2
pattern; Marathon Round 3, lane TB7, row 8).

Pins: the stated Devanagari romanisation (रामायण -> ramayana,
कृष्ण -> krishna, धर्म -> dharma, digits fold); diacritic
folding (café -> cafe); CJK width folding via NFKC (fullwidth
ＡＢＣ -> abc); case folding; and the retrieval consequence —
a romanised query matches a Devanagari page, and a plain query
matches a fullwidth page, through the normalised wrapper,
while the canonical ranker's own behaviour is untouched.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_script_norm", ROOT / "scripts" / "wiki_script_norm.py")
SN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SN)


class NormalizeTests(unittest.TestCase):
    def test_devanagari_table(self):
        self.assertEqual(SN.normalize_text("रामायण"), "ramayana")
        self.assertEqual(SN.normalize_text("कृष्ण"), "krishna")
        self.assertEqual(SN.normalize_text("धर्म"), "dharma")
        self.assertEqual(SN.normalize_text("भारत"), "bharata")
        self.assertEqual(SN.normalize_text("१९४७"), "1947")

    def test_diacritics_and_case(self):
        self.assertEqual(SN.normalize_text("Café"), "cafe")
        self.assertEqual(SN.normalize_text("NAÏVE"), "naive")
        self.assertEqual(SN.normalize_text("Āyurveda"), "ayurveda")

    def test_cjk_width(self):
        self.assertEqual(SN.normalize_text("ＡＢＣ"), "abc")
        self.assertEqual(SN.normalize_text("Ｔｏｋｙｏ"), "tokyo")

    def test_tokens(self):
        self.assertEqual(SN.normalize_tokens("रामायण Café"),
                         ["ramayana", "cafe"])


class CrossScriptSearchTests(unittest.TestCase):
    DOCS = [
        (Path("/x/wiki/epic.md"),
         "# Epic\n\nThe रामायण tells the story of Rama and Sita.\n"),
        (Path("/x/wiki/city.md"),
         "# City\n\nＴｏｋｙｏ is a large city.\n"),
        (Path("/x/wiki/rock.md"),
         "# Rock\n\nGranite is an igneous rock.\n"),
    ]

    def test_roman_query_matches_devanagari_page(self):
        ranked = SN.search_normalized("ramayana", self.DOCS)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][1].name, "epic.md")

    def test_plain_query_matches_fullwidth_page(self):
        ranked = SN.search_normalized("tokyo", self.DOCS)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][1].name, "city.md")

    def test_unrelated_query_still_empty(self):
        self.assertEqual(SN.search_normalized("photosynthesis",
                                              self.DOCS), [])


if __name__ == "__main__":
    unittest.main()
