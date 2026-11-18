#!/usr/bin/env python3
"""CRAG confidence gating (Marathon R3 TB6 row 1; CRAG pattern, idea only).

Scores retrieval confidence per query from passage overlap signals
and applies a stated fallback ladder: proceed (>= high) -> widen
(>= mid) -> re-query (>= low) -> abstain (below low). The live Ask
contract is another lane's; this is the scorer + gate library and
an eval-side CLI. No model calls. Stdlib only.
Exit: 0 proceed/widen, 2 re-query, 3 abstain (CLI, per last query).
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

HIGH, MID, LOW = 0.55, 0.35, 0.18
def score_query(query, passages):
    q=tset(query)
    if not q or not passages: return {"confidence":0.0,"top_overlap":0.0,"margin":0.0,"coverage":0.0,"n":len(passages or [])}
    ovs=sorted((len(q & tset(p))/len(q) for p in passages), reverse=True)
    top=ovs[0]; second=ovs[1] if len(ovs)>1 else 0.0
    cov=len(set().union(*[tset(p) for p in passages]) & q)/len(q) if passages else 0.0
    conf=round(0.6*top+0.25*cov+0.15*(top-second),4)
    return {"confidence":conf,"top_overlap":round(top,4),"margin":round(top-second,4),"coverage":round(cov,4),"n":len(passages)}
def gate(query, passages, high=HIGH, mid=MID, low=LOW):
    s=score_query(query, passages); c=s["confidence"]
    action = "proceed" if c>=high else "widen" if c>=mid else "re-query" if c>=low else "abstain"
    ladder=["widen the retrieval (more passages, facet-drop)","re-formulate the query from its content terms","abstain: state that the corpus does not cover this"]
    nxt = [] if action=="proceed" else ladder[["widen","re-query","abstain"].index(action):] if action in ("widen","re-query","abstain") else ladder
    return {"query":query, **s, "action":action, "fallback_ladder":nxt}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--cases",required=True)
    a=ap.parse_args(); worst=0
    for case in load_jsonl(a.cases):
        r=gate(case["query"], case.get("passages",[])); print(json.dumps(r))
        worst=max(worst, {"proceed":0,"widen":0,"re-query":2,"abstain":3}[r["action"]])
    return worst
if __name__=="__main__": sys.exit(main())
