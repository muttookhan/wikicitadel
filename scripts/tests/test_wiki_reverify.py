#!/usr/bin/env python3
"""Tests for scripts/wiki_reverify.py — per-claim
re-verification scheduling (FSRS-inspired). The scheduler math
is tested as pure functions; the CLI is driven against a
fixture wiki in a temp dir (the real scripts copied in, so
ROOT resolves to the fixture).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _load_reverify():
    spec = importlib.util.spec_from_file_location(
        "wiki_reverify", SCRIPTS / "wiki_reverify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rv = _load_reverify()

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

PLAIN_PAGE = """---
title: Plain
type: concept
created: 2030-10-13
updated: 2030-10-13
sources: []
tags: [x]
---

Hi.
"""


def ev(day, outcome):
    return {"claim": "wiki/concepts/claim-a.md", "date": day,
            "outcome": outcome, "note": "", "source": "manual"}


class SchedulerMathTests(unittest.TestCase):
    FIELDS = {"claim": "x", "as_of": "2030-10-13"}

    def test_no_history_anchors_at_as_of_with_start_values(self):
        d, s = rv.fold_history([])
        self.assertEqual((d, s), (rv.D_START, rv.S_START))
        sched = rv.claim_schedule(self.FIELDS, [], date(2030, 10, 20))
        self.assertEqual(sched["due"], date(2030, 10, 20))
        self.assertEqual(sched["status"], "due")
        self.assertIsNone(sched["last_verified"])
        # At the due date the forgetting curve is at the target.
        self.assertAlmostEqual(sched["retrievability"], 0.90, places=6)

    def test_pass_lengthens_the_interval(self):
        one = rv.claim_schedule(self.FIELDS, [ev("2030-10-14", "pass")],
                                date(2030, 10, 14))
        self.assertEqual(one["due"], date(2030, 10, 25))  # +11d
        two = rv.claim_schedule(
            self.FIELDS,
            [ev("2030-10-14", "pass"), ev("2030-10-25", "pass")],
            date(2030, 10, 25))
        self.assertGreater(two["stability"], one["stability"])
        self.assertEqual(two["due"], date(2030, 11, 13))  # +19d
        self.assertGreater((two["due"] - date(2030, 10, 25)).days,
                           (one["due"] - date(2030, 10, 14)).days)

    def test_fail_shortens_the_interval(self):
        failed = rv.claim_schedule(self.FIELDS, [ev("2030-10-14", "fail")],
                                   date(2030, 10, 14))
        self.assertAlmostEqual(failed["stability"], 2.1)
        self.assertEqual(failed["due"], date(2030, 10, 16))  # +2d
        passed = rv.claim_schedule(self.FIELDS, [ev("2030-10-14", "pass")],
                                   date(2030, 10, 14))
        lapsed = rv.claim_schedule(
            self.FIELDS,
            [ev("2030-10-14", "pass"), ev("2030-10-25", "fail")],
            date(2030, 10, 25))
        self.assertLess(lapsed["stability"], passed["stability"])
        self.assertEqual(lapsed["due"], date(2030, 10, 28))  # +3d

    def test_changed_shortens_moderately(self):
        changed = rv.claim_schedule(
            self.FIELDS, [ev("2030-10-14", "changed")], date(2030, 10, 14))
        self.assertAlmostEqual(changed["stability"], 4.9)
        self.assertEqual(changed["due"], date(2030, 10, 19))  # +5d

    def test_difficulty_moves_with_outcomes(self):
        d, _s = rv.fold_history([ev("2030-10-14", "pass")])
        self.assertAlmostEqual(d, 4.7)
        d, _s = rv.fold_history([ev("2030-10-14", "fail")])
        self.assertAlmostEqual(d, 5.8)
        d, _s = rv.fold_history([ev("2030-10-14", "changed")])
        self.assertAlmostEqual(d, 5.4)
        # Difficulty is clamped to [1, 10] over long streaks.
        d, _s = rv.fold_history([ev("2030-10-14", "fail")] * 20)
        self.assertEqual(d, 10.0)
        d, _s = rv.fold_history([ev("2030-10-14", "pass")] * 40)
        self.assertEqual(d, 1.0)

    def test_overdue_status_and_days(self):
        sched = rv.claim_schedule(self.FIELDS, [], date(2030, 11, 1))
        self.assertEqual(sched["status"], "overdue")
        self.assertEqual(sched["days_overdue"], 12)

    def test_events_fold_in_date_order_not_log_order(self):
        shuffled = [ev("2030-10-25", "pass"), ev("2030-10-14", "pass")]
        ordered = [ev("2030-10-14", "pass"), ev("2030-10-25", "pass")]
        self.assertEqual(rv.fold_history(shuffled), rv.fold_history(ordered))


class FixtureWikiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_reverify.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        page_dir = self.tmp / "wiki" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "claim-a.md").write_text(CLAIM_PAGE, encoding="utf-8")
        (page_dir / "plain.md").write_text(PLAIN_PAGE, encoding="utf-8")
        (self.tmp / "evaluation").mkdir()
        # An in-process handle on the fixture copy for seeding.
        spec = importlib.util.spec_from_file_location(
            "wiki_reverify_fixture", self.tmp / "scripts" / "wiki_reverify.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "wiki_reverify.py"),
             *argv], capture_output=True, text=True)

    def history(self):
        path = self.tmp / "evaluation" / "reverify-history.jsonl"
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_record_appends_and_reschedules(self):
        out = self.run_cli("record", "--page", "wiki/concepts/claim-a.md",
                           "--outcome", "pass", "--date", "2030-10-14")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("next due: 2030-10-25", out.stdout)
        recs = self.history()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["outcome"], "pass")
        self.assertEqual(recs[0]["source"], "manual")

    def test_record_on_non_claim_page_refused(self):
        out = self.run_cli("record", "--page", "wiki/concepts/plain.md",
                           "--outcome", "pass", "--date", "2030-10-14")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.history(), [])

    def test_seed_from_outcomes_is_idempotent(self):
        outcomes = self.tmp / "evaluation" / "outcomes.jsonl"
        outcomes.write_text(
            json.dumps({"page": "wiki/concepts/claim-a.md",
                        "date": "2030-10-15", "outcome": "supports",
                        "note": "held"}) + "\n" +
            json.dumps({"page": "wiki/concepts/claim-a.md",
                        "date": "2030-10-16", "outcome": "contradicts",
                        "note": "moved"}) + "\n", encoding="utf-8")
        self.mod.cmd_seed(argparse.Namespace())
        self.mod.cmd_seed(argparse.Namespace())
        recs = self.history()
        self.assertEqual(len(recs), 2)
        self.assertEqual([r["outcome"] for r in recs], ["pass", "fail"])
        self.assertTrue(all(r["source"] == "seed:outcomes.jsonl"
                            for r in recs))

    def test_due_lists_overdue_first(self):
        (self.tmp / "wiki" / "concepts" / "claim-b.md").write_text(
            CLAIM_PAGE.replace("exactly 913 files", "exactly 12 files")
                      .replace("2030-10-13", "2030-10-19"),
            encoding="utf-8")
        out = self.run_cli("due", "--today", "2030-10-21", "--json")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        rows = json.loads(out.stdout)
        self.assertEqual([r["page"] for r in rows],
                         ["wiki/concepts/claim-a.md",
                          "wiki/concepts/claim-b.md"])
        self.assertEqual(rows[0]["status"], "overdue")
        self.assertEqual(rows[1]["status"], "upcoming")


if __name__ == "__main__":
    unittest.main()
