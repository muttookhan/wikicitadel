"""Tests for scripts/wiki_source_registry.py (Marathon Round 4,
lane B, item 3 -- the Korpora-style registry over raw/sources).

Pins: one manifest over the collections (each immediate
subdirectory is a collection; loose files form "loose-files");
per-collection path pattern, file count and total bytes against
the fixture's known contents; the licence is read ONLY from the
collection's own records (a LICENSE file, then a licence field)
and is null -- never inferred -- when none is recorded; the
load entry point names the load command, and `load` prints the
collection's sorted file list; an unknown collection exits 2;
the compiled page renders from the registry dict alone and
carries full frontmatter plus every collection's numbers.

Run:  python3 -m unittest discover -s scripts/tests
Fixture trees are built in temp dirs; the live corpus is never
touched.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_source_registry",
    ROOT / "scripts" / "wiki_source_registry.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def fixture(tmp):
    root = Path(tmp)
    _write(root, "raw/sources/alpha-notes/a.md", "alpha one\n")
    _write(root, "raw/sources/alpha-notes/deep/b.md", "alpha two\n")
    _write(root, "raw/sources/alpha-notes/LICENSE",
           "MIT License\n\nCopyright (c) 2026 Demo\n")
    _write(root, "raw/sources/beta-data/data.json",
           '{"name": "beta", "license": "CC-BY-4.0"}\n')
    _write(root, "raw/sources/beta-data/rows.csv", "x,y\n1,2\n")
    _write(root, "raw/sources/loose-one.md", "loose\n")
    return root


def by_name(registry):
    return {c["name"]: c for c in registry["collections"]}


class RegistryTests(unittest.TestCase):
    def test_collections_counts_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            reg = mod.build_registry(root)
            cols = by_name(reg)
            self.assertEqual(set(cols), {"alpha-notes", "beta-data",
                                         "loose-files"})
            a = cols["alpha-notes"]
            self.assertEqual(a["file_count"], 3)
            self.assertEqual(a["path_pattern"],
                             "raw/sources/alpha-notes/**")
            expect = sum(p.stat().st_size for p in
                         (root / "raw/sources/alpha-notes")
                         .rglob("*") if p.is_file())
            self.assertEqual(a["total_bytes"], expect)
            self.assertEqual(cols["loose-files"]["path_pattern"],
                             "raw/sources/*")
            self.assertEqual(cols["loose-files"]["file_count"], 1)
            self.assertEqual(reg["totals"]["files"], 6)

    def test_licence_from_own_records_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            cols = by_name(mod.build_registry(root))
            self.assertEqual(cols["alpha-notes"]["licence"],
                             "MIT License")
            self.assertTrue(cols["alpha-notes"]["licence_source"]
                            .endswith("alpha-notes/LICENSE"))
            self.assertEqual(cols["beta-data"]["licence"],
                             "CC-BY-4.0")
            # Nothing recorded in the loose files: null, never a
            # guessed default.
            self.assertIsNone(cols["loose-files"]["licence"])
            self.assertIsNone(cols["loose-files"]["licence_source"])

    def test_load_entry_point_and_file_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            cols = by_name(mod.build_registry(root))
            self.assertEqual(
                cols["beta-data"]["load_entry_point"],
                "python3 scripts/wiki_source_registry.py "
                "load beta-data")
            files = mod.load_collection(root, "alpha-notes")
            self.assertEqual(files, [
                "raw/sources/alpha-notes/LICENSE",
                "raw/sources/alpha-notes/a.md",
                "raw/sources/alpha-notes/deep/b.md",
            ])
            self.assertIsNone(mod.load_collection(root, "ghost"))

    def test_build_writes_json_and_load_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            code = mod.main(["--root", str(root), "build"])
            self.assertEqual(code, 0)
            data = json.loads((root / "evaluation" /
                               "source-catalog.json")
                              .read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "source-registry")
            self.assertEqual(data["totals"]["collections"], 3)
            self.assertEqual(
                mod.main(["--root", str(root), "load",
                          "beta-data"]), 0)
            self.assertEqual(
                mod.main(["--root", str(root), "load", "ghost"]), 2)

    def test_page_renders_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            reg = mod.build_registry(root)
            page = mod.render_page(reg)
            self.assertTrue(page.startswith("---\n"))
            for field in ("title:", "type: synthesis", "created:",
                          "updated:", "sources:", "tags:"):
                self.assertIn(field, page)
            self.assertIn("alpha-notes", page)
            self.assertIn("MIT License", page)
            self.assertIn("*not recorded*", page)


if __name__ == "__main__":
    unittest.main()
