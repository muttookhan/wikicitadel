#!/usr/bin/env python3
"""wiki_rule_amendments.py — Newsroom meta loop (Marathon R3, Tier B
bundle "Graph, portal and capture forms", row 2).

Pattern: llm-wiki-newsroom's meta loop (MIT ideas; re-implemented
from the idea). Recurring failure patterns in the lint/sweep filings
are detected and drafted into RULE AMENDMENT proposals. A proposal
is a draft file only — it is never adopted automatically; adoption
stays an owner act recorded elsewhere.

Filing records are markdown files under a filings directory. A
failure record is a line of the shape:

    - failure: <pattern-key> — <detail>

The detector counts pattern-keys across every record file; a key
seen at least --threshold times (default 3) is "recurring" and gets
one draft proposal written to --out-dir (or printed with --dry-run).

Proposal frontmatter marks it `status: draft-proposal` and
`adoption: manual-only`, so no downstream tool can mistake it for
an adopted rule.

CLI: --root defaults to the tree root; --filings-dir defaults to
wiki/filings; --out-dir defaults to wiki/filings/amendment-proposals.
Exit 0 always on a completed scan; 2 if the filings dir is missing.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

FAIL_RE = re.compile(r"^-\s*failure:\s*([a-z0-9][a-z0-9\-_]*)\s*[—–-]\s*(.*)$",
                     re.MULTILINE)


def scan(filings_dir):
    """Return {pattern: {count, files, details}} from filing records."""
    found = defaultdict(lambda: {"count": 0, "files": set(), "details": []})
    for p in sorted(Path(filings_dir).rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in FAIL_RE.finditer(text):
            key, detail = m.group(1), m.group(2).strip()
            e = found[key]
            e["count"] += 1
            e["files"].add(str(p))
            if detail and len(e["details"]) < 5:
                e["details"].append(detail)
    return {k: {"count": v["count"], "files": sorted(v["files"]),
                "details": v["details"]} for k, v in found.items()}


def recurring(scan_result, threshold=3):
    return {k: v for k, v in scan_result.items() if v["count"] >= threshold}


def draft_text(pattern, info, today):
    details = "\n".join(f"- {d}" for d in info["details"]) or "- (none kept)"
    files = "\n".join(f"- {f}" for f in info["files"])
    return f"""---
title: "Rule amendment proposal — {pattern}"
type: synthesis
created: {today}
updated: {today}
sources: []
tags: [rule-amendment, proposal, meta-loop]
status: draft-proposal
adoption: manual-only
pattern: {pattern}
occurrences: {info['count']}
stage: seedling
planted: {today}
tended: {today}
work_type: advice
methods: "Drafted by scripts/wiki_rule_amendments.py from recurring filing failure records; not reviewed, not adopted."
---

# Rule amendment proposal — {pattern}

DRAFT PROPOSAL ONLY. This text was drafted by the Newsroom meta-loop
detector because the failure pattern `{pattern}` recurred
{info['count']} times in the lint/sweep filings.
Nothing here is in force. Adoption is an explicit owner act,
recorded in the log.

## Observed failures

{details}

## Filing records carrying the pattern

{files}

## Draft amendment (for owner editing)

When a filing or lint pass hits `{pattern}`, the authoring rules
should state the check that would have caught it, in the section of
AGENTS.md that governs the failing artefact, so the same failure
stops recurring instead of being fixed one page at a time.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--filings-dir", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--threshold", type=int, default=3)
    ap.add_argument("--today", default="2026-10-21")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)
    root = Path(ns.root)
    filings = Path(ns.filings_dir) if ns.filings_dir else root / "wiki" / "filings"
    if not filings.is_dir():
        print(f"missing filings dir: {filings}", file=sys.stderr)
        return 2
    result = scan(filings)
    rec = recurring(result, ns.threshold)
    written = []
    if rec and not ns.dry_run:
        out = Path(ns.out_dir) if ns.out_dir else filings / "amendment-proposals"
        out.mkdir(parents=True, exist_ok=True)
        for pattern, info in sorted(rec.items()):
            dest = out / f"amendment-{pattern}.md"
            dest.write_text(draft_text(pattern, info, ns.today),
                            encoding="utf-8")
            written.append(str(dest))
    print(json.dumps({"patterns_seen": len(result),
                      "recurring": {k: v["count"] for k, v in
                                    sorted(rec.items())},
                      "proposals_written": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
