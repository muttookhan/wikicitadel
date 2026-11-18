"""Tests for scripts/wiki_ingest_buffer.py (Memobase-pattern
ingest buffer/flush batching — Marathon Round 3, lane TA4):
entries stage atomically, a flush pushes the batch through
the existing clip path, a failed entry stays pending while
the rest flush, and CRASH SAFETY — an entry claimed by a
killed flush (.json.flushing) is recovered on the next flush,
and one whose draft was already staged before the kill is
retired as already-flushed, never duplicated and never lost.

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

import wiki_ingest_buffer as buf  # noqa: E402

NOW = datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc)
TEXT = ("A buffered note with enough ordinary prose in it to "
        "be worth capturing for the wiki and reading later on.")


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="buffer-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "incoming.md"
        self.src.write_text("# Buffered Note\n\n" + TEXT,
                            encoding="utf-8")
        (self.root / "incoming.md").rename(self.root / "note.md")
        self.src = self.root / "note.md"

    def _add(self):
        return buf.add_file(self.src, root=self.root, now=NOW)

    def test_add_stages_entry_and_payload(self):
        meta = self._add()
        bdir = buf.buffer_dir(self.root)
        self.assertTrue((bdir / (meta["id"] + ".json")).is_file())
        self.assertTrue((bdir / (meta["id"] + ".payload")).is_file())
        self.assertEqual([e["id"] for e in buf.list_entries(self.root)],
                         [meta["id"]])

    def test_flush_goes_through_the_clip_path(self):
        meta = self._add()
        result = buf.flush(root=self.root, now=NOW)
        self.assertEqual(len(result["flushed"]), 1)
        self.assertEqual(result["failed"], [])
        bdir = buf.buffer_dir(self.root)
        self.assertFalse((bdir / (meta["id"] + ".json")).exists())
        self.assertFalse((bdir / (meta["id"] + ".payload")).exists())
        # the clip path's real output: a staged capture draft
        drafts = list((self.root / "staging" / "captures").glob("*-capture.md"))
        self.assertEqual(len(drafts), 1)

    def test_failed_entry_stays_pending_rest_flush(self):
        good = self._add()
        bad_src = self.root / "mystery.xyz"
        bad_src.write_bytes(b"\x00\x01\x02")
        bad = buf.add_file(bad_src, root=self.root, now=NOW)
        result = buf.flush(root=self.root, now=NOW)
        self.assertEqual(len(result["flushed"]), 1)
        self.assertEqual([f["id"] for f in result["failed"]],
                         [bad["id"]])
        pending = [e["id"] for e in buf.list_entries(self.root)]
        self.assertEqual(pending, [bad["id"]])
        self.assertNotIn(good["id"], pending)

    def test_claimed_entry_is_recovered_after_a_kill(self):
        meta = self._add()
        bdir = buf.buffer_dir(self.root)
        # simulate the kill: flush claimed the entry, then died
        (bdir / (meta["id"] + ".json")).rename(
            bdir / (meta["id"] + ".json.flushing"))
        result = buf.flush(root=self.root, now=NOW)
        self.assertEqual(result["recovered"], [meta["id"]])
        self.assertEqual(len(result["flushed"]), 1)
        self.assertEqual(buf.list_entries(self.root), [])

    def test_kill_after_draft_staged_retires_entry(self):
        meta = self._add()
        first = buf.flush(root=self.root, now=NOW)
        self.assertEqual(len(first["flushed"]), 1)
        # re-buffer the same bytes, then simulate: the draft
        # already exists when the flush processes the entry
        meta2 = self._add()
        self.assertEqual(meta2["id"], meta["id"])
        result = buf.flush(root=self.root, now=NOW)
        self.assertEqual(len(result["already_flushed"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(buf.list_entries(self.root), [])
        drafts = list((self.root / "staging" / "captures").glob("*-capture.md"))
        self.assertEqual(len(drafts), 1)  # never duplicated

    def test_url_entries_flush_via_fetcher_seam(self):
        buf.add_url("https://example.net/page", root=self.root,
                    now=NOW)

        def fake_fetcher(url):
            import wiki_clip as clip
            return clip.FetchResult(
                b"<html><body><p>Fetched body text for the "
                b"buffered URL entry.</p></body></html>",
                content_type="text/html", final_url=url)

        result = buf.flush(root=self.root, fetcher=fake_fetcher,
                           now=NOW)
        self.assertEqual(len(result["flushed"]), 1)
        self.assertEqual(result["failed"], [])


if __name__ == "__main__":
    unittest.main()
