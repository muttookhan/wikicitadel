#!/usr/bin/env python3
"""Curation activities + workarounds register.

Marathon R13 lane BA (ideas board line 194, Round 11 RA find 1,
Tier A): Lee & Stvilia 2017, "Practices of research data
curation in institutional repositories" (PLOS ONE 12(3),
e0173987; Texas A&M / Florida State; CC BY) — activity
STRUCTURE only, re-implemented in our own words. The study
describes repository curation work through the activities
performed, their structures, the roles played, the skills
needed, and the contradictions and problems present, the
solutions sought, and the workarounds applied. Those seven
dimensions are this register's columns: one append-only record
per workaround WE actually use, in
evaluation/curation-workarounds.jsonl, stating which curation
activity it belongs to and how it sits in that structure.
Hand-recorded only; this tool makes no model call, changes no
page, and invents no workaround — the register is seeded
empty-but-valid and a workaround is recorded only when one is
in use.
Commands: record / report / check. Exit 0 ok; 1 invalid
register on check; 2 usage error (including an unknown value).
Stdlib only, no network.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "curation-workarounds.jsonl"
COLUMNS = ["activity", "structure", "role", "skills_needed",
           "contradiction_or_problem", "solution_sought",
           "workaround_applied"]
STATUSES = ["in-use", "proposed", "retired"]


def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
    seen_ids = {}
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        if obj.get("kind") == "header":
            continue
        if obj.get("kind") != "curation":
            errors.append(f"line {i}: kind must be 'curation'")
            continue
        for f in ("record_id", "recorded"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        # The study's seven dimensions are the columns; every
        # column must be present, and the activity and the
        # workaround itself must be stated, never left blank —
        # a workaround with no activity is not classified, and
        # a row with no workaround is not a register entry.
        for c in COLUMNS:
            if c not in obj:
                errors.append(f"line {i}: missing curation column {c!r}")
        for c in ("activity", "workaround_applied"):
            if c in obj and not str(obj.get(c) or "").strip():
                errors.append(f"line {i}: {c} must not be empty")
        if obj.get("status") not in STATUSES:
            errors.append(f"line {i}: status {obj.get('status')!r} not in {STATUSES}")
        rid = obj.get("record_id")
        if rid:
            if rid in seen_ids:
                errors.append(f"line {i}: duplicate record_id {rid!r} "
                              f"(first on line {seen_ids[rid]})")
            else:
                seen_ids[rid] = i
        records.append(obj)
    return records, errors


def build_report(path=None):
    records, errors = load_register(path)
    by_status = {s: 0 for s in STATUSES}
    by_activity = {}
    for r in records:
        if r.get("status") in by_status:
            by_status[r["status"]] += 1
        a = r.get("activity")
        if a:
            by_activity[a] = by_activity.get(a, 0) + 1
    return {"records": len(records), "columns": COLUMNS,
            "by_status": by_status, "by_activity": by_activity,
            "workarounds": [{"record_id": r.get("record_id"),
                              "activity": r.get("activity"),
                              "workaround_applied": r.get("workaround_applied"),
                              "status": r.get("status")} for r in records],
            "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Curation activities + workarounds register (Lee & Stvilia slice).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--record-id", required=True)
    for c in COLUMNS:
        pc.add_argument("--" + c.replace("_", "-"), required=True)
    pc.add_argument("--status", required=True, choices=STATUSES)
    pc.add_argument("--note", default="")
    pc.add_argument("--recorded", default=None); pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"curation: {e}", file=sys.stderr)
        print(f"curation: register {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        rec = {"kind": "curation", "record_id": args.record_id,
               "recorded": args.recorded or date.today().isoformat(),
               "status": args.status, "note": args.note}
        for c in COLUMNS:
            rec[c] = getattr(args, c)
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"curation: recorded workaround {args.record_id} "
              f"for activity {args.activity}")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"curation: {rep['records']} workaround record(s)")
        for s in STATUSES:
            print(f"  status {s}: {rep['by_status'][s]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
