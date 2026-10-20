#!/usr/bin/env python3
"""Tests for scripts/wiki_verify_status.py (consolidated-queue
item 67: the verification-status register).

Pins, on a FIXTURE repo in a temp dir (the register seeded
with a bare header, the way the real one began):

  - set REFUSES a record with an empty --evidence (exit 1):
    a label with nothing under it is exactly what the
    register exists to prevent; it also refuses a bad
    --as-of and a register file that does not exist;
  - an unknown --status is rejected by the label vocabulary
    (argparse, exit 2);
  - set appends (history is never rewritten): two records
    for one subject leave both lines on disk, and list shows
    the LATEST as the current label;
  - check passes a fresh register, then flags a
    live-verified label once it ages past the 30-day window
    (re-verify or downgrade), flags a protocol-verified
    label past 90 days, and NEVER flags
    documented-but-unverified — it asserts nothing was
    checked, which does not go stale;
  - check's --json shape carries subjects + flags.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = "wiki_verify_status.py"
REGISTER = "evaluation/verification-status.jsonl"

HEADER = {"kind": "header", "register": "verification-status",
          "version": 1,
          "purpose": "fixture header (the standing rule lives "
                     "in the real register's header)"}


class StatusFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vstatus-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / TOOL, self.tmp / "scripts" / TOOL)
        (self.tmp / "evaluation").mkdir(parents=True)
        (self.tmp / REGISTER).write_text(
            json.dumps(HEADER) + "\n", encoding="utf-8")

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             "--root", str(self.tmp), *args],
            capture_output=True, text=True)

    def set_(self, subject, status, as_of, evidence="some run"):
        return self.run_tool(
            "set", subject, "--claim", f"claim about {subject}",
            "--status", status, "--evidence", evidence,
            "--as-of", as_of)

    def register_lines(self):
        return (self.tmp / REGISTER).read_text(
            encoding="utf-8").splitlines()


class TestSet(StatusFixture):
    def test_set_and_list_latest_wins(self):
        r = self.set_("lens", "protocol-verified", "2030-10-01")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.set_("lens", "live-verified", "2030-10-20",
                      evidence="opened the live site 2030-10-20")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.register_lines()), 3)
        r = self.run_tool("list")
        self.assertIn("live-verified", r.stdout)
        self.assertIn("2030-10-20", r.stdout)
        self.assertNotIn("protocol-verified", r.stdout)

    def test_set_refuses_empty_evidence(self):
        r = self.set_("lens", "live-verified", "2030-10-20",
                      evidence="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no record without evidence", r.stderr)
        self.assertEqual(len(self.register_lines()), 1)

    def test_set_refuses_missing_flag_and_bad_status(self):
        r = self.run_tool("set", "lens", "--claim", "c",
                          "--status", "live-verified",
                          "--as-of", "2030-10-20")
        self.assertEqual(r.returncode, 2)  # --evidence required
        r = self.run_tool("set", "lens", "--claim", "c",
                          "--status", "totally-verified",
                          "--evidence", "e",
                          "--as-of", "2030-10-20")
        self.assertEqual(r.returncode, 2)  # outside the vocabulary

    def test_set_refuses_bad_date(self):
        r = self.set_("lens", "live-verified", "20-10-2030")
        self.assertEqual(r.returncode, 1)
        self.assertIn("YYYY-MM-DD", r.stderr)

    def test_set_refuses_missing_register(self):
        (self.tmp / REGISTER).unlink()
        r = self.set_("lens", "live-verified", "2030-10-20")
        self.assertEqual(r.returncode, 1)
        self.assertIn("header must exist", r.stderr)


class TestCheck(StatusFixture):
    def test_fresh_register_passes(self):
        self.set_("lens", "live-verified", "2030-10-20")
        r = self.run_tool("check", "--today", "2030-10-25")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("0 flag(s)", r.stdout)

    def test_live_label_ages_out_at_30_days(self):
        self.set_("lens", "live-verified", "2030-10-20")
        r = self.run_tool("check", "--today", "2030-11-19")
        self.assertEqual(r.returncode, 0, r.stdout)   # exactly 30
        r = self.run_tool("check", "--today", "2030-11-20")
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE lens", r.stdout)
        self.assertIn("re-verify or downgrade", r.stdout)

    def test_protocol_window_is_90_days(self):
        self.set_("ask", "protocol-verified", "2030-10-20")
        r = self.run_tool("check", "--today", "2030-12-30")
        self.assertEqual(r.returncode, 0, r.stdout)   # 71 days
        r = self.run_tool("check", "--today", "2031-02-01")
        self.assertEqual(r.returncode, 1)             # 104 days

    def test_documented_never_goes_stale(self):
        self.set_("hosted", "documented-but-unverified",
                  "2030-10-20", evidence="not built; docs only")
        r = self.run_tool("check", "--today", "2032-01-01")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_check_json_shape(self):
        self.set_("lens", "live-verified", "2030-10-20")
        r = self.run_tool("check", "--today", "2030-12-01",
                          "--json")
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertEqual(data["subjects"], 1)
        self.assertEqual(data["flags"][0]["subject"], "lens")


if __name__ == "__main__":
    unittest.main()
