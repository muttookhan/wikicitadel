#!/usr/bin/env python3
"""L0/L1/L2 tiered reading (Tier B: OpenViking idea only, re-implemented).

A reading mode beside the traverse door (scripts/wiki_traverse.py is NOT modified): L0 = id + title only, L1 = L0 + the summary (the `## Summary` section when present, else the first body paragraph), L2 = the full page.
Commands: read <page> --level 0|1|2. Page resolves by repo-relative path or file stem under wiki/. Stdlib only."""
import argparse, json, re, sys
from pathlib import Path
import re
def parse_fm(text):
    if not text.startswith("---"): return {}, text
    end=text.find("\n---",3)
    if end<0: return {}, text
    raw=text[3:end]; body=text[end+4:]
    fields={}
    for line in raw.splitlines():
        m=re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$",line)
        if not m: continue
        k,v=m.group(1),m.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            fields[k]=[x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.startswith("- "): fields[k]=[v[2:]]
        else: fields[k]=v.strip("'\"")
    # multiline list items
    cur=None
    for line in raw.splitlines():
        m=re.match(r"^\s+-\s+(.*)$",line)
        if m and cur:
            if not isinstance(fields.get(cur),list): fields[cur]=[]
            fields[cur].append(m.group(1).strip().strip("'\""))
        else:
            mm=re.match(r"^([A-Za-z_][\w-]*):",line)
            cur=mm.group(1) if mm else cur
    return fields, body

def resolve(root, name):
    root=Path(root); w=root/"wiki"
    cands=[root/name, w/name]
    for c in cands:
        if c.exists(): return c
    for p in sorted(w.rglob("*.md")):
        if p.stem==Path(name).stem: return p
    return None
def summary_of(body):
    m=re.search(r"^## Summary\s*$(.*?)(?=^## |\Z)", body, re.M|re.S)
    if m: return m.group(1).strip()
    for para in body.split("\n\n"):
        t=para.strip()
        if t and not t.startswith("#"): return t
    return ""
def read_tiered(root, name, level):
    p=resolve(root,name)
    if p is None: return {"error":f"page not found: {name}"}, 1
    text=p.read_text(encoding="utf-8",errors="replace"); fields,body=parse_fm(text)
    rel=p.relative_to(root).as_posix()
    out={"id":rel,"title":fields.get("title",p.stem),"level":level}
    if level>=1: out["summary"]=summary_of(body)
    if level>=2: out["text"]=text
    return out, 0
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent))
    sub=ap.add_subparsers(dest="cmd",required=True); r=sub.add_parser("read"); r.add_argument("page"); r.add_argument("--level",type=int,choices=[0,1,2],default=1)
    a=ap.parse_args(argv); res,code=read_tiered(a.root,a.page,a.level); print(json.dumps(res,indent=2)); return code
if __name__=="__main__": sys.exit(main())
