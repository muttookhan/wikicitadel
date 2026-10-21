#!/usr/bin/env python3
"""RiC-style typed relation register slice.

Marathon R11 lane BA (ideas board lines 153-156, R9 research,
Tier A): Wasananikornkulchai 2024, RiC-CM review — relation
TYPES only, re-implemented in our own words; the full RiC
ontology is NOT imported. A SEPARATE append-only side register,
evaluation/relation-register.jsonl, holding typed relations
between existing pages/records with a small FIXED predicate
set (the part-of family, the supersession pair, creation
context, and derivation). Hand-recorded only; this tool makes
no model call and changes no page. Whether the named pages
exist is REPORTED (dangling list), never enforced — a relation
may be recorded ahead of a page it anticipates.
Commands: record / report / check. Exit 0 ok; 1 invalid
register on check; 2 usage error (including unknown predicate).
Stdlib only, no network.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "relation-register.jsonl"
PREDICATES = ["part-of", "has-part", "superseded-by", "supersedes",
              "created-in-context-of", "derived-from"]
INVERSES = {"part-of": "has-part", "has-part": "part-of",
            "superseded-by": "supersedes", "supersedes": "superseded-by"}


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
        if obj.get("kind") != "relation":
            errors.append(f"line {i}: kind must be 'relation'")
            continue
        if obj.get("predicate") not in PREDICATES:
            errors.append(f"line {i}: predicate {obj.get('predicate')!r} not in {PREDICATES}")
        for f in ("subject", "object", "recorded"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        if obj.get("subject") and obj.get("subject") == obj.get("object"):
            errors.append(f"line {i}: subject and object must differ (no self-relations)")
        records.append(obj)
    return records, errors


def build_report(path=None, root=None):
    records, errors = load_register(path)
    counts = {p: 0 for p in PREDICATES}
    dangling = []
    base = Path(root) if root else ROOT
    for r in records:
        if r.get("predicate") in counts:
            counts[r["predicate"]] += 1
        for end in ("subject", "object"):
            v = r.get(end)
            if v and not (base / v).exists():
                dangling.append({"end": end, "path": v,
                                 "predicate": r.get("predicate")})
    pairs = {(r.get("subject"), r.get("predicate"), r.get("object")) for r in records}
    missing_inverse = []
    for (s, pred, o) in sorted(pairs):
        inv = INVERSES.get(pred)
        if inv and (o, inv, s) not in pairs:
            missing_inverse.append({"subject": s, "predicate": pred, "object": o,
                                    "inverse_not_recorded": inv})
    return {"relations": len(records), "counts": counts,
            "distinct_subjects": len({r.get("subject") for r in records}),
            "dangling_endpoints": dangling,
            "missing_inverse": missing_inverse, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="RiC-style typed relation register slice.")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--subject", required=True)
    pc.add_argument("--predicate", required=True, choices=PREDICATES)
    pc.add_argument("--object", required=True, dest="object")
    pc.add_argument("--note", default=""); pc.add_argument("--recorded", default=None)
    pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"relation-register: {e}", file=sys.stderr)
        print(f"relation-register: register {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        if args.subject == args.object:
            print("relation-register: subject and object must differ", file=sys.stderr)
            return 2
        rec = {"kind": "relation", "subject": args.subject,
               "predicate": args.predicate, "object": args.object,
               "recorded": args.recorded or date.today().isoformat(), "note": args.note}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"relation-register: recorded {args.subject} {args.predicate} {args.object}")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"relation-register: {rep['relations']} relation(s), "
              f"{rep['distinct_subjects']} distinct subject(s); "
              f"dangling endpoints: {len(rep['dangling_endpoints'])} (reported, not enforced)")
        for p in PREDICATES:
            print(f"  {p}: {rep['counts'][p]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
