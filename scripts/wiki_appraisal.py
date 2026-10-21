#!/usr/bin/env python3
"""Appraisal register slice (Eastwood / InterPARES).

Marathon R11 lane BA (ideas board lines 153-156, R9 research,
Tier A): Eastwood 2004 / InterPARES Appraisal Task Force model —
pattern only, re-implemented in our own words. A SEPARATE side
register, evaluation/appraisal-register.jsonl, holding ONE
append-only record per ingest batch. Each record carries the
four appraisal activities as separate fields — contexts
compiled / value assessed / authenticity assessed / feasibility
assessed — with authenticity kept as its OWN field, never folded
into value (per the paper), plus the appraisal decision and its
disposition. Hand-recorded only; this tool makes no model call,
changes no page, and appraises nothing itself.

Keeping motivation (Marathon R13 lane BA, ideas board line
195, Round 11 RA find 2; Maemura & Wagner 2025, UIUC —
pattern only): a record ALSO carries `keeping_motivation`,
the real reason the material is kept — use / nostalgia /
vigilance / fear-of-loss / legacy — alongside the formal
decision, because a register that records only institutional
reasons misdescribes why a one-person corpus is actually
kept. `record` requires it; lines written before the field
existed load without it (they are legacy lines, counted as
`unrecorded` in the report, never retro-edited).
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
REGISTER = ROOT / "evaluation" / "appraisal-register.jsonl"
ACTIVITIES = ["contexts_compiled", "value_assessed",
              "authenticity_assessed", "feasibility_assessed"]
ACTIVITY_STATES = ["done", "pending", "not-applicable"]
DECISIONS = ["retain", "retain-sample", "dispose", "transfer", "defer", "undecided"]
DISPOSITIONS = ["kept-in-wiki", "kept-as-raw-only", "sample-kept",
                "removed-after-review", "transferred-out", "pending-decision"]
MOTIVATIONS = ["use", "nostalgia", "vigilance", "fear-of-loss", "legacy"]


def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
    seen_batches = {}
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
        if obj.get("kind") != "appraisal":
            errors.append(f"line {i}: kind must be 'appraisal'")
            continue
        for f in ("batch_id", "recorded"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        # The four activities are separate fields; authenticity in
        # particular must be present on its own, never inferred
        # from the value assessment.
        for a in ACTIVITIES:
            if a not in obj:
                errors.append(f"line {i}: missing appraisal activity {a!r}")
            elif obj.get(a) not in ACTIVITY_STATES:
                errors.append(f"line {i}: {a} {obj.get(a)!r} not in {ACTIVITY_STATES}")
        if obj.get("decision") not in DECISIONS:
            errors.append(f"line {i}: decision {obj.get('decision')!r} not in {DECISIONS}")
        if obj.get("disposition") not in DISPOSITIONS:
            errors.append(f"line {i}: disposition {obj.get('disposition')!r} not in {DISPOSITIONS}")
        # Keeping motivation: required by `record` since the
        # R13 extension; a line that carries it must carry a
        # value from the closed list. A line without it is a
        # pre-extension legacy line — valid, counted as
        # unrecorded, never retro-edited.
        if "keeping_motivation" in obj and obj.get("keeping_motivation") not in MOTIVATIONS:
            errors.append(f"line {i}: keeping_motivation "
                          f"{obj.get('keeping_motivation')!r} not in {MOTIVATIONS}")
        bid = obj.get("batch_id")
        if bid:
            if bid in seen_batches:
                errors.append(f"line {i}: duplicate batch_id {bid!r} (first on line {seen_batches[bid]}); "
                              "one appraisal record per ingest batch — a later re-appraisal "
                              "belongs in the occasional-actions register")
            else:
                seen_batches[bid] = i
        records.append(obj)
    return records, errors


def build_report(path=None):
    records, errors = load_register(path)
    by_decision = {d: 0 for d in DECISIONS}
    by_disposition = {d: 0 for d in DISPOSITIONS}
    by_keeping_motivation = {m: 0 for m in MOTIVATIONS}
    by_keeping_motivation["unrecorded"] = 0
    activity_states = {a: {s: 0 for s in ACTIVITY_STATES} for a in ACTIVITIES}
    incomplete = []
    for r in records:
        if r.get("decision") in by_decision:
            by_decision[r["decision"]] += 1
        if r.get("disposition") in by_disposition:
            by_disposition[r["disposition"]] += 1
        if r.get("keeping_motivation") in MOTIVATIONS:
            by_keeping_motivation[r["keeping_motivation"]] += 1
        else:
            by_keeping_motivation["unrecorded"] += 1
        pending = []
        for a in ACTIVITIES:
            if r.get(a) in activity_states[a]:
                activity_states[a][r[a]] += 1
            if r.get(a) == "pending":
                pending.append(a)
        if pending:
            incomplete.append({"batch_id": r.get("batch_id"), "pending": pending})
    return {"batches": len(records), "by_decision": by_decision,
            "by_disposition": by_disposition,
            "by_keeping_motivation": by_keeping_motivation,
            "activity_states": activity_states,
            "incomplete_batches": incomplete, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Appraisal register (Eastwood / InterPARES slice).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--batch-id", required=True)
    pc.add_argument("--batch-label", default="")
    for a in ACTIVITIES:
        pc.add_argument("--" + a.replace("_", "-"), required=True, choices=ACTIVITY_STATES)
    pc.add_argument("--decision", required=True, choices=DECISIONS)
    pc.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    pc.add_argument("--keeping-motivation", required=True, choices=MOTIVATIONS)
    pc.add_argument("--appraiser", default=""); pc.add_argument("--note", default="")
    pc.add_argument("--recorded", default=None); pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"appraisal: {e}", file=sys.stderr)
        print(f"appraisal: register {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        rec = {"kind": "appraisal", "batch_id": args.batch_id,
               "batch_label": args.batch_label,
               "contexts_compiled": args.contexts_compiled,
               "value_assessed": args.value_assessed,
               "authenticity_assessed": args.authenticity_assessed,
               "feasibility_assessed": args.feasibility_assessed,
               "decision": args.decision, "disposition": args.disposition,
               "keeping_motivation": args.keeping_motivation,
               "appraiser": args.appraiser,
               "recorded": args.recorded or date.today().isoformat(), "note": args.note}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"appraisal: recorded {args.decision} for batch {args.batch_id}")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"appraisal: {rep['batches']} batch record(s); "
              f"incomplete (any activity pending): {len(rep['incomplete_batches'])}")
        for d in DECISIONS:
            print(f"  decision {d}: {rep['by_decision'][d]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
