"""Tests for scripts/wiki_csl_export.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_csl_export", SCRIPTS / "wiki_csl_export.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_render_is_byte_stable(self):
        e = MOD.build_export()
        self.assertEqual(MOD.render(e), MOD.render(MOD.build_export()))
    def test_check_passes_on_generated(self):
        self.assertEqual(MOD.main(["check"]), 0)
    def test_entries_carry_no_invented_fields(self):
        for e in MOD.build_export():
            self.assertIn("id", e)
            self.assertEqual(e["type"], "document")
            self.assertLessEqual(set(e), {"id", "type", "note",
                "title", "author", "issued"})

if __name__ == "__main__":
    unittest.main()
