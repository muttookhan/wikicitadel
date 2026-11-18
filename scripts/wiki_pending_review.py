#!/usr/bin/env python3
"""wiki_pending_review.py — self-clearing Pending Review checker.

Marathon Round 3, Lane TA5 (Tier A). Pattern: Vanillaflava/
llm-wiki-skills' self-clearing `## Pending Review` sections
(MIT project; re-implemented from the survey description, no
code copied): a page built from lower-confidence sources
carries a `## Pending Review` section naming the specific
claims still to corroborate, and the section is meant to
disappear once a stronger source resolves the gap. This
checker makes "meant to disappear" checkable — REPORT ONLY.
It never edits a page; clearing a section stays a human (or
reviewed) edit.

The entry grammar (stated here, the convention this tool
enforces by reading):
  a Pending Review section runs from a `## Pending Review`
  heading to the next `## ` heading (or end of page). Its
  entries are bullet lines (`- ` / `* `). An entry's state:
    resolved  the entry carries `(status: resolved)`;
    expired   the entry carries `(expires: YYYY-MM-DD)` with
              a date before --today, and is not resolved;
    open      anything else (including an expiry today or
              in the future).
  A section is CLEARABLE when it holds at least one entry
  and every entry is resolved or expired. An empty section
  is reported as "empty" — a finding of its own, not a
  clearable section.

Output: JSON on stdout (--plain for a short human report).
Exit codes: 0 no clearable sections · 1 at least one
clearable section (so a sweep can surface it) · 2 usage.

    python3 scripts/wiki_pending_review.py [--root DIR]
                                           [--today YYYY-MM-DD]
                                           [--plain]

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADING_RE = re.compile(r"^##\s+Pending Review\s*$", re.I)
H2_RE = re.compile(r"^##\s+")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
STATUS_RE = re.compile(r"\(\s*status:\s*(resolved|open|expired)\s*\)", re.I)
EXPIRES_RE = re.compile(r"\(\s*expires:\s*(\d{4}-\d{2}-\d{2})\s*\)", re.I)


def entry_state(text: str, today: date) -> str:
    """resolved / expired / open for one entry, per the
    grammar in the module docstring."""
    m = STATUS_RE.search(text)
    if m and m.group(1).lower() == "resolved":
        return "resolved"
    if m and m.group(1).lower() == "expired":
        return "expired"
    e = EXPIRES_RE.search(text)
    if e:
        try:
            when = date.fromisoformat(e.group(1))
        except ValueError:
            return "open"
        if when < today:
            return "expired"
    return "open"


def parse_section(lines: list[str], today: date) -> list[dict]:
    """Entries of one Pending Review section body."""
    entries = []
    for line in lines:
        m = BULLET_RE.match(line)
        if m:
            entries.append({"text": m.group(1).strip(),
                            "state": entry_state(m.group(1), today)})
    return entries


def scan_page(text: str, today: date) -> list[dict]:
    """All Pending Review sections of one page:
    [{entries, states, clearable, empty}]."""
    sections = []
    current = None
    for line in text.splitlines():
        if HEADING_RE.match(line):
            current = []
            sections.append(current)
            continue
        if current is not None and H2_RE.match(line) \
                and not HEADING_RE.match(line):
            current = None
            continue
        if current is not None:
            current.append(line)
    out = []
    for body in sections:
        entries = parse_section(body, today)
        states = [e["state"] for e in entries]
        out.append({
            "entries": entries,
            "entry_count": len(entries),
            "open": states.count("open"),
            "resolved": states.count("resolved"),
            "expired": states.count("expired"),
            "empty": len(entries) == 0,
            "clearable": bool(entries)
            and all(s in ("resolved", "expired") for s in states),
        })
    return out


def scan(root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    pages = []
    wiki = Path(root) / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if "pending review" not in text.lower():
                continue
            sections = scan_page(text, today)
            if sections:
                pages.append({"page": str(p.relative_to(root)),
                              "sections": sections})
    clearable = [{"page": pg["page"], "section_index": i}
                 for pg in pages
                 for i, s in enumerate(pg["sections"]) if s["clearable"]]
    empty = [{"page": pg["page"], "section_index": i}
             for pg in pages
             for i, s in enumerate(pg["sections"]) if s["empty"]]
    return {
        "tool": "scripts/wiki_pending_review.py",
        "kind": "pending-review-report",
        "pattern": "Vanillaflava self-clearing Pending Review "
                   "sections — report-only checker; this tool "
                   "never edits a page",
        "date": today.isoformat(),
        "stats": {"pages_with_sections": len(pages),
                  "sections": sum(len(pg["sections"]) for pg in pages),
                  "clearable": len(clearable),
                  "empty": len(empty),
                  "open_entries": sum(s["open"] for pg in pages
                                      for s in pg["sections"])},
        "pages": pages,
        "clearable": clearable,
        "empty_sections": empty,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--today", default=None,
                    help="date treated as today (testing); "
                         "default: the real today")
    ap.add_argument("--plain", action="store_true",
                    help="short human report instead of JSON")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    today = date.fromisoformat(args.today) if args.today else date.today()
    report = scan(root, today=today)
    if args.plain:
        st = report["stats"]
        print(f"pending review: {st['sections']} section(s) on "
              f"{st['pages_with_sections']} page(s); "
              f"{st['open_entries']} open entr(ies); "
              f"{st['clearable']} clearable; {st['empty']} empty")
        for c in report["clearable"]:
            print(f"  CLEARABLE: {c['page']} (section {c['section_index']}) "
                  "— all entries resolved/expired; clearing is a "
                  "separate human edit, this tool changed nothing")
        for c in report["empty_sections"]:
            print(f"  EMPTY: {c['page']} (section {c['section_index']})")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["clearable"] else 0


if __name__ == "__main__":
    sys.exit(main())
