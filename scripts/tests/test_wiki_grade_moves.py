#!/usr/bin/env python3
"""Tests for scripts/wiki_grade_moves.py (TB3-8).

Pins the GRADE moved_by discipline in the claims/outcomes
register format: a subject's first grade is an assignment
(no moved_by owed); a later CHANGE of that grade with a
moved_by is clean; a change without moved_by is a finding
naming from -> to; restating the same grade is not a move;
the source-grades axis lines (subject key `source`, field
`grade`) are linted the same way.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_grade_moves", SCRIPTS / "wiki_grade_moves.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def register(lines):
    p = Path(tempfile.mkdtemp()) / "reg.jsonl"
    p.write_text("".join(json.dumps(ln) + "\n" for ln in lines),
                 encoding="utf-8")
    return p


class TestGradeMoves(unittest.TestCase):
    def test_first_grade_needs_no_moved_by(self):
        p = register([{"page": "wiki/x.md", "grade": "low"}])
        self.assertEqual(M.lint_register(p), [])

    def test_change_with_moved_by_is_clean(self):
        p = register([
            {"page": "wiki/x.md", "grade": "low"},
            {"page": "wiki/x.md", "grade": "medium",
             "moved_by": "outcome o-0007 supports (2026-10-21)"}])
        self.assertEqual(M.lint_register(p), [])

    def test_change_without_moved_by_is_a_finding(self):
        p = register([
            {"page": "wiki/x.md", "confidence": "low"},
            {"page": "wiki/x.md", "confidence": "high"}])
        findings = M.lint_register(p)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["from"], "low")
        self.assertEqual(findings[0]["to"], "high")

    def test_restatement_is_not_a_move(self):
        p = register([
            {"source": "wiki/sources/s.md", "grade": "exact"},
            {"source": "wiki/sources/s.md", "grade": "exact"}])
        self.assertEqual(M.lint_register(p), [])

    def test_header_lines_skipped(self):
        p = register([
            {"kind": "header", "register": "outcomes"},
            {"page": "wiki/x.md", "certainty": "almost-certain"},
            {"page": "wiki/x.md", "certainty": "likely",
             "moved_by": "reverify fail 2026-10-21"}])
        self.assertEqual(M.lint_register(p), [])


if __name__ == "__main__":
    unittest.main()
