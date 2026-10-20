#!/usr/bin/env python3
"""Tests for scripts/wiki_sync.py — temp git repos only, no network."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_sync  # noqa: E402


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


class SyncFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote = base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)],
                       capture_output=True, check=True)
        self.a = base / "a"
        subprocess.run(["git", "clone", str(self.remote), str(self.a)],
                       capture_output=True, check=True)
        sh(self.a, "config", "user.email", "a@example.invalid")
        sh(self.a, "config", "user.name", "A")
        (self.a / "f.md").write_text("one\n", encoding="utf-8")
        sh(self.a, "add", "f.md")
        sh(self.a, "commit", "-m", "init")
        sh(self.a, "push", "origin", "HEAD:master")
        sh(self.a, "branch", "--set-upstream-to=origin/master")
        self.b = base / "b"
        subprocess.run(["git", "clone", str(self.remote), str(self.b)],
                       capture_output=True, check=True)
        sh(self.b, "config", "user.email", "b@example.invalid")
        sh(self.b, "config", "user.name", "B")

    def tearDown(self):
        self.tmp.cleanup()

    def commit_push(self, repo, text, msg):
        (repo / "f.md").write_text(text, encoding="utf-8")
        sh(repo, "add", "f.md")
        sh(repo, "commit", "-m", msg)
        sh(repo, "push", "origin", "HEAD:master")


class TestSync(SyncFixture):
    def test_status_clean(self):
        st = wiki_sync.sync_state(self.b, "origin")
        self.assertEqual(st["ahead"], 0)
        self.assertEqual(st["behind"], 0)
        self.assertEqual(st["conflicts"], [])

    def test_pull_fast_forwards(self):
        self.commit_push(self.a, "two\n", "second")
        rc = wiki_sync.cmd_pull(self.b, "origin")
        self.assertEqual(rc, 0)
        self.assertEqual((self.b / "f.md").read_text(encoding="utf-8"), "two\n")

    def test_pull_diverged_refused(self):
        self.commit_push(self.a, "two\n", "second")
        (self.b / "f.md").write_text("local\n", encoding="utf-8")
        sh(self.b, "add", "f.md")
        sh(self.b, "commit", "-m", "local")
        rc = wiki_sync.cmd_pull(self.b, "origin")
        self.assertEqual(rc, 2)
        # untouched: still the local text, no merge attempted
        self.assertEqual((self.b / "f.md").read_text(encoding="utf-8"), "local\n")

    def test_conflict_surfaced(self):
        self.commit_push(self.a, "alpha\n", "alpha")
        wiki_sync.cmd_pull(self.b, "origin")
        # both sides now edit the same line from the same base
        (self.a / "f.md").write_text("A-side\n", encoding="utf-8")
        sh(self.a, "add", "f.md"); sh(self.a, "commit", "-m", "a-side")
        sh(self.a, "push", "origin", "HEAD:master")
        (self.b / "f.md").write_text("B-side\n", encoding="utf-8")
        sh(self.b, "add", "f.md"); sh(self.b, "commit", "-m", "b-side")
        sh(self.b, "fetch", "origin")
        subprocess.run(["git", "-C", str(self.b), "merge", "origin/master"],
                       capture_output=True)
        self.assertIn("f.md", wiki_sync.conflicted_paths(self.b))
        rc = wiki_sync.cmd_push(self.b, "origin")
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
