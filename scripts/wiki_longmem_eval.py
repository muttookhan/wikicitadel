#!/usr/bin/env python3
"""LongMemEval five-ability eval template + runner (Marathon R3 TB6 row 3).

Case format (JSONL, NEW files beside the eval sets, never inside the
golden set): {id, ability, sessions:[{id, timestamp, turns:[str]}],
question, expected (string|null), fact_key (optional)}.
Abilities: extraction, multi-session, temporal, knowledge-update,
abstention. The runner decomposes sessions into timestamped turns,
retrieves lexically, and answers deterministically: knowledge-update
takes the LATEST matching turn, temporal the earliest/latest per the
question's cue, abstention expects no relevant turn. No model calls.
Exit: 0 template valid / run scored (scores printed as JSON).
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

ABILITIES=["extraction","multi-session","temporal","knowledge-update","abstention"]
def validate_case(case):
    errs=[]
    if case.get("ability") not in ABILITIES: errs.append("ability must be one of the five LongMemEval abilities")
    if not isinstance(case.get("sessions"), list) or not case["sessions"]: errs.append("sessions must be a non-empty list")
    for s in case.get("sessions",[]):
        if "timestamp" not in s or "turns" not in s: errs.append("each session needs timestamp + turns")
    if "question" not in case: errs.append("question required")
    if case.get("ability")=="abstention" and case.get("expected") is not None: errs.append("abstention cases must have expected=null")
    if case.get("ability")!="abstention" and not case.get("expected"): errs.append("non-abstention cases need an expected answer")
    return errs
def decompose(case):
    out=[]
    for s in case["sessions"]:
        for t in s["turns"]: out.append({"session":s["id"],"timestamp":s["timestamp"],"turn":t})
    return sorted(out, key=lambda x: x["timestamp"])
def run_case(case):
    turns=decompose(case); q=tset(case["question"])
    scored=sorted(((len(q & tset(t["turn"])), t) for t in turns), key=lambda x:-x[0])
    best=scored[0] if scored else (0,None)
    if case["ability"]=="abstention":
        ok = best[0]==0; return {"id":case.get("id"),"ability":case["ability"],"passed":ok,"answer":None,"reason":"no relevant turn" if ok else "relevant turn exists"}
    if best[0]==0: return {"id":case.get("id"),"ability":case["ability"],"passed":False,"answer":None,"reason":"no relevant turn found"}
    if case["ability"]=="knowledge-update":
        cand=[t for sc,t in scored if sc==best[0]]; chosen=max(cand, key=lambda t:t["timestamp"])
    elif case["ability"]=="temporal" and "first" in case["question"].lower():
        cand=[t for sc,t in scored if sc==best[0]]; chosen=min(cand, key=lambda t:t["timestamp"])
    else: chosen=best[1]
    exp=tset(case["expected"]); got=tset(chosen["turn"])
    passed = bool(exp) and len(exp & got)/len(exp) >= 0.5
    return {"id":case.get("id"),"ability":case["ability"],"passed":passed,"answer":chosen["turn"],"session":chosen["session"]}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--cases",required=True); ap.add_argument("--validate-only",action="store_true")
    a=ap.parse_args(); cases=load_jsonl(a.cases); bad=0
    for c in cases:
        e=validate_case(c)
        if e: print(json.dumps({"id":c.get("id"),"errors":e})); bad=1
    if a.validate_only or bad: return bad
    res=[run_case(c) for c in cases]
    by={}
    for r in res: by.setdefault(r["ability"],[]).append(r["passed"])
    print(json.dumps({"results":res,"by_ability":{k:{"passed":sum(v),"total":len(v)} for k,v in by.items()},"passed":sum(r["passed"] for r in res),"total":len(res)}, indent=1))
    return 0
if __name__=="__main__": sys.exit(main())
