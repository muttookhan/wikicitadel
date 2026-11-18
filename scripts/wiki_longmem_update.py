#!/usr/bin/env python3
"""Checker for the LongMemEval knowledge-update + temporal slice.

Marathon R9 lane BA (ideas board R7 research, Tier A):
LongMemEval's knowledge-update and temporal-reasoning
abilities restated in our vocabulary over our own registers,
as a SEPARATE slice in the extended-set family:

  evaluation/longmem-update-temporal.json        definitions
      + case schema (classes LMU-KU1 / LMU-TR1);
  evaluation/longmem-update-temporal-cases.jsonl fixture cases
      in the case format scripts/wiki_longmem_eval.py already
      validates and scores, plus this slice's own fields
      (slice_class, expected_as_of, superseding_session for
      knowledge-update cases, forbidden values).

The checker validates the definitions register (both classes
present, verdicts, schema fields) and every fixture case
against the class requirements on the register's face:

  knowledge-update — at least two sessions, timestamps
      strictly increasing, the superseding session last,
      expected_as_of equal to its date, expected's tokens
      present in its turns, the forbidden (superseded) value
      present in an earlier session and absent from expected;
  temporal — at least two sessions with distinct timestamps,
      a temporal cue from the register's cue list in the
      question, expected's tokens present in some session,
      the forbidden value present in a session and absent
      from expected.

HARD BOUNDARY: the pinned 12-case abstention battery
(evaluation/abstention-battery.jsonl) and the golden set stay
byte-identical — this checker never opens either for writing
(it does not open them at all), and no dataset is imported:
definitions, schema and fixture cases only, after the CRUD
definitions precedent (evaluation/crud-lifecycle-tasks.json).

Usage: python3 scripts/wiki_longmem_update.py
       [--definitions FILE] [--cases FILE]
Exit: 0 = slice valid; 1 = findings; 2 = usage error.
Stdlib only. No model calls, no network, writes nothing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEFINITIONS = ROOT / "evaluation" / \
    "longmem-update-temporal.json"
DEFAULT_CASES = ROOT / "evaluation" / \
    "longmem-update-temporal-cases.jsonl"

CLASSES = ("knowledge-update", "temporal")
CASE_REQUIRED = ("id", "ability", "slice_class", "sessions",
                 "question", "expected", "expected_as_of",
                 "forbidden")
STOP = set("the a an of to in is are was were be been it its "
           "this that and or for on at by with as from".split())


def _toks(text):
    return {t for t in re.findall(r"[a-z0-9]+",
                                  (text or "").lower())
            if t not in STOP}


def _session_toks(session):
    out = set()
    for turn in session.get("turns") or []:
        out |= _toks(turn)
    return out


def check_definitions(register):
    findings = []
    if register.get("kind") != "longmem-update-temporal-slice":
        findings.append("kind is not "
                        "longmem-update-temporal-slice")
    classes = register.get("classes")
    if not isinstance(classes, list) or not classes:
        findings.append("classes missing or empty")
        return findings
    seen = set()
    for cls in classes:
        for field in ("id", "slice_class", "staging_sequence",
                      "expected_verdict", "expected_behaviour",
                      "forbidden_behaviour",
                      "case_requirements"):
            if not cls.get(field):
                findings.append(
                    f"{cls.get('id')}: missing {field}")
        if cls.get("slice_class") in CLASSES:
            seen.add(cls["slice_class"])
        if cls.get("expected_verdict") != "answer":
            findings.append(
                f"{cls.get('id')}: this slice's classes expect "
                f"'answer', got "
                f"{cls.get('expected_verdict')!r}")
    for name in CLASSES:
        if name not in seen:
            findings.append(f"class {name} has no definition")
    schema = register.get("case_schema") or {}
    for field in CASE_REQUIRED:
        if field not in schema:
            findings.append(f"case_schema lacks field {field}")
    if not register.get("temporal_cues"):
        findings.append("temporal_cues missing or empty")
    return findings


def check_cases(cases, register):
    findings = []
    cues = [c.lower() for c in
            register.get("temporal_cues") or []]
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)):
        findings.append("duplicate case ids")
    for case in cases:
        cid = case.get("id") or "<no id>"
        for field in CASE_REQUIRED:
            if not case.get(field):
                findings.append(f"{cid}: missing {field}")
        ability = case.get("ability")
        if ability not in CLASSES:
            findings.append(f"{cid}: ability {ability!r} is "
                            f"not a slice class")
            continue
        if case.get("slice_class") != ability:
            findings.append(f"{cid}: slice_class "
                            f"{case.get('slice_class')!r} != "
                            f"ability {ability!r}")
        sessions = case.get("sessions") or []
        if len(sessions) < 2:
            findings.append(f"{cid}: needs at least two "
                            f"sessions")
            continue
        stamps = [s.get("timestamp") for s in sessions]
        expected_toks = _toks(case.get("expected"))
        forbidden = case.get("forbidden") or []
        for value in forbidden:
            if _toks(value) & expected_toks and \
                    _toks(value) <= expected_toks:
                findings.append(f"{cid}: forbidden value "
                                f"{value!r} appears in expected")
        if ability == "knowledge-update":
            if stamps != sorted(stamps) or \
                    len(set(stamps)) != len(stamps):
                findings.append(f"{cid}: session timestamps "
                                f"must strictly increase")
            last = sessions[-1]
            if case.get("superseding_session") != last.get("id"):
                findings.append(f"{cid}: superseding_session "
                                f"must name the last session "
                                f"({last.get('id')!r})")
            if case.get("expected_as_of") != last.get(
                    "timestamp"):
                findings.append(f"{cid}: expected_as_of must "
                                f"be the superseding session's "
                                f"date ({last.get('timestamp')})")
            if not expected_toks <= _session_toks(last):
                findings.append(f"{cid}: expected tokens not "
                                f"all present in the "
                                f"superseding session's turns")
            earlier = set()
            for s in sessions[:-1]:
                earlier |= _session_toks(s)
            if not any(_toks(v) and _toks(v) <= earlier
                       for v in forbidden):
                findings.append(f"{cid}: no forbidden value "
                                f"appears in an earlier "
                                f"session (nothing superseded)")
        else:  # temporal
            if len(set(stamps)) != len(stamps):
                findings.append(f"{cid}: temporal sessions "
                                f"need distinct timestamps")
            question = (case.get("question") or "").lower()
            if not any(cue in question for cue in cues):
                findings.append(f"{cid}: question carries no "
                                f"temporal cue from the "
                                f"register's cue list")
            anywhere = set()
            for s in sessions:
                anywhere |= _session_toks(s)
            if not expected_toks <= anywhere:
                findings.append(f"{cid}: expected tokens not "
                                f"present in any session")
            if not any(_toks(v) and _toks(v) <= anywhere
                       for v in forbidden):
                findings.append(f"{cid}: no forbidden value "
                                f"appears in any session "
                                f"(nothing for the cue to "
                                f"exclude)")
            by_stamp = {s.get("timestamp"): s
                        for s in sessions}
            rested = by_stamp.get(case.get("expected_as_of"))
            if rested is None:
                findings.append(f"{cid}: expected_as_of "
                                f"{case.get('expected_as_of')!r} "
                                f"is no session's date")
            elif not expected_toks <= _session_toks(rested):
                findings.append(f"{cid}: expected tokens not "
                                f"present in the session "
                                f"expected_as_of names")
    return findings


def load_cases(path):
    out = []
    for line in Path(path).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def main(argv):
    ap = argparse.ArgumentParser(
        description="Validate the LongMemEval knowledge-"
                    "update + temporal slice.")
    ap.add_argument("--definitions", default=None)
    ap.add_argument("--cases", default=None)
    args = ap.parse_args(argv[1:])
    dpath = Path(args.definitions) if args.definitions \
        else DEFAULT_DEFINITIONS
    cpath = Path(args.cases) if args.cases else DEFAULT_CASES
    for path in (dpath, cpath):
        if not path.is_file():
            print(f"longmem-update: missing: {path}",
                  file=sys.stderr)
            return 2
    register = json.loads(dpath.read_text(encoding="utf-8"))
    cases = load_cases(cpath)
    findings = check_definitions(register) + \
        check_cases(cases, register)
    for f in findings:
        print(f"  [FINDING] {f}")
    by_class = {}
    for c in cases:
        by_class[c.get("slice_class")] = \
            by_class.get(c.get("slice_class"), 0) + 1
    print(f"longmem-update: {len(cases)} fixture case(s) "
          f"({by_class}), {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
