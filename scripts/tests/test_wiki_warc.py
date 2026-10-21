#!/usr/bin/env python3
"""Tests for scripts/wiki_warc.py (TB3-5).

Pins the round-trip: a fixture fetch (injected fetcher, NO
network) is written as WARC, parses back to warcinfo +
response records whose payload bytes are identical to the
fixture's, and `verify` recomputes every block digest; a
single altered byte in the archive fails verify.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_warc", SCRIPTS / "wiki_warc.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

PAYLOAD = b"<html><body>fixture page \xe2\x80\x94 bytes</body></html>"


def fake_fetcher(url):
    assert url == "https://example.invalid/page"
    return PAYLOAD, "text/html"


class TestWarc(unittest.TestCase):
    def test_round_trip(self):
        out = Path(tempfile.mkdtemp()) / "ingest.warc"
        M.archive("https://example.invalid/page", out, fake_fetcher,
                  {"converter": "fixture"})
        records = M.parse_warc(out)
        self.assertEqual([r["headers"]["WARC-Type"] for r in records],
                         ["warcinfo", "response"])
        self.assertEqual(records[1]["headers"]["WARC-Target-URI"],
                         "https://example.invalid/page")
        self.assertTrue(records[1]["content"].endswith(PAYLOAD))
        ok, problems = M.verify(out)
        self.assertTrue(ok, problems)

    def test_tampered_byte_fails_verify(self):
        out = Path(tempfile.mkdtemp()) / "ingest.warc"
        M.write_warc(out, "https://example.invalid/", PAYLOAD)
        data = bytearray(out.read_bytes())
        data[-10] ^= 0xFF
        out.write_bytes(bytes(data))
        ok, problems = M.verify(out)
        self.assertFalse(ok)
        self.assertTrue(problems)

    def test_from_file_bytes_preserved(self):
        d = Path(tempfile.mkdtemp())
        src = d / "preserved.html"
        src.write_bytes(PAYLOAD)
        out = d / "x.warc"
        M.write_warc(out, "file-preserved", src.read_bytes(),
                     "application/octet-stream",
                     {"preserved-from": str(src)})
        ok, _ = M.verify(out)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
