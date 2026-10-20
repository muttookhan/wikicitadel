#!/usr/bin/env python3
"""Item 40: post-mortem action-item discipline.

The register stops being a store and starts travelling:
action items carry tracking ids, measurable end states,
owners and statuses; the completion metric reads % verified
over trailing windows; filing a new post-mortem PUSHES the
still-open items from earlier ones; and a post-mortem naming
a failed proposal is scored against that proposal's
premortem (did a written premortem exist; was the reason on
its list).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_postmortem", ROOT / "scripts" / "wiki_postmortem.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

TODAY = date(2030, 10, 20)

FIELDS = {
    "title": "Fixture failure",
    "trigger_kind": "failed-check",
    "trigger_ref": "fixture audit",
    "what_happened": "A fixture did a wrong thing.",
    "root_cause_class": "scope",
    "rule_changed": "Check the fixture before integrating it.",
}

WRITTEN_PROPOSAL = """# Fixture proposal

Body.

## Premortem (2030-10-20)

It is 2027-04-20 and this failed. The reasons were:

1. **Promotion overwrote the live page with the staged
   snapshot**, silently reverting every later edit.
   — Mitigation: diff before promoting.
2. **The queue stalled because nobody owned the review.**
   — Accepted risk: noted.

## Notes

Trailing section.
"""

PLACEHOLDER_PROPOSAL = """# Fixture proposal

## Premortem (not yet written)

**NOT YET WRITTEN.** Before this proposal is put to the
owner, a separate pass replaces this placeholder.
"""

BARE_PROPOSAL = "# Fixture proposal\n\nNo premortem here.\n"


def make_root(tmp: Path) -> Path:
    (tmp / "evaluation").mkdir(parents=True)
    (tmp / "staging" / "proposed").mkdir(parents=True)
    return tmp


class TestFilingAndPush(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_ids_increment_and_actions_attach(self):
        entry, still_open = pm.file_postmortem(
            self.root, FIELDS,
            actions=[("End state one.", "Check one.", "agent")],
            today=TODAY)
        self.assertEqual(entry["id"], "PM-2030-001")
        self.assertEqual(still_open, [])
        item = entry["action_items"][0]
        self.assertEqual(item["id"], "PM-2030-001-A1")
        self.assertEqual(item["status"], "open")
        # Register round-trips through disk.
        entries = pm.load_entries(self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action_items"][0]["id"],
                         "PM-2030-001-A1")

    def test_open_items_push_at_next_entry(self):
        pm.file_postmortem(
            self.root, FIELDS,
            actions=[("End state one.", "Check one.", "agent")],
            today=TODAY)
        entry2, still_open = pm.file_postmortem(
            self.root, {**FIELDS, "title": "Second failure"},
            today=TODAY)
        self.assertEqual(entry2["id"], "PM-2030-002")
        self.assertEqual([it["id"] for it in still_open],
                         ["PM-2030-001-A1"])
        # Once the earlier item closes, the push is empty.
        entries = pm.load_entries(self.root)
        pm.set_item_status(entries, "PM-2030-001-A1", "verified",
                           evidence="check run", today=TODAY)
        pm.save_entries(self.root, entries)
        _e3, still_open3 = pm.file_postmortem(
            self.root, {**FIELDS, "title": "Third failure"},
            today=TODAY)
        self.assertEqual(still_open3, [])

    def test_action_item_validation(self):
        entries = []
        with self.assertRaises(ValueError):
            pm.add_action_item(entries, "PM-2030-001",
                               "state", "check", "nobody")
        with self.assertRaises(ValueError):
            pm.add_action_item(entries, "PM-2030-404",
                               "state", "check", "agent")
        with self.assertRaises(ValueError):
            pm.add_action_item(entries, "PM-2030-001",
                               "  ", "check", "agent")


class TestStatusAndMetrics(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))
        pm.file_postmortem(
            self.root, FIELDS,
            actions=[("State A.", "Check A.", "agent"),
                     ("State B.", "Check B.", "system"),
                     ("State C.", "Check C.", "owner")],
            today=TODAY)
        # An older entry, outside the 30d window at TODAY.
        pm.file_postmortem(
            self.root, {**FIELDS, "title": "Old failure"},
            actions=[("Old state.", "Old check.", "agent")],
            today=date(2030, 1, 10))

    def tearDown(self):
        self._tmp.cleanup()

    def test_status_transitions_record_evidence(self):
        entries = pm.load_entries(self.root)
        item = pm.set_item_status(entries, "PM-2030-001-A1",
                                  "done", evidence="did it",
                                  today=TODAY)
        self.assertEqual(item["done_on"], "2030-10-20")
        self.assertEqual(item["done_evidence"], "did it")
        item = pm.set_item_status(entries, "PM-2030-001-A1",
                                  "verified", evidence="saw it",
                                  today=TODAY)
        self.assertEqual(item["status"], "verified")
        self.assertEqual(item["verified_on"], "2030-10-20")
        self.assertEqual(item["verified_evidence"], "saw it")
        with self.assertRaises(ValueError):
            pm.set_item_status(entries, "PM-2030-001-A9", "done")

    def test_completion_metric_windows_and_percentages(self):
        entries = pm.load_entries(self.root)
        pm.set_item_status(entries, "PM-2030-001-A1", "verified",
                           today=TODAY)
        pm.set_item_status(entries, "PM-2030-001-A2", "done",
                           today=TODAY)
        m = pm.completion_metrics(entries, as_of=TODAY)
        # 30d window: only the 2030-10-20 entry's 3 items.
        self.assertEqual(m["30d"]["total"], 3)
        self.assertEqual(m["30d"]["by_status"],
                         {"open": 1, "done": 1, "verified": 1})
        self.assertEqual(m["30d"]["pct_verified"], 33.3)
        self.assertEqual(m["30d"]["pct_done_or_verified"], 66.7)
        # All window: the January item joins, still open.
        self.assertEqual(m["all"]["total"], 4)
        self.assertEqual(m["all"]["pct_verified"], 25.0)


class TestPremortemScoring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))
        proposed = self.root / "staging" / "proposed"
        (proposed / "prop-written.md").write_text(WRITTEN_PROPOSAL)
        (proposed / "prop-placeholder.md").write_text(
            PLACEHOLDER_PROPOSAL)
        (proposed / "prop-bare.md").write_text(BARE_PROPOSAL)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reasons_extracted(self):
        reasons = pm.premortem_reasons(WRITTEN_PROPOSAL)
        self.assertEqual(len(reasons), 2)
        self.assertIn("overwrote the live page", reasons[0])
        self.assertIn("queue stalled", reasons[1])

    def test_failure_on_the_list(self):
        out = pm.score_against_premortem(
            self.root, "staging/proposed/prop-written.md",
            "the promotion overwrote the live page with the "
            "staged snapshot and reverted later edits")
        self.assertTrue(out["premortem_present"])
        self.assertEqual(out["reasons_found"], 2)
        self.assertTrue(out["on_list"])
        self.assertEqual(out["matched_reason"], 1)

    def test_failure_not_on_the_list(self):
        out = pm.score_against_premortem(
            self.root, "staging/proposed/prop-written.md",
            "the staging disk filled up during a backup run")
        self.assertTrue(out["premortem_present"])
        self.assertFalse(out["on_list"])
        self.assertIsNone(out["matched_reason"])

    def test_no_written_premortem_scores_absent(self):
        for name in ("prop-placeholder.md", "prop-bare.md"):
            out = pm.score_against_premortem(
                self.root, f"staging/proposed/{name}", "anything")
            self.assertFalse(out["premortem_present"], name)
            self.assertIsNone(out["on_list"], name)

    def test_filing_stores_the_check(self):
        fields = {**FIELDS,
                  "failure_subject":
                      "staging/proposed/prop-written.md",
                  "failure_reason":
                      "promotion overwrote the live page with "
                      "the staged snapshot, reverting later edits"}
        entry, _ = pm.file_postmortem(self.root, fields,
                                      today=TODAY)
        self.assertIn("premortem_check", entry)
        self.assertTrue(entry["premortem_check"]["on_list"])
        rows = pm.premortem_checks(
            self.root, pm.load_entries(self.root))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pm_id"], entry["id"])


if __name__ == "__main__":
    unittest.main()
