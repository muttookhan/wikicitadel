#!/usr/bin/env python3
"""Tests for scripts/wiki_release_block.py (build
wave 6, item W6: FAIR4RS release block + version-citation
machinery).

Pins:
  - determinism: same scope + version + date + tree →
    byte-identical block and release note;
  - the owner slots ship EMPTY (identifier unfilled,
    author/credit awaiting owner) and the generator has
    no way to fill them;
  - licence is DERIVED: a scope carrying an MIT licence
    file records MIT with the file's hash; a scope with
    no licence file records "none-recorded", never an
    asserted licence; a tampered licence claim fails
    check as licence-mismatch;
  - version markers the scope itself carries
    (server.json "version") bind the block: a mismatch
    fails check by file name;
  - scope integrity: a changed or missing scope file
    fails check (scope-hash-drift / scope-path-missing);
  - provenance: an unresolvable commit fails check;
  - invented values fail by name: an identifier value or
    a credit value without filled_by: owner →
    identifier-invented / credit-invented; the same
    values WITH filled_by: owner pass;
  - dependencies are derived from the code: stdlib
    imports classify python-stdlib, an external import
    is named, a sibling-tool delegation is recorded;
  - the citation entry cites the specific version;
  - one real-tree gate: the worked example block under
    exports/release-blocks/ checks clean against the
    live tree.

Run:  python3 -m unittest scripts.tests.\
test_wiki_release_block (or via discover)
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rb = _load("wiki_release_block")

MIT_TEXT = ("MIT License\n\nCopyright (c) <year> "
            "<copyright holders>\n\nPermission is hereby "
            "granted, free of charge, to any person "
            "obtaining a copy\n")


def _git(root: Path, *argv):
    subprocess.run(["git", "-C", str(root), *argv],
                   check=True, capture_output=True,
                   text=True)


class FixtureTree(unittest.TestCase):
    """A tiny synthetic tree: one tool dir with a
    server.json version marker, a stdlib-only module, an
    external import, a sibling delegation, and (in the
    licensed variant) a licence file."""

    def make_tree(self, licensed=True):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        tool = root / "tools" / "door"
        tool.mkdir(parents=True)
        (tool / "server.json").write_text(json.dumps({
            "name": "example/door", "version": "1.2.3",
            "repository": {
                "url": "https://example.invalid/door"}}),
            encoding="utf-8")
        (tool / "door.py").write_text(
            "from __future__ import annotations\n"
            "import helper\nimport json\nimport os\n"
            "import requests\n"
            "DELEGATE = 'scripts/wiki_search.py'\n",
            encoding="utf-8")
        (tool / "helper.py").write_text(
            "import sys\n", encoding="utf-8")
        if licensed:
            (tool / "LICENSE").write_text(
                MIT_TEXT, encoding="utf-8")
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "-c", "user.email=t@t", "-c",
             "user.name=t", "commit", "-qm", "fixture")
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        self.addCleanup(td.cleanup)
        return root, head

    def build(self, root, head, **kw):
        args = dict(title="Example Door", version="1.2.3",
                    date="2026-10-22", scope=["tools/door"],
                    commit=head)
        args.update(kw)
        return rb.build_block(root, **args)


class TestReleaseBlock(FixtureTree):

    def test_deterministic_bytes(self):
        root, head = self.make_tree()
        a = self.build(root, head)
        b = self.build(root, head)
        self.assertEqual(rb._dump(a), rb._dump(b))
        self.assertEqual(rb.render_md(a), rb.render_md(b))

    def test_owner_slots_ship_empty(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        self.assertIsNone(block["identifier"]["value"])
        self.assertEqual(block["identifier"]["status"],
                         "unfilled")
        for slot in ("author", "credit"):
            self.assertIsNone(block[slot]["value"])
            self.assertEqual(block[slot]["status"],
                             "awaiting-owner")
        self.assertIn("draft release block",
                      block["status"])

    def test_licence_derived_from_file(self):
        root, head = self.make_tree(licensed=True)
        block = self.build(root, head)
        lic = block["license"]
        self.assertEqual(lic["status"], "recorded")
        self.assertEqual(lic["spdx"], "MIT")
        self.assertEqual(lic["file"],
                         "tools/door/LICENSE")
        self.assertEqual(
            lic["sha256"],
            hashlib.sha256(
                (root / "tools/door/LICENSE")
                .read_bytes()).hexdigest())
        self.assertEqual(rb.check_block(root, block), [])

    def test_licence_absent_recorded_not_asserted(self):
        root, head = self.make_tree(licensed=False)
        block = self.build(root, head)
        self.assertEqual(block["license"]["status"],
                         "none-recorded")
        self.assertIsNone(block["license"]["spdx"])
        self.assertEqual(rb.check_block(root, block), [])
        block["license"] = {
            "status": "recorded", "file": "LICENSE",
            "sha256": "0" * 64,
            "name_as_carried": "MIT License",
            "spdx": "MIT"}
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("licence-mismatch")
            for f in findings), findings)

    def test_version_marker_binds(self):
        root, head = self.make_tree()
        block = self.build(root, head, version="9.9.9")
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("version-marker-mismatch:"
                         "tools/door/server.json")
            for f in findings), findings)

    def test_scope_drift_and_missing(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        (root / "tools/door/door.py").write_text(
            "import json\n", encoding="utf-8")
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("scope-hash-drift")
            for f in findings), findings)
        (root / "tools/door/door.py").unlink()
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("scope-path-missing")
            for f in findings), findings)

    def test_provenance_commit_must_resolve(self):
        root, head = self.make_tree()
        block = self.build(root, head, commit="0" * 40)
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("provenance-commit-unresolvable")
            for f in findings), findings)

    def test_invented_identifier_and_credit_fail(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        block["identifier"]["value"] = \
            "10.0000/invented"
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("identifier-invented")
            for f in findings), findings)
        block["identifier"]["filled_by"] = "owner"
        self.assertEqual(rb.check_block(root, block), [])
        block["author"]["value"] = "Somebody Invented"
        findings = rb.check_block(root, block)
        self.assertTrue(any(
            f.startswith("credit-invented:author")
            for f in findings), findings)
        block["author"]["filled_by"] = "owner"
        self.assertEqual(rb.check_block(root, block), [])

    def test_dependencies_derived(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        deps = {(d["name"], d["kind"])
                for d in block["dependencies"]}
        self.assertIn(("json", "python-stdlib"), deps)
        self.assertIn(("os", "python-stdlib"), deps)
        self.assertIn(("requests", "python-external"),
                      deps)
        self.assertIn(("helper", "in-scope-module"),
                      deps)
        self.assertNotIn("__future__",
                         {d["name"] for d in
                          block["dependencies"]})
        self.assertIn(("scripts/wiki_search.py",
                       "sibling-tool"), deps)
        self.assertEqual(block["runtime"]
                         ["externalPackages"], ["requests"])

    def test_citation_cites_the_version(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        self.assertIn("1.2.3",
                      block["citation"]["text"])
        self.assertEqual(block["citation"]
                         ["citesVersion"], "1.2.3")

    def test_related_identifier_as_recorded(self):
        root, head = self.make_tree()
        block = self.build(root, head)
        self.assertEqual(
            block["codeRepository"][0]["url"],
            "https://example.invalid/door")
        self.assertEqual(
            block["codeRepository"][0]["as_recorded_in"],
            "tools/door/server.json")


class TestWorkedExample(unittest.TestCase):

    def test_example_block_checks_clean(self):
        p = ROOT / "exports" / "release-blocks" / \
            "mcp-read" / "release-block.json"
        if not p.is_file():
            self.skipTest("worked example not generated "
                          "yet (see build note)")
        block = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(rb.check_block(ROOT, block), [])
        self.assertIsNone(block["identifier"]["value"])
        self.assertIsNone(block["author"]["value"])


if __name__ == "__main__":
    unittest.main()
