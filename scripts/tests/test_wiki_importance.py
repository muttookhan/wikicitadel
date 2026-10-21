#!/usr/bin/env python3
"""Tests for wiki_importance. Pins decay, attestation, inbound weighting, determinism with fixed as-of."""
import importlib.util, tempfile, unittest
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("im",ROOT/"scripts/wiki_importance.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree(pages):
    r=Path(tempfile.mkdtemp())
    for n,t in pages.items():
        p=r/"wiki"/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(t)
    return r
A="---\ntitle: A\nupdated: 2026-01-01\nstatus: verified\n---\n[[b]]"
B="---\ntitle: B\nupdated: 2025-01-01\n---\n"
class T(unittest.TestCase):
    def setUp(self): self.d=m.compute(tree({"a.md":A,"b.md":B}),date(2026,1,1)); self.rows={r["page"]:r for r in self.d["rows"]}
    def test_attested_newer_scores_higher(self): self.assertGreater(self.rows["wiki/a.md"]["score"],self.rows["wiki/b.md"]["score"])
    def test_inbound_counted(self): self.assertEqual(self.rows["wiki/b.md"]["inbound"],1)
    def test_decay_less_than_one_for_old(self): self.assertLess(self.rows["wiki/b.md"]["decay"],0.4)
    def test_age(self): self.assertEqual(self.rows["wiki/b.md"]["age_days"],365)
    def test_sorted(self): self.assertEqual(self.d["rows"][0]["page"],"wiki/a.md")
if __name__=="__main__": unittest.main()
