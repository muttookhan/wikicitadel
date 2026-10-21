"""Tests for scripts/wiki_blast_radius.py (Marathon R3 TB1 row 3).

Pins the dry-run contract: withdrawing a sole-support source
SEVERS its units (support set empties); a shared source's units
RE-VERIFY; pages citing a severed unit cascade; and the tool
changes NOTHING (fixture tree bytes identical before/after).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_blast_radius", ROOT / "scripts" / "wiki_blast_radius.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _page(title, sources, body="Body."):
    src = "\n".join(f"  - {s}" for s in sources)
    return f"---\ntitle: {title}\ntype: source\nsources:\n{src}\n---\n\n{body}\n"


def fixture(tmp):
    root = Path(tmp)
    _write(root, "raw/sources/sole.md", "sole\n")
    _write(root, "raw/sources/shared.md", "shared\n")
    _write(root, "raw/sources/other.md", "other\n")
    _write(root, "wiki/sources/only-sole.md",
           _page("OnlySole", ["raw/sources/sole.md"]))
    _write(root, "wiki/sources/both.md",
           _page("Both", ["raw/sources/shared.md", "raw/sources/other.md"]))
    _write(root, "wiki/concepts/reader.md",
           _page("Reader", ["raw/sources/other.md"],
                 body="Rests on [[sources/only-sole]]."))
    return root


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class BlastRadiusTests(unittest.TestCase):
    def test_sole_support_severs(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = mod.blast_radius(fixture(tmp), "raw/sources/sole.md")
            self.assertEqual([e["page"] for e in report["sever"]],
                             ["wiki/sources/only-sole.md"])
            self.assertEqual(report["sever"][0]["remaining"], [])

    def test_shared_support_reverifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = mod.blast_radius(fixture(tmp), "raw/sources/shared.md")
            self.assertEqual(report["sever"], [])
            self.assertEqual([e["page"] for e in report["reverify"]],
                             ["wiki/sources/both.md"])
            self.assertEqual(report["reverify"][0]["remaining"],
                             ["raw/sources/other.md"])

    def test_cascade_flags_citers_of_severed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = mod.blast_radius(fixture(tmp), "raw/sources/sole.md")
            self.assertEqual([e["page"] for e in report["cascade_reverify"]],
                             ["wiki/concepts/reader.md"])

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            before = tree_digest(root)
            mod.blast_radius(root, "raw/sources/sole.md")
            self.assertEqual(mod.main(
                ["--root", str(root), "--source", "raw/sources/sole.md"]), 0)
            self.assertEqual(tree_digest(root), before)

    def test_unknown_source_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mod.main(
                ["--root", str(fixture(tmp)),
                 "--source", "raw/sources/nope.md"]), 2)


if __name__ == "__main__":
    unittest.main()
