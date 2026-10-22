#!/usr/bin/env python3
"""Tests for scripts/wiki_review_state.py (Wave 5 —
review-state frontmatter + Review Center).

Fixture corpus with a fixed today (2026-10-22) so every
expected state is arithmetic:

  concepts/plain.md               no review fields
                                  -> undeclared
  concepts/declared-unreviewed.md review_state: unreviewed
  concepts/in-review.md           review_state: in-review
  concepts/reviewed-current.md    reviewed 2026-10-15,
                                  tended before -> current
  concepts/reviewed-stale-change.md reviewed 2026-10-15,
                                  tended 2026-10-20 after
                                  -> stale (changed)
  concepts/reviewed-stale-due.md  reviewed 2026-10-15,
                                  review_due 2026-10-20
                                  -> stale (due-passed, 2d)
  syntheses/reviewed-stale-cadence.md synthesis (30d
                                  PROPOSED cadence),
                                  reviewed 2026-08-01
                                  -> stale (cadence, due
                                  2026-08-31, 52d overdue)
  concepts/reviewed-no-date.md    reviewed, no reviewed_on
                                  -> unverifiable + finding
  concepts/reviewed-no-by.md      reviewed, no reviewed_by
                                  -> unverifiable + finding
  concepts/reviewed-future.md     reviewed_on 2026-12-01
                                  -> finding, unverifiable
  concepts/reviewed-bad-due.md    valid review, review_due
                                  "soon" -> current +
                                  review-due-unparseable
  concepts/bad-state.md           review_state: done
                                  -> unknown-review-state
  concepts/fields-no-state.md     reviewed_on, no state
                                  -> review-fields-without-
                                  state, undeclared
  concepts/retired.md             status: tombstoned
                                  -> out of the population
  syntheses/claim-page.md         claim as_of 2026-10-01
                                  -> queued reverify-
                                  overdue; the Center
                                  annotates the claim

Run:  python3 -m unittest scripts.tests.test_wiki_review_state
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "wiki_review_state", SCRIPTS / "wiki_review_state.py")
rs = importlib.util.module_from_spec(spec)
sys.modules["wiki_review_state"] = rs
spec.loader.exec_module(rs)

TODAY = date(2026, 10, 22)


def page(title, ptype, extra="", body="Body.\n"):
    fm = (f"---\ntitle: {title}\ntype: {ptype}\n"
          f"created: 2026-08-01\nupdated: 2026-10-10\n"
          f"tended: 2026-10-10\nsources: []\ntags: []\n"
          f"{extra}---\n")
    return fm + body


PAGES = {
    "wiki/concepts/plain.md": page("Plain", "concept"),
    "wiki/concepts/declared-unreviewed.md": page(
        "DU", "concept", "review_state: unreviewed\n"),
    "wiki/concepts/in-review.md": page(
        "IR", "concept", "review_state: in-review\n"),
    "wiki/concepts/reviewed-current.md": page(
        "RC", "concept",
        "review_state: reviewed\nreviewed_on: 2026-10-15\n"
        "reviewed_by: agent\n"),
    "wiki/concepts/reviewed-stale-change.md": page(
        "RSC", "concept",
        "review_state: reviewed\nreviewed_on: 2026-10-15\n"
        "reviewed_by: agent\ntended: 2026-10-20\n"
        ).replace("tended: 2026-10-10\n", ""),
    "wiki/concepts/reviewed-stale-due.md": page(
        "RSD", "concept",
        "review_state: reviewed\nreviewed_on: 2026-10-15\n"
        "reviewed_by: agent\nreview_due: 2026-10-20\n"),
    "wiki/syntheses/reviewed-stale-cadence.md": page(
        "RSCad", "synthesis",
        "review_state: reviewed\nreviewed_on: 2026-08-01\n"
        "reviewed_by: agent\ntended: 2026-08-01\n"
        ).replace("tended: 2026-10-10\n", ""),
    "wiki/concepts/reviewed-no-date.md": page(
        "RND", "concept",
        "review_state: reviewed\nreviewed_by: agent\n"),
    "wiki/concepts/reviewed-no-by.md": page(
        "RNB", "concept",
        "review_state: reviewed\nreviewed_on: 2026-10-15\n"),
    "wiki/concepts/reviewed-future.md": page(
        "RF", "concept",
        "review_state: reviewed\nreviewed_on: 2026-12-01\n"
        "reviewed_by: agent\n"),
    "wiki/concepts/reviewed-bad-due.md": page(
        "RBD", "concept",
        "review_state: reviewed\nreviewed_on: 2026-10-15\n"
        "reviewed_by: agent\nreview_due: soon\n"),
    "wiki/concepts/bad-state.md": page(
        "BS", "concept", "review_state: done\n"),
    "wiki/concepts/fields-no-state.md": page(
        "FNS", "concept",
        "reviewed_on: 2026-10-15\nreviewed_by: agent\n"),
    "wiki/concepts/retired.md": page(
        "Ret", "concept",
        "status: tombstoned\nreview_state: reviewed\n"
        "reviewed_on: 2026-10-15\nreviewed_by: agent\n"),
    "wiki/syntheses/claim-page.md": page(
        "CP", "synthesis",
        "claim: The fixture claim stands.\n"
        "as_of: 2026-10-01\n"),
}


def build_fixture(root: Path):
    for rel, text in PAGES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (root / "wiki" / "index.md").write_text(
        "# Index\n", encoding="utf-8")
    (root / "evaluation").mkdir(exist_ok=True)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)
        self.census = rs.build_census(self.root, TODAY)
        self.by_page = {p["page"]: p
                        for p in self.census["pages"]}

    def tearDown(self):
        self._tmp.cleanup()


class TestCensus(FixtureCase):
    def test_population(self):
        pop = self.census["population"]
        self.assertEqual(pop["scanned"], 15)
        self.assertEqual(pop["retired_excluded"], 1)
        self.assertEqual(pop["in_population"], 14)
        self.assertEqual(pop["carrying_review_state"], 11)

    def test_effective_states(self):
        eff = self.census["census"]["by_effective"]
        self.assertEqual(eff, {
            "undeclared": 4, "unreviewed": 1, "in-review": 1,
            "reviewed-current": 2, "reviewed-stale": 3,
            "reviewed-unverifiable": 3})

    def test_stale_vias(self):
        vias = {}
        for p in self.census["pages"]:
            if p["stale"]:
                vias[p["page"]] = (
                    p["stale"]["via"], p["stale"]["days_overdue"])
        self.assertEqual(
            vias["wiki/concepts/reviewed-stale-change.md"],
            ("changed-since-review", 7))
        self.assertEqual(
            vias["wiki/concepts/reviewed-stale-due.md"],
            ("review-due-passed", 2))
        self.assertEqual(
            vias["wiki/syntheses/reviewed-stale-cadence.md"],
            ("cadence-passed", 52))

    def test_findings(self):
        got = {(f["page"], f["finding"])
               for f in self.census["findings"]}
        self.assertIn(("wiki/concepts/reviewed-no-date.md",
                       "reviewed-without-reviewed-on"), got)
        self.assertIn(("wiki/concepts/reviewed-no-by.md",
                       "reviewed-without-reviewed-by"), got)
        self.assertIn(("wiki/concepts/reviewed-future.md",
                       "reviewed-on-in-future"), got)
        self.assertIn(("wiki/concepts/reviewed-bad-due.md",
                       "review-due-unparseable"), got)
        self.assertIn(("wiki/concepts/bad-state.md",
                       "unknown-review-state"), got)
        self.assertIn(("wiki/concepts/fields-no-state.md",
                       "review-fields-without-state"), got)
        # a bad review_due does not impeach the review
        rbd = self.by_page["wiki/concepts/reviewed-bad-due.md"]
        self.assertEqual(rbd["effective_state"],
                         "reviewed-current")


class TestTransitions(unittest.TestCase):
    def test_table(self):
        self.assertTrue(rs.legal_transition(None, "reviewed"))
        self.assertTrue(
            rs.legal_transition("unreviewed", "in-review"))
        self.assertTrue(
            rs.legal_transition("in-review", "unreviewed"))
        self.assertTrue(
            rs.legal_transition("reviewed", "in-review"))
        self.assertTrue(
            rs.legal_transition("reviewed", "reviewed"))
        self.assertFalse(
            rs.legal_transition("reviewed", "unreviewed"))
        self.assertFalse(rs.legal_transition("reviewed", None))
        self.assertFalse(
            rs.legal_transition("unreviewed", None))

    def test_diff(self):
        def census(state, on=None):
            return {"pages": [{
                "page": "wiki/concepts/x.md",
                "declared_state": state, "reviewed_on": on}]}
        old = census("unreviewed")
        self.assertEqual(
            rs.diff_censuses(old, census("in-review")), [])
        jumps = rs.diff_censuses(census("reviewed", "2026-10-15"),
                                 census("unreviewed"))
        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0]["finding"],
                         "illegal-transition")
        jumps = rs.diff_censuses(census("reviewed", "2026-10-15"),
                                 census("reviewed", "2026-10-01"))
        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0]["finding"],
                         "reviewed-on-moved-backward")
        jumps = rs.diff_censuses(census("reviewed", "2026-10-15"),
                                 census("reviewed", "2026-10-20"))
        self.assertEqual(jumps, [])


class TestCenter(FixtureCase):
    def setUp(self):
        super().setUp()
        self.center = rs.build_review_center(self.root, TODAY)
        self.items = {i["page"]: i
                      for i in self.center["worklist"]}

    def test_claim_page_annotated_p1(self):
        item = self.items["wiki/syntheses/claim-page.md"]
        self.assertEqual(item["priority"], 1)
        self.assertIsNotNone(item["claim"])
        self.assertEqual(item["claim"]["claim"],
                         "The fixture claim stands.")
        self.assertIn("candidate",
                      item["claim"]["outcome_status"])
        self.assertIn("reverify-overdue",
                      [r["reason"] for r in item["reasons"]])

    def test_state_stale_and_invalid_items(self):
        stale = self.items[
            "wiki/concepts/reviewed-stale-change.md"]
        self.assertEqual(stale["priority"], 2)
        self.assertIn("review-state-stale",
                      [r["reason"] for r in stale["reasons"]])
        self.assertEqual(stale["review_state"],
                         "reviewed-stale")
        invalid = self.items["wiki/concepts/reviewed-no-date.md"]
        self.assertEqual(invalid["priority"], 1)
        self.assertIn("review-record-invalid",
                      [r["reason"] for r in invalid["reasons"]])

    def test_current_page_has_no_state_reasons(self):
        item = self.items.get("wiki/concepts/reviewed-current.md")
        if item is not None:
            reasons = [r["reason"] for r in item["reasons"]]
            self.assertNotIn("review-state-stale", reasons)
            self.assertNotIn("review-record-invalid", reasons)

    def test_bad_due_is_invalid_record_not_stale(self):
        item = self.items["wiki/concepts/reviewed-bad-due.md"]
        reasons = [r["reason"] for r in item["reasons"]]
        self.assertIn("review-record-invalid", reasons)
        self.assertNotIn("review-state-stale", reasons)
        self.assertEqual(item["review_state"],
                         "reviewed-current")

    def test_in_review_list(self):
        self.assertEqual(self.center["in_review"],
                         ["wiki/concepts/in-review.md"])

    def test_ordering_rule(self):
        keys = [(i["priority"],
                 -(i["max_days_overdue"]
                   if i["max_days_overdue"] is not None
                   else -1),
                 i["page"]) for i in self.center["worklist"]]
        self.assertEqual(keys, sorted(keys))

    def test_next_due_feedback(self):
        item = self.items["wiki/syntheses/claim-page.md"]
        # synthesis cadence proposal is 30d
        self.assertEqual(item["next_due_if_reviewed_today"],
                         "2026-11-21")
        self.assertIn("PROPOSED", item["next_due_basis"])

    def test_payload_shape(self):
        payload = rs.build_ai_payload(self.center)
        self.assertEqual(len(payload),
                         len(self.center["worklist"]))
        self.assertEqual(
            [p["page"] for p in payload],
            [i["page"] for i in self.center["worklist"]])
        for p in payload:
            self.assertIn("task", p)
            self.assertIn("check_against_sources", p)
            self.assertIn("reasons", p)

    def test_determinism(self):
        again = rs.build_review_center(self.root, TODAY)
        self.assertEqual(
            json.dumps(self.center, sort_keys=True),
            json.dumps(again, sort_keys=True))
        c2 = rs.build_census(self.root, TODAY)
        self.assertEqual(
            json.dumps(self.census, sort_keys=True),
            json.dumps(c2, sort_keys=True))

    def test_read_only_over_pages(self):
        before = {rel: (self.root / rel).read_bytes()
                  for rel in PAGES}
        rs.build_review_center(self.root, TODAY)
        rs.build_census(self.root, TODAY)
        for rel, data in before.items():
            self.assertEqual((self.root / rel).read_bytes(),
                             data)


if __name__ == "__main__":
    unittest.main()
