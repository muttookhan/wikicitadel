"""Tests for scripts/wiki_longmem_update.py + the slice
registers evaluation/longmem-update-temporal.json and
evaluation/longmem-update-temporal-cases.jsonl (Marathon R9
lane BA; LongMemEval knowledge-update + temporal board item).

Pins: shipped definitions + fixture cases valid; every
fixture case also passes the EXISTING LongMemEval runner
(scripts/wiki_longmem_eval.py) — the slice speaks the family
format; a knowledge-update case whose expected value is the
superseded one is flagged; a temporal case with no cue is
flagged; and, in a tree carrying the pinned abstention
battery, the battery file is byte-identical to its pinned
hash (this slice landed beside it and never touched it).

Run: python3 -m unittest scripts.tests.test_wiki_longmem_update
"""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent

# sha256 of evaluation/abstention-battery.jsonl as copied at
# Marathon R9 lane BA's base (private HEAD b6dca60). The
# battery is pinned; if this ever changes, the change is a
# finding to surface, not a constant to update quietly.
BATTERY_SHA256 = ("0d5bee4a04e2ae0dbdaaf85c1078f4c301573bc478f17388"
                  "e1fd1e9df47338b0")


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module("wiki_longmem_update")
RUNNER = load_module("wiki_longmem_eval")
REGISTER = json.loads((ROOT / "evaluation" /
                       "longmem-update-temporal.json")
                      .read_text(encoding="utf-8"))
CASES = MOD.load_cases(ROOT / "evaluation" /
                       "longmem-update-temporal-cases.jsonl")


class SliceTests(unittest.TestCase):
    def test_shipped_slice_valid(self):
        self.assertEqual(MOD.check_definitions(REGISTER), [])
        self.assertEqual(MOD.check_cases(CASES, REGISTER), [])

    def test_both_classes_present(self):
        by = {c["slice_class"] for c in CASES}
        self.assertEqual(by, {"knowledge-update", "temporal"})

    def test_cases_pass_existing_runner(self):
        for case in CASES:
            self.assertEqual(RUNNER.validate_case(case), [],
                             case["id"])
            self.assertTrue(RUNNER.run_case(case)["passed"],
                            case["id"])

    def test_superseded_answer_flagged(self):
        broken = json.loads(json.dumps(CASES))
        for c in broken:
            if c["id"] == "LMU-KU1":
                c["expected"] = ("witness copy checkpoint "
                                 "register blue folder")
        findings = MOD.check_cases(broken, REGISTER)
        self.assertTrue(any("LMU-KU1" in f for f in findings))

    def test_temporal_without_cue_flagged(self):
        broken = json.loads(json.dumps(CASES))
        for c in broken:
            if c["id"] == "LMU-TR1":
                c["question"] = "what did the reading room " \
                                 "open at"
        findings = MOD.check_cases(broken, REGISTER)
        self.assertTrue(any("cue" in f for f in findings))

    def test_wrong_as_of_flagged(self):
        broken = json.loads(json.dumps(CASES))
        for c in broken:
            if c["slice_class"] == "knowledge-update":
                c["expected_as_of"] = "2026-01-01"
        findings = MOD.check_cases(broken, REGISTER)
        self.assertTrue(findings)

    def test_definitions_only_no_dataset_payload(self):
        # Definitions/schema only: the register carries no
        # case questions or answers of its own.
        for cls in REGISTER["classes"]:
            self.assertNotIn("question", cls)
            self.assertNotIn("expected_answer", cls)


class BatteryPinTests(unittest.TestCase):
    def test_battery_byte_identical_when_present(self):
        battery = ROOT / "evaluation" / \
            "abstention-battery.jsonl"
        if not battery.is_file():
            self.skipTest("this tree carries no pinned "
                          "abstention battery")
        digest = hashlib.sha256(
            battery.read_bytes()).hexdigest()
        self.assertEqual(digest, BATTERY_SHA256)


if __name__ == "__main__":
    unittest.main()
