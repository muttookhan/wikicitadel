#!/usr/bin/env python3
"""Naming-lock checker (Cablate Tier A half ONLY, TA6).

The atom layer itself is Tier C and is NOT built here. This half is the
naming lock: page stems listed in the register
(default wiki/rules/naming-lock.json) may not be renamed or removed
unless a rename is recorded in the ledger beside it
(wiki/rules/naming-lock-ledger.jsonl, one JSON object per line with
old_stem, new_stem). `check --root R [--register P]` prints JSON;
exit 1 when a locked stem is missing with no ledger entry, or a stem
is duplicated across the wiki.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path
def check(root: Path, register=None):
    reg=Path(register) if register else root/"wiki"/"rules"/"naming-lock.json"
    if not reg.exists(): return [{"kind":"no-register","path":str(reg)}]
    locked=json.loads(reg.read_text()).get("locked",[])
    ledger=reg.parent/"naming-lock-ledger.jsonl"; renamed=set()
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if line.strip():
                try: renamed.add(json.loads(line).get("old_stem"))
                except json.JSONDecodeError: pass
    stems=Counter(f.stem for f in (root/"wiki").rglob("*.md"))
    findings=[]
    for e in locked:
        stem=e["stem"] if isinstance(e,dict) else e
        if stems.get(stem,0)==0 and stem not in renamed:
            findings.append({"kind":"locked-stem-missing","stem":stem})
    locked_stems={e["stem"] if isinstance(e,dict) else e for e in locked}
    for stem,n in stems.items():
        if n>1 and stem in locked_stems: findings.append({"kind":"duplicate-stem","stem":stem,"count":n})
    return findings
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); a.add_argument("--register"); ns=a.parse_args(argv)
    f=check(Path(ns.root),ns.register); print(json.dumps({"findings":f,"count":len(f)},indent=1)); return 1 if f else 0
if __name__=="__main__": sys.exit(main())
