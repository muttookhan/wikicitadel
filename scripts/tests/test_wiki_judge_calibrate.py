#!/usr/bin/env python3
"""Wave-3 set E: judge calibration — confusion math and the refusal.

Covers ``scripts/wiki_judge_calibrate.py`` (the runner) and
``evaluation/judge-calibration/stub_judge.py`` (the deterministic
stand-in judge):

- the confusion matrix and TPR/TNR are computed exactly, with a
  zero-denominator class reported as None, never smoothed;
- certification is REFUSED when any bar is unmet: too few
  examples, too few owner-labelled examples, TPR or TNR below
  0.8, a prompt-pin mismatch (config drift), and judge kinds that
  are not wired (``llm``, unknown);
- the shipped config + starter set: the pin verifies, the stub
  clears both rate bars, and certification is refused on the
  owner-labelling bar alone (owner-labelled examples: 0).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JC = ROOT / "evaluation" / "judge-calibration"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cal = _load("wiki_judge_calibrate", ROOT / "scripts" / "wiki_judge_calibrate.py")
stub = _load("stub_judge", JC / "stub_judge.py")


def real_config():
    return json.loads((JC / "judge-config.json").read_text(encoding="utf-8"))


def real_examples():
    return cal.load_jsonl(JC / "labeled-examples.jsonl")


GOOD = {"answer": "The wiki exists.", "citations": ["overview"]}
BAD = {"answer": "An answer with no citations and no abstention."}


def example(label, candidate, expected=None):
    return {
        "id": "T-1", "question_id": "T", "question": "?",
        "candidate": candidate, "expected": expected or {},
        "label": label, "label_source": "gold-answer",
        "provenance": "test",
    }


class ConfusionTests(unittest.TestCase):
    def test_exact_counts_and_rates(self):
        judgements = [
            {"label": "accept", "verdict": "accept"},
            {"label": "accept", "verdict": "accept"},
            {"label": "accept", "verdict": "reject"},
            {"label": "reject", "verdict": "reject"},
            {"label": "reject", "verdict": "accept"},
        ]
        c = cal.confusion(judgements)
        self.assertEqual((c["tp"], c["fn"], c["tn"], c["fp"]), (2, 1, 1, 1))
        self.assertAlmostEqual(c["tpr"], 2 / 3, places=3)
        self.assertAlmostEqual(c["tnr"], 1 / 2, places=3)

    def test_missing_class_is_none_not_zero(self):
        c = cal.confusion([{"label": "accept", "verdict": "accept"}])
        self.assertEqual(c["tpr"], 1.0)
        self.assertIsNone(c["tnr"])


class StubJudgeTests(unittest.TestCase):
    def test_good_record_accepted(self):
        out = stub.judge(GOOD, {"expected_abstain": False}, ROOT / "wiki")
        self.assertEqual(out["verdict"], "accept")

    def test_uncited_answer_rejected(self):
        out = stub.judge(BAD, {"expected_abstain": False}, ROOT / "wiki")
        self.assertEqual(out["verdict"], "reject")

    def test_forbidden_claim_rejected(self):
        rec = {"answer": "Galen's seat is reserved.",
               "citations": ["overview"]}
        out = stub.judge(
            rec,
            {"expected_abstain": False,
             "forbidden_claims": ["Galen's seat is reserved"]},
            ROOT / "wiki",
        )
        self.assertEqual(out["verdict"], "reject")

    def test_missing_key_fact_rejected(self):
        out = stub.judge(
            GOOD,
            {"expected_abstain": False, "key_facts": ["never stated"]},
            ROOT / "wiki",
        )
        self.assertEqual(out["verdict"], "reject")

    def test_wrong_abstention_both_directions(self):
        abst = {"answer": "Not recorded.", "abstained": True,
                "abstention_reason": "Nothing records it."}
        self.assertEqual(
            stub.judge(abst, {"expected_abstain": True},
                       ROOT / "wiki")["verdict"], "accept")
        self.assertEqual(
            stub.judge(abst, {"expected_abstain": False},
                       ROOT / "wiki")["verdict"], "reject")
        self.assertEqual(
            stub.judge(GOOD, {"expected_abstain": True},
                       ROOT / "wiki")["verdict"], "reject")


class CertificationRefusalTests(unittest.TestCase):
    def test_shipped_set_refused_on_owner_bar_only(self):
        report = cal.run_calibration(real_config(), real_examples())
        self.assertTrue(report["judge"]["pin_ok"])
        self.assertFalse(report["certified"])
        self.assertEqual(report["owner_labeled"], 0)
        reasons = " ".join(report["refusal_reasons"])
        self.assertIn("owner-labelled", reasons)
        # The stub clears both rate bars on the derived set; the
        # ONLY unmet bar is owner labelling.
        self.assertGreaterEqual(report["confusion"]["tpr"], 0.8)
        self.assertGreaterEqual(report["confusion"]["tnr"], 0.8)
        self.assertEqual(len(report["refusal_reasons"]), 1)

    def test_too_few_examples_refused(self):
        report = cal.run_calibration(
            real_config(), [example("accept", GOOD)]
        )
        self.assertFalse(report["certified"])
        self.assertIn("labelled examples",
                      " ".join(report["refusal_reasons"]))

    def test_low_tpr_refused(self):
        examples = [example("accept", BAD) for _ in range(3)]
        report = cal.run_calibration(real_config(), examples)
        self.assertFalse(report["certified"])
        self.assertEqual(report["confusion"]["tpr"], 0.0)
        self.assertIn("TPR", " ".join(report["refusal_reasons"]))

    def test_low_tnr_refused(self):
        examples = [example("reject", GOOD) for _ in range(3)]
        report = cal.run_calibration(real_config(), examples)
        self.assertFalse(report["certified"])
        self.assertEqual(report["confusion"]["tnr"], 0.0)
        self.assertIn("TNR", " ".join(report["refusal_reasons"]))

    def test_pin_drift_refused(self):
        config = copy.deepcopy(real_config())
        config["judge"]["prompt_sha256"] = "0" * 64
        report = cal.run_calibration(config, real_examples())
        self.assertFalse(report["certified"])
        self.assertFalse(report["judge"]["pin_ok"])
        self.assertIn("pin", " ".join(report["refusal_reasons"]))

    def test_llm_kind_refused_not_faked(self):
        config = copy.deepcopy(real_config())
        config["judge"]["kind"] = "llm"
        config["judge"]["model"] = "some-model"
        report = cal.run_calibration(config, real_examples())
        self.assertFalse(report["certified"])
        self.assertIn("no LLM judge",
                      " ".join(report["refusal_reasons"]))

    def test_unknown_kind_refused(self):
        config = copy.deepcopy(real_config())
        config["judge"]["kind"] = "coin-flip"
        report = cal.run_calibration(config, real_examples())
        self.assertFalse(report["certified"])
        self.assertIn("unknown judge kind",
                      " ".join(report["refusal_reasons"]))


if __name__ == "__main__":
    unittest.main()
