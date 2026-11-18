#!/usr/bin/env python3
"""Tests for scripts/wiki_pending_review.py (Marathon R3
TA5; Vanillaflava self-clearing Pending Review sections).

Pins, on FIXTURE page strings + a temp tree:
  - entry states: (status: resolved) resolves; an
    (expires:) date before today expires; an expiry today
    or later, or no marker at all, stays open;
  - a section whose entries are all resolved/expired is
    CLEARABLE; one open entry blocks it; an entry-less
    section is reported empty, never clearable;
  - the section ends at the next `## ` heading — bullets
    after it are not entries;
  - REPORT-ONLY: a full scan leaves every page
    byte-identical, and the CLI exit code is 1 exactly when
    a clearable section exists, else 0.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
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
TODAY = date(2026, 10, 21)


def load_module(root=None):
    path = (root / "scripts" / "wiki_pending_review.py") if root \
        else SCRIPTS / "wiki_pending_review.py"
    spec = importlib.util.spec_from_file_location(
        "wiki_pending_review", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()

CLEARABLE = """# Page One

## Pending Review

- Claim about the harbour (status: resolved)
- Claim about the gulls (expires: 2026-10-01)

## Later

- Not an entry (status: resolved)
"""
BLOCKED = """# Page Two

## Pending Review

- Claim about the orchard (status: resolved)
- Claim about the pruning (expires: 2027-01-01)
- Claim with no marker at all
"""
EMPTY = """# Page Three

## Pending Review

Nothing filed yet.
"""


class TestEntryStates(unittest.TestCase):
    def test_states(self):
        self.assertEqual(MOD.entry_state("x (status: resolved)", TODAY),
                         "resolved")
        self.assertEqual(MOD.entry_state("x (expires: 2026-10-20)", TODAY),
                         "expired")
        self.assertEqual(MOD.entry_state("x (expires: 2026-10-21)", TODAY),
                         "open")
        self.assertEqual(MOD.entry_state("x (expires: 2027-05-01)", TODAY),
                         "open")
        self.assertEqual(MOD.entry_state("x, no marker", TODAY), "open")
        # Resolved wins over a past expiry.
        self.assertEqual(
            MOD.entry_state("x (status: resolved) (expires: 2020-01-01)",
                            TODAY), "resolved")


class TestSections(unittest.TestCase):
    def test_clearable(self):
        secs = MOD.scan_page(CLEARABLE, TODAY)
        self.assertEqual(len(secs), 1)
        self.assertTrue(secs[0]["clearable"])
        self.assertEqual(secs[0]["entry_count"], 2)

    def test_blocked_by_open(self):
        secs = MOD.scan_page(BLOCKED, TODAY)
        self.assertFalse(secs[0]["clearable"])
        self.assertEqual(secs[0]["open"], 2)

    def test_empty_is_not_clearable(self):
        secs = MOD.scan_page(EMPTY, TODAY)
        self.assertTrue(secs[0]["empty"])
        self.assertFalse(secs[0]["clearable"])


class TestScanAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pending-review-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_pending_review.py",
                    scripts / "wiki_pending_review.py")
        wiki = self.tmp / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "one.md").write_text(CLEARABLE, encoding="utf-8")
        (wiki / "two.md").write_text(BLOCKED, encoding="utf-8")
        self.before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in wiki.glob("*.md")}

    def test_scan_report(self):
        report = MOD.scan(self.tmp, today=TODAY)
        self.assertEqual(report["stats"]["clearable"], 1)
        self.assertEqual(report["clearable"][0]["page"],
                         "wiki/concepts/one.md")
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (self.tmp / "wiki" / "concepts").glob("*.md")}
        self.assertEqual(self.before, after)

    def test_cli_exit_codes(self):
        tool = self.tmp / "scripts" / "wiki_pending_review.py"
        proc = subprocess.run(
            [sys.executable, str(tool), "--root", str(self.tmp),
             "--today", "2026-10-21"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        json.loads(proc.stdout)
        # Far past: everything expires -> page two also clearable.
        proc2 = subprocess.run(
            [sys.executable, str(tool), "--root", str(self.tmp),
             "--today", "2028-01-01", "--plain"],
            capture_output=True, text=True)
        self.assertEqual(proc2.returncode, 1)
        self.assertIn("CLEARABLE", proc2.stdout)


if __name__ == "__main__":
    unittest.main()
