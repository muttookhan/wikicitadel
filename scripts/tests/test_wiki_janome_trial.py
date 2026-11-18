"""Tests for scripts/wiki_janome_trial.py (Marathon R13 lane BA)."""
import importlib.util, json, stat, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_janome_trial", SCRIPTS / "wiki_janome_trial.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

def fake_python(td, payload):
    p = Path(td) / "fakepy"
    p.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(payload, ensure_ascii=False) + "\nJSON\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p

class T(unittest.TestCase):
    def test_missing_interpreter_is_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "s.txt"; s.write_text("こんにちは", encoding="utf-8")
            ev, res = Path(td) / "ev.json", Path(td) / "r.json"
            rc = MOD.main(["run", "--sample", str(s), "--python", "/nonexistent/py",
                           "--result", str(res), "--evidence", str(ev)])
            self.assertEqual(rc, 2)
            d = json.loads(ev.read_text())
            self.assertFalse(d["ran"])
            self.assertEqual(d["door_failure"]["stage"], "obtain")
            self.assertEqual(d["library"], "janome")
            self.assertEqual(d["licence"], "Apache-2.0")

    def test_runner_output_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "s.txt"; s.write_text("知識を整理する", encoding="utf-8")
            py = fake_python(td, {"tool_version": "0.5.0",
                                  "tokens": [{"surface": "知識", "part_of_speech": "名詞"}],
                                  "token_count": 1})
            ev, res = Path(td) / "ev.json", Path(td) / "r.json"
            rc = MOD.main(["run", "--sample", str(s), "--python", str(py),
                           "--result", str(res), "--evidence", str(ev)])
            self.assertEqual(rc, 0)
            d = json.loads(ev.read_text())
            self.assertTrue(d["ran"]); self.assertEqual(d["token_count"], 1)
            self.assertEqual(d["tool_version"], "0.5.0")
            self.assertTrue(Path(res).is_file())

    def test_failing_runner_is_run_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "s.txt"; s.write_text("x", encoding="utf-8")
            py = Path(td) / "badpy"
            py.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
            py.chmod(py.stat().st_mode | stat.S_IEXEC)
            ev, res = Path(td) / "ev.json", Path(td) / "r.json"
            rc = MOD.main(["run", "--sample", str(s), "--python", str(py),
                           "--result", str(res), "--evidence", str(ev)])
            self.assertEqual(rc, 2)
            d = json.loads(ev.read_text())
            self.assertFalse(d["ran"])
            self.assertEqual(d["door_failure"]["stage"], "run")
            self.assertIn("boom", d["door_failure"]["error"])

if __name__ == "__main__":
    unittest.main()
