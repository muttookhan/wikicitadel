#!/usr/bin/env python3
"""Tests for scripts/wiki_verify_write.py (B3 round).

Exit-code contract, on a fixture tree + fixture manifest:
  0 — the file's sha256 matches its provenance entry;
  1 — mismatch (tampered file; missing file);
  2 — no entry for the path.
Both manifest shapes are exercised: the provenance-manifest
JSON shape ({"files": {rel: {"sha256", "bytes"}}}) and the
JSONL source-manifest shape ({"path", "sha256"} per line).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = "wiki_verify_write.py"
BODY = "verbatim raw body\n"
REL = "raw/sources/note.md"


class VerifyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-write-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        src = self.tmp / "raw" / "sources"
        src.mkdir(parents=True)
        (src / "note.md").write_text(BODY, encoding="utf-8")
        digest = hashlib.sha256(BODY.encode()).hexdigest()
        manifest = {"files": {REL: {"sha256": digest,
                                    "bytes": len(BODY)}}}
        (src / "provenance-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        self.jsonl = self.tmp / "source-manifest.jsonl"
        self.jsonl.write_text(
            json.dumps({"path": REL, "sha256": digest}) + "\n",
            encoding="utf-8")

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / TOOL), "--root",
             str(self.tmp), *args], capture_output=True, text=True)


class TestVerifyWrite(VerifyFixture):
    def test_match_exits_0(self):
        r = self.run_tool(REL)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("OK", r.stdout)

    def test_match_jsonl_manifest_exits_0(self):
        r = self.run_tool(REL, "--manifest", str(self.jsonl))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_tampered_file_exits_1(self):
        (self.tmp / REL).write_text("tampered body\n",
                                    encoding="utf-8")
        r = self.run_tool(REL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISMATCH", r.stdout)

    def test_missing_file_exits_1(self):
        (self.tmp / REL).unlink()
        r = self.run_tool(REL)
        self.assertEqual(r.returncode, 1)

    def test_no_entry_exits_2(self):
        other = self.tmp / "raw" / "sources" / "other.md"
        other.write_text("unlisted\n", encoding="utf-8")
        r = self.run_tool("raw/sources/other.md")
        self.assertEqual(r.returncode, 2)
        self.assertIn("NO-ENTRY", r.stdout)


if __name__ == "__main__":
    unittest.main()
