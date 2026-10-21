#!/usr/bin/env python3
"""Tests for scripts/wiki_claim_index.py. Fixture trees in temp dirs only.
Run: python3 -m unittest discover -s scripts/tests -v"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
def load(n):
    s=importlib.util.spec_from_file_location(n, SCRIPTS/f"{n}.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def mk(root, rel, text):
    p=Path(root)/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
PAGE="---\ntitle: {t}\ntype: concept\ncreated: 2026-10-20\nupdated: 2026-10-20\nsources: []\ntags: [x]\n{extra}---\n\n## Summary\n\nSummary sentence here.\n\nFull body paragraph follows.\n"

from datetime import date
m=load("wiki_claim_index")
CLAIM=PAGE.replace("type: concept","type: concept").format(t="C",extra='claim: "The harbour light shines nightly."\nas_of: 2026-10-01\n')
class T6(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); mk(self.d,"wiki/concepts/c.md",CLAIM)
        mk(self.d,"evaluation/outcomes.jsonl",'{"claim":"wiki/concepts/c.md","date":"2026-10-02","outcome":"supports"}\n'*3)
    def test_build_appends_and_query_ranks(self):
        m.build(self.d,date(2026,10,20)); m.build(self.d,date(2026,10,20))
        raw=(Path(self.d)/"evaluation/claim-index.jsonl").read_text().strip().splitlines(); self.assertEqual(len(raw),2)  # append-only: second build appends, never rewrites
        out,_=m.query(self.d,"harbour",date(2026,10,20)); self.assertEqual(len(out["results"]),1); self.assertGreater(out["results"][0]["score"],0.3)
    def test_superseded_scores_zero(self):
        rec={"superseded":True,"stated":"2026-10-01","supports":3,"contradicts":0,"verified_n":0}
        self.assertEqual(m.fusion_score(rec,date(2026,10,20)),0.0)
if __name__=="__main__": unittest.main()
