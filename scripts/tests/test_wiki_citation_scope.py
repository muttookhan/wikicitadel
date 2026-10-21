#!/usr/bin/env python3
"""Per-file permission-scoped citations (bisheng pattern;
Marathon Round 3, lane TB7, row 6).

Pins on fixtures: a citation carries its source file's scope
from the register (default scope when unregistered); the
export filter replaces an out-of-scope citation with a scope
note that leaks NOTHING about the source (no path, no anchor);
the answer-text filter rewrites the inline marker in place; a
reader holding the scope sees the citation untouched; the
checker counts withheld citations per page; there is NO
implicit hierarchy — holding a higher-sounding scope does not
grant another.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_citation_scope",
    ROOT / "scripts" / "wiki_citation_scope.py")
CS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CS)

SCOPES = {"default_scope": "internal",
          "files": {"raw/secret-note.md": "personal",
                    "raw/open-note.md": "public"}}

TEXT = ("A public claim. ^[cite: raw/open-note.md#L1-L2]\n\n"
        "A personal claim. ^[cite: raw/secret-note.md#L3]\n\n"
        "An unregistered claim. ^[cite: raw/other.md#L9]\n")


class ScopeTests(unittest.TestCase):
    def test_scope_of(self):
        self.assertEqual(CS.scope_of("raw/secret-note.md", SCOPES),
                         "personal")
        self.assertEqual(CS.scope_of("raw/anything.md", SCOPES),
                         "internal")

    def test_extract(self):
        cites = CS.extract_citations(TEXT)
        self.assertEqual([c["path"] for c in cites],
                         ["raw/open-note.md", "raw/secret-note.md",
                          "raw/other.md"])

    def test_filter_redacts_without_leaking(self):
        cites = CS.extract_citations(TEXT)
        out = CS.filter_citations(cites, SCOPES, {"public"})
        self.assertEqual(len(out), 3)
        self.assertFalse(out[0]["redacted"])
        self.assertEqual(out[0]["scope"], "public")
        for redacted in out[1:]:
            self.assertTrue(redacted["redacted"])
            self.assertNotIn("path", redacted)
            self.assertNotIn("secret-note", json.dumps(redacted))
            self.assertNotIn("other.md", json.dumps(redacted))
            self.assertIn("scope", redacted)
            self.assertIn(redacted["scope"], redacted["scope_note"])

    def test_filter_text_rewrites_markers(self):
        filtered, n = CS.filter_text(TEXT, SCOPES,
                                     {"public", "internal", "personal"})
        self.assertEqual(n, 0)
        self.assertEqual(filtered, TEXT)
        filtered, n = CS.filter_text(TEXT, SCOPES, {"public"})
        self.assertEqual(n, 2)
        self.assertNotIn("secret-note", filtered)
        self.assertIn("citation withheld", filtered)
        self.assertIn("raw/open-note.md", filtered)

    def test_no_implicit_hierarchy(self):
        cites = [{"path": "raw/open-note.md", "anchor": ""}]
        out = CS.filter_citations(cites, SCOPES, {"personal"})
        self.assertTrue(out[0]["redacted"])

    def test_checker_on_fixture_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki").mkdir(parents=True)
            (root / "evaluation").mkdir()
            (root / "evaluation" / "citation-scopes.json").write_text(
                json.dumps({"kind": "citation-scopes", **SCOPES}))
            (root / "wiki" / "page.md").write_text(TEXT)
            report = CS.check_tree(root, {"public"})
            self.assertEqual(report["totals"],
                             {"citations": 3, "withheld": 2})
            report = CS.check_tree(
                root, {"public", "internal", "personal"})
            self.assertEqual(report["totals"]["withheld"], 0)


if __name__ == "__main__":
    unittest.main()
