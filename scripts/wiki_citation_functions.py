#!/usr/bin/env python3
"""Citation-function register (Jurgens et al. six frames).

Marathon R10 lane BA (ideas board R8 research, Tier A): Jurgens
et al., TACL 2018 (CC BY 4.0) — pattern only. A SEPARATE side
register, evaluation/citation-functions.jsonl, in which an
operator may record, per citation, one of six frame labels:
Background / Motivation / Uses / Extension /
Comparison-or-Contrast / Future. Hand-applied only; this tool
makes no model call and changes no page and no lockfile entry.
Commands: record / report / check. Exit 0 ok; 1 invalid
register on check; 2 usage error (including an unknown frame).
Stdlib only, no network.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "citation-functions.jsonl"
LOCKFILE = ROOT / "evaluation" / "citation-lockfile.json"
FRAMES = ["Background", "Motivation", "Uses", "Extension",
          "Comparison-or-Contrast", "Future"]


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
        if obj.get("kind") != "citation-function":
            errors.append(f"line {i}: kind must be 'citation-function'")
            continue
        if obj.get("frame") not in FRAMES:
            errors.append(f"line {i}: frame {obj.get('frame')!r} not in {FRAMES}")
        for f in ("citation_id", "page", "recorded"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        records.append(obj)
    return records, errors


def build_report(path=None):
    records, errors = load_register(path)
    counts = {f: 0 for f in FRAMES}
    for r in records:
        if r.get("frame") in counts:
            counts[r["frame"]] += 1
    total_lock = None
    if LOCKFILE.is_file():
        total_lock = len(json.loads(LOCKFILE.read_text(encoding="utf-8")).get("citations", []))
    labelled_ids = {r.get("citation_id") for r in records}
    return {"frames": FRAMES, "counts": counts, "labelled_records": len(records),
            "distinct_citations_labelled": len(labelled_ids),
            "lockfile_citations": total_lock,
            "unlabelled_lockfile_citations": (total_lock - len(labelled_ids))
            if total_lock is not None else None, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Citation-function register (Jurgens frames).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--citation-id", required=True)
    pc.add_argument("--page", required=True); pc.add_argument("--source", default="")
    pc.add_argument("--frame", required=True, choices=FRAMES)
    pc.add_argument("--note", default=""); pc.add_argument("--recorded", default=None)
    pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"citation-functions: {e}", file=sys.stderr)
        print(f"citation-functions: register {'INVALID' if errors else 'valid'} ({len(_r)} record(s))")
        return 1 if errors else 0
    if cmd == "record":
        rec = {"kind": "citation-function", "citation_id": args.citation_id,
               "page": args.page, "source": args.source, "frame": args.frame,
               "recorded": args.recorded or date.today().isoformat(), "note": args.note}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"citation-functions: recorded {args.frame} for {args.citation_id}")
        return 0
    rep = build_report(args.register)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"citation-functions: {rep['labelled_records']} record(s), "
              f"{rep['distinct_citations_labelled']} distinct citation(s) labelled; "
              f"lockfile citations: {rep['lockfile_citations']}, "
              f"unlabelled: {rep['unlabelled_lockfile_citations']}")
        for f in FRAMES:
            print(f"  {f}: {rep['counts'][f]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
