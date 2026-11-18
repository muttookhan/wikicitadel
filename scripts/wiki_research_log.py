#!/usr/bin/env python3
"""The research log — every search run for a claim, recorded
either way (WikiCitadel v1: the genealogy proof bar).

Genealogy's discipline (Mills; Research Like a Pro): a *negative
finding* is just "I looked and didn't find it" — routine, no
evidentiary weight. *Negative evidence* is an inference from an
absence that should not exist, earned only after the mundane
causes (record loss, incomplete coverage, indexing error, a
failed door) are ruled out. The enabling practice is the
research log: every search recorded with its date, the claim or
page it served, the exact query, the doors tried, and the result
class — so "we found nothing" becomes a checkable statement
instead of an impression, and no search is ever silently
repeated.

The log is `evaluation/research-log.jsonl`, append-only: one
JSON object per line, a header line first (kind: header). The
result classes are exactly three:

  found       — the search located what it was looking for.
  not-found   — the doors were exercised and the thing is not
                there (a negative FINDING; it becomes negative
                EVIDENCE only after the mundane causes are
                checked off in the entry's notes).
  door-failed — a door could not be exercised at all (paywall,
                fetcher block, HTTP refusal). A door failure is
                a statement about the door, never about the
                world: it must never be recorded as not-found.

Usage:
  python3 scripts/wiki_research_log.py append \
      --claim "the claim or question the search served" \
      --query "the exact query or procedure" \
      --doors "door one, door two" \
      --result found|not-found|door-failed \
      [--page wiki/page.md] [--notes "..."] [--date YYYY-MM-DD]

  python3 scripts/wiki_research_log.py list [--claim SUBSTR]
                                            [--result CLASS]

Stdlib only. This tool appends and lists; it never edits or
removes a line.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_REL = Path("evaluation/research-log.jsonl")

RESULTS = ("found", "not-found", "door-failed")

HEADER = {
    "kind": "header",
    "register": "research-log",
    "version": 1,
    "purpose": ("Append-only log of searches run for claims: date, "
                "claim/page served, query, doors tried, result class "
                "(found / not-found / door-failed). A not-found is a "
                "negative finding, not negative evidence; a door-failed "
                "is a statement about the door, never about the world. "
                "Maintained via scripts/wiki_research_log.py. The "
                "discipline is stated on wiki/rules/proof-bar.md "
                "(WikiCitadel v1; Mills / genealogy "
                "practice via the survey)."),
}


def log_path(root: Path) -> Path:
    return root / LOG_REL


def read_entries(root: Path):
    """All search entries (header lines skipped), in file order."""
    p = log_path(root)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("kind") == "search":
            entries.append(obj)
    return entries


def append_entry(root: Path, entry: dict) -> dict:
    """Validate and append one search entry. Creates the log with
    its header line when missing. Never rewrites existing lines."""
    if entry.get("result") not in RESULTS:
        raise ValueError(
            f"result must be one of {RESULTS}, got {entry.get('result')!r}")
    for field in ("date", "claim", "query", "doors"):
        if not entry.get(field):
            raise ValueError(f"missing required field: {field}")
    if not isinstance(entry["doors"], list) or not entry["doors"]:
        raise ValueError("doors must be a non-empty list")
    record = {"kind": "search"}
    for key in ("date", "claim", "page", "query", "doors", "result", "notes"):
        if entry.get(key):
            record[key] = entry[key]
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8") as fh:
        if needs_header:
            header = dict(HEADER, created=date.today().isoformat())
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_entries(root: Path, claim_substr=None, result=None):
    entries = read_entries(root)
    if claim_substr:
        needle = claim_substr.lower()
        entries = [e for e in entries
                   if needle in e.get("claim", "").lower()
                   or needle in e.get("page", "").lower()]
    if result:
        entries = [e for e in entries if e.get("result") == result]
    return entries


def format_entry(e: dict) -> str:
    head = f"{e['date']} · {e['result']} · {e['claim']}"
    lines = [head]
    if e.get("page"):
        lines.append(f"    page:  {e['page']}")
    lines.append(f"    query: {e['query']}")
    lines.append(f"    doors: {'; '.join(e['doors'])}")
    if e.get("notes"):
        lines.append(f"    notes: {e['notes']}")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="append one search record")
    a.add_argument("--claim", required=True)
    a.add_argument("--query", required=True)
    a.add_argument("--doors", required=True,
                   help="comma-separated list of doors tried")
    a.add_argument("--result", required=True, choices=RESULTS)
    a.add_argument("--page", default=None)
    a.add_argument("--notes", default=None)
    a.add_argument("--date", default=None,
                   help="search date (default: today)")

    li = sub.add_parser("list", help="list recorded searches")
    li.add_argument("--claim", default=None,
                    help="substring filter over claim and page")
    li.add_argument("--result", default=None, choices=RESULTS)

    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT

    if args.cmd == "append":
        entry = {
            "date": args.date or date.today().isoformat(),
            "claim": args.claim,
            "page": args.page,
            "query": args.query,
            "doors": [d.strip() for d in args.doors.split(",") if d.strip()],
            "result": args.result,
            "notes": args.notes,
        }
        try:
            record = append_entry(root, entry)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"logged: {format_entry(record).splitlines()[0]}")
        return 0

    entries = list_entries(root, args.claim, args.result)
    if not entries:
        print("no searches recorded (matching filters, if any).")
        return 0
    for e in entries:
        print(format_entry(e))
    print(f"\n{len(entries)} search(es) recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
