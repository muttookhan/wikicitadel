#!/usr/bin/env python3
"""Tests for scripts/wiki_checkpoint_verify_offline.py
(TB3-6).

Pins: a register built with the checkpoint chain rule
(header + chained lines) verifies OFFLINE (the verifier
imports nothing from wiki_checkpoint.py and reads only the
file); a tampered fixture — one line's content altered, and
separately one line removed — is reported as a break at the
right place.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_checkpoint_verify_offline",
    SCRIPTS / "wiki_checkpoint_verify_offline.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

GENESIS = "0" * 64


def build_register(path):
    lines = [{"kind": "header", "register": "checkpoints"}]
    prev = GENESIS
    for i in range(3):
        body = {"kind": "checkpoint", "id": f"cp-{i + 1:06d}",
                "n": i, "prev_hash": prev}
        body["line_hash"] = hashlib.sha256(
            prev.encode() + M.canonical(body)).hexdigest()
        lines.append(body)
        prev = body["line_hash"]
    path.write_text("".join(json.dumps(ln, sort_keys=True) + "\n"
                            for ln in lines), encoding="utf-8")
    return lines


class TestOfflineVerify(unittest.TestCase):
    def test_intact_register(self):
        p = Path(tempfile.mkdtemp()) / "checkpoints.jsonl"
        build_register(p)
        ok, report = M.verify_register(p)
        self.assertTrue(ok, report)
        self.assertEqual(report["chained"], 3)
        self.assertIsNotNone(report["head_hash"])

    def test_tampered_line_detected(self):
        p = Path(tempfile.mkdtemp()) / "checkpoints.jsonl"
        lines = build_register(p)
        lines[2]["n"] = 99  # alter content, keep the hashes
        p.write_text("".join(json.dumps(ln, sort_keys=True) + "\n"
                             for ln in lines), encoding="utf-8")
        ok, report = M.verify_register(p)
        self.assertFalse(ok)
        self.assertIn("line_hash", report["break"]["reason"])

    def test_removed_line_detected(self):
        p = Path(tempfile.mkdtemp()) / "checkpoints.jsonl"
        lines = build_register(p)
        del lines[2]
        p.write_text("".join(json.dumps(ln, sort_keys=True) + "\n"
                             for ln in lines), encoding="utf-8")
        ok, report = M.verify_register(p)
        self.assertFalse(ok)
        self.assertIn("prev_hash", report["break"]["reason"])

    def test_missing_file_is_usage_error(self):
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable,
             str(SCRIPTS / "wiki_checkpoint_verify_offline.py"),
             "/nonexistent/checkpoints.jsonl"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
