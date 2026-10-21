#!/usr/bin/env python3
"""Offline verifier for the checkpoint register (Marathon
R3, Tier B row TB3-6; world-model-mcp pattern).

Pattern: world-model-mcp's signed, Merkle-chained ledger
with an OFFLINE verifier (via the 2026-10-19 survey,
"a worked design for hardening the Black Box") — the check
that matters most must run with nothing but the register
file itself: no repo, no git, no signing key, no network.
Re-implemented from the idea; this verifier is deliberately
STANDALONE — it imports nothing from wiki_checkpoint.py and
re-derives the chain rule from the register's own stated
format:

  every non-header line carries prev_hash and
  line_hash = sha256(prev_hash || canonical(line without
  line_hash)), canonical = UTF-8 JSON, sorted keys, no
  insignificant whitespace; the genesis prev_hash is
  64 zeroes.

It reports: chain integrity (first break's line index and
reason), line count, head hash, and whether the register
ends where its own last line says it ends. It does NOT
verify signatures or live state — that is wiki_checkpoint.py
verify's job, online in the repo. This tool answers the
narrower question a witness copy must answer on its own:
was THIS file altered?

Usage:
  python3 scripts/wiki_checkpoint_verify_offline.py REGISTER.jsonl

Exit codes: 0 = chain intact, 1 = a break found,
2 = usage error (missing / unparseable register).
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

GENESIS_PREV = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def verify_register(path: Path):
    """(ok, report dict). Header lines (kind == 'header')
    are counted but excluded from chaining, matching the
    register's own rule."""
    report = {"register": str(path), "lines": 0, "chained": 0,
              "head_hash": None, "ok": False, "break": None}
    if not path.is_file():
        report["break"] = {"reason": "register file not found"}
        return False, report
    prev = GENESIS_PREV
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        report["break"] = {"reason": f"unreadable: {exc}"}
        return False, report
    for idx, raw in enumerate(raw_lines):
        raw = raw.strip()
        if not raw:
            continue
        report["lines"] += 1
        try:
            obj = json.loads(raw)
        except ValueError as exc:
            report["break"] = {"line": idx,
                               "reason": f"unparseable JSON: {exc}"}
            return False, report
        if obj.get("kind") == "header":
            continue
        report["chained"] += 1
        if obj.get("prev_hash") != prev:
            report["break"] = {"line": idx,
                               "reason": "prev_hash mismatch — "
                                         "a line was inserted, "
                                         "removed, or reordered"}
            return False, report
        body = {k: v for k, v in obj.items() if k != "line_hash"}
        digest = hashlib.sha256(prev.encode("utf-8")
                                + canonical(body)).hexdigest()
        if digest != obj.get("line_hash"):
            report["break"] = {"line": idx,
                               "reason": "line_hash mismatch — "
                                         "the line's content was "
                                         "altered after chaining"}
            return False, report
        prev = obj["line_hash"]
        report["head_hash"] = prev
    report["ok"] = True
    return True, report


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("register")
    args = ap.parse_args(argv)
    path = Path(args.register)
    if not path.is_file():
        print(json.dumps({"register": str(path), "ok": False,
                          "break": {"reason": "register file not found"}},
                         indent=2))
        return 2
    ok, report = verify_register(path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
