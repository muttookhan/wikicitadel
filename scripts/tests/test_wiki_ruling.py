#!/usr/bin/env python3
"""Tests for scripts/wiki_ruling.py — the applier for owner
rulings sent from the Lens (2030-10-20).

The Lens button decides nothing: it sends the ruling through
the Ask door, and the pickup runs this tool to move the item on
wiki/ideas.md. The tool's contract is fail-closed — an exact
bold-title match in the Waiting section or nothing happens —
and idempotent: re-applying a ruling that already stands is a
no-op success, never a second move.

These tests run the real CLI against a fixture ideas page in a
temp dir; the repo's own wiki/ideas.md is never touched.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = SCRIPTS / "wiki_ruling.py"

FIXTURE = """---
title: "Ideas — fixture"
---

# Ideas — awaiting your call

## Waiting for your call

*An italic note about the waiting list.*

- **First waiting idea** — do the first thing (Agent, 2030-10-20) — awaiting the owner's call
- **Second waiting idea** — do the second thing — awaiting the owner's call

## Approved

- **An old approved idea** — built already

## Disapproved

*(none yet)*
"""

MULTILINE_FIXTURE = """# Ideas — fixture

## Waiting for your call

- **Wrapped idea** — a bullet whose text continues
  on a second, indented line

## Approved

## Disapproved

*(none yet)*
"""

DATE = "2030-10-20"


class WikiRulingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page = Path(self.tmp.name) / "ideas.md"

    def write(self, text):
        self.page.write_text(text, encoding="utf-8")

    def run_tool(self, *argv):
        return subprocess.run(
            [sys.executable, str(TOOL), "apply",
             "--file", str(self.page), *argv],
            capture_output=True, text=True)

    def test_approve_moves_to_end_of_approved_with_marker(self):
        self.write(FIXTURE)
        res = self.run_tool("--decision", "approved",
                            "--title", "First waiting idea",
                            "--date", DATE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(),
            "Owner ruling via Lens: First waiting idea — APPROVED "
            "(Ideas board: Waiting → Approved).")
        out = self.page.read_text(encoding="utf-8")
        moved = ("- **First waiting idea** — do the first thing "
                 "(Agent, 2030-10-20) — awaiting the owner's call"
                 " — **APPROVED by the owner via the Lens ruling "
                 f"button, {DATE}**")
        # The moved line is the LAST bullet of the Approved section.
        approved = out.split("## Approved")[1].split("## Disapproved")[0]
        self.assertEqual(approved.strip().splitlines()[-1], moved)
        # It is gone from Waiting; the other bullet is untouched.
        waiting = out.split("## Waiting for your call")[1].split("## Approved")[0]
        self.assertNotIn("First waiting idea", waiting)
        self.assertIn("- **Second waiting idea**", waiting)
        # Nothing else moved: the old approved bullet still stands.
        self.assertIn("- **An old approved idea** — built already", approved)

    def test_reject_moves_to_end_of_disapproved_with_marker(self):
        self.write(FIXTURE)
        res = self.run_tool("--decision", "rejected",
                            "--title", "Second waiting idea",
                            "--date", DATE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(),
            "Owner ruling via Lens: Second waiting idea — REJECTED "
            "(Ideas board: Waiting → Disapproved).")
        out = self.page.read_text(encoding="utf-8")
        moved = ("- **Second waiting idea** — do the second thing"
                 " — awaiting the owner's call"
                 " — **REJECTED by the owner via the Lens ruling "
                 f"button, {DATE}**")
        disapproved = out.split("## Disapproved")[1]
        self.assertEqual(disapproved.strip().splitlines()[-1], moved)
        waiting = out.split("## Waiting for your call")[1].split("## Approved")[0]
        self.assertNotIn("Second waiting idea", waiting)

    def test_already_applied_is_idempotent(self):
        self.write(FIXTURE)
        first = self.run_tool("--decision", "approved",
                              "--title", "First waiting idea",
                              "--date", DATE)
        self.assertEqual(first.returncode, 0, first.stderr)
        after_first = self.page.read_bytes()
        second = self.run_tool("--decision", "approved",
                               "--title", "First waiting idea",
                               "--date", DATE)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "ALREADY-APPLIED")
        self.assertEqual(self.page.read_bytes(), after_first)

    def test_unknown_title_refused_file_byte_identical(self):
        self.write(FIXTURE)
        before = self.page.read_bytes()
        res = self.run_tool("--decision", "approved",
                            "--title", "No such idea",
                            "--date", DATE)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout.strip(), "NOT-FOUND")
        self.assertEqual(self.page.read_bytes(), before)

    def test_title_in_approved_without_lens_marker_is_not_applied(self):
        # A title that stands in Approved for another reason was
        # never ruled on through the Lens: not "already applied",
        # and never moved or marked by this tool.
        self.write(FIXTURE)
        before = self.page.read_bytes()
        res = self.run_tool("--decision", "approved",
                            "--title", "An old approved idea",
                            "--date", DATE)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout.strip(), "NOT-FOUND")
        self.assertEqual(self.page.read_bytes(), before)

    def test_dry_run_writes_nothing(self):
        self.write(FIXTURE)
        before = self.page.read_bytes()
        res = self.run_tool("--decision", "approved",
                            "--title", "First waiting idea",
                            "--date", DATE, "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(),
            "Owner ruling via Lens: First waiting idea — APPROVED "
            "(Ideas board: Waiting → Approved).")
        self.assertEqual(self.page.read_bytes(), before)

    def test_multiline_bullet_refused(self):
        self.write(MULTILINE_FIXTURE)
        before = self.page.read_bytes()
        res = self.run_tool("--decision", "approved",
                            "--title", "Wrapped idea",
                            "--date", DATE)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout.strip(), "REFUSED: multi-line bullet")
        self.assertEqual(self.page.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
