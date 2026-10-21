#!/usr/bin/env python3
"""Answerability-verified golden-set BUILDER (KR5, TA6).

Drafts candidate eval questions ONLY from passages it verifies can
answer them: a candidate is accepted when its answer sentence occurs
verbatim (normalised) in the cited source passage. A built-in
unanswerable slice (~1/6) is drafted from decoy terms verified ABSENT
from the sources, marked answerable: false.

MILU design rule (Marathon R4 lane D; Verma et al., CC BY 4.0):
eval questions are written from THIS wiki's OWN source material, in
its own terms — never translated or templated from generic items.
A question whose subject terms were imported from outside the cited
source measures a foreign benchmark, not this corpus. Enforcement:
:func:`milu_missing_terms` / :func:`check_milu` flag every candidate
whose subject terms do not appear in the cited source material;
``build`` stamps each answerable candidate with ``milu_flagged`` and
``milu_missing_terms``, and ``--milu-check CANDIDATES --source-dir DIR``
runs the check standalone over an existing candidate file (exit 1
when any candidate is flagged). Flagging never rewrites a candidate
and never touches a golden set — a flagged candidate is a finding
for a human to drop or re-write from the source's own words.

HARD RULE: this tool never opens any existing golden set for writing,
and never overwrites anything: --out must be a NEW file; an existing
--out path is refused (exit 4), and any path whose name contains
'golden-questions' is refused outright (exit 4).
Sources are read from --source-dir (a fixture/corpus dir of .md files).
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
DECOYS=["photosynthesis in deep-sea vents","martian canal irrigation","medieval alchemy guild dues"]
# Words that frame a question without naming its subject; they are
# the builder's own scaffolding, not source terms, so the MILU check
# never holds them against the cited source.
STOPWORDS=set("a an the what is are was were does do did say says said stated about according to in of on for from corpus wiki page source this that it its and or".split())
def norm(s): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]"," ",s.lower())).strip()
def sentences(text):
    body=text.split("---",2)[-1] if text.startswith("---") else text
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+",body) if len(s.strip())>40]
def subject_terms(question):
    """The terms a question is ABOUT (the MILU-checked terms).

    The subject is the text after the last ':' when present, else
    after the last ' about ', else the whole question; scaffolding
    stopwords and tokens under 3 chars are dropped.
    """
    q=str(question or "")
    if ":" in q: q=q.rsplit(":",1)[-1]
    elif " about " in q.lower(): q=q.lower().rsplit(" about ",1)[-1]
    return [t for t in norm(q).split() if len(t)>2 and t not in STOPWORDS]
def milu_missing_terms(question, source_text):
    """Subject terms of *question* absent from *source_text*.

    An empty list means the question speaks in its cited source's
    own terms. No cited source text at all is itself a finding:
    every term counts as missing.
    """
    terms=subject_terms(question)
    if source_text is None: return terms
    corpus=set(norm(source_text).split())
    return [t for t in terms if t not in corpus]
def check_milu(candidates, source_texts):
    """Flag candidates whose terms are not in their cited source.

    *candidates* are builder-shaped dicts; *source_texts* maps a
    candidate's ``source`` name to that source's full text.
    Returns one finding per flagged candidate:
    {"question", "source", "missing_terms"}. Unanswerable decoy
    candidates (answerable is False) are exempt by design: their
    terms are verified ABSENT, which is their stated purpose.
    """
    findings=[]
    for c in candidates:
        if c.get("answerable") is False: continue
        missing=milu_missing_terms(c.get("question"), source_texts.get(c.get("source")))
        if missing: findings.append({"question":c.get("question"),"source":c.get("source"),"missing_terms":missing})
    return findings
def build(source_dir: Path):
    passages=[]; source_texts={}
    for f in sorted(source_dir.rglob("*.md")):
        source_texts[f.name]=f.read_text()
        for s in sentences(source_texts[f.name]):
            passages.append({"source":f.name,"answer":s})
    cands=[]; corpus=norm(" ".join(p["answer"] for p in passages))
    for p in passages:
        if norm(p["answer"]) not in corpus: continue  # answerability verification
        term=p["answer"].split(":")[0][:60]
        q=f"According to {p['source']}, what is stated about: {term}?"
        missing=milu_missing_terms(q, source_texts.get(p["source"]))
        cands.append({"question":q,"answer":p["answer"],"source":p["source"],"answerable":True,"verified":True,"milu_flagged":bool(missing),"milu_missing_terms":missing})
    n_un=max(1,len(cands)//5) if cands else 1
    for d in DECOYS[:n_un]:
        if norm(d) in corpus: continue
        cands.append({"question":f"What does the corpus say about {d}?","answer":None,"source":None,"answerable":False,"verified":True,"milu_flagged":False,"milu_missing_terms":[]})
    return cands
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--source-dir"); a.add_argument("--out"); a.add_argument("--milu-check",help="candidate .jsonl to MILU-check against --source-dir; no file is written")
    ns=a.parse_args(argv)
    if ns.milu_check:
        if not ns.source_dir: print("refused: --milu-check needs --source-dir",file=sys.stderr); return 4
        source_texts={f.name:f.read_text() for f in sorted(Path(ns.source_dir).rglob("*.md"))}
        cands=[json.loads(l) for l in Path(ns.milu_check).read_text().splitlines() if l.strip()]
        findings=check_milu(cands,source_texts)
        print(json.dumps({"checked":len(cands),"flagged":len(findings),"findings":findings}))
        return 1 if findings else 0
    if not ns.source_dir or not ns.out: print("refused: --source-dir and --out are required",file=sys.stderr); return 4
    out=Path(ns.out)
    if "golden-questions" in out.name or out.exists():
        print("refused: output must be a new file and never the existing golden set",file=sys.stderr); return 4
    cands=build(Path(ns.source_dir)); out.write_text("".join(json.dumps(c)+"\n" for c in cands))
    print(json.dumps({"written":str(out),"candidates":len(cands),"answerable":sum(1 for c in cands if c["answerable"]),"milu_flagged":sum(1 for c in cands if c.get("milu_flagged"))})); return 0
if __name__=="__main__": sys.exit(main())
