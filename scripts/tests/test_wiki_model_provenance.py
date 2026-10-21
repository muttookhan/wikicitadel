#!/usr/bin/env python3
"""Model-identity provenance (Marathon R8, Panickssery et al.).

Pins scripts/wiki_model_provenance.py plus the recorder
extension: a same-model verification/outcome line is flagged
report-only (self-verification visible on the record), a
different-model line is independent, a pre-existing line with
neither field is legacy-unrecorded (reported honestly, never
failed, never rewritten), and a half-recorded line is a
defect. The recorders (wiki_reverify.record /
wiki_claims.measure) stamp exactly provenance_fields().
No network. Run: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mp = load("wiki_model_provenance", "scripts/wiki_model_provenance.py")


class TestClassify(unittest.TestCase):
    def test_same_model_is_report_only(self):
        rec = {"generator_model": "Model A", "verifier_model": "model a"}
        self.assertEqual(mp.classify_line(rec), "report-only")

    def test_different_models_are_independent(self):
        rec = {"generator_model": "Model A", "verifier_model": "Model B"}
        self.assertEqual(mp.classify_line(rec), "independent")

    def test_legacy_line_is_unrecorded_not_defective(self):
        rec = {"claim": "wiki/x.md", "outcome": "pass"}
        self.assertEqual(mp.classify_line(rec), "legacy-unrecorded")
        self.assertEqual(mp.validate_line(rec), [])

    def test_partial_line_is_a_defect(self):
        rec = {"generator_model": "Model A"}
        self.assertEqual(mp.classify_line(rec), "partial")
        self.assertTrue(mp.validate_line(rec))

    def test_empty_model_is_a_defect(self):
        rec = {"generator_model": "  ", "verifier_model": "Model B"}
        self.assertTrue(mp.validate_line(rec))


class TestProvenanceFields(unittest.TestCase):
    def test_self_verification_flag_stamped(self):
        fields = mp.provenance_fields("Model A", "Model A")
        self.assertTrue(fields["self_verification"])
        self.assertEqual(fields["verification_standing"], "report-only")

    def test_independent_flag_stamped(self):
        fields = mp.provenance_fields("Model A", "Model B")
        self.assertFalse(fields["self_verification"])
        self.assertEqual(fields["verification_standing"], "independent")

    def test_both_or_neither(self):
        self.assertEqual(mp.provenance_fields(None, None), {})
        with self.assertRaises(ValueError):
            mp.provenance_fields("Model A", None)
        with self.assertRaises(ValueError):
            mp.provenance_fields(None, "Model B")

    def test_with_provenance_does_not_mutate_input(self):
        rec = {"outcome": "supports"}
        out = mp.with_provenance(rec, "A", "B")
        self.assertNotIn("generator_model", rec)
        self.assertEqual(out["verifier_model"], "B")


class TestReport(unittest.TestCase):
    def test_report_counts_each_class(self):
        tmp = Path(tempfile.mkdtemp(prefix="prov-fix-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        reg = tmp / "reg.jsonl"
        lines = [
            {"generator_model": "A", "verifier_model": "A"},
            {"generator_model": "A", "verifier_model": "B"},
            {"outcome": "pass"},
            {"generator_model": "A"},
        ]
        reg.write_text("".join(json.dumps(x) + "\n" for x in lines),
                       encoding="utf-8")
        row = mp.report_for(reg)
        self.assertEqual(row["lines"], 4)
        self.assertEqual(row["report-only"], 1)
        self.assertEqual(row["independent"], 1)
        self.assertEqual(row["legacy-unrecorded"], 1)
        self.assertEqual(row["partial"], 1)
        self.assertEqual(len(row["problems"]), 1)

    def test_missing_register_reports_zero_not_error(self):
        row = mp.report_for(ROOT / "evaluation" / "no-such.jsonl")
        self.assertEqual(row["lines"], 0)


class TestRecordersCarryTheFields(unittest.TestCase):
    def test_reverify_and_claims_accept_model_flags(self):
        for rel in ("scripts/wiki_reverify.py", "scripts/wiki_claims.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("--generator-model", text, rel)
            self.assertIn("--verifier-model", text, rel)
            self.assertIn("provenance_fields", text, rel)


if __name__ == "__main__":
    unittest.main()
