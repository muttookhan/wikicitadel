#!/usr/bin/env python3
"""kenfold-pattern both-orders double judging merge gate (TB6 row 6).

A memory-merge proposal may pass ONLY when a judge approves it in
BOTH presentation orders (A/B and B/A); disagreement or any reject
refuses the merge. Judges are callables (interfaces); tests use fake
judges. No judge may be CERTIFIED here without owner-labelled data:
certify_judge() refuses when owner_labelled < required (standing
state: 0 owner-labelled, so certification is always refused today).
No model calls. Stdlib only. Exit (CLI demo with a fake judge): 0/1.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

def judge_both_orders(judge, proposal, existing):
    ab=judge({"candidate":proposal,"incumbent":existing,"order":"AB"})
    ba=judge({"candidate":existing,"incumbent":proposal,"order":"BA"})
    # In BA the roles swap: approval there means the incumbent wins,
    # i.e. the proposal does NOT win; normalise to proposal verdicts.
    prop_ab = (ab=="approve"); prop_ba = (ba=="reject")
    agree = prop_ab==prop_ba
    passed = agree and prop_ab
    return {"passed":passed,"agree":agree,"order_ab":ab,"order_ba":ba,
            "reason":"both orders approve the proposal" if passed else ("orders disagree: positional bias suspected, merge refused" if not agree else "judge does not approve the proposal")}
def certify_judge(owner_labelled, required=100):
    if owner_labelled < required:
        return {"certified":False,"reason":f"refused: {owner_labelled} owner-labelled examples < required {required}; machinery only, no certification claim"}
    return {"certified":True,"reason":"owner-labelled bar met (still requires TPR/TNR calibration by wiki_judge_calibrate)"}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--owner-labelled",type=int,default=0)
    a=ap.parse_args(); print(json.dumps(certify_judge(a.owner_labelled))); return 0 if a.owner_labelled>=100 else 1
if __name__=="__main__": sys.exit(main())
