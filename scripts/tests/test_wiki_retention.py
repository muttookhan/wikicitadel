#!/usr/bin/env python3
"""Tests for scripts/wiki_retention.py (queue item 17).

Pins the retention contract:
  - classes match first-match-wins, in policy order;
  - an item expires ON filed + period_days, and the stamp
    carries the date AND the named rule (Memanto discipline);
  - keep-forever classes never expire, at any as-of date;
  - check is a REPORT: it changes nothing on disk;
  - recall reads git history: a file added after the as-of
    date is absent, and a file whose clock had run out by
    then is marked EXPIRED as of then;
  - an untracked working file falls back to its mtime, and
    the stamp says so;
  - a malformed policy is a usage error (exit 2), never a
    silent pass.

Builds a fixture git repo in a temp dir (the real script
copied in, so ROOT resolves to the fixture) with commits
made under controlled GIT_AUTHOR_DATE / GIT_COMMITTER_DATE,
and drives the CLI.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

POLICY = {
    "schema": "retention-policy/1",
    "version": 1,
    "adopted": "2030-01-01",
    "classes": [
        {"name": "raw-sources", "scope": ["raw/sources/**"],
         "retention": {"kind": "keep-forever"}, "on_expiry": None},
        {"name": "raw-layer", "scope": ["raw/**"],
         "retention": {"kind": "keep-forever"}, "on_expiry": None},
        {"name": "compiled-wiki", "scope": ["wiki/**"],
         "retention": {"kind": "keep-forever"}, "on_expiry": None},
        {"name": "evaluation-registers", "scope": ["evaluation/*.jsonl"],
         "retention": {"kind": "keep-forever"}, "on_expiry": None},
        {"name": "evaluation-reports", "scope": ["evaluation/**"],
         "retention": {"kind": "keep-forever"}, "on_expiry": None},
        {"name": "staging-notes", "scope": ["staging/**"],
         "retention": {"kind": "review-after", "period_days": 7},
         "on_expiry": "review"},
        {"name": "exports-bundles", "scope": ["exports/**"],
         "retention": {"kind": "expire-after", "period_days": 7},
         "on_expiry": "erase-eligible"},
    ],
}


class RetentionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("scripts", "evaluation", "raw/sources", "wiki",
                  "staging", "exports"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPTS / "wiki_retention.py",
                    self.root / "scripts" / "wiki_retention.py")
        self.script = self.root / "scripts" / "wiki_retention.py"
        (self.root / "evaluation" / "retention-policy.json").write_text(
            json.dumps(POLICY), encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Retention Tests")
        for rel in ("raw/sources/keep.md", "staging/old-note.md",
                    "exports/bundle.md", "wiki/page.md"):
            self.write(rel, f"contents of {rel}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "first", date="2030-01-01")
        self.write("staging/new-note.md", "newer staging note\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "second", date="2030-01-09")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def git(self, *args, date=None):
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = f"{date}T12:00:00"
            env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00"
        subprocess.run(["git", "-C", str(self.root), *args],
                       check=True, env=env, capture_output=True,
                       text=True)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True)

    # -- glob + classification (direct module import) ---------

    def load_module(self):
        spec = importlib.util.spec_from_file_location(
            "wiki_retention_fixture", self.script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_glob_semantics(self):
        mod = self.load_module()
        m = mod.glob_to_regex("wiki/**/*.md")
        self.assertTrue(m.match("wiki/index.md"))
        self.assertTrue(m.match("wiki/a/b/c.md"))
        self.assertFalse(m.match("wiki/a/b.txt"))
        m = mod.glob_to_regex("evaluation/*.jsonl")
        self.assertTrue(m.match("evaluation/x.jsonl"))
        self.assertFalse(m.match("evaluation/sub/x.jsonl"))
        m = mod.glob_to_regex("raw/**")
        self.assertTrue(m.match("raw/anything/at/all.bin"))

    def test_first_match_wins(self):
        mod = self.load_module()
        policy = mod.load_policy(
            self.root / "evaluation" / "retention-policy.json")
        classes = policy["classes"]
        self.assertEqual(
            mod.classify("raw/sources/x.md", classes)["name"],
            "raw-sources")
        self.assertEqual(
            mod.classify("raw/other.md", classes)["name"], "raw-layer")
        self.assertIsNone(mod.classify("scripts/tool.py", classes))

    # -- check -------------------------------------------------

    def test_check_stamps_expired_with_rule_and_date(self):
        r = self.run_cli("check", "--as-of", "2030-01-12")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("EXPIRED  staging/old-note.md", r.stdout)
        self.assertIn("rule staging-notes/review-after-7d", r.stdout)
        self.assertIn("filed 2030-01-01 (git)", r.stdout)
        self.assertIn("expiry 2030-01-08", r.stdout)
        self.assertIn("action: review", r.stdout)
        self.assertIn("EXPIRED  exports/bundle.md", r.stdout)
        self.assertIn("action: erase-eligible", r.stdout)
        # Filed 2030-01-09, expires 2030-01-16: not yet.
        self.assertNotIn("EXPIRED  staging/new-note.md", r.stdout)
        # keep-forever classes never appear as expired.
        self.assertNotIn("EXPIRED  raw/sources/keep.md", r.stdout)
        self.assertNotIn("EXPIRED  wiki/page.md", r.stdout)
        self.assertIn("2 expired", r.stdout)

    def test_check_nothing_expired_exit_0(self):
        r = self.run_cli("check", "--as-of", "2030-01-05")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 expired", r.stdout)

    def test_check_is_a_report_only(self):
        before = {p: p.read_bytes() for p in
                  self.root.rglob("*") if p.is_file()
                  and ".git" not in p.parts}
        self.run_cli("check", "--as-of", "2027-01-01")
        after = {p: p.read_bytes() for p in
                 self.root.rglob("*") if p.is_file()
                 and ".git" not in p.parts}
        self.assertEqual(before, after)

    def test_untracked_file_falls_back_to_mtime(self):
        self.write("staging/loose.md", "never committed\n")
        r = self.run_cli("check", "--as-of", "2999-01-01")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("EXPIRED  staging/loose.md", r.stdout)
        self.assertIn("(mtime)", r.stdout)

    # -- policy validation --------------------------------------

    def test_bad_policy_is_usage_error(self):
        bad = json.loads(json.dumps(POLICY))
        bad["classes"][3]["retention"] = {"kind": "shred-after",
                                           "period_days": 7}
        (self.root / "evaluation" / "retention-policy.json").write_text(
            json.dumps(bad), encoding="utf-8")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("retention kind", r.stdout + r.stderr)

    def test_policy_command_lists_classes(self):
        r = self.run_cli("policy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("staging-notes", r.stdout)
        self.assertIn("first match wins", r.stdout)

    # -- recall --------------------------------------------------

    def test_recall_holds_and_absences(self):
        r = self.run_cli("recall", "--as-of", "2030-01-05")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("raw/sources/keep.md", r.stdout)
        self.assertIn("staging/old-note.md", r.stdout)
        self.assertNotIn("staging/new-note.md", r.stdout)
        self.assertIn("bi-temporal", r.stdout)

    def test_recall_marks_already_expired(self):
        r = self.run_cli("recall", "--as-of", "2030-01-12")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("staging/new-note.md", r.stdout)
        line = next(ln for ln in r.stdout.splitlines()
                    if "staging/old-note.md" in ln)
        self.assertIn("EXPIRED (expiry 2030-01-08)", line)

    def test_recall_before_first_commit(self):
        r = self.run_cli("recall", "--as-of", "2029-12-31")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("held nothing yet", r.stdout)


if __name__ == "__main__":
    unittest.main()
