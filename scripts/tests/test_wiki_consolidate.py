#!/usr/bin/env python3
"""Tests for scripts/wiki_consolidate.py (Marathon R3 TA5;
LightMem topic-segmented sleep-time consolidation).

Pins, on a FIXTURE tree in a temp dir:
  - a raw file claimed in a compiled page's `sources:` is
    NOT uncompiled; unclaimed files are, grouped by their
    raw/sources/<segment> directory;
  - files outside raw/sources/ segment by their raw/
    subdirectory; a loose file segments as "unsorted";
  - one proposal filing per segment is written, listing
    the segment's files, with a suggested target page;
  - PROPOSAL-ONLY: no raw file is moved, compiled or
    deleted — the raw tree is byte-identical afterwards.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_consolidate", root / "scripts" / "wiki_consolidate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConsolidate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="consolidate-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_consolidate.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        src = self.tmp / "raw" / "sources"
        (src / "harbour-notes").mkdir(parents=True)
        (src / "orchard-notes").mkdir(parents=True)
        (src / "harbour-notes" / "tides.md").write_text(
            "Tide tables.", encoding="utf-8")
        (src / "harbour-notes" / "gulls.md").write_text(
            "Gull census.", encoding="utf-8")
        (src / "orchard-notes" / "pruning.md").write_text(
            "Pruning diary.", encoding="utf-8")
        (self.tmp / "raw" / "clips").mkdir(parents=True)
        (self.tmp / "raw" / "clips" / "loose-clip.md").write_text(
            "A clip.", encoding="utf-8")
        (self.tmp / "raw" / "stray.md").write_text(
            "Stray.", encoding="utf-8")
        wiki = self.tmp / "wiki" / "sources"
        wiki.mkdir(parents=True)
        (wiki / "tides-page.md").write_text(
            "---\ntitle: Tides\ntype: source\nsources:\n"
            "  - raw/sources/harbour-notes/tides.md\n---\n\n# Tides\n",
            encoding="utf-8")
        self.mod = load_module(self.tmp)
        self.raw_before = {
            str(p.relative_to(self.tmp)):
                hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.tmp / "raw").rglob("*") if p.is_file()}

    def test_uncompiled_grouping(self):
        groups = self.mod.uncompiled_by_segment(self.tmp)
        harbour = [f["path"] for f in groups["harbour-notes"]]
        self.assertEqual(harbour,
                         ["raw/sources/harbour-notes/gulls.md"])
        self.assertEqual([f["path"] for f in groups["orchard-notes"]],
                         ["raw/sources/orchard-notes/pruning.md"])
        self.assertEqual([f["path"] for f in groups["clips"]],
                         ["raw/clips/loose-clip.md"])
        self.assertEqual([f["path"] for f in groups["unsorted"]],
                         ["raw/stray.md"])

    def test_filings_per_segment_and_no_raw_change(self):
        manifest = self.mod.analyse(self.tmp)
        self.assertEqual(manifest["stats"]["uncompiled_files"], 4)
        written = self.mod.write_filings(self.tmp, manifest)
        md_files = [p for p in written if p.suffix == ".md"]
        self.assertEqual(len(md_files), 4)
        harbour = [p for p in md_files if "harbour-notes" in p.name][0]
        text = harbour.read_text(encoding="utf-8")
        self.assertIn("gulls.md", text)
        self.assertIn("PROPOSAL ONLY", text)
        raw_after = {
            str(p.relative_to(self.tmp)):
                hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.tmp / "raw").rglob("*") if p.is_file()}
        self.assertEqual(self.raw_before, raw_after)

    def test_segment_of(self):
        self.assertEqual(
            self.mod.segment_of("raw/sources/topic-x/f.md"), "topic-x")
        self.assertEqual(self.mod.segment_of("raw/clips/f.md"), "clips")
        self.assertEqual(self.mod.segment_of("raw/f.md"), "unsorted")


if __name__ == "__main__":
    unittest.main()
