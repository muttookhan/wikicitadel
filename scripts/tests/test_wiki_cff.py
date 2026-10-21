"""Tests for scripts/wiki_cff.py (Marathon R9 lane BB).

Pins the owner boundary: the generator never emits authors;
validate() reports the omission as the owner-gated finding.
"""
import importlib.util
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
def load():
    s = importlib.util.spec_from_file_location("wiki_cff", SCRIPTS / "wiki_cff.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()
class CffTests(unittest.TestCase):
    def test_generated_shape_and_no_authors(self):
        text = MOD.generate_cff(ROOT)
        self.assertIn("cff-version: 1.2.0", text)
        self.assertNotIn("authors:", text)
        self.assertNotIn("preferred-citation", text)
        keys = MOD.parse_cff(text)
        self.assertEqual(keys["cff-version"], "1.2.0")
        self.assertIn("title", keys)
    def test_validate_reports_owner_gated_authors(self):
        rep = MOD.validate_cff(MOD.generate_cff(ROOT))
        self.assertFalse(rep["valid"])
        self.assertTrue(any("authors" in f and "OWNER-GATED" in f
                            for f in rep["findings"]))
    def test_validate_passes_complete_record(self):
        text = ("cff-version: 1.2.0\nmessage: \"x\"\ntitle: T\n"
                "type: software\nauthors:\n  - family-names: Doe\n")
        rep = MOD.validate_cff(text)
        self.assertTrue(rep["valid"], rep)
if __name__ == "__main__":
    unittest.main()
