#!/usr/bin/env python3
"""Tests for scripts/wiki_preset.py — temp targets only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_preset  # noqa: E402


class TestPresets(unittest.TestCase):
    def test_three_presets_listed(self):
        names = [m["name"] for m in wiki_preset.list_presets()]
        self.assertEqual(names, ["personal-knowledge", "project-wiki",
                                 "research-wiki"])

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


if __name__ == "__main__":
    unittest.main()
