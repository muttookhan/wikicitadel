#!/usr/bin/env python3
"""ARK ?info lookup (TA6). `info --root R --id <stem-or-path>[?info]`
returns the inflection record as JSON: {id, path, title, created,
successor}. Successor is read from frontmatter replaced_by /
is-superseded-by when present. Exit 2 when the id resolves to nothing,
3 when it is ambiguous.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def parse_fm(text):
    if not text.startswith("---"): return {}, text
    end=text.find("\n---",3)
    if end<0: return {}, text
    fm={}; 
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ","-")):
            k,v=line.split(":",1); fm[k.strip()]=v.strip().strip('"').strip("'")
    return fm, text[end+4:]

def lookup(root: Path, ident: str):
    ident=ident.removesuffix("?info").strip()
    stem=Path(ident).stem; cands=[]
    for f in sorted((root/"wiki").rglob("*.md")):
        if f.stem==stem or f.relative_to(root).as_posix()==ident: cands.append(f)
    if not cands: return None,"not-found"
    if len(cands)>1: return {"candidates":[c.relative_to(root).as_posix() for c in cands]},"ambiguous"
    f=cands[0]; fm,_=parse_fm(f.read_text())
    succ=fm.get("replaced_by") or fm.get("is-superseded-by") or None
    return {"id":stem,"path":f.relative_to(root).as_posix(),"title":fm.get("title"),
            "created":fm.get("created"),"type":fm.get("type"),"successor":succ},"ok"
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); a.add_argument("--id",required=True); ns=a.parse_args(argv)
    rec,st=lookup(Path(ns.root),ns.id); print(json.dumps(rec,indent=1))
    return 0 if st=="ok" else (3 if st=="ambiguous" else 2)
if __name__=="__main__": sys.exit(main())
