#!/usr/bin/env python3
"""Phase-2 harvest item 5, gateway side: versioned schemas with
grandfathering (pattern: pyrite-wiki/pyrite, MIT). In enforce
mode, NEW content missing a since-versioned field is refused on
the write path; grandfathered (warn) violations never refuse.

Run:  python3 -m unittest discover -s tests -v   (from tools/gateway)
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
GW_DIR = HERE.parents[1]
sys.path.insert(0, str(GW_DIR))

from fixtures.make_fixtures import build_fixture  # noqa: E402
from gateway.config import Config  # noqa: E402
from gateway.store import GatewayStore, StoreError  # noqa: E402

PROFILE = {
    "name": "fixture-v2", "mode": "enforce", "schema_version": 2,
    "page_types": {"concept": {"required_fields": [
        "title", "type", "created", "updated", "sources", "tags",
        {"field": "status", "since_version": 2}]}},
    "status_transitions": {"draft": ["verified"], "verified": ["published"],
                           "published": ["archived"], "archived": []},
}
WITH_STATUS = ("---\ntitle: New\ntype: concept\ncreated: 2026-10-13\n"
               "updated: 2026-10-13\nsources: []\ntags: [f]\n"
               "status: draft\n---\n\nBody.\n")
WITHOUT_STATUS = ("---\ntitle: New\ntype: concept\ncreated: 2026-10-13\n"
                  "updated: 2026-10-13\nsources: []\ntags: [f]\n"
                  "---\n\nBody.\n")
LEGACY_DECLARED = ("---\ntitle: New\ntype: concept\ncreated: 2026-10-13\n"
                   "updated: 2026-10-13\nsources: []\ntags: [f]\n"
                   "_schema_version: 1\n---\n\nBody.\n")


class TestVersionedSchemaGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = build_fixture(Path(self.tmp.name))
        ppath = Path(self.tmp.name) / "profile.json"
        ppath.write_text(json.dumps(PROFILE), encoding="utf-8")
        env = dict(self.fx["env"])
        env["GATEWAY_PROFILE"] = str(ppath)
        self.store = GatewayStore(Config(env=env))

    def tearDown(self):
        self.tmp.cleanup()

    def _stage(self, content):
        return self.store.stage_proposal(
            actor="collaborator-a", session_id="sv", target_path="wiki/concepts/new.md",
            content=content, cites=[], direction_source={"kind": "owner"},
            task_ref="fixture")

    def test_enforce_refuses_new_content_missing_v2_field(self):
        with self.assertRaises(StoreError):
            self._stage(WITHOUT_STATUS)

    def test_enforce_accepts_new_content_with_v2_field(self):
        meta = self._stage(WITH_STATUS)
        self.assertEqual(meta["state"], "draft")

    def test_explicitly_legacy_content_is_grandfathered_not_refused(self):
        meta = self._stage(LEGACY_DECLARED)
        self.assertEqual(meta["state"], "draft")
        self.assertTrue(any(v["rule"] == "schema-grandfathered"
                            for v in meta["profile_check"]["violations"]))


if __name__ == "__main__":
    unittest.main()
