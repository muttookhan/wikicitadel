"""Tests for the `memo` capture kind (usememos/memos shape,
Marathon Round 4, lane C) in scripts/wiki_capture.py: one
timeline inbox, TAGS AS THE ONLY STRUCTURE, the kind listed,
tags slug-checked and memo-only, and its draft in
staging/captures/ only.

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


class MemoCaptureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="memo-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        dest = self.root / "templates" / "capture"
        dest.mkdir(parents=True)
        for tpl in REAL_TEMPLATES.glob("*.md"):
            shutil.copy(tpl, dest / tpl.name)

    def test_memo_is_a_registered_kind(self):
        self.assertIn("memo", wc.KINDS)
        self.assertIn("memo", wc.list_kinds())
        self.assertIn("memos.jsonl", wc.KINDS["memo"]["destination"])

    def test_memo_renders_with_tags_as_only_structure(self):
        text = wc.render(
            "memo", "Water the greenhouse tomatoes",
            tags=["garden", "Home-Care", "#garden"],
            provenance="porch note, 2026-10-21",
            now=NOW, root=self.root)
        fields, body = wv.parse_frontmatter(text)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["capture_kind"], "memo")
        self.assertEqual(fields["status"], "draft")
        self.assertEqual(fields["sources"], [])
        self.assertEqual(fields["sensitivity"], "TODO")
        # Tags: normalised (lowercased, #-stripped, de-duplicated)
        self.assertEqual([str(t) for t in fields["tags"]],
                         ["garden", "home-care"])
        # Tag-only structure: no folder/category field exists.
        self.assertNotIn("folder", fields)
        self.assertNotIn("category", fields)
        self.assertIn("Water the greenhouse tomatoes", body)

    def test_tags_belong_to_memo_only(self):
        with self.assertRaises(wc.CaptureError):
            wc.render("jot", "A line", tags=["x"], now=NOW,
                      root=self.root)

    def test_bad_tag_refused(self):
        with self.assertRaises(wc.CaptureError):
            wc.render("memo", "A memo", tags=["Not A Tag!"],
                      now=NOW, root=self.root)

    def test_memo_writes_to_staging_only(self):
        rel = wc.new_capture("memo", "Call the seed supplier",
                             tags=["garden"], now=NOW,
                             root=self.root)
        self.assertEqual(
            rel,
            "staging/captures/2026-10-21-memo-call-the-seed-"
            "supplier.md")
        self.assertTrue((self.root / rel).is_file())
        self.assertFalse((self.root / "wiki").exists())


if __name__ == "__main__":
    unittest.main()
