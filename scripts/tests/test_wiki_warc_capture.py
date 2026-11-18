#!/usr/bin/env python3
"""WARC 1.1 source capture with payload-digest locking
(Marathon R8; warcio pattern, no dependency).

Pins scripts/wiki_warc_capture.py on FIXTURE payloads (no
network): a written file parses back as WARC 1.1, its
WARC-Payload-Digest recomputes from the payload bytes, the
digest equals the hash the citation machinery locks to for
the same bytes, a wrong locked hash fails, and one altered
byte fails verification.
Run: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wc = load("wiki_warc_capture", "scripts/wiki_warc_capture.py")
PAYLOAD = b"<html><body>fixture source bytes</body></html>\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="warc-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = self.root / "capture.warc"


class TestWriteRead(Fixture):
    def test_roundtrip_and_payload_digest(self):
        digest = wc.write_warc(self.out, "https://example.org/src",
                               PAYLOAD, "text/html",
                               date="2026-10-21T00:00:00Z")
        self.assertEqual(digest, hashlib.sha256(PAYLOAD).hexdigest())
        records = wc.read_records(self.out)
        self.assertEqual([r["headers"]["WARC-Type"] for r in records],
                         ["warcinfo", "response"])
        resp = records[1]
        self.assertEqual(resp["headers"]["_version"], "WARC/1.1")
        self.assertEqual(resp["content"], PAYLOAD)
        self.assertEqual(resp["headers"]["WARC-Payload-Digest"],
                         "sha256:" + digest)


class TestVerify(Fixture):
    def test_verify_clean_and_against_locked_hash(self):
        digest = wc.write_warc(self.out, "https://example.org/s",
                               PAYLOAD, "text/html")
        self.assertEqual(wc.verify(self.out), [])
        self.assertEqual(wc.verify(self.out, locked_hash=digest), [])

    def test_wrong_locked_hash_fails(self):
        wc.write_warc(self.out, "https://example.org/s", PAYLOAD)
        problems = wc.verify(self.out, locked_hash="0" * 64)
        self.assertTrue(any("locked hash" in p for p in problems))

    def test_tampered_payload_fails(self):
        wc.write_warc(self.out, "https://example.org/s", PAYLOAD)
        data = bytearray(self.out.read_bytes())
        idx = data.find(b"fixture")
        data[idx] = ord("F")
        self.out.write_bytes(bytes(data))
        self.assertTrue(wc.verify(self.out))

    def test_locked_hash_lookup_in_manifest(self):
        # The real manifest registers real sources; an unknown
        # path honestly returns None.
        self.assertIsNone(wc.locked_hash_for("raw/sources/no-such.md"))
        import json
        first = None
        for line in (ROOT / "evaluation" / "source-manifest.jsonl") \
                .read_text(encoding="utf-8").splitlines():
            if line.strip():
                first = json.loads(line)
                break
        if first:
            self.assertEqual(wc.locked_hash_for(first["path"]),
                             first["sha256"])


if __name__ == "__main__":
    unittest.main()
