"""Tests for scripts/wiki_bolognese_trial.py (Marathon R10 lane BB)."""
import importlib.util, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_bolognese_trial", SCRIPTS / "wiki_bolognese_trial.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def test_missing_executable_is_door_failure(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / "ev.json"
            rec = Path(td) / "r.bib"
            rec.write_text("@article{x, title={T}}")
            rc = MOD.main(["run", "--records", str(rec),
                           "--out-dir", td, "--evidence", str(ev),
                           "--bolognese", "/nonexistent/bolognese"])
            # shutil.which fallback: explicit nonexistent path is
            # used verbatim only if truthy; main prefers the flag,
            # so a missing file surfaces as door failure at convert
            # or obtain — either way rc 2 and ran False.
            self.assertEqual(rc, 2)
            self.assertFalse(json.loads(ev.read_text())["ran"])

if __name__ == "__main__":
    unittest.main()
