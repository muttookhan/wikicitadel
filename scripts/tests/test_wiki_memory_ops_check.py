#!/usr/bin/env python3
"""Memory-operations slice (FEB-30 pattern; landscape weekly
2026-10-27, board item (a)).

Pins: the classifier's four classes against fixture trajectories
run through the REAL cores (wiki_claim_match + wiki_severance),
the two known blind spots as disagreements that must be caught
(a value change in free text; a ruling never written to the
register), the zombie-repeat probe, a deliberately mislabelled
fixture (the checker must report it, not agree with it), a
misrecorded supersession, and the shipped battery's exact
first-run profile.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_memory_ops_check", ROOT / "scripts" / "wiki_memory_ops_check.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def run_rows(rows):
    """Write fixture rows to a temp battery file and run the
    slice against this tree's machinery."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "battery.jsonl"
        path.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8")
        return mod.run(ROOT, path)


def traj(steps, claims=None, decisions=None, tid="traj-fx"):
    return {"kind": "trajectory", "id": tid, "title": "fixture",
            "seed": {"claims": claims or [],
                     "decisions": decisions or []},
            "steps": steps}


DECISION = {
    "id": "fx-d1", "title": "Fixture decision",
    "form_title": "The fixture panel meets on Mondays",
    "current_form": "The fixture panel meets on Mondays, "
                    "in the small room by the stairs.",
    "source_page": "wiki/decisions/fx-d1.md",
}


class ClaimClassificationTests(unittest.TestCase):
    def test_create_then_reinforce_agree(self):
        rep = run_rows([traj([
            {"op": "present_claim",
             "text": "The harbour rowing club launches its boats "
                     "at dawn on Saturdays",
             "expect": "create", "page": "wiki/facts/rowing.md"},
            {"op": "present_claim",
             "text": "At dawn on Saturdays, the harbour rowing "
                     "club launches its boats",
             "expect": "reinforce"},
        ])])
        self.assertEqual(rep["steps"], 2)
        self.assertEqual(rep["agreements"], 2)
        self.assertEqual(rep["disagreements"], [])

    def test_text_value_change_is_caught_as_disagreement(self):
        """The FEB blind spot, pinned: a restatement whose value
        changed is classified REINFORCE by the text core — the
        checker must report the disagreement, not paper over it."""
        rep = run_rows([traj([
            {"op": "present_claim",
             "text": "The reading circle meets on the first "
                     "Sunday of the month",
             "expect": "update", "page": "wiki/facts/circle.md"},
        ], claims=[{"page": "wiki/facts/circle.md",
                    "claim": "The reading circle meets on the "
                             "first Saturday of the month"}])])
        self.assertEqual(len(rep["disagreements"]), 1)
        d = rep["disagreements"][0]
        self.assertEqual(d["expect"], "update")
        self.assertEqual(d["classified"], "reinforce")

    def test_deliberately_mislabelled_fixture_is_caught(self):
        """A plain create labelled 'supersede': the classifier
        reads store state, never the label — the wrong label
        must surface as a disagreement."""
        rep = run_rows([traj([
            {"op": "present_claim",
             "text": "Quilting supplies are kept in the cedar "
                     "chest beside the stage",
             "expect": "supersede", "page": "wiki/facts/quilt.md"},
        ])])
        self.assertEqual(rep["agreements"], 0)
        self.assertEqual(len(rep["disagreements"]), 1)
        self.assertEqual(rep["disagreements"][0]["classified"],
                         "create")


class RuleClassificationTests(unittest.TestCase):
    def test_refinement_is_update_reversal_is_supersede(self):
        rep = run_rows([traj([
            {"op": "rule", "decision": "fx-d1", "recorded": True,
             "supersede": False,
             "new_form_title": "The fixture panel meets on "
                               "Monday evenings",
             "new_current_form": "The fixture panel meets on "
                                 "Monday evenings, in the small "
                                 "room by the stairs.",
             "expect": "update"},
            {"op": "rule", "decision": "fx-d1", "recorded": True,
             "supersede": True,
             "match_phrases": ["panel meets on monday evenings"],
             "new_form_title": "The fixture panel meets on "
                               "Thursdays",
             "new_current_form": "The fixture panel meets on "
                                 "Thursdays, in the small room "
                                 "by the stairs.",
             "expect": "supersede"},
        ], decisions=[DECISION])])
        self.assertEqual(rep["disagreements"], [])
        self.assertEqual(rep["per_class"]["update"]["agreements"], 1)
        self.assertEqual(
            rep["per_class"]["supersede"]["agreements"], 1)

    def test_unrecorded_ruling_classifies_none(self):
        rep = run_rows([traj([
            {"op": "rule", "decision": "fx-d1", "recorded": False,
             "new_form_title": "The fixture panel meets on "
                               "Thursdays",
             "new_current_form": "The fixture panel meets on "
                                 "Thursdays.",
             "expect": "supersede"},
        ], decisions=[DECISION])])
        self.assertEqual(len(rep["disagreements"]), 1)
        self.assertEqual(rep["disagreements"][0]["classified"],
                         "none")

    def test_misrecorded_supersession_is_caught(self):
        """The supersession was recorded without the old form's
        actual statement (record_title blank — the register ends
        up hunting a form_id nobody ever wrote): the derivation
        cannot sever the standing form, so the step must NOT
        classify as supersede."""
        rep = run_rows([traj([
            {"op": "rule", "decision": "fx-d1", "recorded": True,
             "supersede": True, "record_title": "",
             "match_phrases": [],
             "new_form_title": "The fixture panel meets on "
                               "Thursdays",
             "new_current_form": "The fixture panel meets on "
                                 "Thursdays, in the small room "
                                 "by the stairs.",
             "expect": "supersede"},
        ], decisions=[DECISION])])
        self.assertEqual(len(rep["disagreements"]), 1)
        self.assertNotEqual(
            rep["disagreements"][0]["classified"], "supersede")

    def test_zombie_repeat_probe_passes(self):
        rep = run_rows([traj([
            {"op": "rule", "decision": "fx-d1", "recorded": True,
             "supersede": True,
             "match_phrases": ["panel meets on mondays"],
             "new_form_title": "The fixture panel meets on "
                               "Thursdays",
             "new_current_form": "The fixture panel meets on "
                                 "Thursdays, in the small room "
                                 "by the stairs.",
             "expect": "supersede"},
            {"op": "present_claim",
             "text": "The fixture panel meets on Mondays",
             "expect": "superseded-repeat", "probe": True},
        ], decisions=[DECISION])])
        self.assertEqual(rep["probes"]["total"], 1)
        self.assertEqual(rep["probes"]["passed"], 1)
        self.assertEqual(rep["probes"]["failures"], [])


class ShippedBatteryTests(unittest.TestCase):
    def test_shipped_battery_profile(self):
        """The shipped battery's first-run profile, pinned: 22
        scored steps, exactly the two designed disagreements
        (traj-02 step 2, traj-05 step 1), all probes green. A
        machinery change that moves any of this fails loudly
        here instead of drifting silently."""
        rep = mod.run(ROOT)
        self.assertEqual(rep["trajectories"], 6)
        self.assertEqual(rep["steps"], 22)
        self.assertEqual(rep["agreements"], 20)
        self.assertEqual(rep["accuracy"], 0.9091)
        self.assertEqual(
            {(d["subject"], d["expect"], d["classified"])
             for d in rep["disagreements"]},
            {("traj-02 step 2", "update", "reinforce"),
             ("traj-05 step 1", "supersede", "none")})
        self.assertEqual(rep["probes"]["passed"],
                         rep["probes"]["total"])
        self.assertEqual(rep["live_probes"]["passed"],
                         rep["live_probes"]["total"])


if __name__ == "__main__":
    unittest.main()
