#!/usr/bin/env python3
"""wiki_current_understanding.py — Honcho pattern (AGPL, idea only, re-implemented): per-entity current-understanding docs.
Row TB4-7. Deterministic extractive, NO model calls: frontmatter status/confidence + bullet claims from the entity page.
Output dir default wiki/understanding/. Usage: ... [--root DIR] [--outdir DIR] Exit 0."""
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

def generate(root, outdir=None):
    root=Path(root); outdir=Path(outdir) if outdir else root/"wiki/understanding"; docs=[]
    for p in wiki_pages(root):
        if p["fm"].get("type")!="entity" and "/entities/" not in p["path"]: continue
        claims=[l.strip()[2:].strip() for l in p["body"].splitlines() if l.strip().startswith("- ")]
        doc={"entity":p["fm"].get("title",p["stem"]),"source_page":p["path"],"status":p["fm"].get("status","not recorded"),"confidence":p["fm"].get("confidence","not recorded"),"updated":p["fm"].get("updated","not recorded"),"claims":claims}
        outdir.mkdir(parents=True,exist_ok=True)
        f=outdir/(p["stem"]+".md")
        lines=[f"# Current understanding — {doc['entity']}","",f"Source: [[{p['stem']}]] · status: {doc['status']} · confidence: {doc['confidence']} · updated: {doc['updated']}","","## Current claims"]+[f"- {c}" for c in claims]+["","_Deterministic extractive summary; no model calls._"]
        f.write_text("\n".join(lines)+"\n",encoding="utf-8"); docs.append(doc)
    return docs
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--outdir"); a=ap.parse_args(argv)
    docs=generate(a.root,a.outdir); print(json.dumps({"generated":len(docs),"entities":[d["entity"] for d in docs]},indent=2)); return 0
if __name__=="__main__": sys.exit(main())
