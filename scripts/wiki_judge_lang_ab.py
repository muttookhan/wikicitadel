#!/usr/bin/env python3
"""KULLM-pattern judge-prompt-language A/B harness (Marathon R3 TB6 row 7).

Compares judge prompts across languages over the SAME labelled
fixture set and reports agreement deltas: per-variant agreement
with the labels, pairwise inter-variant agreement, and the delta
from the baseline variant. Fixtures are small and self-authored;
judges here are fixture outputs, never a provider. A variant with
no owner-labelled fixtures is reported as unmeasurable, never
certified. Stdlib only.
Input JSONL: {id, label, variants: {<lang>: <verdict>, ...}}.
Exit: 0 report produced, 1 empty/unmeasurable set.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

def run(rows, baseline=None):
    if not rows: return {"status":"refused","reason":"empty fixture set: nothing measurable"}
    langs=sorted({k for r in rows for k in r.get("variants",{})})
    base=baseline or langs[0]
    agree={}
    for lang in langs:
        scored=[r for r in rows if lang in r.get("variants",{})]
        agree[lang]={"n":len(scored),"label_agreement":round(sum(1 for r in scored if r["variants"][lang]==r["label"])/len(scored),4) if scored else None}
    pair={}
    for i,l1 in enumerate(langs):
        for l2 in langs[i+1:]:
            both=[r for r in rows if l1 in r.get("variants",{}) and l2 in r.get("variants",{})]
            pair[f"{l1}~{l2}"]=round(sum(1 for r in both if r["variants"][l1]==r["variants"][l2])/len(both),4) if both else None
    deltas={l: (round(agree[l]["label_agreement"]-agree[base]["label_agreement"],4) if agree[l]["label_agreement"] is not None and agree[base]["label_agreement"] is not None else None) for l in langs}
    return {"status":"ok","baseline":base,"cases":len(rows),"label_agreement":agree,"pairwise_agreement":pair,"delta_vs_baseline":deltas,"note":"fixture judges only; no provider called; agreement is not certification"}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--fixtures",required=True); ap.add_argument("--baseline")
    a=ap.parse_args(); rep=run(load_jsonl(a.fixtures), a.baseline); print(json.dumps(rep, indent=1)); return 0 if rep["status"]=="ok" else 1
if __name__=="__main__": sys.exit(main())
