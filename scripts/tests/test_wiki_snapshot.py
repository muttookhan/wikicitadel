"""Tests for scripts/wiki_snapshot.py (Marathon R3 TB5 row 6,
ArchiveBox pattern): a bundle built with an INJECTED fake fetcher
(no network) contains the exact bytes, headers and a hash manifest;
the verifier passes a clean bundle and catches tampering. Run:
python3 -m unittest scripts.tests.test_wiki_snapshot
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_snapshot as ws  # noqa: E402

PAYLOAD = b"<html><body>snapshot me</body></html>"
HEADERS = {"Content-Type": "text/html", "X-Test": "1"}


def fake_fetcher(url):
    assert url.startswith("https://")
    return PAYLOAD, dict(HEADERS)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="snap-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)


class BundleTests(Fixture):
    def test_bundle_layout_and_manifest(self):
        dest, manifest = ws.bundle("https://example.org/page",
                                   self.root, fake_fetcher,
                                   fetched_at="2026-10-21T00:00:00Z")
        self.assertEqual((dest / "original.bin").read_bytes(), PAYLOAD)
        self.assertEqual(json.loads((dest / "headers.json").read_text()),
                         HEADERS)
        self.assertEqual(manifest["sha256"], ws.sha256_bytes(PAYLOAD))
        self.assertEqual(manifest["size"], len(PAYLOAD))
        self.assertEqual(manifest["content_type"], "text/html")

    def test_verify_clean_then_tampered(self):
        dest, _ = ws.bundle("https://example.org/a", self.root,
                            fake_fetcher)
        self.assertEqual(ws.verify(dest), [])
        (dest / "original.bin").write_bytes(b"tampered")
        problems = ws.verify(dest)
        self.assertTrue(problems)
        self.assertTrue(any("hash" in p or "sha256" in p
                            for p in problems))


if __name__ == "__main__":
    unittest.main()
