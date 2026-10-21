#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins judge-language A/B harness: agreement + deltas computed over self-authored fixtures, empty refused.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("ab","scripts/wiki_judge_lang_ab.py")
ROWS=[{"id":"1","label":"accept","variants":{"en":"accept","ko":"accept","ja":"reject"}},
      {"id":"2","label":"reject","variants":{"en":"reject","ko":"accept","ja":"reject"}}]
class T(unittest.TestCase):
    def test_agreements(self):
        r=m.run(ROWS, baseline="en"); self.assertEqual(r["label_agreement"]["en"]["label_agreement"],1.0)
        self.assertEqual(r["label_agreement"]["ko"]["label_agreement"],0.5)
        self.assertEqual(r["delta_vs_baseline"]["ko"],-0.5)
    def test_empty_refused(self): self.assertEqual(m.run([])["status"],"refused")
if __name__=="__main__": unittest.main()
