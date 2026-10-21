#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins native-language gate: agreeing annotators pass, disagreeing fail kappa/agreement, wrong lang is an error.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("ne","scripts/wiki_native_eval_gate.py")
CASES=[{"id":str(i),"lang":"ja","text":"フィクスチャ文","label":l} for i,l in enumerate(["yes","no","yes","no","yes","no"])]
def ann(labels): return [{"id":str(i),"label":l} for i,l in enumerate(labels)]
class T(unittest.TestCase):
    def test_usable(self):
        r=m.check(CASES, ann(["yes","no","yes","no","yes","no"]), ann(["yes","no","yes","no","yes","yes"]), "ja")
        self.assertTrue(r["usable"], r); self.assertGreater(r["kappa"],0.4)
    def test_disagreement_fails(self):
        r=m.check(CASES, ann(["yes"]*6), ann(["no"]*6), "ja"); self.assertFalse(r["usable"])
    def test_wrong_lang(self):
        bad=[dict(c, lang="ko") for c in CASES]; r=m.check(bad, ann(["yes","no","yes","no","yes","no"]), ann(["yes","no","yes","no","yes","no"]), "ja")
        self.assertFalse(r["usable"]); self.assertTrue(r["errors"])
if __name__=="__main__": unittest.main()
