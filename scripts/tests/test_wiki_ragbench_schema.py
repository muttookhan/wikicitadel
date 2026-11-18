"""Tests for scripts/wiki_ragbench_schema.py + evaluation/
ragbench-row-schema.json (Marathon R8 lane BB; schema only -
the external RAGBench dataset is NOT imported).

Pins: a conforming row passes; unsupported-with-keys and
supported-without-keys fail; unknown verdict fails; missing
provenance fails; the shipped schema declares all verdicts.

Run: python3 -m unittest scripts.tests.test_wiki_ragbench_schema
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_ragbench_schema", SCRIPTS / "wiki_ragbench_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()
SCHEMA = MOD.load_schema()


def good_row():
    return {
        "id": "SS-001", "question": "Q?",
        "response_sentences": [
            {"sentence": "A stands.", "support_verdict":
             "supported", "supporting_keys": ["wiki/a.md"]},
            {"sentence": "B falls.", "support_verdict":
             "unsupported", "supporting_keys": []}],
        "scorer_columns": {"deterministic": {"SS-001": 0.5}},
        "provenance": {
            "generator": {"kind": "model", "name": "harness-x"},
            "annotator": {"kind": "human", "name": "owner"}}}


class RowTests(unittest.TestCase):
    def test_good_row_passes(self):
        self.assertEqual(MOD.validate_row(good_row(), SCHEMA),
                         [])

    def test_unsupported_with_keys_fails(self):
        row = good_row()
        row["response_sentences"][1]["supporting_keys"] = ["x"]
        self.assertTrue(MOD.validate_row(row, SCHEMA))

    def test_supported_without_keys_fails(self):
        row = good_row()
        row["response_sentences"][0]["supporting_keys"] = []
        self.assertTrue(MOD.validate_row(row, SCHEMA))

    def test_unknown_verdict_and_missing_provenance_fail(self):
        row = good_row()
        row["response_sentences"][0]["support_verdict"] = "meh"
        self.assertTrue(MOD.validate_row(row, SCHEMA))
        row = good_row()
        del row["provenance"]["annotator"]
        self.assertTrue(MOD.validate_row(row, SCHEMA))

    def test_schema_declares_verdicts(self):
        self.assertEqual(
            set(SCHEMA["row"]["support_verdicts"]),
            {"supported", "partially-supported", "unsupported"})


if __name__ == "__main__":
    unittest.main()
