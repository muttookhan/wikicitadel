"""Tests for scripts/wiki_posq_check.py — the PosQ-style
positional-bias slice (Marathon Round 6, lane BA, item 4):
the shipped slice definition validates; the fixture
carriers are identical apart from passage position (same
token multiset, same length); the check runs the REAL
ranker (scripts/wiki_search.py hybrid_rank) and reports a
rank/score per position; slice-definition defects are
caught; and the verdict logic records a collapse when one
is forced (a criteria dict no ranker could pass), instead
of the report being hard-coded green.

The measured positional behaviour of the current ranker
is asserted as ranges, not a frozen score: BM25 is
position-blind by construction (equal scores across
positions), every carrier must stay within the slice's
max_rank, and the end position's known lead-coverage
penalty must remain visible in the report (ratio < 1.0)
rather than normalised away. If a future ranker change
heals or worsens that penalty, the ratio assertion is the
tripwire that makes the change show up here.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import copy
import importlib.util
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_posq_check", HERE.parents[1] / "wiki_posq_check.py")
posq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(posq)

ROOT = HERE.parents[2]


def shipped():
    return posq.load_slice(ROOT / "evaluation" / "posq-slice.json")


class SliceTest(unittest.TestCase):
    def test_shipped_slice_validates_clean(self):
        self.assertEqual(posq.check_slice(shipped()), [])
        self.assertEqual(posq.main(["check"]), 0)

    def test_slice_defects_are_caught(self):
        data = shipped()
        bad_positions = copy.deepcopy(data)
        bad_positions["carrier"]["positions"] = ["start", "end"]
        self.assertTrue(any("positions" in p
                            for p in posq.check_slice(bad_positions)))
        bad_ratio = copy.deepcopy(data)
        bad_ratio["collapse_criteria"]["min_score_ratio"] = 0
        self.assertTrue(any("min_score_ratio" in p
                            for p in posq.check_slice(bad_ratio)))


class FixtureTest(unittest.TestCase):
    def test_carriers_differ_only_by_position(self):
        docs = posq.build_fixtures(shipped())
        carriers = {str(p): t for p, t in docs
                    if str(p).startswith("carrier-")}
        self.assertEqual(sorted(carriers),
                         ["carrier-end.md", "carrier-middle.md",
                          "carrier-start.md"])
        token_sets = {name: Counter(t.split())
                      for name, t in carriers.items()}
        base = token_sets["carrier-start.md"]
        for name, counts in token_sets.items():
            self.assertEqual(counts, base, name)
        # ...and the passage really is at a different offset.
        passage = shipped()["relevant_passage"][:20]
        offsets = {name: t.index(passage)
                   for name, t in carriers.items()}
        self.assertLess(offsets["carrier-start.md"],
                        offsets["carrier-middle.md"])
        self.assertLess(offsets["carrier-middle.md"],
                        offsets["carrier-end.md"])


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = posq.run_slice(shipped())

    def test_report_covers_every_position(self):
        self.assertEqual(sorted(self.report["positions"]),
                         ["end", "middle", "start"])
        for entry in self.report["positions"].values():
            self.assertIsNotNone(entry["rank"])
            self.assertGreater(entry["score"], 0)

    def test_bm25_is_position_blind(self):
        bm25s = {e["bm25"]
                 for e in self.report["positions"].values()}
        self.assertEqual(len(bm25s), 1)

    def test_no_collapse_on_current_ranker(self):
        self.assertEqual(self.report["verdict"], "no-collapse")
        self.assertEqual(self.report["failures"], [])
        self.assertEqual(posq.main(["run"]), 0)

    def test_positional_penalty_is_reported_not_hidden(self):
        end = self.report["positions"]["end"]
        # The stage-4 lead-coverage rerank rewards query
        # terms inside the first RERANK_LEAD_TOKENS tokens;
        # the end carrier's passage sits beyond that window,
        # so its measured ratio is below 1.0 today. This is
        # reported behaviour, not a failure of the slice's
        # collapse criteria (0.5).
        self.assertLess(end["score_ratio"], 1.0)
        self.assertGreaterEqual(
            end["score_ratio"],
            shipped()["collapse_criteria"]["min_score_ratio"])

    def test_forced_impossible_criteria_record_collapse(self):
        data = shipped()
        data["collapse_criteria"]["min_score_ratio"] = 1.0
        data["collapse_criteria"]["max_rank"] = 1
        report = posq.run_slice(data)
        self.assertEqual(report["verdict"], "collapse")
        self.assertTrue(report["failures"])


if __name__ == "__main__":
    unittest.main()
