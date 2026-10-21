#!/usr/bin/env python3
"""Checker for the CRUD lifecycle task definitions register.

Marathon R8 lane BB (ideas board R6 deep-dive, Tier A): CRUD-RAG
taxonomy restated in our vocabulary, DEFINITIONS ONLY, as data
beside the extended set in evaluation/crud-lifecycle-tasks.json:

  Create - answer after ingest (the page did not exist, a source
           is ingested, the answer now stands on it);
  Read   - answer from a standing page, no lifecycle event;
  Update - answer after superseding ingest (the new answer
           stands, the superseded answer is forbidden);
  Delete - abstain after tombstone (the page is tombstoned, so
           the only correct behaviour is abstention).

No dataset is imported, no task is executed, and neither the
pinned abstention battery nor the golden set is touched - this
checker only validates the definitions register's shape:
all four classes present, ids unique, every definition carrying
its lifecycle sequence, expected verdict and forbidden behaviour.

Usage: python3 scripts/wiki_crud_tasks.py [--register FILE]
Exit: 0 = register valid; 1 = findings; 2 = usage error.
Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = ROOT / "evaluation" / "crud-lifecycle-tasks.json"
CLASSES = ("Create", "Read", "Update", "Delete")
REQUIRED = ("id", "crud_class", "lifecycle_sequence",
            "expected_verdict", "expected_behaviour",
            "forbidden_behaviour")
EXPECTED_VERDICT = {"Create": "answer", "Read": "answer",
                    "Update": "answer", "Delete": "abstain"}


def check_register(register):
    findings = []
    if register.get("kind") != "crud-lifecycle-task-register":
        findings.append("kind is not crud-lifecycle-task-register")
    tasks = register.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        findings.append("tasks missing or empty")
        return findings
    ids = [t.get("id") for t in tasks]
    if len(ids) != len(set(ids)):
        findings.append("duplicate task ids")
    seen = set()
    for t in tasks:
        for field in REQUIRED:
            if not t.get(field):
                findings.append(f"{t.get('id')}: missing {field}")
        cls = t.get("crud_class")
        if cls not in CLASSES:
            findings.append(f"{t.get('id')}: unknown class {cls!r}")
            continue
        seen.add(cls)
        if t.get("expected_verdict") != EXPECTED_VERDICT[cls]:
            findings.append(
                f"{t['id']}: {cls} must expect "
                f"{EXPECTED_VERDICT[cls]!r}, got "
                f"{t.get('expected_verdict')!r}")
        if not isinstance(t.get("lifecycle_sequence"), list) \
                or not t["lifecycle_sequence"]:
            findings.append(
                f"{t.get('id')}: lifecycle_sequence must be a "
                f"non-empty list")
    for cls in CLASSES:
        if cls not in seen:
            findings.append(f"class {cls} has no definition")
    return findings


def main(argv):
    ap = argparse.ArgumentParser(
        description="Validate CRUD lifecycle task definitions.")
    ap.add_argument("--register", default=None)
    args = ap.parse_args(argv[1:])
    path = Path(args.register) if args.register \
        else DEFAULT_REGISTER
    if not path.is_file():
        print(f"crud-tasks: register missing: {path}",
              file=sys.stderr)
        return 2
    register = json.loads(path.read_text(encoding="utf-8"))
    findings = check_register(register)
    for f in findings:
        print(f"  [FINDING] {f}")
    print(f"crud-tasks: {len(register.get('tasks') or [])} "
          f"definitions, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
