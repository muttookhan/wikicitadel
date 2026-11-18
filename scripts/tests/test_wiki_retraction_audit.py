import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_retraction_audit", ROOT / "scripts/wiki_retraction_audit.py")

class RetractionTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
    def test_direct_and_indirect_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td); (r / "wiki").mkdir(); (r / "evaluation").mkdir()
            (r / "evaluation/citation-lockfile.json").write_text(json.dumps({"citations": [
                {"id": "c1", "page": "wiki/a.md", "source": "raw/x.md"},
                {"id": "c2", "page": "wiki/b.md", "source": "raw/y.md"}]}))
            (r / "wiki/a.md").write_text("---\ntitle: A\nsources: [raw/x.md]\n---\nbody")
            (r / "wiki/b.md").write_text("---\ntitle: B\nsources: [raw/y.md]\n---\nsee [[a]] and the withdrawn widget claim")
            (r / "wiki/c.md").write_text("---\ntitle: C\nsources: []\n---\nsee [[a]] only")
            rep = MOD.build_audit(r, "raw/x.md", ["widget"])
            self.assertEqual(rep["direct_count"], 1)
            self.assertEqual(rep["indirect_count"], 2)
            self.assertEqual(rep["indirect_promoted_count"], 1)
            self.assertEqual(rep["indirect"][0]["page"], "wiki/b.md")
    def test_check_rejects_bad_frame_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"withdrawal","source":"raw/x.md"}\n')
            _recs, errs = MOD.load_register(p); self.assertTrue(errs)

if __name__ == "__main__":
    unittest.main()
