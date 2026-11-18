import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_occasional_actions", ROOT / "scripts/wiki_occasional_actions.py")

def _rec(**kw):
    r = {"kind": "occasional-action", "date": "2026-10-21", "page": "wiki/a.md",
         "action": "reappraisal", "trigger": "new evidence", "outcome": "no-change",
         "actor": "", "note": ""}
    r.update(kw); return r

class OccasionalActionTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["events"], 0); self.assertIsNone(rep["date_range"])
    def test_vocabularies_closed(self):
        self.assertEqual(MOD.ACTIONS, ["reappraisal", "migration", "format-refresh",
                                       "integrity-review", "disposal-review", "access-review"])
        self.assertIn("reappraisal", MOD.ACTIONS); self.assertIn("migration", MOD.ACTIONS)
        self.assertEqual(MOD.OUTCOMES, ["completed", "no-change", "deferred", "rejected", "superseded"])
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--page", "wiki/a.md", "--action", "migration",
                           "--trigger", "format risk", "--outcome", "completed",
                           "--date", "2026-10-20", "--register", str(p)])
            self.assertEqual(rc, 0)
            rep = MOD.build_report(p)
            self.assertEqual(rep["events"], 1); self.assertEqual(rep["by_action"]["migration"], 1)
            self.assertEqual(rep["date_range"], ["2026-10-20", "2026-10-20"])
    def test_bad_action_outcome_trigger_and_date_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(action="Bogus")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("action" in e for e in errs))
            p.write_text(json.dumps(_rec(outcome="Bogus")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("outcome" in e for e in errs))
            p.write_text(json.dumps(_rec(trigger="")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("trigger" in e for e in errs))
            p.write_text(json.dumps(_rec(date="21-10-2026")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("YYYY-MM-DD" in e for e in errs))
    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "g.jsonl"; good.write_text(json.dumps(_rec()) + "\n")
            self.assertEqual(MOD.main(["check", "--register", str(good)]), 0)
            bad = Path(td) / "b.jsonl"; bad.write_text('{"kind":"occasional-action"}\n')
            self.assertEqual(MOD.main(["check", "--register", str(bad)]), 1)

if __name__ == "__main__":
    unittest.main()
