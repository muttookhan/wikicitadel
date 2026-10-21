"""conflict_classify.py — FadeMem pattern (paper, idea only, re-implemented): conflict classification on write.
Row TB4-4. NEW module beside the gateway. Classify-only: returns duplicate/refinement/contradiction/unrelated
for an incoming write vs existing texts; NEVER blocks a write by itself.
Heuristic, stdlib only: token Jaccard + negation/antonym cues for contradiction, subset relation for refinement."""
from __future__ import annotations
import re
NEG={"not","no","never","isn't","isnt","cannot","can't","false"}
ANTONYMS=[({"open"},{"closed"}),({"allow","allowed"},{"deny","denied","block","blocked"}),({"increase","increased"},{"decrease","decreased"})]
def tokens(t): return set(re.findall(r"[a-z0-9']+",t.lower()))
def classify(incoming, existing_texts):
    inc=tokens(incoming); best=None
    for ex in existing_texts:
        et=tokens(ex)
        if not inc or not et: continue
        jac=len(inc&et)/len(inc|et)
        contra=False
        if (inc & NEG) != (et & NEG) and len(inc&et)>=3: contra=True
        for a,b in ANTONYMS:
            if (inc&a and et&b) or (inc&b and et&a): contra=True
        if inc==et: label="duplicate"
        elif contra and jac>=0.3: label="contradiction"
        elif jac>=0.85: label="duplicate"
        elif inc<et or et<inc or jac>=0.5: label="refinement"
        elif jac<0.15: label="unrelated"
        else: label="refinement" if jac>=0.3 else "unrelated"
        cand={"label":label,"similarity":round(jac,4),"against":ex[:80]}
        if best is None or cand["similarity"]>best["similarity"]: best=cand
        if label=="duplicate": break
    return best or {"label":"unrelated","similarity":0.0,"against":None}
