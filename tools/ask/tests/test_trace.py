"""Tests for tools/ask/trace.py (Marathon R3 lane TB1, EU6a).

Pins: a trace carries the retrieved ids (packed + dropped +
severed — the road not taken too), the per-passage packing
decisions with reasons, and the gate verdicts computed by the
contract's own functions; traces append/read as JSONL beside
the Q&A file; pickup stamps a supplied trace additively and
the record-answer trace seam files it beside the Q&A record.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pickup  # noqa: E402
import trace  # noqa: E402


def record():
    return {
        "id": "q_tr1", "question": "Where does the wiki live?",
        "answer": "On Azure.", "citations": ["overview"],
        "status": "answered",
    }


def pack():
    return {
        "budget": 100, "tokens_used": 10,
        "packed": [{"page": "overview", "passage": "On Azure.",
                    "score": 0.9, "tokens": 3}],
        "dropped": [{"page": "concepts/x", "passage": "Long.",
                     "score": 0.4, "tokens": 90,
                     "reason": "over-budget"}],
        "severed": [{"page": "sources/old", "passage": "Dead.",
                     "score": 0.8, "tokens": 2, "reason": "severed"}],
        "all_evidence_severed": False,
    }


class BuildTraceTests(unittest.TestCase):
    def test_trace_carries_retrieval_packing_and_gates(self):
        t = trace.build_trace(record(), pack())
        self.assertEqual(t["kind"], "ask-trace")
        self.assertEqual(t["question_id"], "q_tr1")
        self.assertEqual(t["retrieved_ids"],
                         ["overview", "concepts/x", "sources/old"])
        decisions = {p["page"]: p["decision"]
                     for group in ("packed", "dropped", "severed")
                     for p in t["packing"][group]}
        self.assertEqual(decisions, {"overview": "packed",
                                     "concepts/x": "dropped",
                                     "sources/old": "severed"})
        dropped = t["packing"]["dropped"][0]
        self.assertEqual(dropped["reason"], "over-budget")
        self.assertTrue(t["gates"]["contract_ok"])
        self.assertEqual(t["gates"]["trust_verdict"], "ok")
        self.assertFalse(t["gates"]["abstained"])

    def test_trace_without_pack_falls_back_to_citations(self):
        t = trace.build_trace(record())
        self.assertEqual(t["retrieved_ids"], ["overview"])
        self.assertEqual(t["packing"]["packed"], [])

    def test_abstained_record_traces_as_hold(self):
        rec = record()
        rec["abstained"] = True
        rec["abstention_reason"] = "no evidence in the wiki"
        rec["citations"] = []
        t = trace.build_trace(rec)
        self.assertTrue(t["gates"]["abstained"])
        self.assertEqual(t["gates"]["trust_verdict"], "hold")


class BesideFileTests(unittest.TestCase):
    def test_path_and_jsonl_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            qa = Path(tmp) / "qa-2026.jsonl"
            beside = trace.trace_path_beside(qa)
            self.assertEqual(beside.name, "qa-2026.traces.jsonl")
            trace.append_trace(beside, trace.build_trace(record(), pack()))
            trace.append_trace(beside, trace.build_trace(record()))
            rows = trace.read_traces(beside)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["question_id"], "q_tr1")

    def test_pickup_stamps_trace_additively(self):
        t = trace.build_trace(record(), pack())
        rec = pickup.build_qa_record(
            {"id": "q_tr1", "question": "Where does the wiki live?",
             "asker": "owner@example.invalid",
             "asked_at": "2026-10-21T00:00:00Z"},
            "On Azure.", ["overview"], "2026-10-21T00:05:00Z",
            trace=t)
        self.assertEqual(rec["trace"]["kind"], "ask-trace")
        plain = pickup.build_qa_record(
            {"id": "q_tr2", "question": "Q?", "asker": "a",
             "asked_at": "2026-10-21T00:00:00Z"},
            "A.", ["overview"], "2026-10-21T00:06:00Z")
        self.assertNotIn("trace", plain)
        self.assertNotIn("two_phase", plain)


if __name__ == "__main__":
    unittest.main()
