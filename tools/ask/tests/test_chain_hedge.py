"""Tests for the chain-hedge hold (item 34; AbstentionBench).

Covers ``answer_contract.chain_hedge_findings`` and the
``compute_trust_verdict`` overlay: a non-abstained unit whose
carried chain text expresses uncertainty forces the verdict to
``hold``; the identical record without chain text is unaffected;
an abstained unit is never a hedge finding (its hold comes from
the structural abstention rule).

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_chain_hedge -v
or directly:
    python3 tools/ask/tests/test_chain_hedge.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import answer_contract  # noqa: E402


def base_record():
    return {
        "answer": "The wiki's canonical home is its git remote.",
        "citations": [{"page": "overview", "score": 0.9,
                       "passage": "the wiki stays LOCAL + AZURE"}],
    }


class TestChainHedge(unittest.TestCase):
    def test_hedging_chain_forces_hold(self):
        record = base_record()
        record["chain"] = (
            "I am not sure the pages retrieved are the whole "
            "record, and I cannot verify nothing superseded this.")
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "hold")
        findings = answer_contract.chain_hedge_findings(record)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["unit"], "answer")

    def test_same_record_without_chain_stays_ok(self):
        record = base_record()
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "ok")
        self.assertEqual(
            answer_contract.chain_hedge_findings(record), [])

    def test_reasoning_field_is_also_a_chain(self):
        record = base_record()
        record["reasoning"] = "The evidence is insufficient evidence."
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "hold")

    def test_confident_chain_does_not_trigger(self):
        record = base_record()
        record["chain"] = "The decisions page states this directly."
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "ok")
        self.assertEqual(
            answer_contract.chain_hedge_findings(record), [])

    def test_sub_answer_hedge_forces_hold(self):
        record = {
            "answer": "Both parts are settled.",
            "citations": ["overview", "entities/owner"],
            "sub_answers": [
                {"answer": "Part one.",
                 "citations": [{"page": "overview", "score": 0.9,
                                "passage": "the wiki stays LOCAL"}],
                 "chain": "The page is clear."},
                {"answer": "Part two.",
                 "citations": [{"page": "entities/owner",
                                "score": 0.85,
                                "passage": "one founding note"}],
                 "chain": "I cannot determine this from the pages "
                          "retrieved."},
            ],
        }
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "hold")
        findings = answer_contract.chain_hedge_findings(record)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["unit"], "sub_answers[1]")

    def test_abstained_unit_is_never_a_hedge_finding(self):
        record = {
            "answer": "The wiki does not record this.",
            "abstained": True,
            "abstention_reason": "No page records the fact.",
            "citations": [],
            "chain": "I am not sure where else to look.",
        }
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "hold")
        self.assertEqual(
            answer_contract.chain_hedge_findings(record), [])

    def test_hedge_outranks_review_overlay(self):
        # A record already at review (weak scores) with a hedging
        # chain lands on hold: hold outranks review.
        record = {
            "answer": "Possibly Azure.",
            "citations": [{"page": "overview", "score": 0.4,
                           "passage": "the wiki stays LOCAL"}],
            "chain": "This is uncertain — the wiki does not say.",
        }
        self.assertEqual(
            answer_contract.compute_trust_verdict(record), "hold")


if __name__ == "__main__":
    unittest.main()
