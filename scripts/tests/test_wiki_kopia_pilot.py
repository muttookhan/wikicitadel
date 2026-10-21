"""Tests for scripts/wiki_kopia_pilot.py (Marathon R9 lane BB).

The live snapshot/restore test runs only when a kopia binary
is explicitly supplied via KOPIA_BIN or found on PATH; in CI
without kopia it skips — the pilot evidence for this lane's
own run is recorded in evaluation/kopia-pilot-evidence.json.
"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_kopia_pilot", SCRIPTS / "wiki_kopia_pilot.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()
class KopiaPilotTests(unittest.TestCase):
    def test_refuses_own_repo_root(self):
        ev, code = MOD.pilot(MOD.ROOT, Path(tempfile.mkdtemp()))
        self.assertEqual(code, 2)
        self.assertIn("COPY", ev["error"])
    def test_missing_binary_is_a_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "copy"; src.mkdir()
            (src / "a.md").write_text("x\n", encoding="utf-8")
            ev, code = MOD.pilot(src, Path(td) / "work", kopia="/nonexistent/kopia")
            # shutil.which is bypassed only when binary exists;
            # a bogus explicit path surfaces as a failed step.
            self.assertIn(code, (1, 2))
            self.assertFalse(ev["verified"])
    def test_hash_tree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); (base / "a.txt").write_text("hello", encoding="utf-8")
            h = MOD.sha256_tree(base)
            self.assertEqual(list(h), ["a.txt"])
    @unittest.skipUnless(os.environ.get("KOPIA_BIN") or shutil.which("kopia"),
                         "no kopia binary available")
    def test_live_snapshot_restore_verify(self):
        binary = os.environ.get("KOPIA_BIN") or shutil.which("kopia")
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "wikicopy"; src.mkdir()
            (src / "page.md").write_text("# Hi\n", encoding="utf-8")
            ev, code = MOD.pilot(src, Path(td) / "work", kopia=binary)
            self.assertEqual(code, 0, ev)
            self.assertTrue(ev["verified"])
            self.assertTrue(ev["hashes_match"])
if __name__ == "__main__":
    unittest.main()
