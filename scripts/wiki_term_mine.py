#!/usr/bin/env python3
"""Cohesion-based glossary term mining (soynlp idea, TA6).

Idea from soynlp (Korean unsupervised word extraction; re-implemented
from the idea, no code copied): a multiword candidate is a real term
when its parts co-occur far more than chance -- cohesion here is
freq(phrase) / min(freq(part)) for bigrams/trigrams over the wiki
corpus, with a minimum phrase frequency. `mine --root R [--out F]
[--min-freq N] [--min-cohesion X]` prints a JSON candidates report
(and writes it when --out is given) for glossary review. Nothing is
added to the glossary itself.
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter
from pathlib import Path
WORDS=re.compile(r"[a-z][a-z\-]+")
STOP=set("the a an and or of to in is are was were for on with as by at from this that it its be been has have had not no yes".split())
def tokens(text): return [w for w in WORDS.findall(text.lower()) if w not in STOP and len(w)>2]
def mine(root: Path, min_freq=3, min_cohesion=0.3):
    uni=Counter(); grams=Counter()
    wiki=root/"wiki"
    files=list(wiki.rglob("*.md")) if wiki.exists() else []
    for f in files:
        toks=tokens(f.read_text(errors="ignore")); uni.update(toks)
        for n in (2,3): grams.update(tuple(toks[i:i+n]) for i in range(len(toks)-n+1))
    out=[]
    for g,c in grams.items():
        if c<min_freq: continue
        coh=c/min(uni[w] for w in g)
        if coh>=min_cohesion: out.append({"term":" ".join(g),"freq":c,"cohesion":round(coh,3)})
    return sorted(out,key=lambda x:(-x["cohesion"],x["term"]))
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); a.add_argument("--out"); a.add_argument("--min-freq",type=int,default=3); a.add_argument("--min-cohesion",type=float,default=0.3); ns=a.parse_args(argv)
    r=mine(Path(ns.root),ns.min_freq,ns.min_cohesion); payload={"candidates":r,"count":len(r)}
    if ns.out: Path(ns.out).write_text(json.dumps(payload,indent=1))
    print(json.dumps(payload,indent=1)); return 0
if __name__=="__main__": sys.exit(main())
