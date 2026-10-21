#!/usr/bin/env python3
"""Tests for scripts/wiki_compile_watch.py (Marathon R3
TA5; KR-R1 threshold-triggered compile PROPOSALS).

Pins, on a FIXTURE tree in a temp dir (mtimes set with
os.utime, `now` injected — no wall-clock dependence):
  - an old uncompiled source crosses the age threshold and
    a large one crosses the size threshold, each with its
    reason stated;
  - a fresh small uncompiled source crosses nothing;
  - a COMPILED source (claimed in a page's `sources:`)
    never crosses, however old;
  - thresholds resolve flags > config > defaults;
  - filing writes the proposal + one register line in the
    stated format, and a rerun files NOTHING new for a
    source already holding a "proposed" register entry
    (idempotent);
  - PROPOSAL-ONLY: raw files are never modified.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
DAY = 86400


def load_module(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_compile_watch", root / "scripts" / "wiki_compile_watch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCompileWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="compile-watch-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_compile_watch.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        src = self.tmp / "raw" / "sources"
        src.mkdir(parents=True)
        self.old = src / "old-note.md"
        self.old.write_text("old", encoding="utf-8")
        os.utime(self.old, (NOW.timestamp() - 30 * DAY,) * 2)
        self.big = src / "big-note.md"
        self.big.write_text("x" * 5000, encoding="utf-8")
        os.utime(self.big, (NOW.timestamp() - 1 * DAY,) * 2)
        self.fresh = src / "fresh-note.md"
        self.fresh.write_text("fresh", encoding="utf-8")
        os.utime(self.fresh, (NOW.timestamp() - 1 * DAY,) * 2)
        self.done = src / "done-note.md"
        self.done.write_text("done", encoding="utf-8")
        os.utime(self.done, (NOW.timestamp() - 90 * DAY,) * 2)
        wiki = self.tmp / "wiki" / "sources"
        wiki.mkdir(parents=True)
        (wiki / "done-page.md").write_text(
            "---\ntitle: Done\ntype: source\nsources:\n"
            "  - raw/sources/done-note.md\n---\n\n# Done\n",
            encoding="utf-8")
        self.mod = load_module(self.tmp)
        self.th = {"age_days": 14, "size_bytes": 2000}

    def test_crossings_and_reasons(self):
        crossings = self.mod.scan_crossings(self.tmp, self.th, NOW)
        by = {c["source"]: c for c in crossings}
        self.assertIn("raw/sources/old-note.md", by)
        self.assertTrue(any("age" in r
                            for r in by["raw/sources/old-note.md"]["reasons"]))
        self.assertIn("raw/sources/big-note.md", by)
        self.assertTrue(any("size" in r
                            for r in by["raw/sources/big-note.md"]["reasons"]))
        self.assertNotIn("raw/sources/fresh-note.md", by)
        self.assertNotIn("raw/sources/done-note.md", by)

    def test_threshold_resolution(self):
        cfg = {"age_days": 7, "size_bytes": 100}
        self.assertEqual(self.mod.resolve_thresholds(cfg),
                         {"age_days": 7, "size_bytes": 100})
        self.assertEqual(
            self.mod.resolve_thresholds(cfg, age_days=3)["age_days"], 3)
        self.assertEqual(self.mod.resolve_thresholds({}),
                         {"age_days": self.mod.DEFAULT_AGE_DAYS,
                          "size_bytes": self.mod.DEFAULT_SIZE_BYTES})

    def test_filing_register_and_idempotence(self):
        raw_hash = hashlib.sha256(self.old.read_bytes()).hexdigest()
        manifest = self.mod.analyse(self.tmp, self.th, NOW)
        self.assertEqual(manifest["stats"]["new_proposals"], 2)
        self.mod.write_filings(self.tmp, manifest)
        reg = (self.tmp / self.mod.REGISTER_REL).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(reg), 2)
        entry = json.loads(reg[0])
        self.assertEqual(
            set(entry), {"date", "source", "age_days", "bytes",
                         "reasons", "proposal", "status"})
        self.assertEqual(entry["status"], "proposed")
        self.assertTrue((self.tmp / entry["proposal"]).is_file())
        # Rerun: the open register entries suppress re-filing.
        again = self.mod.analyse(self.tmp, self.th, NOW)
        self.assertEqual(again["stats"]["new_proposals"], 0)
        self.assertEqual(
            hashlib.sha256(self.old.read_bytes()).hexdigest(), raw_hash)


if __name__ == "__main__":
    unittest.main()
