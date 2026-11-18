#!/usr/bin/env python3
"""wiki_alias_register.py — Morphik pattern (BSL, idea only, re-implemented): entity-alias register.
Row TB4-2. Register JSON: {"version":1,"aliases":{canonical:[alias,...]}}. Resolver + collision checker.
Usage: python3 scripts/wiki_alias_register.py [--root DIR] (init|check|resolve TERM) [--register FILE]
Exit: 0 ok, 1 collision/not-found, 2 usage."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
SCAFFOLD={"version":1,"aliases":{}}
def load_register(path):
    p=Path(path)
    if not p.exists(): return dict(SCAFFOLD)
    d=json.loads(p.read_text(encoding="utf-8"))
    if d.get("version")!=1 or not isinstance(d.get("aliases"),dict): raise ValueError("bad register format")
    return d
def resolve(term, reg):
    t=term.strip().lower()
    for canon, aliases in reg["aliases"].items():
        if canon.lower()==t: return canon
        if any(a.lower()==t for a in aliases): return canon
    return None
def collisions(reg):
    seen={}; out=[]
    for canon, aliases in reg["aliases"].items():
        for a in list(aliases)+[canon]:
            k=a.lower()
            if k in seen and seen[k]!=canon: out.append({"alias":a,"entities":sorted([seen[k],canon])})
            else: seen[k]=canon
        if len(aliases)!=len(set(x.lower() for x in aliases)): out.append({"alias":canon,"entities":[canon],"problem":"duplicate alias within entity"})
    return out
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--register"); ap.add_argument("cmd",choices=["init","check","resolve"]); ap.add_argument("term",nargs="?"); a=ap.parse_args(argv)
    regpath=Path(a.register) if a.register else Path(a.root)/"evaluation/entity-aliases.json"
    if a.cmd=="init":
        if not regpath.exists(): regpath.parent.mkdir(parents=True,exist_ok=True); regpath.write_text(json.dumps(SCAFFOLD,indent=2),encoding="utf-8")
        print(json.dumps({"register":str(regpath),"created":True})); return 0
    reg=load_register(regpath)
    if a.cmd=="check":
        c=collisions(reg); print(json.dumps({"collisions":c},indent=2)); return 1 if c else 0
    if not a.term: return 2
    r=resolve(a.term,reg); print(json.dumps({"term":a.term,"canonical":r})); return 0 if r else 1
if __name__=="__main__": sys.exit(main())
