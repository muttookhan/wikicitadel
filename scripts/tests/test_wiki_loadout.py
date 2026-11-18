#!/usr/bin/env python3
"""Tests for scripts/wiki_loadout.py. Fixture trees in temp dirs only.
Run: python3 -m unittest discover -s scripts/tests -v"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
def load(n):
    s=importlib.util.spec_from_file_location(n, SCRIPTS/f"{n}.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def mk(root, rel, text):
    p=Path(root)/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
PAGE="---\ntitle: {t}\ntype: concept\ncreated: 2026-10-20\nupdated: 2026-10-20\nsources: []\ntags: [x]\n{extra}---\n\n## Summary\n\nSummary sentence here.\n\nFull body paragraph follows.\n"

m=load("wiki_loadout")
class T1(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp()
        mk(self.d,"evaluation/loadouts.json",json.dumps({"agents":["owner","grok","mehmed"],"loadouts":{"grok":["wiki/concepts/*"],"mehmed":["wiki/concepts/*"]}}))
        mk(self.d,"wiki/concepts/open.md",PAGE.format(t="Open",extra=""))
        mk(self.d,"wiki/concepts/secret.md",PAGE.format(t="Secret",extra="visibility: [owner, mehmed]\n"))
    def test_violation_for_excluded_agent(self):
        res,code=m.check(self.d); self.assertEqual(code,1); self.assertTrue(any(v["agent"]=="grok" for v in res["violations"]))
    def test_no_violation_when_all_open(self):
        mk(self.d,"evaluation/loadouts.json",json.dumps({"agents":["owner","grok"],"loadouts":{"grok":["wiki/concepts/open.md"]}}))
        res,code=m.check(self.d); self.assertEqual(code,0)
    def test_missing_register(self):
        res,code=m.check(tempfile.mkdtemp()); self.assertEqual(code,2)
if __name__=="__main__": unittest.main()
