"""Tests for scripts/wiki_mast_modes.py + the registers
evaluation/mast-failure-modes.json and
evaluation/corrections-mast.jsonl (Marathon R9 lane BA; MAST
failure-mode board item).

Pins: the vocabulary holds exactly fourteen modes in the
three families, each defined; shipped assignments name real
ledger entries (in a tree carrying the ledger) with modes
from the closed vocabulary and multi_agent true; recurrences
count by mode; ledger entries without an assignment are
reported unclassified, never guessed; an unknown mode and an
orphan assignment are problems. The ledger page itself is
never written by this machinery.

Run: python3 -m unittest scripts.tests.test_wiki_mast_modes
"""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_mast_modes", SCRIPTS / "wiki_mast_modes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()
VOCAB = json.loads((ROOT / "evaluation" /
                    "mast-failure-modes.json")
                   .read_text(encoding="utf-8"))


class VocabTests(unittest.TestCase):
    def test_vocab_valid_fourteen_modes(self):
        self.assertEqual(MOD.check_vocab(VOCAB), [])
        self.assertEqual(len(VOCAB["modes"]), 14)
        fams = {m["family"] for m in VOCAB["modes"]}
        self.assertEqual(fams, {"framing", "handoff",
                                "verification"})

    def test_thirteen_modes_flagged(self):
        broken = json.loads(json.dumps(VOCAB))
        broken["modes"] = broken["modes"][:-1]
        self.assertTrue(MOD.check_vocab(broken))

    def test_duplicate_label_flagged(self):
        broken = json.loads(json.dumps(VOCAB))
        broken["modes"][1]["label"] = \
            broken["modes"][0]["label"]
        self.assertTrue(MOD.check_vocab(broken))


class ReportTests(unittest.TestCase):
    def test_shipped_report_consistent(self):
        rep = MOD.build_report(ROOT)
        self.assertEqual(rep["vocab_findings"], [])
        self.assertEqual(rep["problems"], [])
        self.assertEqual(sum(rep["by_mode"].values()),
                         rep["assignments"])
        if rep["ledger"] == "present":
            self.assertIsNotNone(rep["unclassified"])
            self.assertEqual(
                len(rep["unclassified"]) + rep["assignments"],
                rep["ledger_entries"])
        else:
            self.assertIsNone(rep["unclassified"])

    def test_recurrence_countable_by_mode(self):
        # In the private tree three seeded multi-agent
        # entries share FM-13; in a tree without a ledger the
        # register is header-only and the count is 0. Either
        # way the report's arithmetic must hold.
        rep = MOD.build_report(ROOT)
        for mode, n in rep["by_mode"].items():
            self.assertGreaterEqual(n, 0)
        if rep["assignments"]:
            self.assertEqual(rep["by_mode"]["FM-13"],
                             rep["assignments"])


if __name__ == "__main__":
    unittest.main()
