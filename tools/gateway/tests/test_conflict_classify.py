#!/usr/bin/env python3
"""Tests for gateway conflict_classify. Pins the four labels; classify-only (no blocking API exists)."""
import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location("cc",ROOT/"tools/gateway/gateway/conflict_classify.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class T(unittest.TestCase):
    def test_duplicate(self): self.assertEqual(m.classify("the gate is open daily",["the gate is open daily"])["label"],"duplicate")
    def test_contradiction_negation(self): self.assertEqual(m.classify("the gate is not open daily",["the gate is open daily today now"])["label"],"contradiction")
    def test_contradiction_antonym(self): self.assertEqual(m.classify("access is allowed for editors",["access is denied for editors"])["label"],"contradiction")
    def test_refinement_superset(self): self.assertEqual(m.classify("the gate is open",["the gate is open daily for members"])["label"],"refinement")
    def test_unrelated(self): self.assertEqual(m.classify("quantum bananas orbit saturn",["the gate is open daily"])["label"],"unrelated")
    def test_empty_existing(self): self.assertEqual(m.classify("anything",[])["label"],"unrelated")
    def test_no_block_api(self): self.assertFalse(hasattr(m,"block") or hasattr(m,"reject"))
if __name__=="__main__": unittest.main()
