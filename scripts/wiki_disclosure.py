#!/usr/bin/env python3
"""AI-disclosure checker for autonomous writers (JP-R2, TA6).

Stated rule: a page is machine-written when frontmatter carries
autonomous: true or author_type: agent. Such a page is labelled only
when BOTH hold: frontmatter ai_disclosure: true AND a rendered line in
the body beginning '> AI disclosure:'. `check --root R` prints JSON of
unlabelled machine-written pages; exit 1 if any.
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

def is_machine(fm): return fm.get("autonomous")=="true" or fm.get("author_type")=="agent"
def check(root: Path):
    out=[]
    for f in sorted((root/"wiki").rglob("*.md")):
        fm,body=parse_fm(f.read_text())
        if not is_machine(fm): continue
        labelled = fm.get("ai_disclosure")=="true" and any(l.strip().startswith("> AI disclosure:") for l in body.splitlines())
        if not labelled: out.append({"path":f.relative_to(root).as_posix(),"title":fm.get("title")})
    return out
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); ns=a.parse_args(argv)
    o=check(Path(ns.root)); print(json.dumps({"unlabelled":o,"count":len(o)},indent=1)); return 1 if o else 0
if __name__=="__main__": sys.exit(main())
