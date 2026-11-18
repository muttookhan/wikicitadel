#!/usr/bin/env python3
"""Tests for the Lane 2 (stale) additions in
scripts/wiki_lint_lanes.py — owner attestations (verified_until)
and FSRS re-verification due findings (wave-3 set B). The pure
helpers are tested directly; the reverify findings are tested
against a fixture wiki by pointing the lanes' in-process
wiki_reverify module at it.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lanes = _load("wiki_lint_lanes")

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


class AttestationStateTests(unittest.TestCase):
    TODAY = date(2030, 10, 20)

    def test_no_attestation(self):
        self.assertEqual(lanes.attestation_state({}, self.TODAY),
                         (None, None))
        self.assertEqual(lanes.attestation_state(None, self.TODAY),
                         (None, None))
        self.assertEqual(
            lanes.attestation_state({"verified_until": ""}, self.TODAY),
            (None, None))

    def test_current_including_the_last_day(self):
        state, until = lanes.attestation_state(
            {"verified_until": "2031-01-20", "verified_by": "owner"},
            self.TODAY)
        self.assertEqual(state, "current")
        self.assertEqual(until, date(2031, 1, 20))
        state, _ = lanes.attestation_state(
            {"verified_until": "2030-10-20"}, self.TODAY)
        self.assertEqual(state, "current")

    def test_expired_the_day_after(self):
        state, until = lanes.attestation_state(
            {"verified_until": "2030-10-19", "verified_by": "owner"},
            self.TODAY)
        self.assertEqual(state, "expired")
        self.assertEqual(until, date(2030, 10, 19))

    def test_unparseable_date_is_invalid_not_silent(self):
        state, until = lanes.attestation_state(
            {"verified_until": "next spring"}, self.TODAY)
        self.assertEqual(state, "invalid")
        self.assertIsNone(until)

    def test_yaml_date_objects_parse(self):
        state, until = lanes.attestation_state(
            {"verified_until": date(2031, 1, 20)}, self.TODAY)
        self.assertEqual(state, "current")
        self.assertEqual(until, date(2031, 1, 20))


class ReverifyFindingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        page_dir = self.tmp / "wiki" / "concepts"
        page_dir.mkdir(parents=True)
        (page_dir / "claim-a.md").write_text(CLAIM_PAGE, encoding="utf-8")
        (page_dir / "claim-b.md").write_text(
            CLAIM_PAGE.replace("exactly 913 files", "exactly 12 files")
                      .replace("2030-10-13", "2030-10-19"),
            encoding="utf-8")
        (self.tmp / "evaluation").mkdir()
        self._saved = (lanes.reverify.ROOT, lanes.reverify.WIKI,
                       lanes.reverify.HISTORY)
        lanes.reverify.ROOT = self.tmp
        lanes.reverify.WIKI = self.tmp / "wiki"
        lanes.reverify.HISTORY = self.tmp / "evaluation" / "reverify-history.jsonl"

    def tearDown(self):
        (lanes.reverify.ROOT, lanes.reverify.WIKI,
         lanes.reverify.HISTORY) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_due_and_overdue_surface(self):
        rows = lanes.reverify_findings(date(2030, 10, 21))
        self.assertEqual([r["page"] for r in rows],
                         ["wiki/concepts/claim-a.md"])
        self.assertEqual(rows[0]["status"], "overdue")
        self.assertEqual(rows[0]["days_overdue"], 1)
        rows = lanes.reverify_findings(date(2030, 10, 20))
        self.assertEqual([r["page"] for r in rows],
                         ["wiki/concepts/claim-a.md"])
        self.assertEqual(rows[0]["status"], "due")

    def test_nothing_surfaces_before_any_due_date(self):
        self.assertEqual(lanes.reverify_findings(date(2030, 10, 19)), [])


if __name__ == "__main__":
    unittest.main()
