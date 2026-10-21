#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins MiniCheck fallback: overlap supports, disjoint unsupported, negation blocks, small-model slot unwired.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("mc","scripts/wiki_minicheck.py")
class T(unittest.TestCase):
    def setUp(self): self.c=m.LexicalFallbackChecker()
    def test_supported(self): self.assertEqual(self.c.check("the bell was cast in 1881","Records show the bell was cast in 1881 by founders.")["verdict"],"supported")
    def test_unsupported(self): self.assertEqual(self.c.check("the roof is copper","The bell was cast in 1881.")["verdict"],"unsupported")
    def test_negation(self): self.assertEqual(self.c.check("the bell was cast in 1881","The bell was not cast in 1881 at all.")["verdict"],"unsupported")
    def test_slot_unwired(self):
        with self.assertRaises(m.NotWired): m.SmallModelCheckerSlot().check("x","y")
    def test_method_labelled_fallback(self): self.assertIn("fallback", self.c.check("a b","a b")["method"])
if __name__=="__main__": unittest.main()
