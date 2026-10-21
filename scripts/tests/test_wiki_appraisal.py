import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_appraisal", ROOT / "scripts/wiki_appraisal.py")

def _rec(**kw):
    r = {"kind": "appraisal", "batch_id": "b1", "batch_label": "",
         "contexts_compiled": "done", "value_assessed": "done",
         "authenticity_assessed": "pending", "feasibility_assessed": "done",
         "decision": "retain", "disposition": "kept-in-wiki",
         "keeping_motivation": "use", "appraiser": "",
         "recorded": "2026-10-21", "note": ""}
    r.update(kw); return r

class AppraisalTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["batches"], 0)
        self.assertEqual(rep["incomplete_batches"], [])
    def test_vocabularies_closed(self):
        self.assertEqual(MOD.ACTIVITIES, ["contexts_compiled", "value_assessed",
                                          "authenticity_assessed", "feasibility_assessed"])
        self.assertEqual(MOD.ACTIVITY_STATES, ["done", "pending", "not-applicable"])
        self.assertIn("retain", MOD.DECISIONS); self.assertIn("dispose", MOD.DECISIONS)
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--batch-id", "2026-10-21-x", "--contexts-compiled", "done",
                           "--value-assessed", "done", "--authenticity-assessed", "done",
                           "--feasibility-assessed", "pending", "--decision", "retain",
                           "--disposition", "kept-in-wiki", "--keeping-motivation", "legacy",
                           "--register", str(p)])
            self.assertEqual(rc, 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, [])
            self.assertEqual(recs[0]["decision"], "retain")
            self.assertEqual(recs[0]["keeping_motivation"], "legacy")
            rep = MOD.build_report(p)
            self.assertEqual(rep["batches"], 1)
            self.assertEqual(rep["incomplete_batches"][0]["pending"], ["feasibility_assessed"])
    def test_authenticity_is_a_separate_required_field(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; r = _rec(); del r["authenticity_assessed"]
            p.write_text(json.dumps(r) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("authenticity_assessed" in e for e in errs))
    def test_bad_decision_and_duplicate_batch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(decision="Bogus")) + "\n" + json.dumps(_rec()) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("decision" in e for e in errs))
            self.assertTrue(any("duplicate batch_id" in e for e in errs))
    def test_keeping_motivation_vocabulary_closed(self):
        self.assertEqual(MOD.MOTIVATIONS, ["use", "nostalgia", "vigilance",
                                           "fear-of-loss", "legacy"])
    def test_keeping_motivation_counted_alongside_decision(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(keeping_motivation="fear-of-loss")) + "\n")
            rep = MOD.build_report(p)
            self.assertEqual(rep["by_decision"]["retain"], 1)
            self.assertEqual(rep["by_keeping_motivation"]["fear-of-loss"], 1)
            self.assertEqual(rep["by_keeping_motivation"]["unrecorded"], 0)
    def test_bad_keeping_motivation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(keeping_motivation="Bogus")) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("keeping_motivation" in e for e in errs))
    def test_legacy_line_without_motivation_stays_valid_unrecorded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; r = _rec(); del r["keeping_motivation"]
            p.write_text(json.dumps(r) + "\n")
            recs, errs = MOD.load_register(p)
            self.assertEqual(errs, []); self.assertEqual(len(recs), 1)
            rep = MOD.build_report(p)
            self.assertEqual(rep["by_keeping_motivation"]["unrecorded"], 1)
    def test_seeded_register_still_valid_empty_after_extension(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["by_keeping_motivation"]["unrecorded"], 0)
    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "g.jsonl"; good.write_text(json.dumps(_rec()) + "\n")
            self.assertEqual(MOD.main(["check", "--register", str(good)]), 0)
            bad = Path(td) / "b.jsonl"; bad.write_text('{"kind":"appraisal"}\n')
            self.assertEqual(MOD.main(["check", "--register", str(bad)]), 1)
            self.assertEqual(MOD.main(["check", "--register", str(Path(td) / "nope.jsonl")]), 1)

if __name__ == "__main__":
    unittest.main()
