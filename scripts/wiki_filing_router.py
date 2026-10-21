#!/usr/bin/env python3
"""wiki_filing_router.py — filing classifier routing (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 1).

Pattern: crow-hq/llm-wiki-v2's typed-classifier routing for filing
decisions (AGPL — IDEAS ONLY; re-implemented here from the idea, no
code or text copied). An incoming filing or capture is ROUTED to a
proposed destination — never moved. The router reads the item's
frontmatter and body signals and emits one routing proposal per item:
a destination, a confidence (0..1), and the reasons that fired, in
machine-readable JSON. A human (or a later recorded act) applies the
route; this tool writes nothing to the corpus.

Destinations:
    filings-area   an admitted agent's filing for the filings area
    source-page    a read source that wants a compiled source page
    ingest-queue   material awaiting the ingest path
    review-queue   needs an owner/agent decision before filing
    ideas          an undirected idea for the ideas board

Subcommands:
    route <file>...        one proposal per file (JSON list)
    audit <dir>            list MISFILINGS: files under <dir> whose
                           declared `destination:` frontmatter (what
                           a sender asserted) disagrees with the
                           routed destination at confidence >= 0.6.

CLI: --root defaults to the tree root. Exit 0 on success, 2 on a
missing input file.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DESTINATIONS = ("filings-area", "source-page", "ingest-queue",
                "review-queue", "ideas")

AGENTS = ("grok", "hark", "codex", "chatgpt", "antigravity", "jules")


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


def route_item(path, root=None):
    """Return the routing proposal dict for one file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    low = (fm.get("title", "") + " " + body[:4000]).lower()
    scores = {d: 0.0 for d in DESTINATIONS}
    reasons = {d: [] for d in DESTINATIONS}

    def hit(dest, weight, why):
        scores[dest] += weight
        reasons[dest].append(why)

    kind = fm.get("type", "").lower()
    by = (fm.get("by") or fm.get("author") or fm.get("from") or "").lower()
    if kind in ("filing", "agent-filing") or any(a in by for a in AGENTS):
        hit("filings-area", 0.6, "filing kind or admitted-agent author")
    if fm.get("filed_by") or "filing" in Path(path).name:
        hit("filings-area", 0.25, "filing marker present")
    if kind == "source" or fm.get("source_url") or fm.get("url"):
        hit("source-page", 0.5, "source type or source URL present")
    if re.search(r"\b(https?://|www\.)", body) and kind != "filing":
        hit("source-page", 0.15, "body carries an external link")
    if fm.get("capture") or "capture" in low[:400]:
        hit("ingest-queue", 0.4, "capture marker: not yet ingested")
    if kind in ("idea",) or fm.get("idea"):
        hit("ideas", 0.6, "declared idea kind")
    if re.search(r"\b(decide|decision|owner ruling|ruling needed|"
                 r"approve|reject|blocked|escalate)\b", low):
        hit("review-queue", 0.45, "asks for a ruling or is blocked")
    if fm.get("status", "").lower() in ("draft", "unclassified", "new"):
        hit("ingest-queue", 0.2, "status is draft/new: intake not finished")
    if scores["filings-area"] == 0 and scores["source-page"] == 0 \
            and scores["ideas"] == 0 and scores["review-queue"] == 0:
        hit("ingest-queue", 0.3, "no stronger signal: default intake queue")

    dest = max(DESTINATIONS, key=lambda d: scores[d])
    confidence = round(min(0.99, scores[dest]), 2)
    return {
        "file": str(path),
        "destination": dest,
        "confidence": confidence,
        "reasons": reasons[dest],
        "scores": {d: round(s, 2) for d, s in scores.items()},
        "declared": fm.get("destination") or None,
        "proposal_only": True,
    }


def audit(directory):
    """Files whose declared destination disagrees with the route."""
    out = []
    for p in sorted(Path(directory).rglob("*.md")):
        prop = route_item(p)
        if prop["declared"] and prop["declared"] != prop["destination"] \
                and prop["confidence"] >= 0.6:
            out.append({"file": prop["file"],
                        "declared": prop["declared"],
                        "routed": prop["destination"],
                        "confidence": prop["confidence"],
                        "reasons": prop["reasons"]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("route")
    r.add_argument("files", nargs="+")
    a = sub.add_parser("audit")
    a.add_argument("directory")
    ns = ap.parse_args(argv)
    if ns.cmd == "route":
        for f in ns.files:
            if not Path(f).exists():
                print(f"missing: {f}", file=sys.stderr)
                return 2
        print(json.dumps([route_item(f, ns.root) for f in ns.files],
                         indent=2))
    else:
        if not Path(ns.directory).is_dir():
            print(f"missing dir: {ns.directory}", file=sys.stderr)
            return 2
        print(json.dumps(audit(ns.directory), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
