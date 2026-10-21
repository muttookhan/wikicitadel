#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins CRAG scorer+gate: strong retrieval proceeds, weak widens/re-queries, empty abstains with ladder.
Run: python3 -m unittest discover -s scripts/tests"""
g=load("crag","scripts/wiki_crag_gate.py")
class T(unittest.TestCase):
    def test_proceed(self):
        r=g.gate("when was the chapel bell cast", ["The chapel bell was cast in 1881 by the founders."])
        self.assertEqual(r["action"],"proceed")
    def test_abstain_empty(self):
        r=g.gate("quantum tunnelling rates", []); self.assertEqual(r["action"],"abstain"); self.assertTrue(r["fallback_ladder"])
    def test_ladder_order(self):
        r=g.gate("chapel bell founders names", ["unrelated text about farming and weather"])
        self.assertIn(r["action"], ("widen","re-query","abstain"))
    def test_score_bounds(self):
        s=g.score_query("bell", ["bell bell bell"]); self.assertTrue(0<=s["confidence"]<=1)
if __name__=="__main__": unittest.main()
