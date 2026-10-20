#!/usr/bin/env python3
"""Tests for scripts/wiki_tombstone.py (queue item 18).

Pins the tombstone contract:
  - the tool DRY-RUNS by default and writes nothing;
  - --apply requires a --reason (the Withdrawn record carries
    the reason) and preserves the frontmatter while extending
    it (status: tombstoned, tombstoned:, tombstone_reason:,
    replaced_by:), replacing only the body;
  - structural pages, non-wiki paths, and already-tombstoned
    pages are refused;
  - the relation census maps typed edges and frontmatter
    declarations onto the closed vocabulary and counts what
    falls outside it.

Exercised ONLY on fixture pages in a temp dir (the real
scripts copied in, so ROOT resolves to the fixture) — never
on a real wiki page.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent

OLD_PAGE = """---
title: Old Concept
type: concept
created: 2030-01-01
updated: 2030-01-02
sources:
  - raw/sources/example.md
tags: [test]
status: draft
confidence: observed
stage: budding
planted: 2030-01-01
tended: 2030-01-02
work_type: record
---

# Old Concept

Original body text that the tombstone replaces.

## Evidence

Grounded in [[concepts/keeper]].

## Contradictions

Disputed by [[concepts/other]].
"""

KEEPER_PAGE = """---
title: Keeper
type: concept
created: 2030-01-01
updated: 2030-01-02
sources:
  - raw/sources/example.md
tags: [test]
status: draft
confidence: observed
---

# Keeper

## Extensions

Builds on [[concepts/old-page]].
"""

LEGACY_PAGE = """---
title: Legacy
type: source
created: 2030-01-01
updated: 2030-01-02
tags: [test]
status: draft
confidence: observed
superseded_by: wiki/concepts/keeper.md
based_on: vault
---

# Legacy

## Sources

Drawn from [[concepts/keeper]].
"""


class TombstoneTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "tools" / "lens").mkdir(parents=True)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_tombstone.py",
                    self.root / "scripts" / "wiki_tombstone.py")
        shutil.copy(SCRIPTS / "wiki_validate.py",
                    self.root / "scripts" / "wiki_validate.py")
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    self.root / "tools" / "lens" / "lenslib.py")
        self.script = self.root / "scripts" / "wiki_tombstone.py"
        self.old = self.root / "wiki" / "concepts" / "old-page.md"
        self.old.write_text(OLD_PAGE, encoding="utf-8")
        (self.root / "wiki" / "concepts" / "keeper.md").write_text(
            KEEPER_PAGE, encoding="utf-8")
        (self.root / "wiki" / "concepts" / "legacy.md").write_text(
            LEGACY_PAGE, encoding="utf-8")
        (self.root / "wiki" / "index.md").write_text(
            "# Index\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True)

    # -- dry run ------------------------------------------------

    def test_dry_run_writes_nothing(self):
        before = self.old.read_bytes()
        r = self.run_cli(
            "tombstone", "--page", "wiki/concepts/old-page.md",
            "--reason", "Merged into the keeper page",
            "--replaced-by", "wiki/concepts/keeper.md",
            "--date", "2030-02-01")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DRY RUN — nothing written", r.stdout)
        self.assertIn("status: tombstoned", r.stdout)
        self.assertIn("tombstoned: 2030-02-01", r.stdout)
        self.assertEqual(self.old.read_bytes(), before)

    # -- apply ---------------------------------------------------

    def test_apply_preserves_and_extends_frontmatter(self):
        r = self.run_cli(
            "tombstone", "--page", "wiki/concepts/old-page.md",
            "--reason", "Superseded: merged into the keeper page",
            "--replaced-by", "wiki/concepts/keeper.md",
            "--date", "2030-02-01", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = self.old.read_text(encoding="utf-8")
        self.assertIn("title: Old Concept", text)
        self.assertIn("created: 2030-01-01", text)
        self.assertIn("  - raw/sources/example.md", text)
        self.assertIn("status: tombstoned", text)
        self.assertIn("updated: 2030-02-01", text)
        self.assertIn("tombstoned: 2030-02-01", text)
        # A reason containing a colon is quoted, not corrupting.
        self.assertIn('tombstone_reason: "Superseded: merged into'
                      ' the keeper page"', text)
        self.assertIn("replaced_by: wiki/concepts/keeper.md", text)
        self.assertNotIn("Original body text", text)
        self.assertIn("# Old Concept", text)
        self.assertIn("[[concepts/keeper]]", text)
        self.assertIn("is-superseded-by", text)
        self.assertIn("Nothing was\ndeleted.", text)

    def test_apply_requires_reason(self):
        before = self.old.read_bytes()
        r = self.run_cli(
            "tombstone", "--page", "wiki/concepts/old-page.md",
            "--apply")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--reason", r.stdout + r.stderr)
        self.assertEqual(self.old.read_bytes(), before)

    def test_double_tombstone_refused(self):
        self.run_cli("tombstone", "--page",
                     "wiki/concepts/old-page.md",
                     "--reason", "first", "--apply")
        r = self.run_cli("tombstone", "--page",
                         "wiki/concepts/old-page.md",
                         "--reason", "second", "--apply")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("already tombstoned", r.stdout + r.stderr)

    def test_structural_and_outside_paths_refused(self):
        r = self.run_cli("tombstone", "--page", "wiki/index.md",
                         "--reason", "x", "--apply")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.run_cli("tombstone", "--page", "evaluation/x.md",
                         "--reason", "x", "--apply")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.run_cli("tombstone", "--page",
                         "wiki/concepts/missing.md",
                         "--reason", "x", "--apply")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_list_reports_tombstones(self):
        r = self.run_cli("list")
        self.assertIn("no tombstoned pages", r.stdout)
        self.run_cli("tombstone", "--page",
                     "wiki/concepts/old-page.md",
                     "--reason", "merged", "--date", "2030-02-01",
                     "--apply")
        r = self.run_cli("list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("wiki/concepts/old-page.md", r.stdout)
        self.assertIn("tombstoned 2030-02-01", r.stdout)
        self.assertIn("1 tombstone(s)", r.stdout)

    # -- relation census ------------------------------------------

    def test_relations_census_counts(self):
        r = self.run_cli("relations")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Edges: grounds 2 (old-page Evidence, legacy Sources),
        # contradicts 1, extends 1 -> 2 in vocab, 2 outside.
        self.assertRegex(r.stdout, r"grounds\s+2 edge\(s\)")
        self.assertRegex(r.stdout, r"contradicts\s+1 edge\(s\)")
        self.assertRegex(r.stdout,
                         r"TOTAL\s+4 edge\(s\) — 2 in vocabulary,"
                         r" 2 outside")
        # Frontmatter: superseded_by in vocab, based_on outside.
        self.assertRegex(r.stdout, r"superseded_by\s+1 instance\(s\)")
        self.assertRegex(r.stdout, r"based_on\s+1 instance\(s\)")
        self.assertIn("TOTAL 2 instance(s) — 1 in vocabulary,"
                      " 1 outside", r.stdout)
        self.assertIn("sources:` frontmatter: 2", r.stdout)


if __name__ == "__main__":
    unittest.main()
