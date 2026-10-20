"""Tests for scripts/wiki_capture.py (consolidated-queue
item 52): every kind renders a draft whose frontmatter parses
under the wiki validator's own parser, with the harness fills
in place; unknown kinds are refused; and no write ever lands
outside staging/captures/."""
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

NOW = datetime(2030, 10, 20, 8, 4, tzinfo=timezone.utc)
REAL_TEMPLATES = SCRIPTS.parent / "templates" / "capture"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="capture-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        dest = self.root / "templates" / "capture"
        dest.mkdir(parents=True)
        for tpl in REAL_TEMPLATES.glob("*.md"):
            shutil.copy(tpl, dest / tpl.name)


class RenderTests(Fixture):
    def test_every_kind_renders_schema_frontmatter(self):
        for kind in sorted(wc.KINDS):
            text = wc.render(kind, "A test capture",
                             provenance="chat, 2030-10-20",
                             decided="2030-10-13"
                             if kind == "decision" else None,
                             now=NOW, root=self.root)
            fields, body = wv.parse_frontmatter(text)
            self.assertIsNotNone(fields, kind)
            self.assertEqual(fields["title"], "A test capture")
            self.assertEqual(fields["capture_kind"], kind)
            self.assertEqual(fields["status"], "draft")
            self.assertEqual(fields["confidence"], "observed")
            # sources empty — never faked
            self.assertEqual(fields["sources"], [])
            # the item-51 question rides unanswered
            self.assertEqual(fields["sensitivity"], "TODO")
            # the compile stamp is present and unset: a
            # capture is not yet a compile
            for key in ("compiled_prompt", "compiled_converter",
                        "compiled_date"):
                self.assertIn(key, fields, (kind, key))
                self.assertFalse(fields[key], (kind, key))
            self.assertTrue(body.strip(), kind)
            if kind != "filing":
                # the filing kind's body is the filing block,
                # not a headed page
                self.assertIn("# ", body, kind)

    def test_harness_fills_timestamp_and_provenance(self):
        text = wc.render("note", "Balance read",
                         provenance="Portal, 2030-10-20",
                         now=NOW, root=self.root)
        self.assertIn("2030-10-20 08:04 UTC", text)
        self.assertIn("Portal, 2030-10-20", text)
        # no grammar token survives expansion
        for token in ("%U", "%:date", "%^{", "%a", "%?"):
            self.assertNotIn(token, text)

    def test_missing_provenance_becomes_a_prompt_not_a_fake(self):
        text = wc.render("note", "No provenance", now=NOW,
                         root=self.root)
        fields, _ = wv.parse_frontmatter(text)
        self.assertTrue(fields["provenance"].startswith("TODO"))

    def test_the_one_designed_prompt_is_why(self):
        for kind in sorted(wc.KINDS):
            if kind == "filing":
                continue  # the filing order's own field grammar
            text = wc.render(kind, "Prompt check", now=NOW,
                             root=self.root)
            self.assertIn("[prompt: Why", text, kind)

    def test_decision_dual_dating(self):
        text = wc.render("decision", "A ruling",
                         decided="2030-10-13", now=NOW,
                         root=self.root)
        fields, _ = wv.parse_frontmatter(text)
        # event date vs writing date, side by side
        self.assertEqual(fields["decided"], "2030-10-13")
        self.assertTrue(fields["captured"].startswith("2030-10-20"))
        self.assertNotEqual(fields["decided"],
                            fields["capture_date"])

    def test_decision_without_decided_prompts_for_it(self):
        text = wc.render("decision", "A ruling", now=NOW,
                         root=self.root)
        fields, _ = wv.parse_frontmatter(text)
        self.assertTrue(fields["decided"].startswith("TODO"))

    def test_filing_body_is_the_filing_orders_shape(self):
        text = wc.render("filing", "A contribution", now=NOW,
                         root=self.root)
        for line in ("WIKI FILING", "From: agent",
                     "Date: 2030-10-20", "Topic: A contribution",
                     "Type:", "What happened:", "Evidence:",
                     "Uncertain:", "Related:"):
            self.assertIn(line, text)


class RefusalTests(Fixture):
    def test_unknown_kind_refused(self):
        with self.assertRaises(wc.CaptureError):
            wc.render("telegram", "Nope", now=NOW, root=self.root)
        with self.assertRaises(wc.CaptureError):
            wc.new_capture("telegram", "Nope", now=NOW,
                           root=self.root)

    def test_decided_refused_for_other_kinds(self):
        with self.assertRaises(wc.CaptureError):
            wc.render("idea", "Wrong flag", decided="2030-10-13",
                      now=NOW, root=self.root)

    def test_bad_decided_date_refused(self):
        with self.assertRaises(wc.CaptureError):
            wc.render("decision", "Bad date", decided="Oct 13",
                      now=NOW, root=self.root)

    def test_missing_template_refused(self):
        (self.root / "templates" / "capture"
         / "note.md").unlink()
        with self.assertRaises(wc.CaptureError):
            wc.render("note", "Gone", now=NOW, root=self.root)


class WriteTests(Fixture):
    def test_new_writes_into_staging_captures_only(self):
        rel = wc.new_capture("source-note", "An article",
                             now=NOW, root=self.root)
        self.assertEqual(
            rel, "staging/captures/2030-10-20-source-note-"
                 "an-article.md")
        self.assertTrue((self.root / rel).exists())
        # nothing anywhere else in the tree
        written = [p for p in self.root.rglob("*.md")
                   if "templates" not in p.parts]
        self.assertEqual(written, [self.root / rel])
        self.assertFalse((self.root / "wiki").exists())

    def test_existing_draft_refused_not_overwritten(self):
        wc.new_capture("note", "Same title", now=NOW,
                       root=self.root)
        with self.assertRaises(wc.CaptureError):
            wc.new_capture("note", "Same title", now=NOW,
                           root=self.root)

    def test_escaping_file_paths_refused(self):
        for bad in ("../../wiki/evil.md", "/tmp/evil.md",
                    "sub/dir.md", "..\\evil.md"):
            with self.assertRaises(wc.CaptureError, msg=bad):
                wc.new_capture("note", "Escape attempt",
                               file=bad, now=NOW, root=self.root)
        self.assertFalse((self.root / "wiki").exists())
        self.assertFalse(
            (self.root / "staging" / "captures").exists())

    def test_file_name_is_normalised_into_staging(self):
        rel = wc.new_capture("idea", "Named by hand",
                             file="my-idea", now=NOW,
                             root=self.root)
        self.assertEqual(rel, "staging/captures/my-idea.md")
        self.assertTrue((self.root / rel).exists())


class ListTests(Fixture):
    def test_list_names_every_kind_and_destination(self):
        out = wc.list_kinds()
        for kind in wc.KINDS:
            self.assertIn(kind, out)
            self.assertIn(wc.KINDS[kind]["destination"], out)


if __name__ == "__main__":
    unittest.main()
