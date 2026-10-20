#!/usr/bin/env python3
"""Phase-2 harvest item 3: atomic-fact audit (pattern:
shmsw25/FActScore, MIT) on a fixture wiki with known claims:
two supported by the cited source, one fabricated from words
that appear nowhere in the evidence.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_factcheck", ROOT / "scripts" / "wiki_factcheck.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)
wv = fc._load_validate()

SOURCE = """# Irrigation field notes

The irrigation canal delivers water to the northern fields every
morning during the dry season. Farmers open the sluice gates at
dawn and record the water level in the register book.
"""

PAGE = """---
title: Canal Notes
type: source
created: 2030-10-13
updated: 2030-10-13
sources: [raw/sources/field-notes.md]
tags: [fixture]
---

The irrigation canal delivers water to the northern fields every
morning during the dry season. Farmers open the sluice gates at dawn
and record the water level in the register book. The canal was built
by Martian engineers using anti-gravity pumps from Venus.
"""


class TestFactcheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "raw" / "sources").mkdir(parents=True)
        (self.root / "wiki" / "sources").mkdir(parents=True)
        (self.root / "raw" / "sources" / "field-notes.md").write_text(
            SOURCE, encoding="utf-8")
        (self.root / "wiki" / "sources" / "canal.md").write_text(
            PAGE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_supported_fraction_and_length_penalty(self):
        rec = fc.factcheck_page(self.root, "wiki/sources/canal.md", wv,
                                threshold=0.6, gamma=10.0)
        self.assertEqual(rec["claims"], 3)
        self.assertEqual(rec["supported"], 2)
        self.assertAlmostEqual(rec["fraction"], 2 / 3, places=2)
        # gamma penalty: 3 claims against gamma 10 -> * 0.3
        self.assertAlmostEqual(rec["adjusted"], (2 / 3) * 0.3, places=2)
        self.assertEqual(len(rec["unsupported"]), 1)
        self.assertIn("Martian", rec["unsupported"][0]["claim"])

    def test_page_without_readable_sources_is_unverifiable(self):
        page = PAGE.replace("raw/sources/field-notes.md",
                            "raw/sources/missing.pdf")
        (self.root / "wiki" / "sources" / "canal.md").write_text(
            page, encoding="utf-8")
        rec = fc.factcheck_page(self.root, "wiki/sources/canal.md", wv)
        self.assertIsNone(rec["fraction"])
        self.assertEqual(rec["unverifiable_claims"], 3)


if __name__ == "__main__":
    unittest.main()
