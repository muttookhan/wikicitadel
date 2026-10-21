#!/usr/bin/env python3
"""wiki_section_owners.py — Emmimal pattern (MIT idea, re-implemented): section-ownership compiler/checker.
Row TB4-5. Pages declare owners in frontmatter section_owners: {Section: owner} or inline <!-- section-owner: X --> after a heading.
Reports unowned and multiply-owned sections. Usage: ... [--root DIR] Exit: 0 clean, 1 problems."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

import re
FM_RE=re.compile(r"^---\n(.*?)\n---\n?",re.S)
def parse_fm(text):
    m=FM_RE.match(text); fm={}; body=text
    if m:
        body=text[m.end():]
        cur=None
        for line in m.group(1).splitlines():
            mm=re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$",line)
            if mm:
                cur=mm.group(1); v=mm.group(2).strip()
                if v.startswith("[") and v.endswith("]"):
                    fm[cur]=[x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                elif v in ("","|",">"): fm[cur]=[]
                else: fm[cur]=v.strip("'\"")
            elif line.strip().startswith("- ") and cur:
                if not isinstance(fm.get(cur),list): fm[cur]=[]
                fm[cur].append(line.strip()[2:].strip().strip("'\""))
            elif ":" in line and cur and isinstance(fm.get(cur),dict):
                k,v=line.strip().split(":",1); fm[cur][k.strip()]=v.strip().strip("'\"")
            elif line.startswith("  ") and cur:
                # section_owners style nested mapping
                s=line.strip()
                if ":" in s:
                    if not isinstance(fm.get(cur),dict): fm[cur]={}
                    k,v=s.split(":",1); fm[cur][k.strip().strip("'\"")]=v.strip().strip("'\"")
    return fm,body
def wiki_pages(root):
    w=Path(root)/"wiki"; out=[]
    if not w.exists(): return out
    for p in sorted(w.rglob("*.md")):
        t=p.read_text(encoding="utf-8",errors="replace"); fm,body=parse_fm(t)
        out.append({"path":str(p.relative_to(Path(root))), "stem":p.stem, "fm":fm, "body":body, "text":t})
    return out
def links_of(body):
    return sorted(set(re.findall(r"\[\[([^\]|#]+)",body)))

def sections(body):
    out=[]; cur=None
    for line in body.splitlines():
        mm=re.match(r"^##\s+(.+?)\s*$",line)
        if mm: cur={"title":mm.group(1).strip(),"owners":[]}; out.append(cur); continue
        om=re.search(r"<!--\s*section-owner:\s*([^>]+?)\s*-->",line)
        if om and cur is not None: cur["owners"].append(om.group(1).strip())
    return out
def check(root):
    problems=[]; checked=0
    for p in wiki_pages(root):
        declared=p["fm"].get("section_owners")
        secs=sections(p["body"])
        if not secs: continue
        if isinstance(declared,dict):
            checked+=1
            for s in secs:
                owners=[]
                if s["title"] in declared: owners.append(declared[s["title"]])
                owners+=s["owners"]
                if not owners: problems.append({"page":p["path"],"section":s["title"],"problem":"unowned"})
                elif len(set(owners))>1: problems.append({"page":p["path"],"section":s["title"],"problem":"multiply-owned","owners":sorted(set(owners))})
        elif any(s["owners"] for s in secs):
            checked+=1
            for s in secs:
                if not s["owners"]: problems.append({"page":p["path"],"section":s["title"],"problem":"unowned"})
                elif len(set(s["owners"]))>1: problems.append({"page":p["path"],"section":s["title"],"problem":"multiply-owned","owners":sorted(set(s["owners"]))})
    return {"kind":"section-owners","pages_checked":checked,"problems":problems}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); a=ap.parse_args(argv)
    d=check(a.root); print(json.dumps(d,indent=2)); return 1 if d["problems"] else 0
if __name__=="__main__": sys.exit(main())
