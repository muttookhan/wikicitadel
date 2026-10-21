import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_citation_functions", ROOT / "scripts/wiki_citation_functions.py")

class CitationFunctionTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["labelled_records"], 0)
        self.assertEqual(set(rep["counts"].values()), {0})
    def test_frames_closed_vocabulary(self):
        self.assertEqual(MOD.FRAMES, ["Background", "Motivation", "Uses", "Extension", "Comparison-or-Contrast", "Future"])
    def test_record_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            rc = MOD.main(["record", "--citation-id", "c0001", "--page", "wiki/a.md", "--frame", "Uses", "--register", str(p)])
            self.assertEqual(rc, 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, []); self.assertEqual(recs[0]["frame"], "Uses")
    def test_bad_frame_rejected_in_register(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text('{"kind":"citation-function","citation_id":"c1","page":"wiki/a.md","frame":"Bogus","recorded":"2026-10-21"}\n')
            _r, errs = MOD.load_register(p); self.assertTrue(any("frame" in e for e in errs))

if __name__ == "__main__":
    unittest.main()
