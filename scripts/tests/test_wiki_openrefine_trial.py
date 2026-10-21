"""Tests for scripts/wiki_openrefine_trial.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_openrefine_trial", SCRIPTS / "wiki_openrefine_trial.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_missing_binary_is_door_failure(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / "ev.json"
            rc = MOD.main(["run", "--refine", "/nonexistent/refine",
                           "--input", "/nonexistent/in.csv",
                           "--operations", "/nonexistent/ops.json",
                           "--work", td, "--evidence", str(ev)])
            self.assertEqual(rc, 2)
            d = json.loads(ev.read_text())
            self.assertFalse(d["ran"])
            self.assertIn("door_failure", d)

if __name__ == "__main__":
    unittest.main()
