import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_use_log", ROOT / "scripts/wiki_use_log.py")

def _rec(**kw):
    r = {"kind": "use-event", "date": "2026-10-21", "page": "wiki/syntheses/s.md",
         "use_kind": "synthesis", "sources": ["wiki/a.md", "wiki/b.md"],
         "supports": ["wiki/c.md"], "contradicts": [], "note": ""}
    r.update(kw); return r

class UseLogTests(unittest.TestCase):
    def test_seeded_log_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["events"], 0); self.assertEqual(rep["by_kind"]["synthesis"], 0)
    def test_use_kinds_closed_vocabulary(self):
        self.assertEqual(MOD.USE_KINDS, ["synthesis", "answer", "annotation"])
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--page", "wiki/syntheses/s.md", "--use-kind", "answer",
                           "--sources", "wiki/a.md,wiki/b.md", "--supports", "wiki/c.md",
                           "--register", str(p)])
            self.assertEqual(rc, 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, [])
            self.assertEqual(recs[0]["sources"], ["wiki/a.md", "wiki/b.md"])
            rep = MOD.build_report(p, root=ROOT)
            self.assertEqual(rep["by_kind"]["answer"], 1)
            self.assertEqual(rep["distinct_source_pages_used"], 2)
    def test_empty_sources_and_self_source_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(sources=[])) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("at least one source" in e for e in errs))
            p.write_text(json.dumps(_rec(sources=["wiki/syntheses/s.md"])) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("itself" in e for e in errs))
            self.assertEqual(MOD.main(["record", "--page", "wiki/x.md", "--use-kind", "answer",
                                       "--sources", "", "--register", str(p)]), 2)
    def test_supports_contradicts_conflict_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(supports=["wiki/c.md"], contradicts=["wiki/c.md"])) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("BOTH" in e for e in errs))
            self.assertEqual(MOD.main(["record", "--page", "wiki/x.md", "--use-kind", "synthesis",
                                       "--sources", "wiki/a.md", "--supports", "wiki/c.md",
                                       "--contradicts", "wiki/c.md", "--register", str(p)]), 2)
    def test_bad_kind_and_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(use_kind="Bogus")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("use_kind" in e for e in errs))
            self.assertEqual(MOD.main(["check", "--register", str(p)]), 1)
            good = Path(td) / "g.jsonl"; good.write_text(json.dumps(_rec()) + "\n")
            self.assertEqual(MOD.main(["check", "--register", str(good)]), 0)

if __name__ == "__main__":
    unittest.main()
