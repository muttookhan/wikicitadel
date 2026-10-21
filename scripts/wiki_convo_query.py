#!/usr/bin/env python3
"""wiki_convo_query.py — conversation-log query tool (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 5).

Pattern: DiaryKG's source-grounded snippet approach (ideas only;
re-implemented from the idea) applied to CONVERSATION-LOG.md:
answers are verbatim, CITED excerpts — file + line ranges — never
paraphrases. The log's entries look like:

    ### [2026-01-15 09:00 EST] Owner
    <body until the next ### header>

Filters (all supplied filters must match):
    --date YYYY-MM-DD        entries on that date
    --from / --to            inclusive date range
    --speaker NAME           speaker equals NAME (case-insensitive)
    --keyword TEXT           body or header contains TEXT
    --decisions              only entries carrying a decision marker
                             (DECIDED / Decision: / ruled / approved —
                             see DECISION_RE)

Output: JSON list of {file, lines: [start, end], date, speaker,
excerpt}. --format text prints `file#Lstart-Lend` then the excerpt.

CLI: --log defaults to <root>/CONVERSATION-LOG.md. Exit 0 on a
completed query (zero hits is a result, not an error), 2 if the
log file is missing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(
    r"^###\s+\[(\d{4}-\d{2}-\d{2})(?:\s+([^\]]*))?\]\s*(.*)$")
DECISION_RE = re.compile(
    r"\b(DECIDED|Decision:|decided:|ruled|approved|rejected|parked)\b")


def entries(path):
    """Parse the log into entry dicts with 1-based line ranges."""
    lines = Path(path).read_text(encoding="utf-8",
                                 errors="replace").splitlines()
    out, cur = [], None
    for i, line in enumerate(lines, start=1):
        m = HEADER_RE.match(line)
        if m:
            if cur:
                cur["lines"][1] = i - 1
                out.append(cur)
            speaker = m.group(3).strip()
            cur = {"date": m.group(1), "speaker": speaker,
                   "lines": [i, len(lines)], "body_lines": []}
        elif cur is not None:
            cur["body_lines"].append(line)
    if cur:
        out.append(cur)
    for e in out:
        e["excerpt"] = "\n".join(
            [f"### [{e['date']}] {e['speaker']}"] + e["body_lines"]).rstrip()
        del e["body_lines"]
    return out


def query(path, date_=None, from_=None, to=None, speaker=None,
          keyword=None, decisions=False):
    hits = []
    for e in entries(path):
        if date_ and e["date"] != date_:
            continue
        if from_ and e["date"] < from_:
            continue
        if to and e["date"] > to:
            continue
        if speaker and e["speaker"].lower() != speaker.lower():
            continue
        if keyword and keyword.lower() not in e["excerpt"].lower():
            continue
        if decisions and not DECISION_RE.search(e["excerpt"]):
            continue
        hits.append({"file": str(path), "lines": e["lines"],
                     "date": e["date"], "speaker": e["speaker"],
                     "excerpt": e["excerpt"]})
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--log", default=None)
    ap.add_argument("--date", dest="date_", default=None)
    ap.add_argument("--from", dest="from_", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--speaker", default=None)
    ap.add_argument("--keyword", default=None)
    ap.add_argument("--decisions", action="store_true")
    ap.add_argument("--format", choices=("json", "text"), default="json")
    ns = ap.parse_args(argv)
    log = Path(ns.log) if ns.log else Path(ns.root) / "CONVERSATION-LOG.md"
    if not log.exists():
        print(f"missing log: {log}", file=sys.stderr)
        return 2
    hits = query(log, ns.date_, ns.from_, ns.to, ns.speaker,
                 ns.keyword, ns.decisions)
    if ns.format == "text":
        for h in hits:
            print(f"{h['file']}#L{h['lines'][0]}-L{h['lines'][1]}")
            print(h["excerpt"])
            print()
    else:
        print(json.dumps(hits, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
