"""Tests for scripts/wiki_citekeys.py (Marathon R3 TB5 row 10,
Citations plugin pattern): citekeys derive as author-year-key;
the register build refuses collisions; the checker flags a note
missing from the register, a dangling register entry and an
unresolved [@key] reference. Run:
python3 -m unittest scripts.tests.test_wiki_citekeys
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_citekeys as wck  # noqa: E402

NOTE = """---
title: "The LLM Wiki Pattern"
type: source
literature: true
authors: [Andrej Karpathy]
year: 2026
---

Body citing nothing.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cite-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "wiki" / "sources"
        self.src.mkdir(parents=True)
        (self.src / "karpathy.md").write_text(NOTE, encoding="utf-8")


class CitekeyTests(Fixture):
    def test_derive_shape(self):
        fm = wck.parse_frontmatter(NOTE)
        self.assertEqual(wck.derive_citekey(fm), "karpathy-2026-llm")

    def test_build_and_check_clean(self):
        register, collisions = wck.build_register(self.src, self.root)
        self.assertEqual(collisions, {})
        reg_path = self.root / "wiki" / "citekeys.json"
        reg_path.write_text(json.dumps(register), encoding="utf-8")
        problems = wck.check(self.src, reg_path, self.root,
                             pages_dir=self.root / "wiki")
        self.assertEqual(problems, [])

    def test_unresolved_reference_flagged(self):
        register, _ = wck.build_register(self.src, self.root)
        reg_path = self.root / "wiki" / "citekeys.json"
        reg_path.write_text(json.dumps(register), encoding="utf-8")
        page = self.root / "wiki" / "reader.md"
        page.write_text("See [@karpathy-2026-llm] and [@ghost-1999-x].\n",
                        encoding="utf-8")
        problems = wck.check(self.src, reg_path, self.root,
                             pages_dir=self.root / "wiki")
        self.assertTrue(any("ghost-1999-x" in p for p in problems))
        self.assertFalse(any("karpathy-2026-llm" in p and "unresolved" in p
                             for p in problems))

    def test_collision_refused(self):
        (self.src / "karpathy2.md").write_text(
            NOTE.replace("Pattern", "Patterns"), encoding="utf-8")
        register, collisions = wck.build_register(self.src, self.root)
        self.assertTrue(collisions)


if __name__ == "__main__":
    unittest.main()
