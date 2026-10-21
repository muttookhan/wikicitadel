#!/usr/bin/env python3
"""Model-identity provenance on verification / outcome lines
(Marathon R8, Tier A; Panickssery et al., NeurIPS 2024).

Pattern: a model asked to verify its own output recognises and
favours it, so a verification performed by the SAME model that
generated the claim is weaker evidence than an independent one.
That weakness is invisible unless the record says who did what.
So, from this build on, a per-claim verification line
(evaluation/reverify-history.jsonl, written by
scripts/wiki_reverify.py) and a per-claim outcome line
(evaluation/outcomes.jsonl, written by scripts/wiki_claims.py)
MAY carry two extra fields, and new lines written through those
tools' --generator-model / --verifier-model flags DO:

    "generator_model": "<model that produced the claim/answer>"
    "verifier_model":  "<model that verified / measured it>"

plus the derived pair the recorders stamp at write time:

    "self_verification": true | false
    "verification_standing": "report-only" | "independent"

A same-model line (generator_model == verifier_model, compared
case-insensitively after stripping) is flagged REPORT-ONLY: it
is on the record, it is never hidden, and it must not be cited
as independent verification.

HISTORY IS NEVER REWRITTEN. Lines written before this field
existed carry neither field; the report below counts them
honestly as "legacy-unrecorded" — it does not guess a model
for them, and no tool here edits a register in place. The only
writes are the recorders' normal appends of NEW lines.

Usage:
  python3 scripts/wiki_model_provenance.py report
          [--register FILE ...] [--json]
  python3 scripts/wiki_model_provenance.py check
          [--register FILE ...]

`report` prints, per register and in total: lines, lines with
provenance, independent lines, same-model (report-only) lines,
partial lines (only one of the two fields — a defect on a new
line), and legacy-unrecorded lines. `check` exits 1 when any
line is partial (exactly one field present) or carries an
empty / non-string model value; legacy lines are NOT a check
failure — they are history, reported as such.

Exit codes: report 0; check 0 = no defects, 1 = defects;
2 = usage error. Stdlib only, no network, no model calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTERS = (
    ROOT / "evaluation" / "reverify-history.jsonl",
    ROOT / "evaluation" / "outcomes.jsonl",
)

FIELDS = ("generator_model", "verifier_model")


def _norm(value):
    return value.strip().lower() if isinstance(value, str) else None


def classify_line(record):
    """One register line -> its provenance class, one of:
    "independent"       both fields, different models;
    "report-only"       both fields, the SAME model (self-verification);
    "partial"           exactly one field present (a defect);
    "legacy-unrecorded" neither field (pre-existing history)."""
    gen, ver = record.get("generator_model"), record.get("verifier_model")
    if gen is None and ver is None:
        return "legacy-unrecorded"
    if gen is None or ver is None:
        return "partial"
    if _norm(gen) and _norm(gen) == _norm(ver):
        return "report-only"
    return "independent"


def validate_line(record):
    """Problems with one line's provenance fields ([] = clean).
    Legacy lines are clean by definition: absence is reported,
    never retro-fitted and never an error."""
    problems = []
    cls = classify_line(record)
    if cls == "partial":
        present = "generator_model" if record.get("generator_model") \
            is not None else "verifier_model"
        problems.append(
            f"partial provenance: {present} present without its pair "
            f"(a new line must record both models or neither)")
    for field in FIELDS:
        value = record.get(field)
        if value is not None and (not isinstance(value, str)
                                  or not value.strip()):
            problems.append(f"{field} is present but empty / not a string")
    return problems


def provenance_fields(generator_model, verifier_model):
    """The field dict a recorder appends for a NEW line. Both
    models or neither: a lone model raises ValueError, because a
    half-recorded provenance is worse than an honest absence."""
    if (generator_model is None) != (verifier_model is None):
        raise ValueError(
            "generator_model and verifier_model must be given together")
    if generator_model is None:
        return {}
    gen, ver = str(generator_model).strip(), str(verifier_model).strip()
    if not gen or not ver:
        raise ValueError("model identities must be non-empty strings")
    same = gen.lower() == ver.lower()
    return {
        "generator_model": gen,
        "verifier_model": ver,
        "self_verification": same,
        "verification_standing": "report-only" if same else "independent",
    }


def with_provenance(record, generator_model, verifier_model):
    """A COPY of `record` extended with the provenance fields
    (the input dict is never mutated)."""
    out = dict(record)
    out.update(provenance_fields(generator_model, verifier_model))
    return out


def load_register(path):
    records = []
    if not Path(path).exists():
        return records
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def report_for(path):
    records = load_register(path)
    counts = {"lines": len(records), "independent": 0, "report-only": 0,
              "partial": 0, "legacy-unrecorded": 0, "problems": []}
    for i, rec in enumerate(records, 1):
        counts[classify_line(rec)] += 1
        for problem in validate_line(rec):
            counts["problems"].append(f"line {i}: {problem}")
    counts["with_provenance"] = counts["independent"] + counts["report-only"]
    counts["register"] = str(path)
    return counts


def build_report(paths):
    per = [report_for(p) for p in paths]
    total = {"lines": 0, "independent": 0, "report-only": 0, "partial": 0,
             "legacy-unrecorded": 0, "with_provenance": 0, "problems": []}
    for row in per:
        for key in ("lines", "independent", "report-only", "partial",
                    "legacy-unrecorded", "with_provenance"):
            total[key] += row[key]
        total["problems"] += [f"{row['register']}: {p}"
                              for p in row["problems"]]
    return {"registers": per, "total": total}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", action="append", default=None,
                    help="register file (repeatable; default: the "
                         "reverify history and the outcomes log)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.register] if args.register \
        else list(DEFAULT_REGISTERS)
    report = build_report(paths)
    if args.cmd == "report":
        for row in report["registers"]:
            print(f"{row['register']}: {row['lines']} line(s) — "
                  f"{row['with_provenance']} with provenance "
                  f"({row['independent']} independent, "
                  f"{row['report-only']} same-model/report-only), "
                  f"{row['partial']} partial, "
                  f"{row['legacy-unrecorded']} legacy-unrecorded")
        t = report["total"]
        print(f"total: {t['lines']} line(s), {t['report-only']} "
              f"same-model line(s) flagged report-only, "
              f"{t['legacy-unrecorded']} legacy line(s) with no "
              f"model identity recorded (history, not a defect)")
        for problem in t["problems"]:
            print(f"  PROBLEM: {problem}")
        return 0
    problems = report["total"]["problems"]
    if problems:
        print(f"model-provenance check: {len(problems)} defect(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("model-provenance check: OK (no partial or empty "
          "provenance fields; legacy lines reported, not failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
