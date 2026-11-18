#!/usr/bin/env python3
"""wiki_relation_maps.py — Trilium pattern (AGPL, idea only, re-implemented): relation-map views + hoisting report.
Row TB4-1. Emits JSON: typed edges as navigable map + pages whose linked/directory subtree could be hoisted.
Usage: python3 scripts/wiki_relation_maps.py [--root DIR] [--out FILE]
Exit: 0 ok, 2 usage."""
from __future__ import annotations
import argparse, json, sys
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

def build(root):
    pages=wiki_pages(root); by_stem={p["stem"]:p for p in pages}
    edges=[]; children={}
    for p in pages:
        for tgt in links_of(p["body"]):
            kind="wikilink"
            edges.append({"source":p["path"],"target":tgt,"type":kind})
            if tgt in by_stem: children.setdefault(p["path"],[]).append(by_stem[tgt]["path"])
        rels=p["fm"].get("links")
        if isinstance(rels,list):
            for r in rels:
                if isinstance(r,str) and ":" in r:
                    k,t=r.split(":",1); edges.append({"source":p["path"],"target":t.strip(),"type":k.strip()})
    hoist=[]
    for p in pages:
        kids=sorted(set(children.get(p["path"],[])))
        # directory subtree: pages in a subdir named after stem
        sub=[q["path"] for q in pages if q["path"].startswith(p["path"][:-3]+"/")]
        cand=sorted(set(kids+sub))
        if len(cand)>=3:
            hoist.append({"page":p["path"],"child_count":len(cand),"children":cand,"suggestion":"hoist subtree into a section view headed by this page"})
    types=sorted(set(e["type"] for e in edges))
    return {"kind":"relation-maps","edge_types":types,"nodes":[p["path"] for p in pages],"edges":sorted(edges,key=lambda e:(e["source"],e["target"],e["type"])),"relation_maps":{t:[e for e in edges if e["type"]==t] for t in types},"hoisting":hoist}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--out"); a=ap.parse_args(argv)
    data=build(a.root); txt=json.dumps(data,indent=2,sort_keys=True)
    if a.out: Path(a.out).write_text(txt,encoding="utf-8")
    else: print(txt)
    return 0
if __name__=="__main__": sys.exit(main())
