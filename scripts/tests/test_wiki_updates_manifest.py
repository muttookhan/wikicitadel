"""Tests for scripts/wiki_updates_manifest.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_updates_manifest", SCRIPTS / "wiki_updates_manifest.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_manifest_byte_stable_and_checks(self):
        self.assertEqual(MOD.render(MOD.build_manifest()),
                         MOD.render(MOD.build_manifest()))
        self.assertEqual(MOD.main(["check"]), 0)
    def test_updates_shape(self):
        m = MOD.build_manifest()
        for u in m["updates"]:
            self.assertIn(u["status"], ("corrected", "superseded"))
            self.assertTrue(u["page"])
            self.assertTrue(u["by_record"])
    def test_absent_register_reported_not_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(MOD.treatment_updates(Path(td) / "nope.jsonl"))

if __name__ == "__main__":
    unittest.main()
