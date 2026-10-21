#!/usr/bin/env python3
"""Tests for wiki_alias_register. Pins resolver, collisions, scaffold. Fixtures only. Run: python3 -m unittest discover -s scripts/tests -p test_wiki_alias_register.py"""
import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("al",ROOT/"scripts/wiki_alias_register.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
REG={"version":1,"aliases":{"Erlotinib":["Tarceva"],"EGFR inhibitor":["Erlotinib-class"]}}
class T(unittest.TestCase):
    def test_resolve_alias(self): self.assertEqual(m.resolve("tarceva",REG),"Erlotinib")
    def test_resolve_canonical(self): self.assertEqual(m.resolve("Erlotinib",REG),"Erlotinib")
    def test_resolve_miss(self): self.assertIsNone(m.resolve("nope",REG))
    def test_no_collision(self): self.assertEqual(m.collisions(REG),[])
    def test_collision_two_entities(self):
        r={"version":1,"aliases":{"A":["x"],"B":["X"]}}; self.assertTrue(m.collisions(r))
    def test_collision_alias_is_canonical(self):
        r={"version":1,"aliases":{"A":["B"],"B":[]}}; self.assertTrue(m.collisions(r))
    def test_scaffold_empty(self): self.assertEqual(m.SCAFFOLD["aliases"],{})
if __name__=="__main__": unittest.main()
