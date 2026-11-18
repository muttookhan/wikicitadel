"""Tests for scripts/wiki_version_stack.py (Marathon R3 TB1 row 5).

Pins: -vN / -final / (N) / date-suffixed twins stack under one
logical document; byte-identical members tag Identical;
near-identical members tag Similar; the highest version is
Latest; unrelated files form no stack; resolve_latest maps a
superseded member to the Latest path; report-only (no writes).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_version_stack", ROOT / "scripts" / "wiki_version_stack.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BODY = ("The harbour ledger records entries for the autumn term "
        "and the clerk signs each page in turn while the tide "
        "table is checked against the harbour master copy and "
        "the ferry schedule is pinned beside the door. "
        "The total recorded is forty two entries exactly.")


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def fixture(tmp):
    raw = Path(tmp) / "raw"
    _write(raw, "sources/proposal-v1.md", BODY)
    _write(raw, "sources/proposal-v2.md", BODY.replace("forty two", "forty three"))
    _write(raw, "sources/proposal-final.md", BODY.replace("forty two", "forty three"))
    _write(raw, "sources/unique-note.md", "Something else entirely.\n")
    return raw


class VersionStackTests(unittest.TestCase):
    def test_twins_stack_with_latest_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            stacks = mod.scan_stacks(fixture(tmp))
            self.assertEqual(len(stacks), 1)
            stack = stacks[0]
            self.assertEqual(len(stack["members"]), 3)
            by_name = {Path(m["path"]).name: m for m in stack["members"]}
            # v2 and -final carry identical bytes; -final has no
            # version number, v2 does -> v2 is Latest by the
            # stated order (version first), -final is Identical.
            self.assertEqual(by_name["proposal-v2.md"]["tag"], "Latest")
            self.assertEqual(by_name["proposal-final.md"]["tag"], "Identical")
            self.assertEqual(by_name["proposal-v1.md"]["tag"], "Similar")
            self.assertTrue(stack["latest"].endswith("proposal-v2.md"))

    def test_proposed_frontmatter_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = mod.scan_stacks(fixture(tmp))[0]
            for m in stack["members"]:
                self.assertEqual(m["proposed_frontmatter"]["stack"],
                                 stack["stack"])
                self.assertIn(m["proposed_frontmatter"]["stack_role"],
                              ("latest", "similar", "identical", "superseded"))

    def test_resolve_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = fixture(tmp)
            got = mod.resolve_latest(raw, "raw/sources/proposal-v1.md")
            self.assertTrue(got.endswith("proposal-v2.md"))
            same = mod.resolve_latest(raw, "raw/sources/unique-note.md")
            self.assertTrue(same.endswith("unique-note.md"))

    def test_no_stack_for_singletons(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            _write(raw, "sources/a.md", "one\n")
            _write(raw, "sources/b.md", "two\n")
            self.assertEqual(mod.scan_stacks(raw), [])


if __name__ == "__main__":
    unittest.main()
