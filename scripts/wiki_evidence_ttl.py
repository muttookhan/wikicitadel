#!/usr/bin/env python3
"""EU-N5 — evidence TTL convention: due-for-refresh checker.

Item: EU-N5 (Weaviate object TTL, from the project's
global-landscape research notes):
"evidence expires unless reaffirmed". The convention is
documented on the rules page `wiki/rules/evidence-ttl.md`;
this checker is its enforcement surface. It REPORTS only —
it never edits a page, extends a date, or retires a claim.

Convention (summary; the rules page governs):

  A page (a claim page included — claim pages are pages)
  may carry, in frontmatter:

    evidence_as_of: YYYY-MM-DD   when its evidence was last
                                 gathered / checked
    evidence_ttl_days: <int>     how many days that evidence
                                 may be relied on from as_of
    (or evidence_ttl: "90d" / "90 days" / <int>, same meaning)

  due date = evidence_as_of + TTL. On or after the due date
  the evidence is DUE FOR REFRESH: the page's claims may be
  resting on evidence older than the page itself declared
  acceptable. Pages carrying no TTL fields are outside the
  convention and are counted, not flagged. A TTL with no
  as_of, an unparseable as_of, or an unparseable TTL is an
  INVALID finding — a half-stated TTL is worse than none,
  because a reader may trust a horizon that does not exist.

Unlike owner attestations (`verified_until`, Lane 2 of the
lint lanes), evidence dates are agent-writable: they record
when evidence was gathered, not that the owner verified
anything. The two signals are kept distinct on purpose.

Output: human summary, or JSON with --json. `--all` also
lists pages still inside their TTL. Exit codes: 0 = nothing
due and nothing invalid, 1 = due or invalid findings,
2 = usage error.

Usage:
  python3 scripts/wiki_evidence_ttl.py [--root DIR]
      [--as-of YYYY-MM-DD] [--json] [--all]

Stdlib only.
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
TTL_RE = re.compile(r"^\s*(\d+)\s*(?:d|day|days)?\s*$", re.I)


def _load_validate():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_ttl_days(fields):
    """(days, error) from evidence_ttl_days / evidence_ttl.
    (None, None) when the page carries no TTL at all."""
    for key in ("evidence_ttl_days", "evidence_ttl"):
        if key not in fields or fields.get(key) is None:
            continue
        raw = str(fields[key]).strip()
        if raw == "":
            continue
        m = TTL_RE.match(raw)
        if not m:
            return None, f"{key}={raw!r} is not a day count"
        days = int(m.group(1))
        if days <= 0:
            return None, f"{key}={raw!r} must be a positive day count"
        return days, None
    return None, None


def parse_as_of(fields):
    """(date, present, error) from evidence_as_of (also
    accepts evidence_asof)."""
    for key in ("evidence_as_of", "evidence_asof"):
        if key not in fields or fields.get(key) is None:
            continue
        raw = str(fields[key]).strip()
        if raw == "":
            continue
        m = DATE_RE.search(raw)
        if not m:
            return None, True, f"{key}={raw!r} carries no ISO date"
        try:
            return date(int(m.group(1)), int(m.group(2)),
                        int(m.group(3))), True, None
        except ValueError:
            return None, True, f"{key}={raw!r} is not a real date"
    return None, False, None


def page_state(fields, today):
    """One page's TTL state: None (outside the convention),
    or a dict with status current / due / invalid."""
    days, ttl_err = parse_ttl_days(fields or {})
    as_of, present, asof_err = parse_as_of(fields or {})
    if ttl_err:
        return {"status": "invalid", "reason": ttl_err}
    if days is None and not present:
        return None
    if days is None:
        # as_of without a TTL states a date but no horizon:
        # inside the convention's record, outside its clock.
        return {"status": "no-ttl", "evidence_as_of": as_of.isoformat()}
    if asof_err:
        return {"status": "invalid", "reason": asof_err}
    if not present:
        return {"status": "invalid",
                "reason": "evidence TTL carried with no evidence_as_of"}
    due = as_of + timedelta(days=days)
    row = {"status": "due" if today >= due else "current",
           "evidence_as_of": as_of.isoformat(),
           "ttl_days": days, "due": due.isoformat(),
           "days_overdue": max(0, (today - due).days),
           "days_remaining": max(0, (due - today).days)}
    return row


def check(root, today):
    root = Path(root)
    validate = _load_validate()
    due, invalid, current, no_ttl = [], [], [], []
    scanned = with_any = 0
    wiki = root / "wiki"
    if wiki.is_dir():
        for path in sorted(wiki.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in EXCLUDED_FILES or rel.startswith(EXCLUDED_DIRS):
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            fields, _body = validate.parse_frontmatter(text)
            state = page_state(fields, today)
            if state is None:
                continue
            with_any += 1
            row = {"page": rel, **state}
            if state["status"] == "due":
                due.append(row)
            elif state["status"] == "invalid":
                invalid.append(row)
            elif state["status"] == "no-ttl":
                no_ttl.append(row)
            else:
                current.append(row)
    due.sort(key=lambda r: (-r["days_overdue"], r["page"]))
    invalid.sort(key=lambda r: r["page"])
    current.sort(key=lambda r: (r["days_remaining"], r["page"]))
    no_ttl.sort(key=lambda r: r["page"])
    return {"tool": "wiki_evidence_ttl", "as_of": today.isoformat(),
            "scanned": scanned, "with_evidence_fields": with_any,
            "due": due, "due_count": len(due),
            "invalid": invalid, "invalid_count": len(invalid),
            "current": current, "current_count": len(current),
            "no_ttl": no_ttl, "no_ttl_count": len(no_ttl)}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Evidence-TTL due-for-refresh checker (EU-N5).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--as-of", default=None,
                    help="judge as of this date (default: today)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="also list pages still inside their TTL")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    if args.as_of:
        try:
            today = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"error: --as-of {args.as_of!r} is not an ISO date",
                  file=sys.stderr)
            return 2
    else:
        today = date.today()
    report = check(root, today)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("== Evidence TTL (EU-N5) ==")
        print(f"as of {report['as_of']}: {report['scanned']} pages"
              f" scanned, {report['with_evidence_fields']} carrying"
              f" evidence fields; due {report['due_count']},"
              f" invalid {report['invalid_count']},"
              f" current {report['current_count']},"
              f" as-of-only {report['no_ttl_count']}")
        for r in report["due"]:
            print(f"  DUE {r['page']} — evidence as of"
                  f" {r['evidence_as_of']}, TTL {r['ttl_days']}d,"
                  f" due {r['due']} ({r['days_overdue']}d overdue)")
        for r in report["invalid"]:
            print(f"  INVALID {r['page']} — {r['reason']}")
        if args.all:
            for r in report["current"]:
                print(f"  current {r['page']} — due {r['due']}"
                      f" ({r['days_remaining']}d left)")
    return 1 if (report["due"] or report["invalid"]) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
