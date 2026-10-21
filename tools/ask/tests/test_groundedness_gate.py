#!/usr/bin/env python3
"""Tests for tools/ask/groundedness_gate.py — pins: default-off passes anything; enabled gate passes a fully evidenced answer and BLOCKS an unevidenced one with a correction request naming the ungrounded claims.
Run: python3 -m unittest discover -s tools/ask/tests -v"""
import importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("groundedness_gate", Path(__file__).resolve().parents[1]/"groundedness_gate.py")
g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
EV=["The harbour lighthouse was built in 1901 and guides ships into the harbour."]
GOOD="The harbour lighthouse was built in 1901. It guides ships into the harbour."
BAD="The harbour lighthouse was built in 1901. Martian colonies fund its upkeep entirely."
class GateTests(unittest.TestCase):
    def test_default_off(self):
        self.assertFalse(g.GATE_ENABLED_DEFAULT)
        self.assertEqual(g.evaluate(BAD, EV)["verdict"],"pass")
    def test_grounded_passes(self):
        r=g.evaluate(GOOD, EV, enabled=True); self.assertEqual(r["verdict"],"pass"); self.assertGreaterEqual(r["score"],0.6)
    def test_ungrounded_blocks_with_correction(self):
        r=g.evaluate(BAD, EV, enabled=True); self.assertEqual(r["verdict"],"block")
        self.assertTrue(any("Martian" in c for c in r["correction_request"]["ungrounded_claims"]))
    def test_no_claims_blocks(self):
        self.assertEqual(g.evaluate("Hi.", EV, enabled=True)["verdict"],"block")
if __name__=="__main__": unittest.main()
