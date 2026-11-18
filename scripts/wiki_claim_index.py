#!/usr/bin/env python3
"""Claim-level append-only index with temporal multi-signal fusion (Tier B: Mem0 pattern — design re-implemented; Mem0 OSS is Apache-2.0 per the europe harvest, but no foreign code is copied).

Index: evaluation/claim-index.jsonl, APPEND-ONLY (build appends one record per claim page per run; it never rewrites the file). Record: claim_id (page path), text, stated (as_of), supports/contradicts (outcomes), verified_n (reverify events), superseded (outcome_status retired or status superseded), hash of text.
Fusion ranker: score = 0.45*verification + 0.35*recency + 0.20*support_ratio, superseded claims scored 0. Recency decays with age in days from `stated` to --as-of (default today): recency = 1/(1+age/365).
Commands: build, query --text, check. Stdlib only."""
import argparse, hashlib, json, sys
from datetime import date
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

def _jsonl(p):
    p=Path(p)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
def claim_pages(root):
    w=Path(root)/"wiki"; out=[]
    if w.exists():
        for p in sorted(w.rglob("*.md")):
            f,_=parse_fm(p.read_text(encoding="utf-8",errors="replace"))
            if f.get("claim"): out.append((p,f))
    return out
def build(root, as_of=None):
    root=Path(root); outcomes=_jsonl(root/"evaluation"/"outcomes.jsonl"); rev=_jsonl(root/"evaluation"/"reverify-history.jsonl")
    idx=root/"evaluation"/"claim-index.jsonl"; idx.parent.mkdir(parents=True,exist_ok=True); added=0
    with idx.open("a",encoding="utf-8") as fh:
        for p,f in claim_pages(root):
            rel=p.relative_to(root).as_posix()
            oc=[o for o in outcomes if o.get("claim")==rel or o.get("page")==rel]
            rec={"claim_id":rel,"text":f.get("claim",""),"stated":str(f.get("as_of","")),"supports":sum(1 for o in oc if o.get("outcome")=="supports"),"contradicts":sum(1 for o in oc if o.get("outcome")=="contradicts"),"verified_n":sum(1 for r in rev if r.get("claim")==rel or r.get("page")==rel),"superseded":(f.get("outcome_status")=="retired" or f.get("status")=="superseded"),"indexed_on":str(as_of or date.today())}
            rec["hash"]=hashlib.sha256(rec["text"].encode()).hexdigest()[:16]
            fh.write(json.dumps(rec)+"\n"); added+=1
    return {"appended":added},0
def latest(root):
    seen={}
    for r in _jsonl(Path(root)/"evaluation"/"claim-index.jsonl"): seen[r["claim_id"]]=r
    return list(seen.values())
def fusion_score(rec, as_of):
    if rec.get("superseded"): return 0.0
    try: stated=date.fromisoformat(str(rec.get("stated"))[:10]); age=max(0,(as_of-stated).days)
    except Exception: age=365
    recency=1.0/(1.0+age/365.0)
    total=rec.get("supports",0)+rec.get("contradicts",0)
    support=(rec.get("supports",0)/total) if total else 0.5
    verification=min(1.0,(total+rec.get("verified_n",0))/3.0)
    return round(0.45*verification+0.35*recency+0.20*support,6)
def query(root, text, as_of=None):
    as_of=as_of or date.today(); words={w.lower() for w in text.split() if len(w)>2}
    out=[]
    for r in latest(root):
        if words and not (words & {w.lower().strip(".,") for w in r.get("text","").split()}): continue
        out.append({**r,"score":fusion_score(r,as_of)})
    out.sort(key=lambda x:-x["score"]); return {"results":out},0
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--as-of",default=None)
    sub=ap.add_subparsers(dest="cmd",required=True); sub.add_parser("build"); sub.add_parser("check")
    q=sub.add_parser("query"); q.add_argument("--text",default="")
    a=ap.parse_args(argv); ao=date.fromisoformat(a.as_of) if a.as_of else None
    if a.cmd=="build": res,code=build(a.root,ao)
    elif a.cmd=="check": res,code={"records":len(_jsonl(Path(a.root)/"evaluation"/"claim-index.jsonl")),"claims":len(latest(a.root))},0
    else: res,code=query(a.root,a.text,ao)
    print(json.dumps(res,indent=2)); return code
if __name__=="__main__": sys.exit(main())
