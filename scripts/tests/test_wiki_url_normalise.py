#!/usr/bin/env python3
"""Tests for scripts/wiki_url_normalise.py + its capture wiring
(Marathon R7 lane BA): tracking stripped at capture, ORIGINAL
preserved in the clip sidecar and the snapshot bundle manifest.
Run: python3 -m unittest scripts.tests.test_wiki_url_normalise
"""
import json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_url_normalise as wun  # noqa: E402
import wiki_clip as clip  # noqa: E402
import wiki_snapshot as snap  # noqa: E402

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
TRACKED = "https://example.com/story?utm_source=news&id=7&fbclid=ABC&utm_medium=email"
CLEAN = "https://example.com/story?id=7"

class Normalise(unittest.TestCase):
    def test_tracking_stripped_others_kept(self):
        n, o, ch = wun.normalise_url(TRACKED)
        self.assertEqual(n, CLEAN); self.assertEqual(o, TRACKED)
        self.assertIn("stripped:utm_source", ch); self.assertIn("stripped:fbclid", ch)
    def test_clean_url_unchanged(self):
        self.assertEqual(wun.normalise_url(CLEAN), (CLEAN, CLEAN, []))
    def test_gclid_and_mc_stripped(self):
        n, _, _ = wun.normalise_url("https://x.example/a?gclid=1&mc_cid=2&keep=3")
        self.assertEqual(n, "https://x.example/a?keep=3")
    def test_feedburner_unwrapped(self):
        n, o, ch = wun.normalise_url(
            "https://feedproxy.google.com/r/x?url=https%3A%2F%2Fexample.com%2Fpost%3Futm_source%3Dfb%26id%3D3")
        self.assertEqual(n, "https://example.com/post?id=3")
        self.assertTrue(o.startswith("https://feedproxy.google.com"))
        self.assertTrue(any(c.startswith("unwrapped:") for c in ch))
    def test_non_http_unchanged(self):
        self.assertEqual(wun.normalise_url("file:///tmp/x?utm_a=1")[0], "file:///tmp/x?utm_a=1")

def _fake(url):
    return clip.FetchResult(b"<html><head><title>Story</title></head><body><p>Hello world, a clean paragraph of text.</p></body></html>", content_type="text/html", final_url=url)

class ClipWiring(unittest.TestCase):
    def test_sidecar_records_normalised_and_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/"wiki").mkdir(); (root/"wiki/index.md").write_text("# i\n")
            res = clip.clip_url(TRACKED, sensitivity="public", root=root, fetcher=_fake, now=NOW)
            side = json.loads((root/res["sidecar"]).read_text())
            self.assertEqual(side["clip"]["url"], CLEAN)
            self.assertEqual(side["clip"]["original_url"], TRACKED)
            self.assertIn("stripped:utm_source", side["clip"]["url_normalisation"])
            draft = (root/res["draft"]).read_text()
            self.assertIn(CLEAN, draft)
            self.assertNotIn("fbclid", draft)

class SnapshotWiring(unittest.TestCase):
    def test_bundle_manifest_preserves_original(self):
        with tempfile.TemporaryDirectory() as td:
            dest, manifest = snap.bundle(TRACKED, Path(td), lambda u: (b"bytes", {"Content-Type": "text/html"}), fetched_at="2026-10-21")
            self.assertEqual(manifest["url"], CLEAN)
            self.assertEqual(manifest["original_url"], TRACKED)
            on_disk = json.loads((Path(dest)/"manifest.json").read_text())
            self.assertEqual(on_disk["original_url"], TRACKED)

if __name__ == "__main__":
    unittest.main()
