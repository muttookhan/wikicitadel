"""Tests for scripts/wiki_heed_rate.py (Marathon R9 lane BB)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
def load():
    s = importlib.util.spec_from_file_location("wiki_heed_rate", SCRIPTS / "wiki_heed_rate.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()
LEDGER = ("### 2026-01-01 — First error\n\ntext\n\n"
          "### 2026-01-02 — Second error\n\ntext\n\n"
          "| Entry | Class | Error kind | Standing rule |\n|---|---|---|---|\n"
          "| 2026-01-01 — First error | correction | wrong-fact | r1 |\n"
          "| 2026-01-02 — Second error | correction | wrong-date | r2 |\n")
class HeedTests(unittest.TestCase):
    def test_wilson(self):
        lo, hi = MOD.wilson(8, 10)
        self.assertTrue(0 < lo < 0.8 < hi <= 1)
        self.assertEqual(MOD.wilson(0, 0), (None, None))
    def test_unmeasured_is_honest(self):
        rep = MOD.build_report(LEDGER, {})
        self.assertEqual(rep["measured"], 0)
        self.assertEqual(rep["unmeasured"], 2)
        self.assertIsNone(rep["heed_rate"])
    def test_measured_rate(self):
        outcomes = {"2026-01-01 — First error":
                    {"entry": "2026-01-01 — First error",
                     "retrieved": True, "heeded": True, "recurred": False}}
        rep = MOD.build_report(LEDGER, outcomes)
        self.assertEqual(rep["heed_rate"], 1.0)
        self.assertEqual(rep["unmeasured"], 1)
    def test_real_ledger_and_register(self):
        ledger = ROOT / "wiki/rules/corrections-ledger.md"
        if not ledger.is_file():
            self.skipTest("this tree's seed corpus has no "
                          "corrections ledger page")
        text = ledger.read_text(encoding="utf-8")
        rep = MOD.build_report(text, MOD.load_outcomes())
        self.assertEqual(rep["measured"] + rep["unmeasured"], rep["ledger_entries"])
        self.assertGreater(rep["ledger_entries"], 0)
    def test_record_refuses_unknown_entry(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "ledger.md"; led.write_text(LEDGER, encoding="utf-8")
            reg = Path(td) / "out.jsonl"
            rc = MOD.main(["record", "--entry", "1999-01-01 — Nope",
                           "--ledger", str(led), "--register", str(reg)])
            self.assertEqual(rc, 2)
if __name__ == "__main__":
    unittest.main()
