"""Tests for the MarkDownload preview-and-edit checkpoint
(Marathon Round 3, lane TA4): scripts/wiki_clip.py --preview
stages a draft in staging/previews/ marked
capture_state: preview-unfiled and NOTHING in
staging/captures/; scripts/wiki_preview.py confirm is the
only step that files it — filing the EDITED bytes, flipping
the state line, and leaving a receipt whose sha256 matches
the filed content; confirm refuses non-previews and refuses
to overwrite a filed draft; discard moves a preview aside
without deleting it.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_clip as clip  # noqa: E402
import wiki_preview as wp  # noqa: E402

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class PreviewCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="preview-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "page.md"
        self.src.write_text(
            "# Checkpoint Page\n\nContent captured for the "
            "checkpoint test, long enough to be a real clip.",
            encoding="utf-8")

    def _clip_preview(self):
        return clip.clip_file(self.src, root=self.root, now=NOW,
                              preview=True)

    def test_preview_lands_in_previews_not_captures(self):
        res = self._clip_preview()
        self.assertTrue(res["preview"])
        self.assertTrue(res["draft"].startswith("staging/previews/"))
        self.assertTrue((self.root / res["draft"]).is_file())
        captures = self.root / "staging" / "captures"
        self.assertFalse(captures.exists()
                         and list(captures.glob("*-capture.md")))
        text = (self.root / res["draft"]).read_text(encoding="utf-8")
        self.assertIn(wp.PREVIEW_STATE, text)

    def test_confirm_files_the_edited_preview(self):
        res = self._clip_preview()
        preview_path = self.root / res["draft"]
        edited = preview_path.read_text(encoding="utf-8").replace(
            "Checkpoint Page", "Checkpoint Page (edited title)")
        preview_path.write_text(edited, encoding="utf-8")
        rel = wp.confirm(preview_path.name, root=self.root, now=NOW)
        self.assertEqual(rel, "staging/captures/" + preview_path.name)
        filed = (self.root / rel).read_text(encoding="utf-8")
        self.assertIn("edited title", filed)  # the EDIT crossed
        self.assertIn("capture_state: filed (confirmed 2026-10-21)",
                      filed)
        self.assertNotIn(wp.PREVIEW_STATE, filed)
        self.assertFalse(preview_path.exists())
        receipt = json.loads(
            (self.root / "staging" / "previews"
             / (preview_path.name + ".confirmed.json")).read_text(
                 encoding="utf-8"))
        self.assertEqual(receipt["sha256_at_confirm"],
                         hashlib.sha256(
                             filed.encode("utf-8")).hexdigest())

    def test_confirm_refuses_a_non_preview(self):
        plain = self.root / "staging" / "previews"
        plain.mkdir(parents=True)
        (plain / "plain.md").write_text("# Not a preview\n",
                                        encoding="utf-8")
        with self.assertRaises(wp.PreviewError):
            wp.confirm("plain.md", root=self.root, now=NOW)

    def test_confirm_refuses_to_overwrite_a_filed_draft(self):
        res = self._clip_preview()
        name = Path(res["draft"]).name
        filed_dir = self.root / "staging" / "captures"
        filed_dir.mkdir(parents=True, exist_ok=True)
        (filed_dir / name).write_text("# Already filed\n",
                                      encoding="utf-8")
        with self.assertRaises(wp.PreviewError):
            wp.confirm(name, root=self.root, now=NOW)
        # and the preview is still waiting, unfiled
        self.assertEqual(wp.list_previews(self.root), [name])

    def test_discard_moves_aside_never_deletes(self):
        res = self._clip_preview()
        name = Path(res["draft"]).name
        rel = wp.discard(name, root=self.root)
        self.assertTrue((self.root / rel).is_file())
        self.assertEqual(wp.list_previews(self.root), [])

    def test_normal_clip_is_unaffected(self):
        res = clip.clip_file(self.src, root=self.root, now=NOW)
        self.assertFalse(res["preview"])
        self.assertTrue(res["draft"].startswith("staging/captures/"))
        text = (self.root / res["draft"]).read_text(encoding="utf-8")
        self.assertNotIn("capture_state", text)


if __name__ == "__main__":
    unittest.main()
