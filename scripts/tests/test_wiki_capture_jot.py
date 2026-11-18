"""Tests for the `jot` capture kind (Memos pattern, Marathon
Round 3, lane TA4) in scripts/wiki_capture.py: a jot renders
with the full schema frontmatter every kind carries, the
title is the one line, provenance is minimal (the
invocation's, or a TODO prompt — never faked), the kind is
listed, and its draft lands in staging/captures/ only.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_capture as wc  # noqa: E402
import wiki_validate as wv  # noqa: E402

NOW = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
REAL_TEMPLATES = SCRIPTS.parent / "templates" / "capture"


class JotTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jot-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        dest = self.root / "templates" / "capture"
        dest.mkdir(parents=True)
        for tpl in REAL_TEMPLATES.glob("*.md"):
            shutil.copy(tpl, dest / tpl.name)

    def test_jot_is_a_registered_kind(self):
        self.assertIn("jot", wc.KINDS)
        self.assertIn("jot", wc.list_kinds())

    def test_jot_renders_schema_frontmatter(self):
        text = wc.render("jot", "The gate code is on the fridge",
                         provenance="kitchen note, 2026-10-21",
                         now=NOW, root=self.root)
        fields, body = wv.parse_frontmatter(text)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["capture_kind"], "jot")
        self.assertEqual(fields["title"],
                         "The gate code is on the fridge")
        self.assertEqual(fields["status"], "draft")
        self.assertEqual(fields["sources"], [])
        self.assertEqual(fields["sensitivity"], "TODO")
        self.assertIn("[prompt: Why", text)
        self.assertIn("The gate code is on the fridge", body)

    def test_jot_provenance_minimal_but_never_faked(self):
        with_prov = wc.render("jot", "A line",
                              provenance="chat, 2026-10-21",
                              now=NOW, root=self.root)
        self.assertIn("chat, 2026-10-21", with_prov)
        without = wc.render("jot", "A line", now=NOW,
                            root=self.root)
        fields, _ = wv.parse_frontmatter(without)
        self.assertTrue(fields["provenance"].startswith("TODO"))

    def test_jot_writes_to_staging_only(self):
        rel = wc.new_capture("jot", "One line to keep",
                             now=NOW, root=self.root)
        self.assertEqual(
            rel, "staging/captures/2026-10-21-jot-one-line-to-keep.md")
        self.assertTrue((self.root / rel).is_file())
        self.assertFalse((self.root / "wiki").exists())


if __name__ == "__main__":
    unittest.main()
