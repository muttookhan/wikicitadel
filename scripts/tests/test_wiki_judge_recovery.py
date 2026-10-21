#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins judge recovery: strict JSON parses, fenced/embedded + verdict-line recover, ambiguity refused, audit counts.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("jr","scripts/wiki_judge_recovery.py")
class T(unittest.TestCase):
    def test_strict(self): self.assertEqual(m.recover('{"verdict":"accept"}')["status"],"parsed")
    def test_embedded(self):
        r=m.recover('The judge says: {"verdict": "reject"} overall.'); self.assertEqual((r["status"],r["verdict"]),("recovered","reject"))
    def test_verdict_line(self): self.assertEqual(m.recover("Reasoning here.\nVerdict: accept")["rule"],"verdict-line")
    def test_ambiguous_refused(self): self.assertEqual(m.recover("I could accept or reject this")["status"],"refused")
    def test_garbage_refused(self): self.assertEqual(m.recover("???")["status"],"refused")
    def test_audit(self):
        rep=m.recover_all([{"id":"1","output":'{"verdict":"accept"}'},{"id":"2","output":"junk"}])
        self.assertEqual((rep["parsed"],rep["refused"]),(1,1)); self.assertIn("not certification", rep["certification"])
if __name__=="__main__": unittest.main()
