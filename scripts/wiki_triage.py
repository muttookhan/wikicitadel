#!/usr/bin/env python3
"""wiki_triage.py — triage verdicts over open items (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 3).

Pattern: gavishap/omnia-vault's plan-aware /intel triage (ideas
only — licence discrepancy in the source; re-implemented from the
idea). A triage pass over open items — filings, proposals, review
queues — emitting one verdict per item:

    act       the item is actionable now (clear next step, no
              ruling outstanding)
    park      the item is waiting on time or on other work; log the
              verdict so it is not re-litigated
    escalate  the item needs the owner (a decision, a block, or an
              item left open past the stale horizon)

REPORT ONLY: the tool reads items and prints a report (JSON, or
markdown with --format md). It never edits an item, moves a file,
or records a verdict anywhere itself — filing the report is a
separate act by whoever runs it.

An item is a markdown file with frontmatter. Signals, in order:
`status: decided|done|closed|filed` items are skipped (not open);
an explicit `verdict:` frontmatter field is respected as a prior
verdict and the item is reported as already-triaged; body markers
"owner decision", "ruling needed", "blocked" force escalate; an
`updated:`/`created:` date older than --stale-days (default 14)
with no progress marker escalates as stale; a "next:" or "action:"
line means act; anything else parks with its reason stated.

CLI: --root defaults to the tree root; items are the .md files
under each --dir (repeatable; default wiki/filings). --today pins
the clock for tests. Exit 0 on a completed pass, 2 on a missing dir.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

CLOSED = {"decided", "done", "closed", "filed", "adopted", "rejected"}


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1).lower()] = m.group(2).strip().strip('"\'')
    return fm, text[end + 4:]


def _parse_day(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def verdict_for(path, today, stale_days=14):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    status = fm.get("status", "").lower()
    item = {"file": str(path), "status": status or "open"}
    if status in CLOSED:
        return None
    if fm.get("verdict"):
        item.update(verdict=fm["verdict"], reason="prior verdict recorded "
                    "in frontmatter; not re-litigated",
                    already_triaged=True)
        return item
    low = body.lower()
    if re.search(r"owner decision|ruling needed|needs (a )?ruling|blocked",
                 low):
        item.update(verdict="escalate",
                    reason="asks for an owner ruling or is blocked")
        return item
    stamp = _parse_day(fm.get("updated") or fm.get("created"))
    if stamp and (today - stamp).days >= stale_days \
            and "progress:" not in low:
        item.update(verdict="escalate",
                    reason=f"open {((today - stamp).days)} days with no "
                           f"progress marker (stale horizon {stale_days})")
        return item
    if re.search(r"^\s*(next|action):", body, re.MULTILINE | re.IGNORECASE):
        item.update(verdict="act",
                    reason="carries an explicit next/action step")
        return item
    item.update(verdict="park",
                reason="open but no ruling outstanding and no stated "
                       "next step; parked, verdict logged by report")
    return item


def triage(directories, today, stale_days=14):
    items = []
    for d in directories:
        for p in sorted(Path(d).rglob("*.md")):
            v = verdict_for(p, today, stale_days)
            if v is not None:
                items.append(v)
    return items


def to_markdown(items, today):
    lines = [f"# Triage report — {today.isoformat()}", "",
             "Report only: no item was edited. Verdicts are proposals "
             "for the reviewer to file or act on.", ""]
    for v in ("act", "park", "escalate"):
        group = [i for i in items if i["verdict"] == v]
        lines.append(f"## {v} ({len(group)})")
        lines += [f"- {i['file']} — {i['reason']}" for i in group] or ["- (none)"]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--dir", action="append", dest="dirs", default=None)
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--today", default=None)
    ap.add_argument("--format", choices=("json", "md"), default="json")
    ns = ap.parse_args(argv)
    dirs = ns.dirs or [str(Path(ns.root) / "wiki" / "filings")]
    for d in dirs:
        if not Path(d).is_dir():
            print(f"missing dir: {d}", file=sys.stderr)
            return 2
    today = _parse_day(ns.today) if ns.today else date.today()
    items = triage(dirs, today, ns.stale_days)
    if ns.format == "md":
        print(to_markdown(items, today))
    else:
        counts = {v: sum(1 for i in items if i["verdict"] == v)
                  for v in ("act", "park", "escalate")}
        print(json.dumps({"today": today.isoformat(), "counts": counts,
                          "items": items}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
