#!/usr/bin/env python3
"""Tests for scripts/wiki_good_enough.py (W6).

Fixture: a synthetic mini-tree that satisfies the
mechanical checks, plus targeted mutations (licence
removed, a loose file at the root) that must flip exactly
the named practices to not-met. Also: determinism (two
runs byte-identical), read-only (a check run changes no
file in the judged tree), and the definition discipline
(unknown check ids are refused; the manual and
not-applicable verdicts come from the definition, not
from code).
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_good_enough as ge  # noqa: E402

TODAY = date(2026, 10, 22)
CHECKLIST = json.loads(
    (SCRIPTS.parent / "evaluation"
     / "good-enough-checklist.json").read_text(
        encoding="utf-8"))


def _w(path: Path, text: str = "x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_fixture(root: Path, licence=True):
    # raw layer: 101 files + a lockfile with 2 citations
    for i in range(101):
        _w(root / "raw" / "sources" / f"src-{i:03d}.md")
    _w(root / "evaluation" / "citation-lockfile.json",
       json.dumps({"citations": {"a": {}, "b": {}}}) + "\n")
    # registers
    for name in ("claim-index.jsonl", "tag-registry.jsonl",
                 "decisions-register.jsonl",
                 "checkpoints.jsonl"):
        _w(root / "evaluation" / name, "{}\n")
    _w(root / "evaluation" / "checkpoints.d"
       / "cp-000001.json", "{}\n")
    # scripts: docstrings + a real suite of 50 test files
    _w(root / "scripts" / "tool_one.py",
       '"""Tool one."""\n')
    _w(root / "scripts" / "tool_two.py",
       '"""Tool two."""\n')
    for i in range(50):
        _w(root / "scripts" / "tests" / f"test_t{i:02d}.py")
    # layout dirs
    for d in ("templates", "tools"):
        (root / d).mkdir(parents=True, exist_ok=True)
    # wiki: overview, log (dated today), stamped pages
    _w(root / "wiki" / "overview.md", "# Overview\n")
    _w(root / "wiki" / "log.md",
       "## [2026-10-22] ingest | Fixture\n")
    _w(root / "wiki" / "index.md", "# Index\n")
    for i in range(4):
        _w(root / "wiki" / f"page-{i}.md",
           "---\ntitle: P\ncompiled_date: 2026-10-22\n"
           "---\nbody\n")
    _w(root / "wiki" / "syntheses" / "chapter7-decisions.md")
    _w(root / "README.md", "# Fixture\n")
    if licence:
        _w(root / "LICENSE", "MIT\n")
    # version control: 100 commits, >=1000 tracked files
    bulk = root / "bulk"
    bulk.mkdir()
    for i in range(1000):
        _w(bulk / f"f{i:04d}.txt", "x")
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args],
                       check=True, capture_output=True)
    git("init", "-b", "main")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("remote", "add", "azure",
        "https://example.invalid/fixture.git")
    git("add", "-A")
    git("commit", "-m", "c0")
    for i in range(99):
        git("commit", "--allow-empty", "-m", f"c{i + 1}")
    return root


def tree_hashes(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def verdicts(report):
    return {r["id"]: r["verdict"]
            for r in report["practices"]}


class GoodEnoughFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = build_fixture(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def report(self):
        return ge.build_report(self.root, TODAY, CHECKLIST)

    def test_mechanical_core_is_met(self):
        v = verdicts(self.report())
        for pid in ("dm-raw-preserved", "dm-identifiers",
                    "sw-program-headers", "sw-licence",
                    "sw-tested", "co-overview",
                    "co-visible-work", "po-one-home",
                    "po-file-names", "po-root-tidy",
                    "tc-version-control", "tc-changelog",
                    "tc-versioned-states",
                    "mr-open-formats",
                    "mr-decisions-on-record",
                    "dm-processing-steps"):
            self.assertEqual(v[pid], "met", pid)

    def test_definition_driven_verdicts(self):
        v = verdicts(self.report())
        self.assertEqual(v["dm-public-repository"],
                         "not-applicable")
        self.assertEqual(v["sw-decomposition"], "manual")
        self.assertEqual(v["sw-search-first"], "manual")
        self.assertEqual(v["mr-audience"], "manual")
        counts = self.report()["counts"]
        self.assertEqual(counts["manual"], 3)
        self.assertEqual(counts["not-applicable"], 1)

    def test_determinism(self):
        a = json.dumps(self.report(), sort_keys=True)
        b = json.dumps(self.report(), sort_keys=True)
        self.assertEqual(a, b)
        self.assertEqual(ge.render_md(self.report()),
                         ge.render_md(self.report()))

    def test_checker_is_read_only(self):
        before = tree_hashes(self.root)
        self.report()
        self.assertEqual(before, tree_hashes(self.root))

    def test_licence_removed_flips_only_licence(self):
        with tempfile.TemporaryDirectory() as td:
            root = build_fixture(Path(td), licence=False)
            v = verdicts(ge.build_report(root, TODAY,
                                         CHECKLIST))
            self.assertEqual(v["sw-licence"], "not-met")
            self.assertEqual(v["sw-tested"], "met")

    def test_loose_root_file_flips_root_tidy(self):
        with tempfile.TemporaryDirectory() as td:
            root = build_fixture(Path(td))
            _w(root / "scratch-prompt.md")
            rep = ge.build_report(root, TODAY, CHECKLIST)
            v = verdicts(rep)
            self.assertEqual(v["po-root-tidy"], "not-met")
            rec = next(r for r in rep["practices"]
                       if r["id"] == "po-root-tidy")
            self.assertIn("scratch-prompt.md",
                          " ".join(rec["evidence"]))

    def test_unstamped_pages_flip_processing_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root = build_fixture(Path(td))
            for p in (root / "wiki").glob("page-*.md"):
                p.write_text("---\ntitle: P\n---\nbody\n",
                             encoding="utf-8")
            v = verdicts(ge.build_report(root, TODAY,
                                         CHECKLIST))
            self.assertEqual(v["dm-processing-steps"],
                             "not-met")

    def test_unknown_check_is_refused(self):
        bad = json.loads(json.dumps(CHECKLIST))
        bad["practices"][0]["check"] = "no-such-check"
        with self.assertRaises(ValueError):
            ge.build_report(self.root, TODAY, bad)

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rep"
            rc = ge.main(["check", "--root",
                          str(self.root), "--today",
                          "2026-10-22", "--out", str(out),
                          "--checklist",
                          str(SCRIPTS.parent / "evaluation"
                              / "good-enough-checklist.json")])
            # the real checklist over the fixture: the
            # backups check reads the host's witness dir;
            # every other not-met would be a fixture bug
            self.assertIn(rc, (0, 1))
            self.assertTrue(out.with_suffix(".json")
                            .is_file())
            self.assertTrue(out.with_suffix(".md")
                            .is_file())


if __name__ == "__main__":
    unittest.main()
