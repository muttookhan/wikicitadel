#!/usr/bin/env python3
"""Tests for scripts/wiki_answer_key_audit.py (Marathon R2 lane B2).

Fixture contract: a deliberately WRONG key is flagged suspect; a
correct key passes; a cited page that no longer exists is flagged;
an abstention question has no key to check and passes with that
reason stated. The audit is report-only — the set file is compared
byte-for-byte before and after."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load("wiki_answer_key_audit")


class TestAnswerKeyAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        (self.root / "wiki" / "page.md").write_text(
            "# Page\n\nThe seat is OPEN since 2026-10-16 and the "
            "rate is $44/hr.\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_correct_key_passes(self):
        q = {"id": "T-1", "key_facts": ["OPEN", "2026-10-16", "$44/hr"],
             "must_cite": ["wiki/page.md"], "expected_answer": "x"}
        row = audit.audit_question(q, self.root)
        self.assertEqual(row["verdict"], "ok", row)

    def test_deliberately_wrong_key_is_flagged_suspect(self):
        q = {"id": "T-2", "key_facts": ["OPEN", "purple elephants"],
             "must_cite": ["wiki/page.md"], "expected_answer": "x"}
        row = audit.audit_question(q, self.root)
        self.assertEqual(row["verdict"], "suspect")
        self.assertIn("purple elephants", row["reason"])

    def test_missing_cited_page_is_flagged_suspect(self):
        q = {"id": "T-3", "key_facts": ["OPEN"],
             "must_cite": ["wiki/gone.md"], "expected_answer": "x"}
        row = audit.audit_question(q, self.root)
        self.assertEqual(row["verdict"], "suspect")
        self.assertIn("wiki/gone.md", row["reason"])

    def test_abstention_question_has_no_key_to_check(self):
        q = {"id": "T-4", "expected_abstain": True, "key_facts": [],
             "must_cite": [], "expected_answer": ""}
        row = audit.audit_question(q, self.root)
        self.assertEqual(row["verdict"], "ok")
        self.assertIn("abstention", row["reason"])

    def test_golden_style_derived_terms(self):
        # No key_facts: salient terms derive from expected_answer.
        q = {"id": "T-5",
             "expected_answer": "OPEN since 2026-10-16 at $44/hr.",
             "must_cite": ["wiki/page.md"]}
        self.assertEqual(audit.audit_question(q, self.root)["verdict"], "ok")
        q2 = dict(q, expected_answer="CLOSED since 1999-01-01.")
        self.assertEqual(audit.audit_question(q2, self.root)["verdict"],
                         "suspect")

    def test_audit_never_edits_the_set(self):
        evaldir = self.root / "evaluation"
        evaldir.mkdir()
        setfile = evaldir / "set.jsonl"
        rows = [{"id": "T-1", "key_facts": ["OPEN"],
                 "must_cite": ["wiki/page.md"], "expected_answer": "x"},
                {"id": "T-2", "key_facts": ["absent term"],
                 "must_cite": ["wiki/page.md"], "expected_answer": "x"}]
        setfile.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                           encoding="utf-8")
        before = setfile.read_bytes()
        findings = audit.audit_sets(self.root, [setfile])
        self.assertEqual(setfile.read_bytes(), before)
        self.assertEqual([f["verdict"] for f in findings], ["ok", "suspect"])
        self.assertIn("report only", audit.render_report(findings))


if __name__ == "__main__":
    unittest.main()
