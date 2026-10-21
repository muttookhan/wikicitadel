#!/usr/bin/env python3
"""Occasional-actions register slice (DCC Curation Lifecycle).

Marathon R11 lane BA (ideas board lines 153-156, R9 research,
Tier A): Higgins 2008, DCC Curation Lifecycle Model, IJDC 3(1)
— pattern only, re-implemented in our own words. In the DCC
model most curation is sequential, but some actions are
OCCASIONAL — reappraisal, migration and their kin happen when
triggered, not on the pipeline. A SEPARATE append-only side
register, evaluation/occasional-actions.jsonl, logs those
events as first-class records (date, page, action, trigger,
outcome). Hand-recorded only; this tool performs no action
itself, makes no model call and changes no page.
Commands: record / report / check. Exit 0 ok; 1 invalid
register on check; 2 usage error (including unknown values).
Stdlib only, no network.
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "occasional-actions.jsonl"
ACTIONS = ["reappraisal", "migration", "format-refresh",
           "integrity-review", "disposal-review", "access-review"]
OUTCOMES = ["completed", "no-change", "deferred", "rejected", "superseded"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
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
        if obj.get("kind") != "occasional-action":
            errors.append(f"line {i}: kind must be 'occasional-action'")
            continue
        if obj.get("action") not in ACTIONS:
            errors.append(f"line {i}: action {obj.get('action')!r} not in {ACTIONS}")
        if obj.get("outcome") not in OUTCOMES:
            errors.append(f"line {i}: outcome {obj.get('outcome')!r} not in {OUTCOMES}")
        for f in ("date", "page", "trigger"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        if obj.get("date") and not DATE_RE.match(str(obj["date"])):
            errors.append(f"line {i}: date {obj.get('date')!r} is not YYYY-MM-DD")
        records.append(obj)
    return records, errors


def build_report(path=None):
    records, errors = load_register(path)
    by_action = {a: 0 for a in ACTIONS}
    by_outcome = {o: 0 for o in OUTCOMES}
    pages = Counter()
    dates = []
    for r in records:
        if r.get("action") in by_action:
            by_action[r["action"]] += 1
        if r.get("outcome") in by_outcome:
            by_outcome[r["outcome"]] += 1
        if r.get("page"):
            pages[r["page"]] += 1
        if r.get("date"):
            dates.append(str(r["date"]))
    return {"events": len(records), "by_action": by_action,
            "by_outcome": by_outcome,
            "pages_with_most_actions": pages.most_common(5),
            "date_range": [min(dates), max(dates)] if dates else None,
            "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Occasional-actions register (DCC lifecycle slice).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--page", required=True)
    pc.add_argument("--action", required=True, choices=ACTIONS)
    pc.add_argument("--trigger", required=True)
    pc.add_argument("--outcome", required=True, choices=OUTCOMES)
    pc.add_argument("--actor", default=""); pc.add_argument("--note", default="")
    pc.add_argument("--date", default=None); pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"occasional-actions: {e}", file=sys.stderr)
        print(f"occasional-actions: register {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        d = args.date or date.today().isoformat()
        if not DATE_RE.match(d):
            print("occasional-actions: --date must be YYYY-MM-DD", file=sys.stderr)
            return 2
        rec = {"kind": "occasional-action", "date": d, "page": args.page,
               "action": args.action, "trigger": args.trigger,
               "outcome": args.outcome, "actor": args.actor, "note": args.note}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"occasional-actions: recorded {args.action} on {args.page} ({args.outcome})")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"occasional-actions: {rep['events']} event(s); date range: {rep['date_range']}")
        for a in ACTIONS:
            print(f"  {a}: {rep['by_action'][a]}")
        for o in OUTCOMES:
            print(f"  outcome {o}: {rep['by_outcome'][o]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
