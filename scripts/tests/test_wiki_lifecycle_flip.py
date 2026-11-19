#!/usr/bin/env python3
"""Lifecycle flip (Owner ruling 2026-11-08, item 29: YES, ENFORCE).

Pins the flip of tools/gateway/profiles/wiki-default.json from
mode "warn-legacy" to mode "enforce", through the REAL validator
(scripts/wiki_validate.py main()) run against a fixture tree that
carries the tree's own SHIPPED profile file — so the tests track
the shipped profile, not a fixture copy of it:

- the shipped profile's mode is "enforce" and its comment
  records the ruling;
- a fixture page carrying an undeclared initial status is an
  ERROR under the flipped validator (exit 1) and passes once
  fixed to a declared state;
- the same fixture under a warn-legacy copy of the profile only
  warns (exit 0) — the mode is the switch, not the checker;
- a grandfathered (schema-grandfathered) violation stays a
  warning under enforce — grandfathering is untouched by the
  flip, in the validator and on the gateway write path.

The undeclared fixture value is "needs-verification": it sits
in the profile axes vocabulary but in NEITHER tree's
status_transitions, so it is undeclared as an initial status in
both trees (the private tree's transitions declare only draft /
verified / published / archived as initial states; WikiCitadel's
declare those plus active / superseded / current / tombstoned).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
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
validator = _load("wiki_validate", ROOT / "scripts/wiki_validate.py")

SHIPPED_PROFILE = ROOT / "tools" / "gateway" / "profiles" / "wiki-default.json"

PAGE = ("---\ntitle: Flip Fixture\ntype: synthesis\ncreated: 2026-11-08\n"
        "updated: 2026-11-08\nsources: []\ntags: [fixture]\nstatus: {status}\n"
        "---\n\nBody.\n")
LEGACY_PAGE = ("---\ntitle: Legacy Fixture\ntype: synthesis\ncreated: 2026-11-08\n"
               "updated: 2026-11-08\nsources: []\ntags: [fixture]\n---\n\nBody.\n")


class TestLifecycleFlip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "syntheses").mkdir(parents=True)
        (self.root / "raw" / "sources").mkdir(parents=True)
        # Real profile machinery, shipped profile file.
        gw = self.root / "tools" / "gateway"
        (gw / "gateway").mkdir(parents=True)
        (gw / "profiles").mkdir(parents=True)
        shutil.copyfile(ROOT / "tools" / "gateway" / "gateway" / "profile.py",
                        gw / "gateway" / "profile.py")
        shutil.copyfile(SHIPPED_PROFILE, gw / "profiles" / "wiki-default.json")
        self.page = self.root / "wiki" / "syntheses" / "fixture.md"
        # Patch the validator's repo-root globals at the fixture tree.
        self._saved = {k: getattr(validator, k) for k in
                       ("ROOT", "WIKI", "RAW", "RAW_SOURCES",
                        "MANIFEST_PATH", "NOTE_PATH")}
        validator.ROOT = self.root
        validator.WIKI = self.root / "wiki"
        validator.RAW = self.root / "raw"
        validator.RAW_SOURCES = self.root / "raw" / "sources"
        validator.MANIFEST_PATH = self.root / "raw" / "sources" / "provenance-manifest.json"
        validator.NOTE_PATH = self.root / "raw" / "sources" / "note.md"

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(validator, k, v)
        self.tmp.cleanup()

    def _run_validator(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = validator.main([])
        return code, buf.getvalue()

    def _write_profile_mode(self, mode):
        p = self.root / "tools" / "gateway" / "profiles" / "wiki-default.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["mode"] = mode
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def test_shipped_profile_mode_is_enforce(self):
        profile = profile_mod.load_profile(SHIPPED_PROFILE)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.get("mode"), "enforce")
        self.assertIn("2026-11-08", profile.get("comment", ""))
        self.assertIn("29", profile.get("comment", ""))

    def test_undeclared_initial_status_errors_under_enforce(self):
        self.page.write_text(PAGE.format(status="needs-verification"),
                             encoding="utf-8")
        code, out = self._run_validator()
        self.assertEqual(code, 1)
        self.assertIn("[lifecycle profile]", out)
        self.assertIn("initial status 'needs-verification' is not a "
                      "declared state", out)

    def test_same_page_passes_once_fixed(self):
        self.page.write_text(PAGE.format(status="published"),
                             encoding="utf-8")
        code, out = self._run_validator()
        self.assertEqual(code, 0)
        self.assertNotIn("[lifecycle profile]", out)

    def test_warn_legacy_copy_only_warns(self):
        self._write_profile_mode("warn-legacy")
        self.page.write_text(PAGE.format(status="needs-verification"),
                             encoding="utf-8")
        code, out = self._run_validator()
        self.assertEqual(code, 0)
        self.assertIn("[lifecycle profile]", out)
        self.assertIn("WARNINGS", out)

    def test_grandfathered_violation_stays_a_warning_under_enforce(self):
        # Legacy page (no _schema_version) missing the v2 'status'
        # field: schema-grandfathered, severity warn — never an
        # error, even with the profile flipped to enforce.
        profile = profile_mod.load_profile(SHIPPED_PROFILE)
        fields = {"title": "Legacy Fixture", "type": "synthesis",
                  "created": "2026-11-08", "updated": "2026-11-08",
                  "sources": [], "tags": ["fixture"]}
        gf = [v for v in profile_mod.violations_for(profile, fields)
              if v["rule"] == "schema-grandfathered"]
        self.assertEqual(len(gf), 1)
        self.assertEqual(gf[0]["severity"], "warn")
        self.page.write_text(LEGACY_PAGE, encoding="utf-8")
        code, out = self._run_validator()
        self.assertEqual(code, 0)
        self.assertIn("schema grandfathering", out)
        self.assertNotIn("[lifecycle profile]", out)


if __name__ == "__main__":
    unittest.main()
