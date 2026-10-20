#!/usr/bin/env python3
"""Tests for scripts/wiki_okf_audit.py — the §4.1 round-trip
derivation on synthetic source/bundle pairs (wave-10 fold-in).
The audit's verdict must come from the bytes: a preserved
page passes, a dropped field or a changed body fails."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "wiki_okf_audit.py"
_spec = importlib.util.spec_from_file_location("wiki_okf_audit", SCRIPT)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

SOURCE = """---
title: Fixture page
type: source
created: 2030-10-20
status: superseded
tags: [one, two]
sources:
  - raw/sources/example.md
custom_key: keep-me
---

Body text with a [[wikilink]].
"""

BUNDLE_OK = """---
type: source
title: Fixture page
tags: [one, two]
sources:
  - id: example
    resource: raw/sources/example.md
status: deprecated
llm_wiki:
  created: 2030-10-20
  status: superseded
  custom_key: keep-me
---

Body text with a [[wikilink]].
"""


def make_tree(bundle_text):
    root = Path(tempfile.mkdtemp(prefix="okf-audit-fixture-"))
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "wiki" / "sources" / "page.md").write_text(
        SOURCE, encoding="utf-8")
    out = root / "bundle"
    (out / "sources").mkdir(parents=True)
    (out / "sources" / "page.md").write_text(
        bundle_text, encoding="utf-8")
    return root, out


class RoundTrip(unittest.TestCase):
    def test_preserved_page_passes_with_omissions(self):
        root, out = make_tree(BUNDLE_OK)
        verdict, problems, omissions = audit.audit_concept(
            root, out, "sources/page.md")
        self.assertEqual(problems, [])
        self.assertEqual(verdict, "PASS-WITH-OMISSIONS")
        self.assertIn("llm_wiki extension namespace in use", omissions)

    def test_dropped_field_fails(self):
        broken = BUNDLE_OK.replace("  custom_key: keep-me\n", "")
        root, out = make_tree(broken)
        verdict, problems, _ = audit.audit_concept(
            root, out, "sources/page.md")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(any("custom_key" in p for p in problems))

    def test_changed_body_fails(self):
        broken = BUNDLE_OK.replace("Body text", "Altered text")
        root, out = make_tree(broken)
        verdict, problems, _ = audit.audit_concept(
            root, out, "sources/page.md")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(any("body differs" in p for p in problems))

    def test_unpreserved_raw_status_fails(self):
        broken = BUNDLE_OK.replace("  status: superseded\n", "")
        root, out = make_tree(broken)
        verdict, problems, _ = audit.audit_concept(
            root, out, "sources/page.md")
        self.assertEqual(verdict, "FAIL")

    def test_missing_bundle_file_fails(self):
        root, out = make_tree(BUNDLE_OK)
        (out / "sources" / "page.md").unlink()
        verdict, problems, _ = audit.audit_concept(
            root, out, "sources/page.md")
        self.assertEqual(verdict, "FAIL")
        self.assertIn("bundle file missing", problems)


if __name__ == "__main__":
    unittest.main()
