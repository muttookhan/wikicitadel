#!/usr/bin/env python3
"""Capability register — the research programme's gap analysis as data.

The comprehensive research report (Completed Edition, 2026-10-22)
groups the world's-best comparison into fifteen capabilities.
This register keeps one row per capability as standing data in
evaluation/capability-register.jsonl, so the gap analysis is
queryable and maintainable instead of living only in report
prose. Each row carries:

  capability    the capability's name (the report's own heading);
  best_source   {name, licence} — the best source the study
                opened for it, with the licence AS RECORDED in
                the study row (taken from the source's licence
                at study time, never borrowed from another row);
  verdict       the standing adoption ruling for that source's
                mechanism in this tree, one of:
                  idea          — the idea was taken and
                                  re-implemented in our own code
                                  (pattern credited on the artefact);
                  code          — code adapted, with attribution
                                  carried on the artefact;
                  owner-gated   — adoption waits on the owner;
                  rejected      — not adopted; `reason` is owed
                                  and read with the verdict;
  status        what this tree actually has today, stated from
                its artefacts (paths in `artefacts`);
  source_ref    where the row's evidence lives (the ingested
                gap analysis in raw/, section per capability).

Append-only, like the other registers: a row is never edited in
place; a changed ruling is a new row with the same id superseding
the old (check reports the CURRENT row per id — the latest one —
and counts superseded rows separately). Commands: check / list /
add. Exit 0 ok; 1 invalid register on check; 2 usage error.
Stdlib only, no network.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "capability-register.jsonl"
VERDICTS = ["idea", "code", "owner-gated", "rejected"]


def load_register(path=None):
    p = Path(path) if path else REGISTER
    rows, errors = [], []
    if not p.is_file():
        return rows, [f"register missing: {p}"]
    header_seen = False
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        if obj.get("kind") == "header":
            if i != 1:
                errors.append(f"line {i}: header must be the first line")
            if obj.get("register") != "capabilities":
                errors.append(f"line {i}: header register must be 'capabilities'")
            header_seen = True
            continue
        if obj.get("kind") != "capability":
            errors.append(f"line {i}: kind must be 'capability'")
            continue
        if not obj.get("id"):
            errors.append(f"line {i}: missing field 'id'")
        if not obj.get("capability"):
            errors.append(f"line {i}: missing field 'capability'")
        src = obj.get("best_source") or {}
        if not src.get("name"):
            errors.append(f"line {i}: best_source.name missing")
        if not src.get("licence"):
            errors.append(f"line {i}: best_source.licence missing "
                          "(a licence is recorded from the source itself, "
                          "or the row does not stand)")
        if obj.get("verdict") not in VERDICTS:
            errors.append(f"line {i}: verdict {obj.get('verdict')!r} not in {VERDICTS}")
        if obj.get("verdict") == "rejected" and not obj.get("reason"):
            errors.append(f"line {i}: a rejected verdict owes its reason")
        if not obj.get("status"):
            errors.append(f"line {i}: missing field 'status'")
        if not isinstance(obj.get("artefacts"), list):
            errors.append(f"line {i}: 'artefacts' must be a list (empty when nothing stands)")
        if not obj.get("recorded"):
            errors.append(f"line {i}: missing field 'recorded'")
        rows.append(obj)
    if not header_seen:
        errors.append("no header line (kind: 'header', register: 'capabilities')")
    seen, current = {}, {}
    for obj in rows:
        current[obj.get("id")] = obj  # latest row per id stands
    return rows, errors


def current_rows(rows):
    cur = {}
    for obj in rows:
        cur[obj.get("id")] = obj
    return [cur[k] for k in sorted(cur)]


def build_report(path=None):
    rows, errors = load_register(path)
    cur = current_rows(rows)
    counts = {v: 0 for v in VERDICTS}
    for obj in cur:
        if obj.get("verdict") in counts:
            counts[obj["verdict"]] += 1
    return {"rows": len(rows), "current": len(cur),
            "superseded_rows": len(rows) - len(cur),
            "counts": counts, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Capability register (the gap analysis as data).")
    sub = ap.add_subparsers(dest="command")
    pc = sub.add_parser("check"); pc.add_argument("--register", default=None)
    pl = sub.add_parser("list"); pl.add_argument("--register", default=None)
    pl.add_argument("--json", action="store_true")
    pa = sub.add_parser("add")
    pa.add_argument("--id", required=True)
    pa.add_argument("--capability", required=True)
    pa.add_argument("--source-name", required=True)
    pa.add_argument("--licence", required=True)
    pa.add_argument("--verdict", required=True, choices=VERDICTS)
    pa.add_argument("--status", required=True)
    pa.add_argument("--reason", default="")
    pa.add_argument("--artefact", action="append", default=[])
    pa.add_argument("--source-ref", default="")
    pa.add_argument("--recorded", default=None)
    pa.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "check"
    if cmd == "check":
        rep = build_report(args.register)
        for e in rep["errors"]:
            print(f"capability-register: {e}", file=sys.stderr)
        print(f"capability-register: register "
              f"{'INVALID' if rep['errors'] else 'valid'} "
              f"({rep['current']} current row(s), "
              f"{rep['superseded_rows']} superseded)")
        for v in VERDICTS:
            print(f"  {v}: {rep['counts'][v]}")
        return 1 if rep["errors"] else 0
    if cmd == "list":
        rows, errors = load_register(args.register)
        if errors:
            for e in errors:
                print(f"capability-register: {e}", file=sys.stderr)
            return 1
        cur = current_rows(rows)
        if args.json:
            print(json.dumps(cur, indent=2, ensure_ascii=False))
        else:
            for obj in cur:
                print(f"{obj['id']}  [{obj['verdict']}]  {obj['capability']}  "
                      f"— best: {obj['best_source']['name']} "
                      f"({obj['best_source']['licence']})")
        return 0
    if cmd == "add":
        if args.verdict == "rejected" and not args.reason:
            print("capability-register: a rejected verdict owes its reason",
                  file=sys.stderr)
            return 2
        rec = {"kind": "capability", "id": args.id,
               "capability": args.capability,
               "best_source": {"name": args.source_name,
                               "licence": args.licence},
               "verdict": args.verdict, "reason": args.reason,
               "status": args.status, "artefacts": args.artefact,
               "source_ref": args.source_ref,
               "recorded": args.recorded or date.today().isoformat()}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"capability-register: recorded {args.id} [{args.verdict}] "
              f"{args.capability}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
