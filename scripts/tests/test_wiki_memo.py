"""Tests for scripts/wiki_memo.py — the Memos-shaped memo
store: add/list/timeline over staging/memos.jsonl, tags as the
only structure (slug-checked, de-duplicated), timeline
newest-first, tag filtering, malformed store lines refused.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_memo as wm  # noqa: E402

T1 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)


class MemoStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="memo-store-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_add_appends_jsonl_record(self):
        rec = wm.add_memo("First memo", tags=["Garden", "#demo"],
                          by="tester", now=T1, root=self.root)
        self.assertEqual(rec["kind"], "memo")
        self.assertEqual(rec["tags"], ["garden", "demo"])
        self.assertEqual(rec["date"], "2026-10-20")
        store = self.root / "staging" / "memos.jsonl"
        lines = store.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["text"],
                         "First memo")

    def test_list_is_capture_order_timeline_is_newest_first(self):
        wm.add_memo("one", now=T1, root=self.root)
        wm.add_memo("two", now=T2, root=self.root)
        wm.add_memo("three", now=T3, root=self.root)
        self.assertEqual([m["text"] for m in wm.list_memos(
            root=self.root)], ["one", "two", "three"])
        self.assertEqual([m["text"] for m in wm.timeline(
            root=self.root)], ["three", "two", "one"])

    def test_tag_filter(self):
        wm.add_memo("alpha", tags=["garden"], now=T1,
                    root=self.root)
        wm.add_memo("beta", tags=["demo"], now=T2, root=self.root)
        self.assertEqual([m["text"] for m in wm.list_memos(
            root=self.root, tag="garden")], ["alpha"])
        self.assertEqual(wm.list_memos(root=self.root,
                                       tag="absent"), [])

    def test_empty_store_is_empty_not_an_error(self):
        self.assertEqual(wm.list_memos(root=self.root), [])
        self.assertEqual(wm.timeline(root=self.root), [])

    def test_refusals(self):
        with self.assertRaises(wm.MemoError):
            wm.add_memo("   ", root=self.root)
        with self.assertRaises(wm.MemoError):
            wm.add_memo("ok", tags=["Not A Tag!"], root=self.root)
        store = self.root / "staging" / "memos.jsonl"
        store.parent.mkdir(parents=True)
        store.write_text("not json\n", encoding="utf-8")
        with self.assertRaises(wm.MemoError):
            wm.list_memos(root=self.root)

    def test_cli_round_trip(self):
        store = self.root / "s.jsonl"
        self.assertEqual(wm.main(
            ["--store", str(store), "add", "via cli",
             "--tags", "demo,cli"]), 0)
        self.assertEqual(wm.main(
            ["--store", str(store), "timeline", "--json"]), 0)
        self.assertEqual([m["text"] for m in wm.list_memos(
            store=store)], ["via cli"])


if __name__ == "__main__":
    unittest.main()
