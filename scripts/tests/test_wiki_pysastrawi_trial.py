"""Tests for scripts/wiki_pysastrawi_trial.py (Marathon R11 lane BB)."""
import importlib.util, json, stat, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_pysastrawi_trial", SCRIPTS / "wiki_pysastrawi_trial.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

def fake_python(td, payload):
    p = Path(td) / "fakepy"
    p.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(payload) + "\nJSON\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p

class T(unittest.TestCase):
    def test_missing_interpreter_is_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "s.txt"; s.write_text("menonton")
            ev, res = Path(td) / "ev.json", Path(td) / "r.json"
            rc = MOD.main(["run", "--sample", str(s), "--python", "/nonexistent/py",
                           "--result", str(res), "--evidence", str(ev)])
            self.assertEqual(rc, 2)
            d = json.loads(ev.read_text())
            self.assertFalse(d["ran"])
            self.assertIn("CC-BY-NC-SA", d["licence_dictionary"])

    def test_runner_output_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "s.txt"; s.write_text("Mereka menonton.")
            py = fake_python(td, {"stemmed": "mereka tonton", "word_map": {"menonton": "tonton"}})
            ev, res = Path(td) / "ev.json", Path(td) / "r.json"
            rc = MOD.main(["run", "--sample", str(s), "--python", str(py),
                           "--result", str(res), "--evidence", str(ev)])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(ev.read_text())["ran"])

if __name__ == "__main__":
    unittest.main()
