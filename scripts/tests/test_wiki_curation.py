import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_curation", ROOT / "scripts/wiki_curation.py")

def _rec(**kw):
    r = {"kind": "curation", "record_id": "w1", "recorded": "2026-10-21",
         "activity": "metadata creation", "structure": "at ingest, per source",
         "role": "compiler", "skills_needed": "citation discipline",
         "contradiction_or_problem": "metadata quality vs ingest volume",
         "solution_sought": "a lighter required field set",
         "workaround_applied": "record the gap on the page and compile on",
         "status": "in-use", "note": ""}
    r.update(kw); return r

class CurationTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["records"], 0); self.assertEqual(rep["workarounds"], [])
    def test_columns_are_the_study_structure(self):
        self.assertEqual(MOD.COLUMNS, ["activity", "structure", "role", "skills_needed",
                                       "contradiction_or_problem", "solution_sought",
                                       "workaround_applied"])
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--record-id", "w-1", "--activity", "ingest",
                           "--structure", "per batch", "--role", "compiler",
                           "--skills-needed", "triage", "--contradiction-or-problem",
                           "policy vs practice", "--solution-sought", "a ruling",
                           "--workaround-applied", "stage it and flag it",
                           "--status", "in-use", "--register", str(p)])
            self.assertEqual(rc, 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, [])
            self.assertEqual(recs[0]["workaround_applied"], "stage it and flag it")
            rep = MOD.build_report(p)
            self.assertEqual(rep["records"], 1)
            self.assertEqual(rep["by_activity"], {"ingest": 1})
            self.assertEqual(rep["by_status"]["in-use"], 1)
    def test_missing_column_and_empty_workaround_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; r = _rec(); del r["skills_needed"]
            p.write_text(json.dumps(r) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("skills_needed" in e for e in errs))
            p.write_text(json.dumps(_rec(workaround_applied="  ")) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("workaround_applied" in e for e in errs))
    def test_bad_status_and_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(status="Bogus")) + "\n" + json.dumps(_rec()) + "\n")
            _recs, errs = MOD.load_register(p)
            self.assertTrue(any("status" in e for e in errs))
            self.assertTrue(any("duplicate record_id" in e for e in errs))
    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "g.jsonl"; good.write_text(json.dumps(_rec()) + "\n")
            self.assertEqual(MOD.main(["check", "--register", str(good)]), 0)
            bad = Path(td) / "b.jsonl"; bad.write_text('{"kind":"curation"}\n')
            self.assertEqual(MOD.main(["check", "--register", str(bad)]), 1)
            self.assertEqual(MOD.main(["check", "--register", str(Path(td) / "nope.jsonl")]), 1)

if __name__ == "__main__":
    unittest.main()
