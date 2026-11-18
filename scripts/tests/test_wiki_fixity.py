#!/usr/bin/env python3
"""Tests for scripts/wiki_fixity.py — the cross-copy fixity poll
(consolidated queue item 24, 2030-10-20).

Fixture strategy: a real temp git repo (the poll's git seams are
exercised, not mocked), a bare clone standing in for the Azure
remote, and hand-built zips — one faithful to the fixture HEAD,
one with a member's bytes altered, so DIVERGE must name that
member. UNREACHABLE is exercised with a remote path that does
not exist. The pure comparison + sampling functions are tested
directly.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_fixity_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_fixity_under_test", SCRIPTS / "wiki_fixity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx = load_fixity_module()


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FixtureRepo(unittest.TestCase):
    """A tiny wiki-shaped repo + a bare remote + zips of it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="fixity-test-")
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "master")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Fixture")
        _write(self.repo / "wiki/rules/rule-one.md", "rule one\n")
        _write(self.repo / "wiki/pages/page-a.md", "page a body\n")
        _write(self.repo / "evaluation/reg.jsonl", '{"a": 1}\n')
        _write(self.repo / "README.md", "fixture\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "fixture commit")
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        # A bare clone stands in for the canonical remote.
        self.bare = self.base / "remote.git"
        subprocess.run(["git", "clone", "-q", "--bare",
                        str(self.repo), str(self.bare)],
                       check=True, capture_output=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_zip(self, alter=None):
        """Zip the working tree (prefix fxwiki/) + the .git dir,
        exactly the nightly job's shape. `alter` = {relpath: bytes}
        overrides a member's content."""
        zpath = self.base / "takehome.zip"
        alter = alter or {}
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(self.repo.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(self.repo).as_posix()
                arc = f"fxwiki/{rel}"
                if rel in alter:
                    zf.writestr(arc, alter[rel])
                else:
                    zf.write(p, arc)
        return zpath


class TestCompareHashes(unittest.TestCase):
    def test_agree(self):
        verdict, div = fx.compare_hashes({"a": "1", "b": "2"},
                                         {"a": "1", "b": "2"})
        self.assertEqual(verdict, "AGREE")
        self.assertEqual(div, [])

    def test_divergence_is_named(self):
        verdict, div = fx.compare_hashes({"a": "1"}, {"a": "9"})
        self.assertEqual(verdict, "DIVERGE")
        self.assertEqual([d["path"] for d in div], ["a"])
        self.assertEqual(div[0]["reason"], "bytes differ")

    def test_missing_member_is_named(self):
        verdict, div = fx.compare_hashes({}, {"a": "1"})
        self.assertEqual(verdict, "DIVERGE")
        self.assertEqual(div[0]["reason"], "missing from zip")


class TestChooseSample(unittest.TestCase):
    def test_always_classes_included_and_deterministic(self):
        tracked = ([f"wiki/pages/p{i:03}.md" for i in range(200)]
                   + ["wiki/rules/r1.md", "evaluation/a.jsonl",
                      "evaluation/b.jsonl", "evaluation/c.md"])
        s1 = fx.choose_sample(tracked, target=10)
        s2 = fx.choose_sample(list(reversed(tracked)), target=10)
        self.assertEqual(s1, s2)                      # deterministic
        self.assertIn("wiki/rules/r1.md", s1)         # rules always in
        self.assertIn("evaluation/a.jsonl", s1)       # jsonl always in
        self.assertNotIn("evaluation/c.md", s1[:3])   # not an always class
        self.assertLess(len(s1), 40)                  # bounded


class TestPoll(FixtureRepo):
    def test_all_copies_agree(self):
        report = fx.poll(self.repo, zip_path=self._make_zip(),
                         remote=str(self.bare))
        self.assertEqual(report["classes"]["head_equality"]["verdict"],
                         "AGREE")
        self.assertEqual(report["classes"]["zip_fidelity"]["verdict"],
                         "AGREE")
        self.assertEqual(report["overall"], "AGREE")

    def test_altered_member_diverges_and_is_named(self):
        zpath = self._make_zip(alter={"wiki/rules/rule-one.md":
                                      b"tampered\n"})
        report = fx.poll(self.repo, zip_path=zpath,
                         remote=str(self.bare))
        fid = report["classes"]["zip_fidelity"]
        self.assertEqual(fid["verdict"], "DIVERGE")
        named = [d["path"] for d in fid["divergent"]]
        self.assertIn("wiki/rules/rule-one.md", named)
        self.assertEqual(report["overall"], "DIVERGE")

    def test_unreachable_remote(self):
        report = fx.poll(self.repo, zip_path=self._make_zip(),
                         remote=str(self.base / "no-such-remote.git"))
        self.assertEqual(report["classes"]["head_equality"]["verdict"],
                         "UNREACHABLE")
        self.assertEqual(report["overall"], "UNREACHABLE")

    def test_zip_head_is_the_fixture_head(self):
        zpath = self._make_zip()
        head, _date, prefix = fx.zip_head_commit(
            zpath, self.base / "gz")
        self.assertEqual(head, self.head)
        self.assertEqual(prefix, "fxwiki/")


if __name__ == "__main__":
    unittest.main()
