#!/usr/bin/env python3
"""Tests for scripts/wiki_decision_basis.py (wave-10
fold-in: decision-basis hashing, the Rutter pattern).

Pins the contract on a FIXTURE repo in a temp dir:

  - the basis is derived MECHANICALLY from the register:
    the source.page, paths named in current_form, paths
    named in a superseded form's superseded_by — and
    nothing else;
  - build records sha256_now plus the decision-date hash
    from git history;
  - check is CLEAN on the fresh build, then flags
    BASIS CHANGED (exit 1) when a basis file's bytes move,
    and BASIS MISSING when one disappears;
  - a decision with no derivable basis is reported
    underivable-from-record, never given a guessed basis.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

ENV = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@x",
       "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "f@x",
       "GIT_AUTHOR_DATE": "2030-01-01T10:00:00Z",
       "GIT_COMMITTER_DATE": "2030-01-01T10:00:00Z"}


def git(root, *args):
    env = dict(os.environ); env.update(ENV)
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, env=env,
                          check=True)


class BasisFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-basis-"))
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / "wiki_decision_basis.py",
                     self.repo / "scripts" / "wiki_decision_basis.py")
        (self.repo / "wiki" / "syntheses").mkdir(parents=True)
        (self.repo / "evaluation").mkdir(parents=True)
        (self.repo / "wiki" / "syntheses" / "decisions.md").write_text(
            "# Decisions\n\nThe record.\n")
        (self.repo / "wiki" / "syntheses" / "design.md").write_text(
            "# Design\n\nBasis evidence v1.\n")
        register = [
            {"kind": "header", "register": "decisions-register"},
            {"kind": "decision", "id": "fx-d1", "title": "With design",
             "status": "active", "decided": "2030-01-01",
             "decided_by": "owner",
             "source": {"page": "wiki/syntheses/decisions.md",
                        "section": "1"},
             "current_form": "Pursue the design in "
                             "wiki/syntheses/design.md.",
             "superseded_forms": []},
            {"kind": "decision", "id": "fx-d2", "title": "No basis named",
             "status": "active", "decided": "2030-01-01",
             "decided_by": "owner", "source": {},
             "current_form": "Decided in conversation; nothing cited.",
             "superseded_forms": []},
        ]
        (self.repo / "evaluation" / "decisions-register.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in register))
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable,
             str(self.repo / "scripts" / "wiki_decision_basis.py"),
             *args], capture_output=True, text=True, cwd=self.repo)

    def test_build_derives_mechanically(self):
        r = self.run_tool("build")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((self.repo / "evaluation"
                           / "decision-basis.json").read_text())
        d1, d2 = data["decisions"]
        paths = [b["path"] for b in d1["basis"]]
        self.assertEqual(paths, ["wiki/syntheses/decisions.md",
                                 "wiki/syntheses/design.md"])
        for b in d1["basis"]:
            self.assertEqual(len(b["sha256_now"]), 64)
            # committed on the decision date → at-decision hash present
            self.assertEqual(b["sha256_at_decision"], b["sha256_now"])
        self.assertEqual(d2["basis_status"], "underivable-from-record")
        self.assertEqual(d2["basis"], [])

    def test_check_clean_then_changed_then_missing(self):
        self.assertEqual(self.run_tool("build").returncode, 0)
        clean = self.run_tool("check")
        self.assertEqual(clean.returncode, 0, clean.stdout)
        self.assertIn("CLEAN", clean.stdout)
        design = self.repo / "wiki" / "syntheses" / "design.md"
        design.write_text("# Design\n\nBasis evidence v2 — moved.\n")
        moved = self.run_tool("check")
        self.assertEqual(moved.returncode, 1)
        self.assertIn("BASIS CHANGED fx-d1: wiki/syntheses/design.md",
                      moved.stdout)
        # --report surfaces but never blocks
        self.assertEqual(self.run_tool("check", "--report").returncode, 0)
        design.unlink()
        gone = self.run_tool("check")
        self.assertEqual(gone.returncode, 1)
        self.assertIn("BASIS MISSING fx-d1", gone.stdout)


if __name__ == "__main__":
    unittest.main()
