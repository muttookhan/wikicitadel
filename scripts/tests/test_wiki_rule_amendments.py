"""Tests for scripts/wiki_rule_amendments.py (Marathon R3 TB5 row 2,
Newsroom meta loop): a failure pattern recurs only at the threshold;
the drafted proposal is marked draft + manual-only adoption and is
never written on a dry run. Run:
python3 -m unittest scripts.tests.test_wiki_rule_amendments
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_rule_amendments as wra  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="amend-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.filings = self.root / "filings"
        self.filings.mkdir()
        (self.filings / "lint-1.md").write_text(
            "# Lint\n\n- failure: stale-tended — page A\n"
            "- failure: stale-tended — page B\n"
            "- failure: orphan-link — page C\n", encoding="utf-8")
        (self.filings / "lint-2.md").write_text(
            "# Lint 2\n\n- failure: stale-tended — page D\n",
            encoding="utf-8")


class ScanTests(Fixture):
    def test_scan_counts_patterns(self):
        result = wra.scan(self.filings)
        self.assertEqual(result["stale-tended"]["count"], 3)
        self.assertEqual(result["orphan-link"]["count"], 1)
        self.assertEqual(len(result["stale-tended"]["files"]), 2)

    def test_threshold_gates_recurrence(self):
        rec = wra.recurring(wra.scan(self.filings), threshold=3)
        self.assertIn("stale-tended", rec)
        self.assertNotIn("orphan-link", rec)

    def test_draft_is_marked_proposal_only(self):
        info = wra.scan(self.filings)["stale-tended"]
        text = wra.draft_text("stale-tended", info, "2026-10-21")
        self.assertIn("status: draft-proposal", text)
        self.assertIn("adoption: manual-only", text)
        self.assertIn("Nothing here is in force", text)

    def test_cli_dry_run_writes_nothing(self):
        out = self.root / "out"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "wiki_rule_amendments.py"),
             "--filings-dir", str(self.filings), "--out-dir", str(out),
             "--dry-run"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["recurring"], {"stale-tended": 3})
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
