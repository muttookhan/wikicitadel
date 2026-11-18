#!/usr/bin/env python3
"""Tests for scripts/wiki_compile_check.py + the
templates/compilation/ grammars (TB3-3).

Pins: all four templates load with a grammar; a page that
carries the required frontmatter and the required sections
in order conforms; a missing section, a missing frontmatter
field, and an out-of-order section each violate.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TREE = SCRIPTS.parent
_spec = importlib.util.spec_from_file_location(
    "wiki_compile_check", SCRIPTS / "wiki_compile_check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

GOOD_PAPER = """---
title: "A paper"
type: source
created: 2026-10-21
updated: 2026-10-21
sources: [raw/sources/x.pdf]
tags: [t]
---

# A paper

## Summary
s

## Claims
c

## Evidence
e

## Conditions and limits
l

## Connections
x
"""


def fixture():
    root = Path(tempfile.mkdtemp())
    shutil.copytree(TREE / "templates", root / "templates")
    return root


class TestCompileCheck(unittest.TestCase):
    def test_all_templates_load(self):
        root = fixture()
        for t in M.TYPES:
            tmpl = M.load_template(root, t)
            self.assertIsNotNone(tmpl, t)
            self.assertTrue(tmpl["required_sections"], t)

    def test_conforming_page(self):
        root = fixture()
        page = root / "p.md"
        page.write_text(GOOD_PAPER, encoding="utf-8")
        self.assertEqual(M.check_page(root, page, "paper"), [])

    def test_missing_section(self):
        root = fixture()
        page = root / "p.md"
        page.write_text(GOOD_PAPER.replace("## Evidence\ne\n", ""),
                        encoding="utf-8")
        v = M.check_page(root, page, "paper")
        self.assertTrue(any("Evidence" in s for s in v))

    def test_out_of_order(self):
        root = fixture()
        page = root / "p.md"
        bad = GOOD_PAPER.replace("## Claims\nc\n\n## Evidence\ne\n",
                                  "## Evidence\ne\n\n## Claims\nc\n")
        page.write_text(bad, encoding="utf-8")
        v = M.check_page(root, page, "paper")
        self.assertTrue(any("order" in s or "Claims" in s for s in v))

    def test_missing_frontmatter(self):
        root = fixture()
        page = root / "p.md"
        page.write_text(GOOD_PAPER.replace("tags: [t]\n", ""),
                        encoding="utf-8")
        v = M.check_page(root, page, "paper")
        self.assertTrue(any("tags" in s for s in v))


if __name__ == "__main__":
    unittest.main()
