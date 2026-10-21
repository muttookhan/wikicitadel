#!/usr/bin/env python3
"""Pins wiki_collections classify/census. Run: python3 -m unittest discover -s scripts/tests -p 'test_wiki_collections.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_collections as m
class T(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(m.classify("raw/sources/x.md"),"sources")
        self.assertEqual(m.classify("wiki/sources/x.md"),"sources")
        self.assertEqual(m.classify("wiki/concepts/x.md"),"compiled")
        self.assertEqual(m.classify("wiki/rules/r.md"),"governance")
        self.assertEqual(m.classify("AGENTS.md"),"governance")
        self.assertEqual(m.classify("wiki/index.md"),"governance")
        self.assertEqual(m.classify("other/x.md"),"unclassified")
    def test_census_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d)
            for p in ("wiki/concepts/a.md","wiki/sources/b.md","wiki/rules/c.md"):
                (r/p).parent.mkdir(parents=True,exist_ok=True); (r/p).write_text("x")
            (r/"AGENTS.md").write_text("x")
            c=m.census(r); self.assertEqual(c["counts"]["compiled"],1)
            self.assertEqual(c["counts"]["sources"],1); self.assertEqual(c["counts"]["governance"],2)
            self.assertEqual(c["unclassified"],[])
if __name__=="__main__": unittest.main()
