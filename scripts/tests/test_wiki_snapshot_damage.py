#!/usr/bin/env python3
"""Weighted damage field on snapshot records (Marathon R8,
Brunelle et al., JCDL 2014).

Pins scripts/wiki_snapshot.py's damage machinery: resources
are classed and weighted (document > script/stylesheet >
image/font/media > other); a NEW bundle manifest carries
missing_weight beside missing_count; damage_report() computes
the same field for an EXISTING bundle read-only and never
rewrites its manifest. Fixture fetcher only — no network.
Run: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

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
HEADERS = {"Content-Type": "text/html"}


def fake_fetcher(url):
    return PAYLOAD, dict(HEADERS)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dmg-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)


class TestClassifyAndWeight(unittest.TestCase):
    def test_classes_by_type_and_extension(self):
        self.assertEqual(ws.classify_resource("x", "text/html"), "document")
        self.assertEqual(ws.classify_resource("a/b.js"), "script")
        self.assertEqual(ws.classify_resource("a/b.css"), "stylesheet")
        self.assertEqual(ws.classify_resource("a/b.png"), "image")
        self.assertEqual(ws.classify_resource("a/b.bin"), "other")
        self.assertGreater(ws.RESOURCE_WEIGHTS["document"],
                           ws.RESOURCE_WEIGHTS["image"])

    def test_weighted_damage_counts_weight_not_just_files(self):
        dmg = ws.weighted_damage([
            {"name": "page.html", "present": False},
            {"name": "logo.png", "present": False},
            {"name": "app.js", "present": True},
        ])
        self.assertEqual(dmg["missing_count"], 2)
        self.assertAlmostEqual(
            dmg["missing_weight"],
            ws.RESOURCE_WEIGHTS["document"] + ws.RESOURCE_WEIGHTS["image"])
        self.assertAlmostEqual(
            dmg["weighted_damage"],
            dmg["missing_weight"] / dmg["total_weight"])


class TestBundleField(Fixture):
    def test_new_bundle_manifest_carries_damage_field(self):
        dest, manifest = ws.bundle("https://example.org/page",
                                   self.root, fake_fetcher)
        self.assertIn("damage", manifest)
        self.assertEqual(manifest["damage"]["missing_count"], 0)
        self.assertEqual(manifest["damage"]["missing_weight"], 0.0)
        self.assertEqual(manifest["damage"]["resources"][0]
                         ["resource_class"], "document")
        self.assertEqual(ws.verify(dest), [])

    def test_damage_report_on_existing_bundle_is_read_only(self):
        dest, _m = ws.bundle("https://example.org/a", self.root,
                             fake_fetcher)
        before = (dest / "manifest.json").read_bytes()
        (dest / "original.bin").unlink()
        dmg = ws.damage_report(dest)
        self.assertEqual(dmg["missing_count"], 1)
        self.assertEqual(dmg["missing_weight"],
                         ws.RESOURCE_WEIGHTS["document"])
        self.assertEqual((dest / "manifest.json").read_bytes(), before)

    def test_damage_report_handles_pre_field_manifest(self):
        # A manifest written before the damage field existed:
        # the report computes from its files list, read-only.
        dest = self.root / "old"
        dest.mkdir()
        (dest / "original.bin").write_bytes(b"x")
        (dest / "manifest.json").write_text(json.dumps({
            "content_type": "text/html",
            "files": {"original.bin": "0" * 64,
                      "headers.json": "0" * 64}}), encoding="utf-8")
        dmg = ws.damage_report(dest)
        self.assertEqual(dmg["missing_count"], 1)
        self.assertEqual(dmg["resources"][1]["resource_class"], "other")


if __name__ == "__main__":
    unittest.main()
