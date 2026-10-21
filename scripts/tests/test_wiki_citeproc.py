"""Tests for scripts/wiki_citeproc.py (Marathon R9 lane BB)."""
import importlib.util
import json
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
def load():
    s = importlib.util.spec_from_file_location("wiki_citeproc", SCRIPTS / "wiki_citeproc.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()
class CiteprocTests(unittest.TestCase):
    def test_shipped_lockfile_renders_all_entries(self):
        lock = MOD.load_lockfile()
        text = MOD.render_bibliography(lock)
        self.assertEqual(text.count("\n["), len(lock["citations"]))
        self.assertIn(MOD.STYLE_NAME, text)
        for c in lock["citations"]:
            self.assertIn(c["source"], text)
    def test_grouping_and_no_invention(self):
        lock = {"generated": "2026-01-01", "lockfile_version": 2,
                "citations": [
                    {"id": "c2", "page": "wiki/b.md", "page_line": 3,
                     "claim": "Second.", "source": "raw/z.md",
                     "range": [1, 2], "selector": {"exact": "zz"}},
                    {"id": "c1", "page": "wiki/a.md", "page_line": 1,
                     "claim": "First.", "source": "raw/a.md",
                     "range": [5, 5], "selector": {"exact": "aa"}}]}
        text = MOD.render_bibliography(lock)
        self.assertLess(text.index("raw/a.md"), text.index("raw/z.md"))
        self.assertIn('"aa"', text)
        self.assertNotIn("et al", text)
    def test_trial_is_derived_and_stable(self):
        lock = MOD.load_lockfile()
        self.assertEqual(MOD.trial_text(lock), MOD.trial_text(lock))
        self.assertIn("DERIVED ARTEFACT", MOD.trial_text(lock))
        trial = ROOT / "evaluation" / "citeproc-trial.md"
        self.assertTrue(trial.is_file())
        self.assertEqual(trial.read_text(encoding="utf-8"), MOD.trial_text(lock))
if __name__ == "__main__":
    unittest.main()
