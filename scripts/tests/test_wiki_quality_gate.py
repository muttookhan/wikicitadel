#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins quality gate: grounded outputs pass, ungrounded fail, empty run refused.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("qg","scripts/wiki_quality_gate.py")
class T(unittest.TestCase):
    def test_pass(self):
        r=m.run([{"id":"1","question":"when was the bell cast","answer":"the bell was cast in 1881","evidence":"the bell was cast in 1881 by the founders"}])
        self.assertEqual(r["status"],"pass")
    def test_fail(self):
        r=m.run([{"id":"1","question":"when was the bell cast","answer":"purple elephants dance nightly","evidence":"the bell was cast in 1881"}])
        self.assertEqual(r["status"],"fail")
    def test_empty_refused(self): self.assertEqual(m.run([])["status"],"refused")
    def test_proxies_labelled(self): self.assertIn("proxies", m.run([{"id":"1","question":"a b","answer":"a b","evidence":"a b"}])["metrics_are"])
if __name__=="__main__": unittest.main()
