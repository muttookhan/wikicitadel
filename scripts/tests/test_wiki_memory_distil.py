"""Tests for scripts/wiki_memory_distil.py — the MemU-shaped
pipeline over memory-shaped fixture logs ONLY (never the real
memory corpus): dated entries are mined, duplicates collapse
with a count, and the distilled digest attributes every entry
to its source file + date, with a matching index JSON.
Inputs are byte-identical after the run.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_memory_distil as wmd  # noqa: E402

DAY1 = """# 2026-10-20

## [2026-10-20] ingest | Lantern archive

Ingested the lantern archive notes.

## Decisions

The demo council chose the harbour venue.
"""

DAY2 = """# 2026-10-21

## [2026-10-20] ingest | Lantern archive

Ingested the lantern archive notes.

## [2026-10-21] query | Harbour venue

The harbour venue seats forty people.
"""


class MemoryDistilTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="distil-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.logs = self.dir / "logs"
        self.logs.mkdir()
        (self.logs / "2026-10-20.md").write_text(
            DAY1, encoding="utf-8")
        (self.logs / "2026-10-21.md").write_text(
            DAY2, encoding="utf-8")

    def _hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.logs.glob("*.md"))}

    def test_distil_topics_attribution_and_duplicates(self):
        topics, index = wmd.distil(self.logs)
        self.assertEqual(index["total_entries"], 4)
        self.assertEqual(index["unique_entries"], 3)
        self.assertEqual(index["duplicates_collapsed"], 1)
        self.assertIn("ingest | Lantern archive", topics)
        dup = topics["ingest | Lantern archive"][0]
        self.assertEqual(dup["count"], 2)
        self.assertEqual(
            {(s["source_file"], s["date"]) for s in dup["sources"]},
            {("2026-10-20.md", "2026-10-20"),
             ("2026-10-21.md", "2026-10-20")})
        # The undated heading inherits its file's date.
        dec = topics["Decisions"][0]
        self.assertEqual(dec["date"], "2026-10-20")
        self.assertEqual(dec["source_file"], "2026-10-20.md")

    def test_digest_and_index_files(self):
        out = self.dir / "digest.md"
        idx = self.dir / "index.json"
        before = self._hashes()
        rc = wmd.main([str(self.logs), "--out", str(out),
                       "--index", str(idx)])
        self.assertEqual(rc, 0)
        self.assertEqual(self._hashes(), before)
        digest = out.read_text(encoding="utf-8")
        self.assertIn("## ingest | Lantern archive", digest)
        self.assertIn("— source: 2026-10-20.md, 2026-10-20",
                      digest)
        self.assertIn("×2 duplicates collapsed", digest)
        index = json.loads(idx.read_text(encoding="utf-8"))
        self.assertEqual(index["kind"], "memory-distil-index")
        self.assertEqual(index["files"],
                         ["2026-10-20.md", "2026-10-21.md"])
        entry = index["topics"]["query | Harbour venue"][0]
        self.assertEqual(entry["source_file"], "2026-10-21.md")
        self.assertEqual(entry["date"], "2026-10-21")

    def test_refusals(self):
        with self.assertRaises(wmd.DistilError):
            wmd.distil(self.dir / "missing")
        empty = self.dir / "empty"
        empty.mkdir()
        with self.assertRaises(wmd.DistilError):
            wmd.distil(empty)


if __name__ == "__main__":
    unittest.main()
