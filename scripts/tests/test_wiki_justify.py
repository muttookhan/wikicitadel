#!/usr/bin/env python3
"""Tests for scripts/wiki_justify.py — justification
trails for headings (consolidated queue item 48,
2030-10-20).

The three behaviours the item pins: a trail parses and
renders (670 found / 675 not-found / established); the
check lists authority pages without trails (surfacing,
never failing); and a not-found record that names no
actual search is REFUSED — a negative claim without a
search behind it is not evidence. A fourth pins the
append-only rule: lines already on a page survive an
``add`` byte-for-byte and in order.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = SCRIPTS / "wiki_justify.py"

PAGE = """---
title: Fixture Person
type: entity
---

# Fixture Person

Body text.
"""

TRAILED = PAGE + """
## Justification

Preamble prose lives here.

### Form: Fixture Person

- Found: "Fixture Person" — raw/fixture.md#L3-L4 — the
  list as given.
- Not found: raw/elsewhere/ — searched 2030-10-20 (grep
  for "Fixture Person"): no match.
- Established: 2030-10-20 · by: tester
"""


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_justify", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ParseRenderTests(unittest.TestCase):
    def test_no_section_parses_as_none(self):
        mod = load_module()
        self.assertIsNone(mod.parse_trail(PAGE))

    def test_entry_parses(self):
        mod = load_module()
        entries = mod.parse_trail(TRAILED)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["form"], "Fixture Person")
        self.assertEqual(len(e["found"]), 1)
        self.assertIn("raw/fixture.md#L3-L4", e["found"][0])
        self.assertEqual(len(e["not_found"]), 1)
        self.assertEqual(e["unsearched_not_found"], 0)
        self.assertEqual(e["established"],
                         "2030-10-20 · by: tester")

    def test_unsearched_not_found_is_flagged(self):
        mod = load_module()
        bad = TRAILED.replace(
            'raw/elsewhere/ — searched 2030-10-20 (grep\n'
            '  for "Fixture Person"): no match.',
            "raw/elsewhere/ — not there.")
        entries = mod.parse_trail(bad)
        self.assertEqual(entries[0]["unsearched_not_found"], 1)

    def test_render_names_both_halves(self):
        mod = load_module()
        out = mod.render(Path("wiki/entities/x.md"),
                         mod.parse_trail(TRAILED))
        self.assertIn("found (670)", out)
        self.assertIn("not found (675)", out)
        self.assertIn("Fixture Person", out)


class AddTests(unittest.TestCase):
    """add runs against the real tree layout via a copied
    tool rooted at a temp repo: the module's ROOT is its
    own location, so copy the script into the fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "wiki" / "entities").mkdir(parents=True)
        self.tool = self.root / "scripts" / "wiki_justify.py"
        self.tool.write_text(TOOL.read_text(encoding="utf-8"),
                             encoding="utf-8")
        self.page = self.root / "wiki" / "entities" / "fix.md"
        self.page.write_text(PAGE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tool), *argv],
            capture_output=True, text=True)

    def test_add_creates_section_and_entry(self):
        r = self.run_tool(
            "add", "wiki/entities/fix.md",
            "--form", "Fixture Person",
            "--found", '"Fixture Person" — raw/f.md#L1 — note',
            "--not-found",
            'raw/v/ — searched 2030-10-20 (grep): no match',
            "--established", "2030-10-20", "--by", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.page.read_text(encoding="utf-8")
        self.assertIn("## Justification", text)
        self.assertIn("### Form: Fixture Person", text)

    def test_add_refuses_searchless_not_found(self):
        before = self.page.read_text(encoding="utf-8")
        r = self.run_tool(
            "add", "wiki/entities/fix.md",
            "--form", "Fixture Person",
            "--not-found", "raw/v/ — not there, trust me",
            "--established", "2030-10-20", "--by", "tester")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUSED", r.stderr)
        self.assertEqual(self.page.read_text(encoding="utf-8"),
                         before)

    def test_add_appends_without_rewriting(self):
        self.page.write_text(TRAILED, encoding="utf-8")
        before_lines = TRAILED.splitlines()
        r = self.run_tool(
            "add", "wiki/entities/fix.md",
            "--form", "Fixture Person",
            "--found", '"F. Person" — raw/g.md#L9 — short form',
            "--established", "2030-10-20", "--by", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        after_lines = self.page.read_text(
            encoding="utf-8").splitlines()
        # every pre-existing line survives verbatim, in order
        it = iter(after_lines)
        for ln in before_lines:
            self.assertIn(ln, it)
        # and the new evidence landed inside the same entry,
        # before its Established line
        est = next(i for i, ln in enumerate(after_lines)
                   if ln.startswith("- Established:"))
        self.assertTrue(any("raw/g.md#L9" in ln
                            for ln in after_lines[:est]))

    def test_check_lists_untrailed_authority_page(self):
        r = self.run_tool("check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("wiki/entities/fix.md", r.stdout)


if __name__ == "__main__":
    unittest.main()
