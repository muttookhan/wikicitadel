"""Tests for scripts/wiki_citeindex_gate.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_citeindex_gate", SCRIPTS / "wiki_citeindex_gate.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_catalog_change_detection(self):
        old = {"collections": [{"name": "a", "licence": "MIT",
                                "file_count": 1}]}
        new = {"collections": [{"name": "a", "licence": "GPL",
                                "file_count": 1}]}
        ch = MOD.catalog_changes(old, new)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["field"], "licence")
    def test_evidence_matching(self):
        ch = {"source": "a", "field": "licence"}
        ev = [{"source": "a", "field": "licence", "quote": "q",
               "locator": "f#L1-L2", "date": "2026-01-01"}]
        self.assertFalse(MOD.lacks_evidence(ch, ev))
        self.assertTrue(MOD.lacks_evidence(ch, []))
    def test_shape_is_data(self):
        for k in ("source", "field", "quote", "locator", "date"):
            self.assertIn(k, MOD.EVIDENCE_ENTRY_SHAPE)
    def test_real_report_runs(self):
        rep = MOD.build_report(MOD.ROOT, [])
        self.assertTrue(rep["report_only"])
        self.assertEqual(rep["lacking_count"],
                         len(rep["changes_lacking_evidence"]))

if __name__ == "__main__":
    unittest.main()
