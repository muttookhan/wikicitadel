#!/usr/bin/env python3
"""wiki_importance.py — ByteRover pattern (idea only, re-implemented): per-page importance with decay.
Row TB4-3. Score artefact ONLY (no ranker change): inbound links + recency + owner attestation, decayed by age.
score = (0.6*inbound_norm + 0.25*attested + 0.15*fresh) * exp(-age_days/365)
Usage: python3 scripts/wiki_importance.py [--root DIR] [--as-of YYYY-MM-DD] [--out FILE]
Exit: 0 ok."""
from __future__ import annotations
import argparse, json, math, sys
from datetime import date
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

def _d(s):
    try: return date.fromisoformat(str(s)[:10])
    except Exception: return None
def compute(root, as_of=None):
    as_of=as_of or date.today(); pages=wiki_pages(root)
    inbound={p["stem"]:0 for p in pages}
    for p in pages:
        for t in links_of(p["body"]):
            if t in inbound: inbound[t]+=1
    mx=max(inbound.values(),default=0) or 1
    rows=[]
    for p in pages:
        upd=_d(p["fm"].get("updated") or p["fm"].get("created") or "")
        age=(as_of-upd).days if upd else 365
        age=max(age,0); decay=math.exp(-age/365.0)
        attested=1.0 if str(p["fm"].get("status","")).lower() in ("verified","attested") or str(p["fm"].get("attested","")).lower()=="true" else 0.0
        fresh=1.0/(1+age/30.0)
        base=0.6*(inbound[p["stem"]]/mx)+0.25*attested+0.15*fresh
        rows.append({"page":p["path"],"inbound":inbound[p["stem"]],"age_days":age,"attested":bool(attested),"decay":round(decay,6),"score":round(base*decay,6)})
    return {"kind":"page-importance","as_of":as_of.isoformat(),"rows":sorted(rows,key=lambda r:(-r["score"],r["page"]))}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--as-of"); ap.add_argument("--out"); a=ap.parse_args(argv)
    asof=date.fromisoformat(a.as_of) if a.as_of else None; data=compute(a.root,asof); txt=json.dumps(data,indent=2)
    if a.out: Path(a.out).write_text(txt,encoding="utf-8")
    else: print(txt)
    return 0
if __name__=="__main__": sys.exit(main())
