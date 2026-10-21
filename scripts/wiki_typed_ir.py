#!/usr/bin/env python3
"""wiki_typed_ir.py — scraps pattern (MIT, re-implemented): cached typed IR of pages.
Row TB4-6. Blocks typed heading/paragraph/list/code/callout/wikilink; cache JSON with source sha256; stale if hash differs.
Usage: python3 scripts/wiki_typed_ir.py [--root DIR] (build|check) [--cache FILE] Exit: build 0, check 0 fresh / 1 stale."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
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

def blocks(body):
    out=[]; in_code=False; buf=[]
    def flush():
        if buf: out.append({"type":"paragraph","text":" ".join(buf)}); buf.clear()
    for line in body.splitlines():
        if line.strip().startswith("```"):
            flush(); in_code=not in_code; 
            if in_code: buf_code=[]
            continue
        if in_code: continue
        hm=re.match(r"^(#{1,6})\s+(.*)",line)
        if hm: flush(); out.append({"type":"heading","level":len(hm.group(1)),"text":hm.group(2).strip()}); continue
        if line.strip().startswith("- ") or re.match(r"^\d+\. ",line.strip()): flush(); out.append({"type":"list_item","text":line.strip().lstrip("-0123456789. ").strip()}); continue
        if line.strip().startswith("> [!"): flush(); out.append({"type":"callout","text":line.strip()}); continue
        for wl in re.findall(r"\[\[([^\]]+)\]\]",line): out.append({"type":"wikilink","target":wl})
        if line.strip(): buf.append(line.strip())
        else: flush()
    flush(); return out
def build(root):
    entries=[]
    for p in wiki_pages(root):
        entries.append({"page":p["path"],"sha256":hashlib.sha256(p["text"].encode()).hexdigest(),"blocks":blocks(p["body"])})
    return {"kind":"typed-ir","version":1,"pages":entries}
def stale(root, cache):
    if not Path(cache).exists(): return [p["path"] for p in wiki_pages(root)]
    data=json.loads(Path(cache).read_text(encoding="utf-8")); old={e["page"]:e["sha256"] for e in data.get("pages",[])}
    return [p["path"] for p in wiki_pages(root) if old.get(p["path"])!=hashlib.sha256(p["text"].encode()).hexdigest()]
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--cache"); ap.add_argument("cmd",choices=["build","check"]); a=ap.parse_args(argv)
    cache=Path(a.cache) if a.cache else Path(a.root)/"evaluation/typed-ir.json"
    if a.cmd=="build": cache.parent.mkdir(parents=True,exist_ok=True); cache.write_text(json.dumps(build(a.root),indent=2),encoding="utf-8"); print(json.dumps({"cache":str(cache),"pages":len(build(a.root)["pages"])})); return 0
    s=stale(a.root,cache); print(json.dumps({"stale":s})); return 1 if s else 0
if __name__=="__main__": sys.exit(main())
