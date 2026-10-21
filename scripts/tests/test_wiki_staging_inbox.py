"""Tests for scripts/wiki_staging_inbox.py (Marathon R3 TB5 row 9,
staging-inbox group): captures land as state `new` in the sidecar
register; only the allowed transitions move them; a move appends
history and never edits the item file; `filed` is final. Run:
python3 -m unittest scripts.tests.test_wiki_staging_inbox
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_staging_inbox as wsi  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="stage-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.staging = self.root / "staging"


class InboxTests(Fixture):
    def test_add_lands_new_with_item_file(self):
        item = wsi.add_item(self.staging, "A link", "body text",
                            at="2026-10-21")
        self.assertEqual(item["state"], "new")
        self.assertTrue((self.staging / "items" / "a-link.md").exists())
        listed = wsi.list_items(self.staging, state="new")
        self.assertEqual([i["id"] for i in listed], ["a-link"])

    def test_duplicate_titles_get_unique_ids(self):
        a = wsi.add_item(self.staging, "Same", "x")
        b = wsi.add_item(self.staging, "Same", "y")
        self.assertNotEqual(a["id"], b["id"])

    def test_allowed_and_refused_transitions(self):
        item = wsi.add_item(self.staging, "T", "b")
        with self.assertRaises(ValueError):
            wsi.move(self.staging, item["id"], "filed")  # new -> filed
        moved = wsi.move(self.staging, item["id"], "triaged",
                         at="2026-10-21")
        self.assertEqual(moved["state"], "triaged")
        self.assertEqual(len(moved["history"]), 2)
        done = wsi.move(self.staging, item["id"], "filed")
        self.assertEqual(done["state"], "filed")
        with self.assertRaises(ValueError):
            wsi.move(self.staging, item["id"], "triaged")  # final

    def test_park_and_revive(self):
        item = wsi.add_item(self.staging, "P", "b")
        wsi.move(self.staging, item["id"], "parked")
        revived = wsi.move(self.staging, item["id"], "triaged")
        self.assertEqual(revived["state"], "triaged")
        self.assertEqual(wsi.list_items(self.staging, "parked"), [])


if __name__ == "__main__":
    unittest.main()
