#!/usr/bin/env python3
"""Tests for scripts/wiki_advisory_memory.py. Fixture trees in temp dirs only.
Run: python3 -m unittest discover -s scripts/tests -v"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
def load(n):
    s=importlib.util.spec_from_file_location(n, SCRIPTS/f"{n}.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def mk(root, rel, text):
    p=Path(root)/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
PAGE="---\ntitle: {t}\ntype: concept\ncreated: 2026-10-20\nupdated: 2026-10-20\nsources: []\ntags: [x]\n{extra}---\n\n## Summary\n\nSummary sentence here.\n\nFull body paragraph follows.\n"

m=load("wiki_advisory_memory")
class T4(unittest.TestCase):
    def setUp(self): self.d=tempfile.mkdtemp(); mk(self.d,"wiki/concepts/p.md",PAGE.format(t="P",extra=""))
    def test_refuses_without_citation(self):
        _,code=m.add_entry(self.d,"note",""); self.assertEqual(code,1)
        _,code=m.add_entry(self.d,"note","wiki/concepts/missing.md"); self.assertEqual(code,1)
    def test_add_check_query(self):
        rec,code=m.add_entry(self.d,"harbour retrieval tip","wiki/concepts/p.md","2026-10-20"); self.assertEqual(code,0)
        res,code=m.check(self.d); self.assertEqual(code,0)
        out,_=m.query(self.d,"harbour"); self.assertEqual(len(out["results"]),1)
    def test_check_flags_broken_citation(self):
        mk(self.d,"evaluation/advisory-memory.jsonl",'{"id":"am0001","note":"x","citation":"wiki/gone.md","created":""}\n')
        _,code=m.check(self.d); self.assertEqual(code,1)
if __name__=="__main__": unittest.main()
