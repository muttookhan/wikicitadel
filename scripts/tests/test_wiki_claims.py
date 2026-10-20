#!/usr/bin/env python3
"""Tests for scripts/wiki_claims.py — the outcome-verified claim
lifecycle. Builds a fixture wiki in a temp dir (the real scripts
copied in, so ROOT resolves to the fixture) and drives the CLI.

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

CLAIM_PAGE = """---
title: Fixture claim
type: concept
created: 2030-10-13
updated: 2030-10-13
sources: []
tags: [fixture]
claim: "The fixture corpus holds exactly 913 files."
as_of: 2030-10-13
---

Body text.
"""


class ClaimLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_claims.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        page_dir = self.tmp / "wiki" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "claim-a.md").write_text(CLAIM_PAGE, encoding="utf-8")
        (self.tmp / "evaluation").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "wiki_claims.py"), *argv],
            capture_output=True, text=True)

    def measure(self, outcome, day):
        return self.run_cli("measure", "--page", "wiki/concepts/claim-a.md",
                            "--outcome", outcome, "--date", day,
                            "--note", "fixture outcome")

    def page_text(self):
        return (self.tmp / "wiki" / "concepts" / "claim-a.md").read_text()

    def test_check_clean_with_no_outcomes(self):
        out = self.run_cli("check")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("candidate", out.stdout)

    def test_three_supports_make_a_rule(self):
        for day in ("2030-10-14", "2030-10-15", "2030-10-16"):
            r = self.measure("supports", day)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.run_cli("check")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("rule", out.stdout)
        text = self.page_text()
        self.assertIn("outcome_n: 3", text)
        self.assertIn("outcome_status: rule", text)

    def test_three_contradictions_retire_never_delete(self):
        for day in ("2030-10-14", "2030-10-15", "2030-10-16"):
            self.measure("contradicts", day)
        out = self.run_cli("check")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("retired", out.stdout)
        self.assertTrue((self.tmp / "wiki" / "concepts" / "claim-a.md").exists())

    def test_tampered_counter_fails_check(self):
        self.measure("supports", "2030-10-14")
        text = self.page_text().replace("outcome_n: 1", "outcome_n: 9")
        (self.tmp / "wiki" / "concepts" / "claim-a.md").write_text(text)
        out = self.run_cli("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("outcomes log implies", out.stdout)

    def test_measure_on_non_claim_page_refused(self):
        plain = self.tmp / "wiki" / "concepts" / "plain.md"
        plain.write_text("---\ntitle: Plain\ntype: concept\ncreated: 2030-10-13\n"
                          "updated: 2030-10-13\nsources: []\ntags: [x]\n---\n\nHi.\n")
        out = self.run_cli("measure", "--page", "wiki/concepts/plain.md",
                           "--outcome", "supports", "--date", "2030-10-14")
        self.assertEqual(out.returncode, 1)
        self.assertFalse((self.tmp / "evaluation" / "outcomes.jsonl").exists())

    def test_outcomes_log_is_append_only_jsonl(self):
        self.measure("supports", "2030-10-14")
        self.measure("contradicts", "2030-10-15")
        lines = (self.tmp / "evaluation" / "outcomes.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        recs = [json.loads(l) for l in lines]
        self.assertEqual([r["outcome"] for r in recs], ["supports", "contradicts"])
        self.assertTrue(all(r["page"] == "wiki/concepts/claim-a.md" for r in recs))


if __name__ == "__main__":
    unittest.main()
