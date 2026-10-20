#!/usr/bin/env python3
"""wiki_verify_status.py — the verification-status register.

WikiCitadel v1, the build queue's last item and its honesty
capstone. Pattern: register discipline — a governed,
append-only jsonl register in evaluation/ beside the decisions,
treatment and source-grades registers, with this tool as its
only writer.

The problem it exists to close: this wiki's documents assert
things about its own machinery ("the Lens is live", "the Ask
door answers questions", "checkpoints are anchored") and those
assertions age silently. The register gives every tooling and
capability claim ONE honest label, with the evidence the label
rests on and the date it was earned:

  live-verified            the real thing was exercised
                           against its real counterpart (the
                           live site served, real filings
                           moved) on the as_of date;
  protocol-verified        the mechanism was exercised end to
                           end against fixtures / a protocol /
                           a test suite, but NOT against the
                           live counterpart;
  documented-but-unverified
                           the claim exists in documentation
                           only; nothing has exercised it.

A claim that outruns its label is a defect. The register's
header carries that as a standing rule: no page, doc or report
in this wiki may claim more about a tool or capability than
this register's label for it.

Labels age. Freshness windows: live-verified goes stale after
30 days, protocol-verified after 90 (a fixture suite re-run is
cheap; a stale protocol label means even that has not happened
lately). Documented-but-unverified never goes "stale" — it
asserts nothing was checked, which stays true until a `set`
supersedes it. `check` flags every stale label: a label that
has aged out must be re-verified or downgraded — it may not
simply be repeated.

One honesty limit, stated plainly: the three labels cannot say
"attempted, and the attempt FAILED". The timestamp-anchor
entry is the standing example — the mechanism is built, the
attempts ran twice and earned nothing. Its label is
documented-but-unverified (nothing stands verified, which is
true) and its evidence line carries the whole truth. Do not
stretch a label to cover a failure; put the failure in the
evidence.

Register: evaluation/verification-status.jsonl, append-only;
`set` appends a fresh record for a subject (the latest record
is the subject's current label; history is never rewritten).
`set` REFUSES a record without --evidence: a label with
nothing under it is exactly what this register exists to
prevent.

Commands:

    python3 scripts/wiki_verify_status.py list [--json]
    python3 scripts/wiki_verify_status.py set <subject> \
        --claim "..." --status <label> --evidence "..." \
        [--as-of YYYY-MM-DD] [--by <who>]
    python3 scripts/wiki_verify_status.py check [--today YYYY-MM-DD]
        [--window-live 30] [--window-protocol 90] [--json]

Exit codes: 0 ok · 1 refusal / stale labels found · 2 usage error.
"""
import argparse
import json
import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/verification-status.jsonl"

LABELS = ("live-verified", "protocol-verified",
          "documented-but-unverified")
DEFAULT_WINDOWS = {"live-verified": 30, "protocol-verified": 90}


class Refusal(Exception):
    """A record the register will not take (exit 1)."""


def register_path(root):
    return root / REGISTER_REL


def load_records(root):
    path = register_path(root)
    header, records = None, []
    if not path.exists():
        return header, records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        elif obj.get("kind") == "status":
            records.append(obj)
    return header, records


def latest_by_subject(records):
    latest = {}
    for r in records:
        latest[r["subject"]] = r
    return latest


def parse_day(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def age_days(as_of, today):
    return (today - parse_day(as_of)).days


def cmd_list(root, as_json):
    _header, records = load_records(root)
    latest = latest_by_subject(records)
    rows = [latest[s] for s in sorted(latest)]
    if as_json:
        return {"subjects": rows}
    lines = [f"verification status — {len(rows)} subject(s)"]
    for r in rows:
        lines.append(f"- {r['subject']} [{r['status']}, as of "
                     f"{r['as_of']}]")
        lines.append(f"    claim: {r['claim']}")
        lines.append(f"    evidence: {r['evidence']}")
    return "\n".join(lines) + "\n"


def cmd_set(root, subject, claim, status, evidence, as_of, by):
    if status not in LABELS:
        raise Refusal(f"status '{status}' is not a label "
                      f"(labels: {', '.join(LABELS)})")
    if not evidence or not evidence.strip():
        raise Refusal("no record without evidence: state what the "
                      "label rests on (a dated live check, a "
                      "protocol/fixture run, or the documented "
                      "absence of any exercise)")
    if not claim or not claim.strip():
        raise Refusal("no record without a claim: state the "
                      "assertion the label covers, in one line")
    try:
        parse_day(as_of)
    except ValueError:
        raise Refusal(f"--as-of '{as_of}' is not YYYY-MM-DD")
    path = register_path(root)
    if not path.exists():
        raise Refusal("register file missing — the header must "
                      "exist before any status record (the "
                      "register is seeded, not improvised)")
    record = {"kind": "status", "subject": subject, "claim": claim,
              "status": status, "evidence": evidence,
              "as_of": as_of, "by": by}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def cmd_check(root, today, windows, as_json):
    _header, records = load_records(root)
    latest = latest_by_subject(records)
    flags = []
    for subject in sorted(latest):
        r = latest[subject]
        if r["status"] not in LABELS:
            flags.append({"subject": subject, "problem":
                          f"label '{r['status']}' is outside the "
                          f"vocabulary"})
            continue
        win = windows.get(r["status"])
        if win is not None:
            age = age_days(r["as_of"], today)
            if age > win:
                flags.append({"subject": subject, "problem":
                              f"{r['status']} label is {age} days "
                              f"old (window {win}) — re-verify or "
                              f"downgrade; the label may not simply "
                              f"be repeated"})
    result = {"subjects": len(latest), "flags": flags}
    if as_json:
        return result
    lines = [f"verification-status check: {len(latest)} "
             f"subject(s) · {len(flags)} flag(s)"]
    for f in flags:
        lines.append(f"  STALE {f['subject']}: {f['problem']}")
    return "\n".join(lines) + "\n", 1 if flags else 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="The verification-status register: honest "
                    "labels for the wiki's own tooling claims.")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repo root (default: this tool's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="latest label per subject")
    lp.add_argument("--json", action="store_true")

    sp = sub.add_parser("set", help="append a status record")
    sp.add_argument("subject")
    sp.add_argument("--claim", required=True)
    sp.add_argument("--status", required=True, choices=LABELS)
    sp.add_argument("--evidence", required=True)
    sp.add_argument("--as-of", default=_date.today().isoformat())
    sp.add_argument("--by", default="agent")
    sp.add_argument("--json", action="store_true")

    cp = sub.add_parser("check", help="flag stale labels")
    cp.add_argument("--today", default=_date.today().isoformat())
    cp.add_argument("--window-live", type=int,
                    default=DEFAULT_WINDOWS["live-verified"])
    cp.add_argument("--window-protocol", type=int,
                    default=DEFAULT_WINDOWS["protocol-verified"])
    cp.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    root = args.root
    try:
        if args.cmd == "list":
            out = cmd_list(root, args.json)
            if args.json:
                print(json.dumps(out, indent=1))
            else:
                print(out, end="")
            return 0
        if args.cmd == "set":
            rec = cmd_set(root, args.subject, args.claim,
                          args.status, args.evidence, args.as_of,
                          args.by)
            print(json.dumps(rec, indent=1) if args.json else
                  f"recorded: {rec['subject']} [{rec['status']}, "
                  f"as of {rec['as_of']}]")
            return 0
        if args.cmd == "check":
            windows = {"live-verified": args.window_live,
                       "protocol-verified": args.window_protocol}
            out = cmd_check(root, parse_day(args.today), windows,
                            args.json)
            if args.json:
                print(json.dumps(out, indent=1))
                return 1 if out["flags"] else 0
            text, code = out
            print(text, end="")
            return code
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
