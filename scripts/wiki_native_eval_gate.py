#!/usr/bin/env python3
"""JGLUE/KLUE-pattern native-language eval-set gate (TB6 row 8).

Format + checker for native-language eval sets. A set counts as
USABLE only when (a) every case is well-formed ({id, lang, text,
label} with lang matching the set language) and (b) the annotator-
agreement gate passes: two annotation files over the same ids must
reach agreement >= threshold AND Cohen's kappa >= kappa_min (the
JGLUE practice of an agreement gate on gold labels). Sets failing
the gate are reported unusable, never silently accepted.
Stdlib only. Exit: 0 usable, 1 not usable / malformed.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

def kappa(a, b):
    n=len(a)
    if n==0: return 0.0
    po=sum(1 for x,y in zip(a,b) if x==y)/n
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    pe=sum((ca[k]/n)*(cb[k]/n) for k in set(ca)|set(cb))
    return round((po-pe)/(1-pe),4) if pe<1 else 1.0
def check(cases, ann_a, ann_b, lang, agree_min=0.7, kappa_min=0.4):
    errs=[]
    ids=set()
    for c in cases:
        if not all(k in c for k in ("id","lang","text","label")): errs.append(f"{c.get('id','?')}: missing field")
        elif c["lang"]!=lang: errs.append(f"{c['id']}: lang {c['lang']} != set lang {lang}")
        ids.add(c.get("id"))
    la={x["id"]:x["label"] for x in ann_a}; lb={x["id"]:x["label"] for x in ann_b}
    common=sorted(ids & set(la) & set(lb))
    if not common: return {"usable":False,"errors":errs+["no commonly annotated cases"],"agreement":None,"kappa":None}
    agree=round(sum(1 for i in common if la[i]==lb[i])/len(common),4)
    k=kappa([la[i] for i in common],[lb[i] for i in common])
    usable = not errs and agree>=agree_min and k>=kappa_min
    return {"usable":usable,"errors":errs,"cases":len(cases),"annotated":len(common),"agreement":agree,"kappa":k,"thresholds":{"agreement":agree_min,"kappa":kappa_min}}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--set",required=True); ap.add_argument("--annotations-a",required=True); ap.add_argument("--annotations-b",required=True); ap.add_argument("--lang",required=True)
    a=ap.parse_args(); rep=check(load_jsonl(a.set), load_jsonl(a.annotations_a), load_jsonl(a.annotations_b), a.lang); print(json.dumps(rep, indent=1)); return 0 if rep["usable"] else 1
if __name__=="__main__": sys.exit(main())
