#!/usr/bin/env python3
"""Tests for wiki_feedback_triage. Pins validation and triage aggregation."""
import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("fb",ROOT/"scripts/wiki_feedback_triage.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
RECS=[{"id":"1","ts":"2026-01-01","source":"ask","page":"wiki/a.md","kind":"thumbs_up"},{"id":"2","ts":"2026-01-01","source":"portal","page":"wiki/a.md","kind":"correction","text":"wrong date"},{"id":"3","ts":"2026-01-02","source":"ask","page":"wiki/b.md","kind":"thumbs_down"}]
class T(unittest.TestCase):
    def test_valid(self): self.assertEqual([m.validate(r) for r in RECS],[[],[],[]])
    def test_correction_needs_text(self): self.assertTrue(m.validate({"id":"x","ts":"t","source":"ask","page":"p","kind":"correction"}))
    def test_bad_kind(self): self.assertTrue(m.validate({"id":"x","ts":"t","source":"ask","page":"p","kind":"meh"}))
    def test_triage(self):
        d=m.triage(RECS); self.assertEqual(d["total"],3); a=[p for p in d["pages"] if p["page"]=="wiki/a.md"][0]; self.assertTrue(a["needs_attention"]); self.assertEqual(len(d["corrections"]),1)
if __name__=="__main__": unittest.main()
