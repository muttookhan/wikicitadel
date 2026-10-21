#!/usr/bin/env python3
"""Pins wiki_ark_info lookup. Run: discover -p 'test_wiki_ark_info.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_ark_info as m
class T(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); self.r=Path(self.d); (self.r/"wiki"/"concepts").mkdir(parents=True)
        (self.r/"wiki"/"concepts"/"old-page.md").write_text("---\ntitle: Old\ncreated: 2026-01-01\ntype: concept\nreplaced_by: wiki/concepts/new-page.md\n---\nx")
    def test_info_suffix_and_successor(self):
        rec,st=m.lookup(self.r,"old-page?info"); self.assertEqual(st,"ok")
        self.assertEqual(rec["title"],"Old"); self.assertEqual(rec["successor"],"wiki/concepts/new-page.md")
    def test_missing(self): self.assertEqual(m.lookup(self.r,"nope")[1],"not-found")
if __name__=="__main__": unittest.main()
