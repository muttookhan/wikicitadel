#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins both-orders merge gate with fake judges: consistent approval passes, order-flip refuses, certification refused at 0 owner-labelled.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("mg","scripts/wiki_merge_judge_gate.py")
def good(d): return "approve" if d["candidate"]=="new" else "reject"
def biased(d): return "approve"  # approves whatever is presented as candidate -> positional bias
class T(unittest.TestCase):
    def test_both_orders_pass(self): self.assertTrue(m.judge_both_orders(good,"new","old")["passed"])
    def test_bias_refused(self):
        r=m.judge_both_orders(biased,"new","old"); self.assertFalse(r["passed"]); self.assertIn("disagree", r["reason"])
    def test_reject_refused(self):
        r=m.judge_both_orders(lambda d:"reject","new","old"); self.assertFalse(r["passed"])
    def test_certify_refused_zero(self): self.assertFalse(m.certify_judge(0)["certified"])
if __name__=="__main__": unittest.main()
