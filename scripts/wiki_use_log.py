#!/usr/bin/env python3
"""Use / knowledge-enhancement log slice (DCC&U).

Marathon R11 lane BA (ideas board lines 153-156, R9 research,
Tier A): Constantopoulos et al. 2009, DCC&U, IJDC 4(1) —
pattern only, re-implemented in our own words. Knowledge
enhancement happens when a synthesis or an answer is FILED
BACK into the wiki and is then used: each such use is an
append-only event in the SEPARATE side log
evaluation/use-log.jsonl, recording the filed-back page, the
source pages it drew on, and the pages it supports or
contradicts. Hand-recorded only; this tool makes no model
call, files nothing back itself and changes no page. Pages
named but not present in the tree are REPORTED as dangling
by the checker/report, never treated as an error of record.
Commands: record / report / check. Exit 0 ok; 1 invalid log
on check; 2 usage error (including unknown values).
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
REGISTER = ROOT / "evaluation" / "use-log.jsonl"
USE_KINDS = ["synthesis", "answer", "annotation"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIST_FIELDS = ("sources", "supports", "contradicts")


def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"log missing: {p}"]
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
        if obj.get("kind") != "use-event":
            errors.append(f"line {i}: kind must be 'use-event'")
            continue
        if obj.get("use_kind") not in USE_KINDS:
            errors.append(f"line {i}: use_kind {obj.get('use_kind')!r} not in {USE_KINDS}")
        for f in ("page", "date"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        if obj.get("date") and not DATE_RE.match(str(obj["date"])):
            errors.append(f"line {i}: date {obj.get('date')!r} is not YYYY-MM-DD")
        for f in LIST_FIELDS:
            v = obj.get(f)
            if v is None:
                errors.append(f"line {i}: missing list field {f!r}")
            elif not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                errors.append(f"line {i}: {f} must be a list of non-empty page paths")
        if isinstance(obj.get("sources"), list) and not obj["sources"]:
            errors.append(f"line {i}: sources must name at least one source page "
                          "(a use event with no sources is not a knowledge-enhancement record)")
        sup, con = obj.get("supports") or [], obj.get("contradicts") or []
        both = sorted(set(sup) & set(con))
        if both:
            errors.append(f"line {i}: page(s) in BOTH supports and contradicts: {both}")
        if obj.get("page") and isinstance(obj.get("sources"), list) \
                and obj["page"] in obj["sources"]:
            errors.append(f"line {i}: page must not list itself among its sources")
        records.append(obj)
    return records, errors


def build_report(path=None, root=None):
    records, errors = load_register(path)
    by_kind = {k: 0 for k in USE_KINDS}
    source_use = Counter()
    supported, contradicted = Counter(), Counter()
    dangling = []
    base = Path(root) if root else ROOT
    named = set()
    for r in records:
        if r.get("use_kind") in by_kind:
            by_kind[r["use_kind"]] += 1
        for s in r.get("sources") or []:
            source_use[s] += 1
        for s in r.get("supports") or []:
            supported[s] += 1
        for s in r.get("contradicts") or []:
            contradicted[s] += 1
        named.add(r.get("page"))
        for f in LIST_FIELDS:
            named.update(r.get(f) or [])
    for v in sorted(x for x in named if x):
        if not (base / v).exists():
            dangling.append(v)
    return {"events": len(records), "by_kind": by_kind,
            "distinct_source_pages_used": len(source_use),
            "most_used_sources": source_use.most_common(5),
            "pages_supported": dict(supported), "pages_contradicted": dict(contradicted),
            "dangling_pages": dangling, "errors": errors}


def _split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Use / knowledge-enhancement log (DCC&U slice).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--page", required=True)
    pc.add_argument("--use-kind", required=True, choices=USE_KINDS)
    pc.add_argument("--sources", required=True,
                    help="comma-separated source page paths (at least one)")
    pc.add_argument("--supports", default="", help="comma-separated page paths")
    pc.add_argument("--contradicts", default="", help="comma-separated page paths")
    pc.add_argument("--note", default=""); pc.add_argument("--date", default=None)
    pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"use-log: {e}", file=sys.stderr)
        print(f"use-log: log {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        sources, supports, contradicts = _split(args.sources), _split(args.supports), _split(args.contradicts)
        if not sources:
            print("use-log: --sources must name at least one source page", file=sys.stderr)
            return 2
        if set(supports) & set(contradicts):
            print("use-log: a page cannot be in both --supports and --contradicts", file=sys.stderr)
            return 2
        if args.page in sources:
            print("use-log: --page must not list itself among --sources", file=sys.stderr)
            return 2
        d = args.date or date.today().isoformat()
        if not DATE_RE.match(d):
            print("use-log: --date must be YYYY-MM-DD", file=sys.stderr)
            return 2
        rec = {"kind": "use-event", "date": d, "page": args.page,
               "use_kind": args.use_kind, "sources": sources,
               "supports": supports, "contradicts": contradicts, "note": args.note}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"use-log: recorded {args.use_kind} use of {args.page} "
              f"({len(sources)} source(s), supports {len(supports)}, contradicts {len(contradicts)})")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"use-log: {rep['events']} event(s); distinct source pages used: "
              f"{rep['distinct_source_pages_used']}; dangling pages: {len(rep['dangling_pages'])} "
              "(reported, not an error of record)")
        for k in USE_KINDS:
            print(f"  {k}: {rep['by_kind'][k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
