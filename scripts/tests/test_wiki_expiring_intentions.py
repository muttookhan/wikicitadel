"""Tests for scripts/wiki_expiring_intentions.py (R3 TB1 row 4).

Pins: an intention claim past its ``expires:`` date is due for
demotion; an unexpired one is not; dry-run writes nothing;
--apply appends the demotion event log AND updates the page
frontmatter in the FIXTURE tree only; a second --apply is a
no-op (already demoted); non-intention claims are ignored.

Run:  python3 -m unittest discover -s scripts/tests
All roots are temp fixture trees — the live claims register is
never a test target.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_expiring_intentions",
    ROOT / "scripts" / "wiki_expiring_intentions.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

AS_OF = date(2026, 10, 21)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _intention(title, claim, expires, extra=""):
    return (f"---\ntitle: {title}\ntype: concept\nclaim_type: intention\n"
            f"claim: \"{claim}\"\nexpires: {expires}\n{extra}---\n\nBody.\n")


def fixture(tmp):
    root = Path(tmp)
    _write(root, "wiki/concepts/old-plan.md",
           _intention("Old", "We intend to trial the roster.", "2026-10-01"))
    _write(root, "wiki/concepts/live-plan.md",
           _intention("Live", "We intend to keep the ledger.", "2027-01-01"))
    _write(root, "wiki/concepts/plain-claim.md",
           "---\ntitle: Plain\ntype: concept\n"
           "claim: \"A plain fact claim.\"\nas_of: 2026-10-01\n---\n\nBody.\n")
    return root


class ExpiringIntentionsTests(unittest.TestCase):
    def test_list_marks_only_expired_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = mod.list_intentions(fixture(tmp), AS_OF)
            self.assertEqual(len(rows), 2)
            by_page = {r["page"]: r for r in rows}
            self.assertTrue(by_page["wiki/concepts/old-plan.md"]["demotion_due"])
            self.assertFalse(by_page["wiki/concepts/live-plan.md"]["demotion_due"])
            self.assertEqual(
                by_page["wiki/concepts/live-plan.md"]["effective_status"],
                "active")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            before = (root / "wiki/concepts/old-plan.md").read_text()
            result = mod.demote(root, AS_OF, apply=False)
            self.assertEqual(len(result["events"]), 1)
            self.assertFalse(result["applied"])
            self.assertFalse((root / mod.EVENTS_REL).exists())
            self.assertEqual(
                (root / "wiki/concepts/old-plan.md").read_text(), before)

    def test_apply_files_event_and_updates_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            result = mod.demote(root, AS_OF, apply=True)
            self.assertTrue(result["applied"])
            events = [json.loads(l) for l in
                      (root / mod.EVENTS_REL).read_text().splitlines() if l]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["page"], "wiki/concepts/old-plan.md")
            self.assertEqual(events[0]["to_status"], "demoted")
            text = (root / "wiki/concepts/old-plan.md").read_text()
            self.assertIn("intention_status: demoted", text)
            # Idempotent: already demoted -> nothing due.
            again = mod.demote(root, AS_OF, apply=True)
            self.assertEqual(again["events"], [])

    def test_boundary_expiry_day_itself_not_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "wiki/concepts/today.md",
                   _intention("Today", "We intend to ship today.",
                              "2026-10-21"))
            rows = mod.list_intentions(root, AS_OF)
            self.assertFalse(rows[0]["expired"])


if __name__ == "__main__":
    unittest.main()
