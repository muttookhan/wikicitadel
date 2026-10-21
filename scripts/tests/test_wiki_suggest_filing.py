"""Tests for scripts/wiki_suggest_filing.py (DEVONthink
Classify, Tier A half — Marathon Round 3, lane TA4): ranked
destination suggestions from title/tag similarity over a
fixture index, an honest empty result on no overlap, and the
hard seam — the tool SUGGESTS ONLY: the fixture tree is
byte-identical after a run.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_suggest_filing as wsf  # noqa: E402

INDEX_MD = """# Index

## Concepts
- [[wiki/concepts/spaced-repetition]] — flashcards and review intervals for memory
- [[wiki/concepts/sourdough-basics]] — flour, water, starter and slow fermentation

## Entities
- [[wiki/entities/library-of-alexandria]] — the ancient library and its scrolls
"""


def _tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class SuggestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="suggest-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "wiki").mkdir(parents=True)
        (self.root / "wiki" / "index.md").write_text(
            INDEX_MD, encoding="utf-8")

    def test_matching_title_suggests_the_page(self):
        out = wsf.suggest(self.root,
                          "Spaced repetition for flashcards")
        self.assertTrue(out)
        self.assertEqual(out[0]["page"],
                         "wiki/concepts/spaced-repetition.md")
        self.assertIn("spaced", out[0]["matched_terms"])
        self.assertGreater(out[0]["score"], 0)

    def test_summary_terms_also_match(self):
        out = wsf.suggest(self.root, "Slow fermentation notes")
        self.assertEqual(out[0]["page"],
                         "wiki/concepts/sourdough-basics.md")

    def test_no_overlap_is_an_honest_empty(self):
        self.assertEqual(
            wsf.suggest(self.root, "Quantum chromodynamics"), [])

    def test_limit_respected(self):
        out = wsf.suggest(self.root, "memory library scrolls",
                          limit=1)
        self.assertEqual(len(out), 1)

    def test_suggestion_only_tree_unchanged(self):
        before = _tree_hash(self.root)
        wsf.suggest(self.root, "Spaced repetition")
        rc = wsf.main(["--root", str(self.root), "suggest",
                       "--title", "Sourdough basics"])
        self.assertEqual(rc, 0)
        self.assertEqual(_tree_hash(self.root), before)


if __name__ == "__main__":
    unittest.main()
