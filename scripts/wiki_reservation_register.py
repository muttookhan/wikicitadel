#!/usr/bin/env python3
"""Advisory reservation register (MCP Agent Mail pattern,
RE-IMPLEMENTED — ideas only, no copied code).

Marathon R12 lane BB (ideas board line 188, deep-dive batch 7,
Tier A): MCP Agent Mail's file-reservation idea, re-implemented
from the idea alone — its licence is not stated in the research
record, so NO code, text or schema was copied from it; the
shape below is this wiki's own, in the idiom of its other
registers. Parallel build lanes signal INTENT by reserving
globs ("I am about to work on scripts/wiki_*.py") for a TTL.

ADVISORY ONLY, stated on its face: a reservation BLOCKS
NOTHING. It does not lock a file, gate a write, fail a check or
stop another lane; `check` validates the register's shape only
and overlapping or conflicting reservations are REPORTED, never
enforced. The register exists so a coordinator (or a lane,
before starting) can SEE who intends to touch what, and so
stale intent expires instead of lingering: every reservation
carries expires (ISO datetime, UTC); after it, the reservation
is expired and `report`/`expire` say so plainly.

Glob overlap is a documented heuristic, not a proof: two
patterns overlap when, compared path-segment by segment up to
the first wildcard segment, their literal segments agree, or
one pattern fnmatch-matches the other's fully literal text.
It is a signalling aid for humans, never a decision.

Register: evaluation/reservation-register.jsonl, append-only,
seeded with a header line only — no reservation is invented at
seed time. Commands: record / report / check / expire.
Exit 0 ok (expire/report always 0 when the register loads);
1 invalid register on check; 2 usage error. Stdlib only.
"""
import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "reservation-register.jsonl"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse_ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


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
        if obj.get("kind") != "reservation":
            errors.append(f"line {i}: kind must be 'reservation'")
            continue
        for f in ("agent", "glob", "reserved_at", "expires"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        for f in ("reserved_at", "expires"):
            if obj.get(f) and _parse_ts(obj[f]) is None:
                errors.append(f"line {i}: {f} {obj[f]!r} is not an "
                              "ISO datetime")
        ra, ex = _parse_ts(obj.get("reserved_at") or ""), \
            _parse_ts(obj.get("expires") or "")
        if ra and ex and ex <= ra:
            errors.append(f"line {i}: expires must be after reserved_at "
                          "(a reservation with no live window is not a "
                          "reservation)")
        records.append(obj)
    return records, errors


def is_active(rec, at=None):
    at = at or now_utc()
    ex = _parse_ts(rec.get("expires") or "")
    return ex is not None and at < ex


def expire(records, at=None):
    """Split records into (active, expired) at a moment. Pure:
    nothing is deleted or rewritten — expiry is reported."""
    at = at or now_utc()
    active = [r for r in records if is_active(r, at)]
    expired = [r for r in records if not is_active(r, at)]
    return active, expired


def globs_overlap(a, b):
    """Documented heuristic (see module docstring)."""
    if a == b:
        return True
    if not any(ch in a for ch in "*?[") and fnmatch.fnmatch(a, b):
        return True
    if not any(ch in b for ch in "*?[") and fnmatch.fnmatch(b, a):
        return True
    sa, sb = a.split("/"), b.split("/")
    for x, y in zip(sa, sb):
        if any(ch in x for ch in "*?[") or any(ch in y for ch in "*?["):
            return fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x)
        if x != y:
            return False
    return True  # one is a literal prefix of the other


def find_overlaps(records, at=None):
    """Overlapping ACTIVE reservation pairs (advisory report):
    [{agents: [a, b], globs: [g, g]}]. Same-agent pairs are not
    overlaps — a lane may widen its own intent."""
    active, _e = expire(records, at)
    pairs = []
    for i, r in enumerate(active):
        for s in active[i + 1:]:
            if r.get("agent") != s.get("agent") and \
                    globs_overlap(r.get("glob", ""), s.get("glob", "")):
                pairs.append({"agents": [r["agent"], s["agent"]],
                              "globs": [r["glob"], s["glob"]]})
    return pairs


def build_report(path=None, at=None):
    records, errors = load_register(path)
    active, expired = expire(records, at)
    return {"reservations": len(records), "active": len(active),
            "expired": len(expired),
            "active_agents": sorted({r["agent"] for r in active}),
            "overlaps": find_overlaps(records, at),
            "advisory_only": True, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Advisory reservation register (blocks nothing).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("record"); pr.add_argument("--agent", required=True)
    pr.add_argument("--glob", required=True, dest="glob")
    pr.add_argument("--ttl-minutes", type=int, default=120)
    pr.add_argument("--note", default="")
    pr.add_argument("--register", default=None)
    for name in ("report", "check", "expire"):
        sp = sub.add_parser(name); sp.add_argument("--register", default=None)
        if name == "report":
            sp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "record":
        if args.ttl_minutes <= 0:
            print("reservation: --ttl-minutes must be positive",
                  file=sys.stderr)
            return 2
        t = now_utc().replace(microsecond=0)
        rec = {"kind": "reservation", "agent": args.agent,
               "glob": args.glob,
               "reserved_at": t.isoformat().replace("+00:00", "Z"),
               "expires": (t + timedelta(minutes=args.ttl_minutes))
               .isoformat().replace("+00:00", "Z"),
               "note": args.note, "advisory_only": True}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"reservation: {args.agent} signals intent on "
              f"{args.glob} until {rec['expires']} "
              "(advisory only — blocks nothing)")
        return 0
    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"reservation: {e}", file=sys.stderr)
        print(f"reservation: register {'INVALID' if errors else 'valid'} "
              f"({len(_r)} record(s); advisory only, blocks nothing)")
        return 1 if errors else 0
    if cmd == "expire":
        records, errors = load_register(args.register)
        if errors:
            for e in errors:
                print(f"reservation: {e}", file=sys.stderr)
            return 1
        active, expired = expire(records)
        for r in expired:
            print(f"expired: {r['agent']} {r['glob']} "
                  f"(expired {r['expires']})")
        print(f"reservation: {len(expired)} expired, {len(active)} "
              "active (report only — nothing deleted)")
        return 0
    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"reservation: {rep['reservations']} reservation(s): "
              f"{rep['active']} active, {rep['expired']} expired, "
              f"{len(rep['overlaps'])} advisory overlap(s) "
              "(advisory only — blocks nothing)")
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
