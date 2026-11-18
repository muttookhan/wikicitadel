#!/usr/bin/env python3
"""MiniCheck-class small claim checker (Marathon R3 TB6 row 2; idea only).

Claim-vs-evidence checker interface sized for a small local model.
Ships a deterministic lexical fallback (token-overlap entailment
heuristic) HONESTLY LABELLED as the fallback. The small-model slot
is an interface only and is never wired to any provider: calling it
raises NotWired. No model calls anywhere. Stdlib only.
Exit: 0 all claims supported, 1 any unsupported/uncertain.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

class NotWired(RuntimeError): pass
class ClaimChecker:
    """Interface: check(claim, evidence) -> {verdict, score, method}."""
    method="interface"
    def check(self, claim, evidence): raise NotImplementedError
class LexicalFallbackChecker(ClaimChecker):
    method="lexical-fallback (token-overlap heuristic; NOT a model)"
    def __init__(self, support=0.6, uncertain=0.3): self.support, self.uncertain = support, uncertain
    def check(self, claim, evidence):
        c=tset(claim); e=tset(evidence)
        if not c: return {"verdict":"uncertain","score":0.0,"method":self.method}
        # negation guard: a negated evidence sentence cannot support a positive claim
        neg = bool(re.search(r"\b(not|no|never|n't)\b", (evidence or "").lower()))
        score=len(c & e)/len(c)
        if neg and score>=self.support: verdict="unsupported"
        elif score>=self.support: verdict="supported"
        elif score>=self.uncertain: verdict="uncertain"
        else: verdict="unsupported"
        return {"verdict":verdict,"score":round(score,4),"method":self.method}
class SmallModelCheckerSlot(ClaimChecker):
    method="small-model-slot (unwired)"
    def check(self, claim, evidence):
        raise NotWired("small-model checker slot is an interface only; no provider is wired and none may be added by this module")
def get_checker(name="lexical"):
    return {"lexical":LexicalFallbackChecker, "small-model":SmallModelCheckerSlot}[name]()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--cases",required=True); ap.add_argument("--checker",default="lexical")
    a=ap.parse_args(); chk=get_checker(a.checker); bad=0
    for case in load_jsonl(a.cases):
        r=chk.check(case["claim"], case["evidence"]); print(json.dumps({"id":case.get("id"), **r}))
        bad |= (r["verdict"]!="supported")
    return 1 if bad else 0
if __name__=="__main__": sys.exit(main())
