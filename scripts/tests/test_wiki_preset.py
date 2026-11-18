#!/usr/bin/env python3
"""Tests for scripts/wiki_preset.py — temp targets only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_preset  # noqa: E402


class TestPresets(unittest.TestCase):
    def test_five_presets_listed(self):
        names = [m["name"] for m in wiki_preset.list_presets()]
        self.assertEqual(names, ["personal-knowledge", "project-wiki",
                                 "reading-group-wiki", "research-wiki",
                                 "team-research-wiki"])

    def test_each_preset_has_files(self):
        for m in wiki_preset.list_presets():
            _, files, _ = wiki_preset.load_preset(wiki_preset.PRESETS_DIR,
                                                  m["name"])
            self.assertGreaterEqual(len(files), 2, m["name"])

    def test_install_copies_and_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            r = wiki_preset.install(wiki_preset.PRESETS_DIR, "research-wiki", td)
            self.assertEqual(len(r["installed"]), 2)
            self.assertEqual(r["skipped_existing"], [])
            target = Path(td)
            self.assertTrue((target / "wiki/concepts/research-questions.md").is_file())
            self.assertTrue((target / "preset-research-wiki.receipt.json").is_file())

    def test_install_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            wiki_preset.install(wiki_preset.PRESETS_DIR, "project-wiki", td)
            p = Path(td) / "wiki/concepts/project-state.md"
            p.write_text("MY OWN WORDS\n", encoding="utf-8")
            r = wiki_preset.install(wiki_preset.PRESETS_DIR, "project-wiki", td)
            self.assertEqual(r["installed"], [])
            self.assertEqual(len(r["skipped_existing"]), 2)
            self.assertEqual(p.read_text(encoding="utf-8"), "MY OWN WORDS\n")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            r = wiki_preset.install(wiki_preset.PRESETS_DIR,
                                    "personal-knowledge", td, dry_run=True)
            self.assertEqual(len(r["installed"]), 2)
            self.assertEqual(list(Path(td).rglob("*")), [])

    def test_unknown_preset_raises(self):
        with self.assertRaises(KeyError):
            wiki_preset.load_preset(wiki_preset.PRESETS_DIR, "no-such")


class TestNewPresets(unittest.TestCase):
    def test_new_presets_have_full_structure(self):
        for name in ("team-research-wiki", "reading-group-wiki"):
            meta, files, _ = wiki_preset.load_preset(
                wiki_preset.PRESETS_DIR, name)
            self.assertEqual(meta["name"], name)
            for key in ("title", "description", "best_for"):
                self.assertTrue(meta[key], f"{name}:{key}")
            self.assertEqual(len(files), 2, name)
            self.assertTrue(any("/concepts/" in f for f in files), name)
            self.assertTrue(any("/rules/" in f for f in files), name)

    def test_new_presets_install(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("team-research-wiki", "reading-group-wiki"):
                r = wiki_preset.install(wiki_preset.PRESETS_DIR, name, td)
                self.assertEqual(len(r["installed"]), 2, name)
                self.assertTrue(
                    (Path(td) / f"preset-{name}.receipt.json").is_file())


class TestGallery(unittest.TestCase):
    def test_gallery_lists_all_presets_and_templates(self):
        page = wiki_preset.build_gallery_html()
        for name in ("personal-knowledge", "project-wiki",
                     "reading-group-wiki", "research-wiki",
                     "team-research-wiki"):
            self.assertIn(name, page)
        # A preset file list and a template row are both present.
        self.assertIn("wiki/concepts/research-questions.md", page)
        self.assertIn("capture/note.md", page)

    def test_gallery_is_deterministic_and_self_contained(self):
        first = wiki_preset.build_gallery_html()
        second = wiki_preset.build_gallery_html()
        self.assertEqual(first, second)
        self.assertNotIn("<script", first)
        self.assertNotIn('src="http', first)
        self.assertNotIn('href="http', first)
        self.assertIn("<style>", first)

    def test_gallery_escapes_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            presets = Path(td) / "presets"
            evil = presets / "evil" / "files"
            evil.mkdir(parents=True)
            (presets / "evil" / "preset.json").write_text(
                '{"name": "evil", "title": "<script>x</script>", '
                '"description": "d", "best_for": "b"}',
                encoding="utf-8")
            (evil / "a.md").write_text("x\n", encoding="utf-8")
            page = wiki_preset.build_gallery_html(
                presets, Path(td) / "no-templates")
            self.assertNotIn("<script>x</script>", page)
            self.assertIn("&lt;script&gt;", page)

    def test_write_gallery_writes_file_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "gallery.html"
            summary = wiki_preset.write_gallery(out)
            self.assertTrue(out.is_file())
            self.assertEqual(summary["presets"], 5)
            self.assertGreaterEqual(summary["templates"], 5)
            self.assertEqual(out.read_text(encoding="utf-8"),
                             wiki_preset.build_gallery_html())

    def test_list_templates_excludes_presets(self):
        names = [t["name"] for t in wiki_preset.list_templates()]
        self.assertTrue(names)
        self.assertFalse(any(n.startswith("presets/") for n in names))
        self.assertIn("capture/note.md", names)

if __name__ == "__main__":
    unittest.main()
