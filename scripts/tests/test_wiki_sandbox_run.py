#!/usr/bin/env python3
"""Tests for scripts/wiki_sandbox_run.py (E2B pattern, TB8 row 3).

Pins: a clean script runs and reports no violations; the child
environment is scrubbed (a parent secret is invisible); a script
that overruns the timeout is killed and the overrun is a named
violation; a non-zero exit is a violation; relative writes land
in the temp cwd and are reported as produced_files; the report
states the sandbox's limits on its face (network isolation is
reported, never overstated).

Fixture scripts are written into temp dirs; no network use.
Run:  python3 -m unittest discover -s scripts/tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_sandbox_run  # noqa: E402

import os  # noqa: E402
import tempfile  # noqa: E402


def write_script(td, name, body):
    p = Path(td) / name
    p.write_text(body, encoding="utf-8")
    return p


class TestSandboxRun(unittest.TestCase):
    def test_clean_script(self):
        with tempfile.TemporaryDirectory() as td:
            s = write_script(td, "ok.py", "print('hello sandbox')\n")
            r = wiki_sandbox_run.run_sandboxed(s, timeout=10)
        self.assertEqual(r["violations"], [])
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("hello sandbox", r["stdout"])

    def test_env_scrubbed(self):
        os.environ["SANDBOX_TEST_SECRET"] = "should-not-leak"
        try:
            with tempfile.TemporaryDirectory() as td:
                s = write_script(
                    td, "env.py",
                    "import os\n"
                    "print('SECRET=' + os.environ.get("
                    "'SANDBOX_TEST_SECRET', 'ABSENT'))\n"
                    "print('FLAG=' + os.environ.get('SANDBOX', ''))\n")
                r = wiki_sandbox_run.run_sandboxed(s, timeout=10)
        finally:
            del os.environ["SANDBOX_TEST_SECRET"]
        self.assertIn("SECRET=ABSENT", r["stdout"])
        self.assertIn("FLAG=1", r["stdout"])

    def test_timeout_is_violation(self):
        with tempfile.TemporaryDirectory() as td:
            s = write_script(td, "slow.py",
                             "import time\ntime.sleep(30)\n")
            r = wiki_sandbox_run.run_sandboxed(s, timeout=2)
        self.assertTrue(r["timed_out"])
        self.assertTrue(any("timeout" in v
                            for v in r["violations"]))

    def test_nonzero_exit_is_violation(self):
        with tempfile.TemporaryDirectory() as td:
            s = write_script(td, "bad.py",
                             "import sys\nsys.exit(4)\n")
            r = wiki_sandbox_run.run_sandboxed(s, timeout=10)
        self.assertEqual(r["exit_code"], 4)
        self.assertTrue(any("non-zero" in v
                            for v in r["violations"]))

    def test_relative_write_confined_and_reported(self):
        with tempfile.TemporaryDirectory() as td:
            s = write_script(
                td, "w.py",
                "open('out.txt', 'w').write('data')\n")
            r = wiki_sandbox_run.run_sandboxed(s, timeout=10)
            self.assertEqual(r["produced_files"], ["out.txt"])
            self.assertFalse((Path(td) / "out.txt").exists())

    def test_limits_stated_on_face(self):
        with tempfile.TemporaryDirectory() as td:
            s = write_script(td, "ok.py", "pass\n")
            r = wiki_sandbox_run.run_sandboxed(s, timeout=10)
        self.assertIn(r["constraints"]["network_isolation"],
                      ("none", "unshare-n"))
        self.assertTrue(any("NOT a security boundary" in lim
                            or "not a security boundary" in lim
                            for lim in r["limits"]))


if __name__ == "__main__":
    unittest.main()
