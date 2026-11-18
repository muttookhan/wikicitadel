"""Tests for scripts/wiki_citeproof_ledger.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_citeproof_ledger", SCRIPTS / "wiki_citeproof_ledger.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_all_seeded_bad_caught(self):
        led = MOD.build_ledger()
        self.assertEqual(led["false_cleans"], 0)
        self.assertEqual(led["catches"], led["seeded_bad"])
        self.assertEqual(led["controls_passed"], led["controls"])
        self.assertGreaterEqual(led["seeded_bad"], 3)
        self.assertGreaterEqual(led["controls"], 1)
    def test_check_passes(self):
        self.assertEqual(MOD.main(["check"]), 0)
    def test_fixture_kinds_present(self):
        import json
        fx = json.loads(MOD.FIXTURES.read_text())
        kinds = {f["kind"] for f in fx["fixtures"]}
        self.assertIn("fabricated-locator", kinds)
        self.assertIn("swapped-source", kinds)
        self.assertIn("one-word-altered-quote", kinds)

if __name__ == "__main__":
    unittest.main()
