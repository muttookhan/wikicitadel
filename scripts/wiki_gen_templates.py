#!/usr/bin/env python3
"""Generation-template lister (Text Generator pattern, TA6).

Generation/prompt templates live as files under templates/generation/,
each with frontmatter: name, inputs (comma list), description.
Model-agnostic: no model names, no provider calls.
`list --root R` prints JSON; exit 1 if any template is malformed.
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

REQUIRED=("name","inputs","description")
def list_templates(root: Path):
    d=root/"templates"/"generation"; out=[]; errors=[]
    if not d.exists(): return out,[{"kind":"missing-dir","path":"templates/generation"}]
    for f in sorted(d.glob("*.md")):
        fm,_=parse_fm(f.read_text())
        missing=[k for k in REQUIRED if not fm.get(k)]
        if missing: errors.append({"kind":"missing-fields","path":f.relative_to(root).as_posix(),"missing":missing})
        else: out.append({"name":fm["name"],"inputs":[x.strip() for x in fm["inputs"].split(",") if x.strip()],"description":fm["description"],"path":f.relative_to(root).as_posix()})
    return out,errors
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); ns=a.parse_args(argv)
    out,err=list_templates(Path(ns.root)); print(json.dumps({"templates":out,"errors":err},indent=1)); return 1 if err else 0
if __name__=="__main__": sys.exit(main())
