#!/usr/bin/env python3
"""Rosenthal threat-and-disclosure register (Marathon R8,
Tier A; Rosenthal et al., D-Lib Magazine 2005).

Rosenthal's preservation threat taxonomy names the ways a
stored corpus actually dies: failures of the media, the
hardware and the software; obsolescence; operator error;
natural / man-made disaster; attack; and economic or
organisational failure. A wiki that cannot say, per threat,
what its strategy is and WHICH script or register evidences
that strategy does not have a preservation story — it has a
hope.

The register is evaluation/threat-register.jsonl: a header
line, then exactly one row per threat class:

    {"kind": "threat", "threat": "<class>",
     "strategy": "<the wiki's stated strategy, or ''>",
     "evidence": ["<repo-relative path>", ...],
     "status": "mapped" | "gap"}

A GAP IS A FINDING, NOT AN EMBARRASSMENT TO PAPER OVER: a
threat with no stated strategy keeps an empty strategy and
empty evidence and status "gap", and this checker lists it
on every run until a real strategy exists. Nothing here
auto-remediates anything: `check` reports, `report` prints
the register readably, and neither writes a file.

Usage:
  python3 scripts/wiki_threat_register.py report [--register F]
  python3 scripts/wiki_threat_register.py check  [--register F]

`check` exits 1 when: a threat class is missing or duplicated,
a "mapped" row's evidence path does not exist in the tree, a
row claims status "mapped" with an empty strategy or no
evidence, or any row is a gap / unevidenced (the findings are
the point of the run). Exit 2 = usage error (no register).
Stdlib only, no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "threat-register.jsonl"

THREAT_CLASSES = (
    "media-failure",
    "hardware-failure",
    "software-failure",
    "obsolescence",
    "operator-error",
    "disaster",
    "attack",
    "economic-failure",
    "organisational-failure",
)


def load_register(path):
    header, rows = None, []
    if not Path(path).exists():
        return header, rows
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        elif obj.get("kind") == "threat":
            rows.append(obj)
    return header, rows


def findings(rows, root=ROOT):
    """(unmapped, unevidenced, structural) for a register's rows.

    unmapped:    threat classes with no row, or a row whose
                 strategy is empty (a stated gap counts here —
                 it is unmapped until a strategy exists);
    unevidenced: rows with a strategy but no evidence, or whose
                 evidence paths do not resolve in the tree;
    structural:  duplicate / unknown classes, status drift."""
    unmapped, unevidenced, structural = [], [], []
    seen = {}
    for row in rows:
        threat = row.get("threat")
        if threat not in THREAT_CLASSES:
            structural.append(f"unknown threat class: {threat!r}")
            continue
        if threat in seen:
            structural.append(f"duplicate row for {threat}")
        seen[threat] = row
        strategy = (row.get("strategy") or "").strip()
        evidence = row.get("evidence") or []
        if row.get("status") == "mapped" and not strategy:
            structural.append(f"{threat}: status 'mapped' but no strategy")
        if row.get("status") == "mapped" and not evidence:
            structural.append(f"{threat}: status 'mapped' but no evidence")
        if row.get("status") not in ("mapped", "gap"):
            structural.append(
                f"{threat}: status {row.get('status')!r} not in "
                f"('mapped', 'gap')")
        if not strategy:
            unmapped.append(threat)
            continue
        if not evidence:
            unevidenced.append(f"{threat}: strategy stated, no evidence")
            continue
        for ref in evidence:
            if not (Path(root) / ref).exists():
                unevidenced.append(f"{threat}: evidence missing: {ref}")
    for threat in THREAT_CLASSES:
        if threat not in seen:
            unmapped.append(f"{threat} (no row)")
    return unmapped, unevidenced, structural


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", default=str(REGISTER))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    if not Path(args.register).exists():
        print(f"no threat register: {args.register}", file=sys.stderr)
        return 2
    _header, rows = load_register(args.register)
    unmapped, unevidenced, structural = findings(rows)
    if args.cmd == "report":
        for row in rows:
            strategy = (row.get("strategy") or "").strip() or "(none — GAP)"
            evidence = ", ".join(row.get("evidence") or []) or "(none)"
            print(f"{row.get('threat')}: [{row.get('status')}] {strategy}")
            print(f"    evidence: {evidence}")
    print(f"threat register: {len(rows)} row(s); "
          f"unmapped: {len(unmapped)}; unevidenced: {len(unevidenced)}; "
          f"structural problems: {len(structural)}")
    for threat in unmapped:
        print(f"  UNMAPPED (finding): {threat}")
    for item in unevidenced:
        print(f"  UNEVIDENCED (finding): {item}")
    for item in structural:
        print(f"  STRUCTURAL: {item}")
    if args.cmd == "check":
        return 1 if (unmapped or unevidenced or structural) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
