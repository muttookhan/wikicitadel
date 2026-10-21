import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_relation_register", ROOT / "scripts/wiki_relation_register.py")

def _rec(**kw):
    r = {"kind": "relation", "subject": "wiki/a.md", "predicate": "part-of",
         "object": "wiki/b.md", "recorded": "2026-10-21", "note": ""}
    r.update(kw); return r

class RelationRegisterTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["relations"], 0); self.assertEqual(rep["dangling_endpoints"], [])
    def test_predicates_closed_vocabulary(self):
        self.assertEqual(MOD.PREDICATES, ["part-of", "has-part", "superseded-by",
                                          "supersedes", "created-in-context-of", "derived-from"])
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--subject", "wiki/a.md", "--predicate", "superseded-by",
                           "--object", "wiki/b.md", "--register", str(p)])
            self.assertEqual(rc, 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, [])
            self.assertEqual(recs[0]["predicate"], "superseded-by")
    def test_bad_predicate_and_self_relation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(predicate="Bogus")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("predicate" in e for e in errs))
            p.write_text(json.dumps(_rec(object="wiki/a.md")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("differ" in e for e in errs))
            self.assertEqual(MOD.main(["record", "--subject", "wiki/a.md", "--predicate", "part-of",
                                       "--object", "wiki/a.md", "--register", str(p)]), 2)
    def test_dangling_reported_not_enforced_and_inverse_noted(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text(json.dumps(_rec()) + "\n")
            rep = MOD.build_report(p, root=td)
            self.assertEqual(len(rep["dangling_endpoints"]), 2)
            self.assertEqual(rep["missing_inverse"][0]["inverse_not_recorded"], "has-part")
            # the register itself still checks valid: dangling is report-only
            self.assertEqual(MOD.main(["check", "--register", str(p)]), 0)
    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "b.jsonl"; bad.write_text('{"kind":"relation"}\n')
            self.assertEqual(MOD.main(["check", "--register", str(bad)]), 1)

if __name__ == "__main__":
    unittest.main()
