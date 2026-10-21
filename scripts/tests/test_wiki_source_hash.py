"""Tests for scripts/wiki_source_hash.py (Marathon R3 TB1 row 1).

Pins: snapshot/check round-trip on a clean fixture tree; a
changed source marks its page stale and BLOCKS (exit semantics
via report['blocking']); staleness propagates transitively
through wikilink citation edges (A stale -> B citing A stale ->
C citing B stale); a missing source blocks; an unregistered
source is reported but does not block; inline frontmatter
source_hashes are honoured without a register.

Run:  python3 -m unittest discover -s scripts/tests
Fixture trees are built in temp dirs; the live corpus is never
touched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_source_hash", ROOT / "scripts" / "wiki_source_hash.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _page(title, sources, body="Body."):
    src = "\n".join(f"  - {s}" for s in sources)
    return f"---\ntitle: {title}\ntype: source\nsources:\n{src}\n---\n\n{body}\n"


def fixture(tmp):
    root = Path(tmp)
    _write(root, "raw/sources/alpha.md", "alpha v1\n")
    _write(root, "raw/sources/beta.md", "beta v1\n")
    _write(root, "wiki/sources/a.md",
           _page("A", ["raw/sources/alpha.md"]))
    _write(root, "wiki/concepts/b.md",
           _page("B", ["raw/sources/beta.md"],
                 body="Builds on [[sources/a]]."))
    _write(root, "wiki/syntheses/c.md",
           _page("C", [], body="Uses [[concepts/b]] heavily."))
    return root


class SourceHashTests(unittest.TestCase):
    def test_clean_tree_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            report = mod.check(root, mod.build_register(root))
            self.assertFalse(report["blocking"])
            self.assertEqual(report["stale_pages"], [])

    def test_changed_source_blocks_and_propagates_transitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            register = mod.build_register(root)
            _write(root, "raw/sources/alpha.md", "alpha v2 CHANGED\n")
            report = mod.check(root, register)
            self.assertTrue(report["blocking"])
            self.assertTrue(report["publish_blocked"])
            self.assertEqual(report["stale_pages"], ["wiki/sources/a.md"])
            prop = {p["page"]: p["via"] for p in report["propagated"]}
            self.assertIn("wiki/concepts/b.md", prop)
            self.assertIn("wiki/syntheses/c.md", prop)
            self.assertEqual(prop["wiki/syntheses/c.md"],
                             ["wiki/sources/a.md", "wiki/concepts/b.md",
                              "wiki/syntheses/c.md"])

    def test_missing_source_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            register = mod.build_register(root)
            (root / "raw/sources/beta.md").unlink()
            report = mod.check(root, register)
            self.assertTrue(report["blocking"])
            self.assertIn("wiki/concepts/b.md", report["stale_pages"])
            self.assertTrue(any(d["status"] == "missing"
                                for d in report["direct"]))

    def test_unregistered_is_reported_not_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            report = mod.check(root, None)
            self.assertFalse(report["blocking"])
            self.assertGreater(report["summary"]["unregistered"], 0)

    def test_inline_frontmatter_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "raw/sources/alpha.md", "alpha v1\n")
            good = hashlib.sha256(b"alpha v1\n").hexdigest()
            _write(root, "wiki/sources/a.md",
                   "---\ntitle: A\ntype: source\n"
                   "sources: [raw/sources/alpha.md]\n"
                   "source_hashes:\n"
                   f"  raw/sources/alpha.md: {good}\n---\n\nBody.\n")
            self.assertFalse(mod.check(root, None)["blocking"])
            _write(root, "raw/sources/alpha.md", "tampered\n")
            self.assertTrue(mod.check(root, None)["blocking"])

    def test_snapshot_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            reg = root / "evaluation" / "source-hashes.json"
            self.assertEqual(mod.main(
                ["--root", str(root), "--register", str(reg), "snapshot"]), 0)
            self.assertTrue(reg.is_file())
            self.assertEqual(mod.main(
                ["--root", str(root), "--register", str(reg), "check"]), 0)
            _write(root, "raw/sources/beta.md", "beta v2\n")
            self.assertEqual(mod.main(
                ["--root", str(root), "--register", str(reg), "check"]), 1)


if __name__ == "__main__":
    unittest.main()
