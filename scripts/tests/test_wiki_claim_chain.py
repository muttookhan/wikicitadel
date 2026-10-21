#!/usr/bin/env python3
"""Tests for scripts/wiki_claim_chain.py. Fixture trees in temp dirs only.
Run: python3 -m unittest discover -s scripts/tests -v"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
def load(n):
    s=importlib.util.spec_from_file_location(n, SCRIPTS/f"{n}.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def mk(root, rel, text):
    p=Path(root)/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
PAGE="---\ntitle: {t}\ntype: concept\ncreated: 2026-10-20\nupdated: 2026-10-20\nsources: []\ntags: [x]\n{extra}---\n\n## Summary\n\nSummary sentence here.\n\nFull body paragraph follows.\n"

m=load("wiki_claim_chain")
class T2(unittest.TestCase):
    def test_chain_orders_and_diffs(self):
        d=tempfile.mkdtemp()
        mk(d,"evaluation/claim-versions.jsonl",'{"claim":"wiki/concepts/a.md","version":1,"date":"2026-10-01","text":"Alpha holds."}\n{"claim":"wiki/concepts/a.md","version":2,"date":"2026-10-05","text":"Alpha holds firmly."}\n')
        mk(d,"evaluation/outcomes.jsonl",'{"claim":"wiki/concepts/a.md","date":"2026-10-06","outcome":"supports","note":"seen"}\n')
        c=m.build_chain(d,"wiki/concepts/a.md"); self.assertEqual(c["count"],3)
        v2=[n for n in c["versions"] if n.get("version")==2][0]; self.assertTrue(any("firmly" in line for line in v2["diff"]))
    def test_unknown_claim_empty(self):
        self.assertEqual(m.build_chain(tempfile.mkdtemp(),"nope")["count"],0)
if __name__=="__main__": unittest.main()
