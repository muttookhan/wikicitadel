#!/usr/bin/env python3
"""wiki_feedback_triage.py — PLUR pattern (Apache per PyPI, re-implemented): Ask/portal feedback loop.
Row TB4-11. Structured feedback records (JSONL) + periodic triage report. Fixtures only; NO live Ask wiring.
Record: {id, ts, source: ask|portal, page, kind: thumbs_up|thumbs_down|correction, text}
Usage: ... (validate FILE | triage FILE) Exit: 0 ok, 1 invalid."""
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path
KINDS=('thumbs_up', 'thumbs_down', 'correction'); SOURCES=('ask', 'portal')
def validate(rec):
    errs=[]
    for k in ("id","ts","source","page","kind"): 
        if k not in rec: errs.append(f"missing {k}")
    if rec.get("kind") not in KINDS: errs.append("bad kind")
    if rec.get("source") not in SOURCES: errs.append("bad source")
    if rec.get("kind")=="correction" and not rec.get("text"): errs.append("correction needs text")
    return errs
def load(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
def triage(records):
    by_page=defaultdict(Counter); corr=[]
    for r in records:
        by_page[r["page"]][r["kind"]]+=1
        if r["kind"]=="correction": corr.append({"page":r["page"],"text":r.get("text",""),"ts":r["ts"],"id":r["id"]})
    pages=[{"page":p,"counts":dict(c),"net":c["thumbs_up"]-c["thumbs_down"],"needs_attention":c["thumbs_down"]>c["thumbs_up"] or c["correction"]>0} for p,c in sorted(by_page.items())]
    return {"kind":"feedback-triage","total":len(records),"pages":pages,"corrections":corr}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("cmd",choices=["validate","triage"]); ap.add_argument("file"); a=ap.parse_args(argv)
    recs=load(a.file)
    if a.cmd=="validate":
        bad=[{"id":r.get("id"),"errors":validate(r)} for r in recs if validate(r)]; print(json.dumps({"invalid":bad},indent=2)); return 1 if bad else 0
    print(json.dumps(triage(recs),indent=2)); return 0
if __name__=="__main__": sys.exit(main())
