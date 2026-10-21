#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins LongMemEval template: five abilities validate, knowledge-update picks latest, abstention needs no relevant turn.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("lm","scripts/wiki_longmem_eval.py")
def case(ability, **kw):
    base={"id":"F1","ability":ability,"sessions":[{"id":"s1","timestamp":"2026-01-01","turns":["The harbour fee is ten coins."]}],"question":"what is the harbour fee","expected":"harbour fee ten coins"}
    base.update(kw); return base
class T(unittest.TestCase):
    def test_all_abilities_validate(self):
        for ab in m.ABILITIES:
            c=case(ab, expected=None) if ab=="abstention" else case(ab)
            self.assertEqual(m.validate_case(c), [], ab)
    def test_bad_ability(self): self.assertTrue(m.validate_case(case("telepathy")))
    def test_extraction_passes(self): self.assertTrue(m.run_case(case("extraction"))["passed"])
    def test_update_latest_wins(self):
        c=case("knowledge-update", sessions=[{"id":"s1","timestamp":"2026-01-01","turns":["The harbour fee is ten coins."]},{"id":"s2","timestamp":"2026-02-01","turns":["The harbour fee is twelve coins now."]}], expected="harbour fee twelve coins")
        self.assertTrue(m.run_case(c)["passed"])
    def test_abstention(self):
        c=case("abstention", expected=None, question="what is the mayor's favourite song")
        self.assertTrue(m.run_case(c)["passed"])
if __name__=="__main__": unittest.main()
