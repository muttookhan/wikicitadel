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


class BundleFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        wiki = self.root / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "b-page.md").write_text(
            "---\ntitle: Beta page\n---\n\n# Beta\n\nBeta body text.\n",
            encoding="utf-8")
        (wiki / "a-page.md").write_text(
            "# Alpha\n\nAlpha body with a <script>alert(1)</script> "
            "payload.\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()


class TestBundle(BundleFixture):
    def test_bundle_has_index_and_full_texts(self):
        text, pages = wiki_sync.build_bundle(self.root)
        self.assertEqual([p["path"] for p in pages],
                         ["wiki/concepts/a-page.md",
                          "wiki/concepts/b-page.md"])
        self.assertIn("Beta page", text)       # frontmatter title
        self.assertIn("Alpha body", text)       # full page text
        self.assertIn("Beta body text.", text)
        self.assertIn('href="#p0"', text)
        self.assertIn('href="#p1"', text)

    def test_bundle_deterministic(self):
        self.assertEqual(wiki_sync.build_bundle(self.root)[0],
                         wiki_sync.build_bundle(self.root)[0])

    def test_bundle_no_external_assets_and_search_inline(self):
        text, _ = wiki_sync.build_bundle(self.root)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("<link", text)
        self.assertNotIn("src=", text)
        self.assertIn('id="q"', text)          # in-page search box
        self.assertIn("addEventListener", text)  # inline script only

    def test_bundle_escapes_page_text(self):
        text, _ = wiki_sync.build_bundle(self.root)
        self.assertIn("&lt;script&gt;alert(1)", text)
        self.assertNotIn("<script>alert(1)</script>", text)

    def test_cmd_bundle_writes_one_file(self):
        out = self.root / "out.html"
        rc = wiki_sync.cmd_bundle(self.root, out)
        self.assertEqual(rc, 0)
        self.assertTrue(out.is_file())
        self.assertIn("Alpha", out.read_text(encoding="utf-8"))


class TestBundleConflictRefusal(SyncFixture):
    def test_bundle_refused_while_conflicted(self):
        self.commit_push(self.a, "alpha\n", "alpha")
        wiki_sync.cmd_pull(self.b, "origin")
        (self.a / "f.md").write_text("A-side\n", encoding="utf-8")
        sh(self.a, "add", "f.md"); sh(self.a, "commit", "-m", "a-side")
        sh(self.a, "push", "origin", "HEAD:master")
        (self.b / "f.md").write_text("B-side\n", encoding="utf-8")
        sh(self.b, "add", "f.md"); sh(self.b, "commit", "-m", "b-side")
        sh(self.b, "fetch", "origin")
        subprocess.run(["git", "-C", str(self.b), "merge", "origin/master"],
                       capture_output=True)
        self.assertIn("f.md", wiki_sync.conflicted_paths(self.b))
        out = self.b / "bundle.html"
        rc = wiki_sync.cmd_bundle(self.b, out)
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
