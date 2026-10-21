#!/usr/bin/env python3
"""Tests for scripts/wiki_checkpoint_predicates.py (TB3-1).

Pins: a predicate whose artefacts exist with the stated
digests/fields AND whose evidence meets the minimum rung is
MET; a missing artefact, a wrong digest, and — the oota
point — evidence below the minimum rung (agent self-report
can never satisfy an important condition) are each UNMET,
and `check` names the unmet checkpoint.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_checkpoint_predicates", SCRIPTS / "wiki_checkpoint_predicates.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def fixture():
    root = Path(tempfile.mkdtemp())
    (root / "evaluation").mkdir(parents=True)
    (root / "evaluation" / "result.json").write_text(
        json.dumps({"verdict": "PASS"}), encoding="utf-8")
    return root


def define(root, pred):
    reg = root / "evaluation" / "checkpoint-predicates.jsonl"
    with reg.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(pred, kind="predicate")) + "\n")


BASE_COND = {"name": "battery", "artefact": "evaluation/result.json",
             "kind": "json-field", "field": "verdict", "equals": "PASS"}


class TestPredicates(unittest.TestCase):
    def test_met_at_required_rung(self):
        root = fixture()
        define(root, {"checkpoint": "cp-1", "min_evidence": "repeatable-test",
                      "conditions": [dict(BASE_COND, evidence={
                          "rung": "repeatable-test", "ref": "t.py"})]})
        report, all_met = M.evaluate(root)
        self.assertTrue(all_met)
        self.assertTrue(report[0]["met"])

    def test_self_report_below_minimum_rung_is_unmet(self):
        root = fixture()
        define(root, {"checkpoint": "cp-1", "min_evidence": "repeatable-test",
                      "conditions": [dict(BASE_COND, evidence={
                          "rung": "agent-assertion", "ref": "me"})]})
        report, all_met = M.evaluate(root)
        self.assertFalse(all_met)
        self.assertFalse(report[0]["conditions"][0]["met"])

    def test_wrong_field_value_unmet(self):
        root = fixture()
        (root / "evaluation" / "result.json").write_text(
            json.dumps({"verdict": "FAIL"}), encoding="utf-8")
        define(root, {"checkpoint": "cp-1", "min_evidence": "command-output",
                      "conditions": [dict(BASE_COND, evidence={
                          "rung": "command-output", "ref": "run"})]})
        _report, all_met = M.evaluate(root)
        self.assertFalse(all_met)

    def test_missing_artefact_unmet(self):
        root = fixture()
        define(root, {"checkpoint": "cp-1", "min_evidence": "command-output",
                      "conditions": [dict(
                          BASE_COND, artefact="evaluation/nope.json",
                          evidence={"rung": "artifact-digest",
                                    "ref": "x"})]})
        _report, all_met = M.evaluate(root)
        self.assertFalse(all_met)

    def test_ladder_order(self):
        self.assertLess(M.rung("agent-assertion"),
                        M.rung("artifact-digest"))
        self.assertEqual(M.rung("nonsense"), -1)


if __name__ == "__main__":
    unittest.main()
