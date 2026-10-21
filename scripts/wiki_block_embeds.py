#!/usr/bin/env python3
"""wiki_block_embeds.py — Foam/SiYuan patterns (MIT/idea, re-implemented): block IDs + section embeds.
Row TB4-8. Headings may carry {#block-id}; embeds ![[page#Section]] or ![[page#block-id]] resolve at render time.
Usage: python3 scripts/wiki_block_embeds.py [--root DIR] (check|render FILE) Exit: 0 ok, 1 problems."""
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

EMBED_RE=re.compile(r"!\[\[([^\]#]+)#([^\]]+)\]\]")
def sections_of(body):
    secs={}; cur=None; buf=[]
    def save():
        if cur is not None: secs[cur]="\n".join(buf).strip()
    for line in body.splitlines():
        hm=re.match(r"^##\s+(.+?)\s*(?:\{#([A-Za-z0-9_-]+)\})?\s*$",line)
        if hm: save(); cur=hm.group(1).strip(); buf=[]; 
            # also register block id alias
        if hm and hm.group(2): secs["#"+hm.group(2)]=""; pending=(hm.group(2),hm.group(1))
        if not hm and cur is not None: buf.append(line)
        if hm: pass
    save()
    # second pass for block ids: map id -> its section text
    cur=None; buf=[]; mapping={}
    for line in body.splitlines():
        hm=re.match(r"^##\s+(.+?)\s*(?:\{#([A-Za-z0-9_-]+)\})?\s*$",line)
        if hm:
            if cur: mapping[cur]="\n".join(buf).strip()
            cur=hm.group(2) or hm.group(1).strip(); buf=[]
            if hm.group(2): mapping.setdefault(hm.group(1).strip(),"")
        elif cur is not None: buf.append(line)
    if cur: mapping[cur]="\n".join(buf).strip()
    # merge: title keys from first pass take precedence for text
    for k,v in secs.items():
        if k not in mapping or not mapping[k]: mapping[k]=v
    return mapping
def collect(root):
    pages={}; ids={}; problems=[]
    for p in wiki_pages(root):
        pages[p["stem"]]=sections_of(p["body"]); pages[p["path"]]=pages[p["stem"]]
        for line in p["body"].splitlines():
            for bid in re.findall(r"\{#([A-Za-z0-9_-]+)\}",line):
                if bid in ids: problems.append({"problem":"duplicate block id","id":bid,"pages":[ids[bid],p["path"]]})
                ids[bid]=p["path"]
    return pages,problems
def render(text, pages):
    missing=[]
    def repl(mo):
        pg,sec=mo.group(1).strip(),mo.group(2).strip()
        secs=pages.get(pg) or pages.get(Path(pg).stem)
        if not secs or sec not in secs: missing.append(mo.group(0)); return mo.group(0)
        return secs[sec]
    return EMBED_RE.sub(repl,text),missing
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("cmd",choices=["check","render"]); ap.add_argument("file",nargs="?"); a=ap.parse_args(argv)
    pages,problems=collect(a.root)
    if a.cmd=="check":
        for p in wiki_pages(a.root):
            _,miss=render(p["body"],pages)
            for x in miss: problems.append({"problem":"unresolved embed","embed":x,"page":p["path"]})
        print(json.dumps({"problems":problems},indent=2)); return 1 if problems else 0
    txt=Path(a.file).read_text(encoding="utf-8"); out,miss=render(txt,pages); print(out); return 1 if miss else 0
if __name__=="__main__": sys.exit(main())
