#!/usr/bin/env python3
"""Groundedness gate — delivery-side (Tier B: Upstage pattern, idea only, re-implemented; the academic CRAG form is another lane's row).

An OPTIONAL gate for the Ask machinery: it scores an answer's claims against its evidence pack and BLOCKS delivery when groundedness is below threshold, returning a correction request the caller loops back with. It is NOT wired into the standing answer contract: GATE_ENABLED_DEFAULT is False and answer_contract.py is unmodified — a caller opts in explicitly by calling evaluate(..., enabled=True) or constructing Gate(threshold=..., enabled=True).

Scoring (deterministic, stdlib): the answer is split into claim sentences; a claim is grounded when its content-token overlap with the union of evidence passages is >= CLAIM_OVERLAP (0.34). Groundedness = grounded claims / total claims (an answer with no claims scores 0.0 and blocks). Default threshold 0.60.
"""
import re
STOP=set("the a an is are was were be been of to in on for and or it its this that with as at by from".split())
GATE_ENABLED_DEFAULT=False
DEFAULT_THRESHOLD=0.60
CLAIM_OVERLAP=0.34
def _tokens(text): return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w)>2}
def split_claims(answer):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if len(s.strip())>10]
def score_answer(answer, evidence):
    claims=split_claims(answer); ev=_tokens(" ".join(evidence or []))
    per=[]
    for c in claims:
        toks=_tokens(c); ov=(len(toks & ev)/len(toks)) if toks else 0.0
        per.append({"claim":c,"overlap":round(ov,4),"grounded":ov>=CLAIM_OVERLAP})
    score=(sum(1 for p in per if p["grounded"])/len(per)) if per else 0.0
    return round(score,6), per
class Gate:
    def __init__(self, threshold=DEFAULT_THRESHOLD, enabled=GATE_ENABLED_DEFAULT):
        self.threshold=threshold; self.enabled=enabled
    def evaluate(self, answer, evidence):
        if not self.enabled:
            return {"enabled":False,"verdict":"pass","reason":"gate disabled (default off in the standing contract)","score":None}
        score,per=score_answer(answer,evidence)
        if score>=self.threshold:
            return {"enabled":True,"verdict":"pass","score":score,"claims":per}
        ungrounded=[p["claim"] for p in per if not p["grounded"]]
        return {"enabled":True,"verdict":"block","score":score,"threshold":self.threshold,"claims":per,
                "correction_request":{"action":"revise-and-resubmit","reason":"groundedness below threshold","ungrounded_claims":ungrounded,"instruction":"Remove or evidence each ungrounded claim, then resubmit through the gate."}}
def evaluate(answer, evidence, threshold=DEFAULT_THRESHOLD, enabled=GATE_ENABLED_DEFAULT):
    return Gate(threshold=threshold, enabled=enabled).evaluate(answer, evidence)
