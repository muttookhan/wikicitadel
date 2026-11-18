#!/usr/bin/env python3
"""Japanese retrieval recipe as a DORMANT configuration
(Marathon Round 3, lane TB7, row 10a).

Pins the profile file evaluation/retrieval-profiles/
japanese-dual-track.json: it parses; its status is dormant;
its activation condition is stated with a measurable signal
and a licence gate; the dual track is present (native +
translated) with the JMTEB evaluation named; and NOTHING is
wired — embeddings_wired and network_calls are false at the
profile level and on every track.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "evaluation" / "retrieval-profiles" / \
    "japanese-dual-track.json"


class JapaneseProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(PROFILE.read_text(encoding="utf-8"))

    def test_dormant_and_unwired(self):
        p = self.profile
        self.assertEqual(p["kind"], "retrieval-profile")
        self.assertEqual(p["status"], "dormant")
        self.assertIs(p["embeddings_wired"], False)
        self.assertIs(p["network_calls"], False)
        for track in p["tracks"]:
            self.assertIs(track["embeddings_wired"], False)

    def test_dual_track_and_evaluation(self):
        ids = [t["id"] for t in self.profile["tracks"]]
        self.assertEqual(ids, ["native", "translated"])
        self.assertEqual(self.profile["evaluation"]["benchmark"],
                         "JMTEB")
        native = self.profile["tracks"][0]
        self.assertIn("Ruri-v3", native["model_class"])
        self.assertTrue(any("prefix" in s for s in native["stages"]))

    def test_activation_condition_stated(self):
        cond = self.profile["activation_condition"]
        self.assertGreaterEqual(cond["min_japanese_pages"], 1)
        self.assertIn("Japanese", cond["signal"])
        self.assertIn("licence", cond["licence_gate"].lower())


if __name__ == "__main__":
    unittest.main()
