#!/usr/bin/env python3
"""exocortex proposed lenses from un-filed sources (MIT pattern).

Pins, on a fixture tree only:
- a raw source named in a compiled page's frontmatter
  `sources:` (inline or block spelling) — or matched by a
  wiki/sources/ stem — is filed, and never proposed;
- >= 2 un-filed sources sharing a tag (verbatim) propose a
  lens with status "proposed"; a lone tagged source does not;
- untagged un-filed sources group by their raw collection;
- running with no --out writes NOTHING (the tree checksum is
  unchanged); with --out it writes exactly that file.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lp = _load("wiki_lens_propose")


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def checksums(root):
    return {p.relative_to(root).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class TestLensPropose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Filed by inline sources: and by block sources:.
        write(self.root, "wiki/sources/filed-one.md",
              "---\ntitle: Filed One\nsources: [raw/sources/filed-one.md]\n"
              "tags: []\n---\n\n# Filed One\n")
        write(self.root, "wiki/concepts/x.md",
              "---\ntitle: X\nsources:\n  - raw/sources/filed-two.md\n"
              "---\n\n# X\n")
        # Filed by wiki/sources stem match (filed-one above doubles).
        write(self.root, "raw/sources/filed-one.md", "# filed\n")
        write(self.root, "raw/sources/filed-two.md", "# filed\n")
        # Two un-filed sharing a verbatim tag.
        write(self.root, "raw/sources/garden-a.md",
              "---\ntags: [garden-notes]\n---\n\n# A\n")
        write(self.root, "raw/sources/garden-b.md",
              "---\ntags:\n  - garden-notes\n---\n\n# B\n")
        # One lone tagged source: no lens.
        write(self.root, "raw/sources/lone.md",
              "---\ntags: [solo-tag]\n---\n\n# Lone\n")
        # Two untagged in one collection directory.
        write(self.root, "raw/clippings/note-1.md", "# one\n")
        write(self.root, "raw/clippings/note-2.md", "# two\n")
        # A sidecar is not a source.
        write(self.root, "raw/sources/garden-a.md.annotations.jsonl",
              "{}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_excludes_filed(self):
        paths = [u["path"] for u in lp.scan_unfiled(self.root)]
        self.assertNotIn("raw/sources/filed-one.md", paths)
        self.assertNotIn("raw/sources/filed-two.md", paths)
        self.assertIn("raw/sources/garden-a.md", paths)
        self.assertFalse(any("annotations" in p for p in paths))

    def test_proposals(self):
        report = lp.build_report(self.root)
        names = {p["name"]: p for p in report["proposals"]}
        self.assertIn("garden-notes", names)
        self.assertEqual(names["garden-notes"]["status"], "proposed")
        self.assertEqual(names["garden-notes"]["basis"],
                         "shared tag (verbatim)")
        self.assertEqual(names["garden-notes"]["members"],
                         ["raw/sources/garden-a.md",
                          "raw/sources/garden-b.md"])
        self.assertIn("clippings", names)
        self.assertNotIn("solo-tag", names)
        self.assertIn("raw/sources/lone.md", report["ungrouped"])

    def test_no_out_writes_nothing_out_writes_one_file(self):
        before = checksums(self.root)
        self.assertEqual(lp.main(["--root", str(self.root)]), 0)
        self.assertEqual(checksums(self.root), before)
        out = self.root / "staging" / "lens-proposals.md"
        self.assertEqual(
            lp.main(["--root", str(self.root), "--out", str(out)]), 0)
        after = checksums(self.root)
        added = set(after) - set(before)
        self.assertEqual(added, {"staging/lens-proposals.md"})
        self.assertIn("Proposed lens: garden-notes",
                      out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
