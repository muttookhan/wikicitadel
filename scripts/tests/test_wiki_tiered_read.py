#!/usr/bin/env python3
"""Tests for scripts/wiki_tiered_read.py. Fixture trees in temp dirs only.
Run: python3 -m unittest discover -s scripts/tests -v"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
def load(n):
    s=importlib.util.spec_from_file_location(n, SCRIPTS/f"{n}.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def mk(root, rel, text):
    p=Path(root)/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
PAGE="---\ntitle: {t}\ntype: concept\ncreated: 2026-10-20\nupdated: 2026-10-20\nsources: []\ntags: [x]\n{extra}---\n\n## Summary\n\nSummary sentence here.\n\nFull body paragraph follows.\n"

m=load("wiki_tiered_read")
class T3(unittest.TestCase):
    def setUp(self): self.d=tempfile.mkdtemp(); mk(self.d,"wiki/concepts/p.md",PAGE.format(t="Pagetitle",extra=""))
    def test_levels(self):
        r0,_=m.read_tiered(self.d,"p",0); self.assertEqual(r0["title"],"Pagetitle"); self.assertNotIn("summary",r0)
        r1,_=m.read_tiered(self.d,"p",1); self.assertIn("Summary sentence",r1["summary"]); self.assertNotIn("text",r1)
        r2,_=m.read_tiered(self.d,"p",2); self.assertIn("Full body",r2["text"])
    def test_missing(self):
        _,code=m.read_tiered(self.d,"nope",1); self.assertEqual(code,1)
if __name__=="__main__": unittest.main()
