#!/usr/bin/env python3
"""Tests for scripts/wiki_decision_watch.py
(consolidated-queue item 38 + the wave-10 watch fold-in).

Pins the contract on a FIXTURE git repo in a temp dir:

  - the sidecar register is hash-chained: verify passes
    on the authored fixture and check reports a BROKEN
    chain (exit 1) after a line is altered;
  - check evaluates the mechanical trip tests:
    register-form (CLEAR on the authored form, TRIPPED
    after the register's current_form moves), branch-
    scope (CLEAR in-area, TRIPPED out-of-area, MANUAL
    when the branch ref is absent), git-remote (TRIPPED
    when a second remote appears), git-object (CLEAR for
    a live commit, TRIPPED for a missing one), path-
    exists / path-absent;
  - a condition the machinery cannot evaluate is
    reported MANUAL, never silently CLEAR;
  - nothing tripped → exit 0; any trip → exit 1;
    --report always exits 0.

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
TOOL = "wiki_decision_watch.py"

ENV = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@x",
       "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "f@x",
       "GIT_AUTHOR_DATE": "2030-01-01T10:00:00Z",
       "GIT_COMMITTER_DATE": "2030-01-01T10:00:00Z"}


def git(root, *args):
    env = dict(os.environ)
    env.update(ENV)
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, env=env,
                          check=True)


def load_tool(repo):
    spec = importlib.util.spec_from_file_location(
        "wiki_decision_watch_fixture", repo / "scripts" / TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WatchFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-watch-"))
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / TOOL, self.repo / "scripts" / TOOL)
        (self.repo / "evaluation").mkdir(parents=True)
        (self.repo / "wiki" / "syntheses").mkdir(parents=True)
        self.mod = load_tool(self.repo)
        # decisions register with two decisions
        self.register = [
            {"kind": "header", "register": "decisions-register"},
            {"kind": "decision", "id": "fx-d1", "title": "Branch seat",
             "status": "active", "decided": "2030-01-01",
             "current_form": "The seat is OPEN.",
             "superseded_forms": []},
            {"kind": "decision", "id": "fx-d2", "title": "Home",
             "status": "active", "decided": "2030-01-01",
             "current_form": "Home is the fixture repo.",
             "superseded_forms": []},
        ]
        self.write_register()
        (self.repo / "evaluation" / "decision-basis.json").write_text(
            json.dumps({"kind": "decision-basis", "decisions": [
                {"id": "fx-d1", "basis": [
                    {"path": "wiki/syntheses/decisions.md"}]},
                {"id": "fx-d2", "basis": [
                    {"path": "wiki/syntheses/decisions.md"}]},
            ]}), encoding="utf-8")
        (self.repo / "wiki" / "syntheses" / "decisions.md").write_text(
            "# Decisions\n")
        # a git repo with an azure remote + a branch
        git(self.repo, "init", "-b", "master")
        git(self.repo, "remote", "add", "azure",
            "git@ssh.dev.azure.com:v3/fixture/fixture/fixture")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "base")
        self.head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "branch", "agent/filings")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_register(self):
        (self.repo / "evaluation" / "decisions-register.jsonl") \
            .write_text("".join(json.dumps(o) + "\n"
                                for o in self.register),
                        encoding="utf-8")

    def author(self, watches_d1, watches_d2=()):
        """Write the sidecar with correct hashes + chain,
        using the tool's own helpers (as the real authoring
        did)."""
        decisions = self.mod.load_decisions(self.repo)
        path = self.repo / "evaluation" / "decision-watches.jsonl"
        if path.exists():
            path.unlink()
        path.write_text(json.dumps(
            {"kind": "header", "register": "decision-watches"})
            + "\n", encoding="utf-8")
        for did, watches in (("fx-d1", watches_d1),
                             ("fx-d2", watches_d2)):
            self.mod.append_chained(path, {
                "kind": "watch", "decision": did,
                "title": decisions[did]["title"],
                "recorded": "2030-01-02", "recorded_by": "agent",
                "basis_files": ["wiki/syntheses/decisions.md"],
                "form_sha256": self.mod.form_sha256(decisions[did]),
                "linchpin": "L", "key_assumptions": [],
                "watches": list(watches),
            })

    def check(self, *extra):
        return subprocess.run(
            [sys.executable, str(self.repo / "scripts" / TOOL),
             "--root", str(self.repo), "check", *extra],
            capture_output=True, text=True)

    # -- chain ------------------------------------------------------

    def test_chain_verifies_and_detects_tamper(self):
        self.author([{"id": "fx-d1-w0", "condition": "form",
                      "trip_test": {"kind": "register-form"}}])
        v = subprocess.run(
            [sys.executable, str(self.repo / "scripts" / TOOL),
             "--root", str(self.repo), "verify"],
            capture_output=True, text=True)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        path = self.repo / "evaluation" / "decision-watches.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[1])
        obj["linchpin"] = "quietly rewritten"
        lines[1] = json.dumps(obj, sort_keys=True,
                              separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = self.check()
        self.assertEqual(out.returncode, 1)
        self.assertIn("CHAIN BROKEN", out.stdout)

    # -- register-form ----------------------------------------------

    def test_form_clear_then_trips_on_re_ruling(self):
        self.author([{"id": "fx-d1-w0", "condition": "form changes",
                      "trip_test": {"kind": "register-form"}}])
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("0 tripped", out.stdout)
        self.register[1]["current_form"] = "The seat is CLOSED."
        self.write_register()
        out = self.check()
        self.assertEqual(out.returncode, 1)
        self.assertIn("TRIPPED fx-d1-w0", out.stdout)
        self.assertIn("form CHANGED", out.stdout)
        out = self.check("--report")
        self.assertEqual(out.returncode, 0)  # surfacing only

    # -- the mechanical kinds ----------------------------------------

    def test_branch_scope_clear_trips_and_manual(self):
        watch = {"id": "fx-d1-w1", "condition": "branch scope",
                 "trip_test": {"kind": "branch-scope",
                               "branch": "agent/filings",
                               "allowed_prefixes": ["raw/filings/"]}}
        self.author([watch])
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("1 clear", out.stdout)
        # an out-of-area file lands on the branch
        git(self.repo, "checkout", "agent/filings")
        (self.repo / "wiki" / "index.md").write_text("stray\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "out of area")
        git(self.repo, "checkout", "master")
        # the sidecar was swept into the branch commit by
        # `add -A` and left the worktree on checkout —
        # re-author it (same content, same register)
        self.author([watch])
        out = self.check()
        self.assertEqual(out.returncode, 1)
        self.assertIn("TRIPPED fx-d1-w1", out.stdout)
        # branch gone entirely → MANUAL, not CLEAR
        git(self.repo, "branch", "-D", "agent/filings")
        out = self.check()
        self.assertIn("MANUAL fx-d1-w1", out.stdout)

    def test_git_remote_trips_on_a_second_remote(self):
        watch = {"id": "fx-d2-w1", "condition": "remote set",
                 "trip_test": {"kind": "git-remote",
                               "expected_remotes": ["azure"],
                               "url_contains": {"azure":
                                                "fixture/fixture"}}}
        self.author([], [watch])
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        git(self.repo, "remote", "add", "elsewhere",
            "https://example.invalid/x.git")
        out = self.check()
        self.assertEqual(out.returncode, 1)
        self.assertIn("TRIPPED fx-d2-w1", out.stdout)

    def test_git_object_and_paths(self):
        watches = [
            {"id": "fx-d2-w1", "condition": "object lives",
             "trip_test": {"kind": "git-object", "ref": self.head}},
            {"id": "fx-d2-w2", "condition": "object gone",
             "trip_test": {"kind": "git-object",
                           "ref": "deadbeef" * 5}},
            {"id": "fx-d2-w3", "condition": "vault stays",
             "trip_test": {"kind": "path-absent",
                           "path": "raw/sources/vault"}},
            {"id": "fx-d2-w4", "condition": "stray stays away",
             "trip_test": {"kind": "path-exists",
                           "path": "raw/copy-folder"}},
        ]
        (self.repo / "raw" / "sources" / "vault").mkdir(
            parents=True)
        self.author([], watches)
        out = self.check()
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("TRIPPED fx-d2-w2", out.stdout)
        self.assertNotIn("TRIPPED fx-d2-w1", out.stdout)
        self.assertNotIn("TRIPPED fx-d2-w3", out.stdout)
        self.assertNotIn("TRIPPED fx-d2-w4", out.stdout)

    def test_manual_is_reported_never_clear(self):
        self.author([{"id": "fx-d1-w9", "condition": "owner rules",
                      "trip_test": {"kind": "manual",
                                    "evidence": "read the log"}}])
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("MANUAL fx-d1-w9", out.stdout)
        self.assertIn("1 manual", out.stdout)


if __name__ == "__main__":
    unittest.main()
