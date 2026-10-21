#!/usr/bin/env python3
"""GRADE moved_by discipline on certainty grades (Marathon
R3, Tier B row TB3-8).

Pattern: GRADE (the evidence-certainty framework used in
systematic reviews) — a certainty grade is never just
changed; it is MOVED, by named evidence, and the move is
part of the record. Adopted here as a lint over this wiki's
grade-bearing registers, in the claims/outcomes register
format family (append-only JSONL, one event per line, a
subject's current state the fold of its lines — the same
shape as evaluation/outcomes.jsonl and
evaluation/source-grades.jsonl).

THE RULE: a line that carries a grade field — `grade`,
`confidence`, or `certainty` — and CHANGES the value that
subject (the line's `subject`, `source`, or `page` key, in
that order) previously held for that field, must itself
carry `moved_by`: a non-empty string naming who or what
evidence moved the grade ("outcome o-0042 contradicts",
"owner ruling 2026-10-21"). A subject's FIRST grade is an
assignment, not a move, and needs no moved_by. A line that
restates the same grade is not a move. Moves recorded
without moved_by are findings, listed by register, line,
subject, field, and the from -> to values.

The lint reports; it never rewrites a register line (the
registers are append-only — a missing moved_by is cured by
a new line recording it, not by editing history).

Usage:
  python3 scripts/wiki_grade_moves.py check [REGISTER...]
      (default: evaluation/outcomes.jsonl and
       evaluation/source-grades.jsonl under --root)

Exit codes: 0 = no undisciplined moves, 1 = findings,
2 = usage error. Output is JSON. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRADE_FIELDS = ("grade", "confidence", "certainty")
SUBJECT_KEYS = ("subject", "source", "page")
DEFAULT_REGISTERS = ("evaluation/outcomes.jsonl",
                     "evaluation/source-grades.jsonl")


def lint_register(path: Path):
    """Findings for one register: moves of a grade field
    that carry no moved_by."""
    findings = []
    if not path.is_file():
        return findings
    current = {}  # (subject, field) -> value
    for idx, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines()):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            findings.append({"line": idx, "problem": "unparseable line"})
            continue
        if rec.get("kind") == "header":
            continue
        subject = next((rec[k] for k in SUBJECT_KEYS if rec.get(k)),
                       None)
        if subject is None:
            continue
        for field in GRADE_FIELDS:
            if field not in rec:
                continue
            value = rec[field]
            # A register may grade one subject on several axes
            # (source-grades: integrity / precision) — a move is
            # a change within one axis, never across axes.
            key = (subject, rec.get("axis"), field)
            if key in current and current[key] != value:
                moved_by = rec.get("moved_by")
                if not (isinstance(moved_by, str)
                        and moved_by.strip()):
                    findings.append({
                        "line": idx, "subject": subject,
                        "field": field, "from": current[key],
                        "to": value,
                        "problem": "grade changed without moved_by"})
            current[key] = value
    return findings


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("registers", nargs="*",
                    help="registers to lint (default: the claims/"
                         "outcomes + source-grades registers)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    rels = list(args.registers)
    if rels and rels[0] == "check":
        rels = rels[1:]
    rels = rels or list(DEFAULT_REGISTERS)
    report, bad = {}, False
    for rel in rels:
        findings = lint_register(root / rel)
        report[rel] = findings
        bad = bad or bool(findings)
    print(json.dumps({"registers": report, "clean": not bad},
                     indent=2, sort_keys=True))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
