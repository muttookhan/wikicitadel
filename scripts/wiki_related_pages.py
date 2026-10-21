#!/usr/bin/env python3
"""wiki_related_pages.py — Smart Connections pattern (restrictive licence, idea only, re-implemented): related-pages rail data.
Row TB4-10. Score: shared tags x3, link either way x2, shared content terms x0.1 (capped). Emits per-page lists for portal rail.
Usage: ... [--root DIR] [--top N] [--out FILE] Exit 0."""
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter
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

STOP=set("the a an and or of to in for on with is are be this that from by as at it its".split())
def terms(body): return Counter(w for w in re.findall(r"[a-z][a-z0-9-]{2,}",body.lower()) if w not in STOP)
def compute(root, top=5):
    pages=wiki_pages(root); out={}
    tmap={p["path"]:terms(p["body"]) for p in pages}
    for p in pages:
        scores=[]
        pt=set(p["fm"].get("tags") or []); pl=set(links_of(p["body"]))
        for q in pages:
            if q is p: continue
            s=0.0; why=[]
            shared=pt & set(q["fm"].get("tags") or [])
            if shared: s+=3*len(shared); why.append("tags:"+",".join(sorted(shared)))
            if q["stem"] in pl or p["stem"] in set(links_of(q["body"])): s+=2; why.append("linked")
            common=sum((tmap[p["path"]] & tmap[q["path"]]).values()); cs=min(common*0.1,2.0)
            if cs: s+=cs; why.append(f"terms:{common}")
            if s>0: scores.append({"page":q["path"],"score":round(s,3),"why":why})
        out[p["path"]]=sorted(scores,key=lambda x:(-x["score"],x["page"]))[:top]
    return {"kind":"related-pages","related":out}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--top",type=int,default=5); ap.add_argument("--out"); a=ap.parse_args(argv)
    d=compute(a.root,a.top); txt=json.dumps(d,indent=2)
    if a.out: Path(a.out).write_text(txt,encoding="utf-8")
    else: print(txt)
    return 0
if __name__=="__main__": sys.exit(main())
