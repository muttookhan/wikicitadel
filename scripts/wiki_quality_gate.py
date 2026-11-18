#!/usr/bin/env python3
"""Ragas/UpTrain-style standing quality gates (Marathon R3 TB6 row 4).

Computes DETERMINISTIC PROXY metrics over eval outputs — labelled
as proxies, never as model judgements: faithfulness proxy = answer
content-token overlap with its cited evidence; answer-relevance
proxy = answer/question content-token overlap. A run FAILS (exit 1)
when any mean metric is below its threshold. Refuses to certify a
run as passing on zero cases. No model calls. Stdlib only.
Input JSONL: {id, question, answer, evidence}.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

DEFAULTS={"faithfulness":0.5,"relevance":0.25}
def faithfulness_proxy(answer, evidence):
    a=tset(answer); return 0.0 if not a else round(len(a & tset(evidence))/len(a),4)
def relevance_proxy(question, answer):
    q=tset(question); return 0.0 if not q else round(len(q & tset(answer))/len(q),4)
def run(rows, thresholds=None):
    th={**DEFAULTS, **(thresholds or {})}
    if not rows: return {"status":"refused","reason":"no cases: a quality gate cannot certify an empty run","cases":0}
    per=[{"id":r.get("id"),"faithfulness":faithfulness_proxy(r["answer"], r.get("evidence","")),"relevance":relevance_proxy(r["question"], r["answer"])} for r in rows]
    means={m: round(sum(p[m] for p in per)/len(per),4) for m in ("faithfulness","relevance")}
    failed=[m for m in means if means[m] < th[m]]
    return {"status":"fail" if failed else "pass","metrics_are":"deterministic proxies (labelled, not model judgements)","means":means,"thresholds":th,"failed_metrics":failed,"per_case":per,"cases":len(rows)}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--outputs",required=True); ap.add_argument("--faithfulness",type=float); ap.add_argument("--relevance",type=float)
    a=ap.parse_args(); th={k:v for k,v in (("faithfulness",a.faithfulness),("relevance",a.relevance)) if v is not None}
    rep=run(load_jsonl(a.outputs), th); print(json.dumps(rep, indent=1)); return 0 if rep["status"]=="pass" else 1
if __name__=="__main__": sys.exit(main())
