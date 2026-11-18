#!/usr/bin/env python3
"""Phase-2 harvest item 5: versioned schemas with grandfathering
(pattern: pyrite-wiki/pyrite, MIT).

- profile machinery: legacy page missing a since-versioned field
  -> warn (grandfathered); new-schema page missing it -> error;
- gateway enforce mode refuses new content missing it, but never
  refuses on a grandfathered warning alone;
- validator-side severity honoured by profile module consumers;
- schema migrate is a DRY-RUN: it emits a diff and writes nothing.

Run:  python3 -m unittest discover -s scripts/tests
       python3 -m unittest discover -s tools/gateway/tests
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gateway"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


profile_mod = _load("gw_profile", ROOT / "tools/gateway/gateway/profile.py")
schema = _load("wiki_schema", ROOT / "scripts/wiki_schema.py")

PROFILE = {
    "name": "fixture", "mode": "warn-legacy", "schema_version": 2,
    "page_types": {"concept": {"required_fields": [
        "title", "type", {"field": "status", "since_version": 2}]}},
    "status_transitions": {"draft": ["verified"], "verified": ["published"],
                           "published": ["archived"], "archived": []},
}
BASE = {"title": "X", "type": "concept"}


class TestGrandfathering(unittest.TestCase):
    def test_legacy_page_warns(self):
        v = profile_mod.violations_for(PROFILE, dict(BASE))
        gf = [x for x in v if x["rule"] == "schema-grandfathered"]
        self.assertEqual(len(gf), 1)
        self.assertEqual(gf[0]["severity"], "warn")
        self.assertEqual(gf[0]["field"], "status")

    def test_new_schema_page_errors(self):
        fields = dict(BASE, _schema_version="2")
        v = profile_mod.violations_for(PROFILE, fields)
        hard = [x for x in v if x.get("severity") == "error"]
        self.assertEqual(len(hard), 1)
        self.assertEqual(hard[0]["rule"], "required-field")

    def test_new_schema_page_with_field_is_clean(self):
        fields = dict(BASE, _schema_version="2", status="draft")
        v = profile_mod.violations_for(PROFILE, fields)
        self.assertEqual([x for x in v if x["rule"] in
                          ("required-field", "schema-grandfathered")], [])

    def test_assume_version_judges_new_content_as_current(self):
        # Write path: no _schema_version declared -> judged at the
        # profile's current version (the dodge does not work).
        v = profile_mod.violations_for(PROFILE, dict(BASE), assume_version=2)
        self.assertTrue(any(x.get("severity") == "error" for x in v))


class TestMigrateDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        self.page = self.root / "wiki" / "concepts" / "legacy.md"
        self.original = ("---\ntitle: Legacy\ntype: concept\n"
                          "created: 2030-10-01\nupdated: 2030-10-01\n"
                          "sources: []\ntags: [fixture]\n---\n\nBody.\n")
        self.page.write_text(self.original, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_diff_shows_version_and_default_status(self):
        n, diffs = schema.migrate_dry_run(self.root, PROFILE, profile_mod)
        self.assertEqual(n, 1)
        diff = diffs[0]
        self.assertIn("+_schema_version: 2", diff)
        self.assertIn("+status: draft", diff)
        # Dry-run means dry: the file is byte-identical afterwards.
        self.assertEqual(self.page.read_text(encoding="utf-8"), self.original)

    def test_current_page_produces_no_diff(self):
        self.page.write_text(
            self.original.replace("tags: [fixture]",
                                  "tags: [fixture]\n_schema_version: 2\n"
                                  "status: draft"),
            encoding="utf-8")
        n, _diffs = schema.migrate_dry_run(self.root, PROFILE, profile_mod)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
