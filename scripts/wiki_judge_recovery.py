#!/usr/bin/env python3
"""shaberi-pattern judge-output recovery pass (Marathon R3 TB6 row 5).

Judge outputs that fail strict JSON parsing are recovered by a
repair pass with STATED rules, and every outcome is audit-trailed:
recovered (with the rule that fired) vs refused (with the reason).
Rules, in order: (1) strict JSON with a verdict field; (2) JSON
embedded in prose/fences; (3) an explicit 'verdict:' line; (4) a
 lone verdict keyword as the whole output. Anything ambiguous
(both accept and reject signals) is REFUSED, never guessed.
Recovery NEVER certifies: certification still requires owner-
labelled data (standing state: 0 labelled for certification).
Stdlib only, no model calls. Exit: 0 no refusals, 1 any refused.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

VERDICTS=("accept","reject")
def _from_obj(obj):
    if isinstance(obj, dict):
        v=str(obj.get("verdict","")).lower()
        if v in VERDICTS: return v
    return None
def recover(text):
    t=(text or "").strip()
    try: 
        v=_from_obj(json.loads(t))
        if v: return {"status":"parsed","verdict":v,"rule":"strict-json"}
    except Exception: pass
    m=re.search(r"\{[^{}]*\}", t, re.S)
    if m:
        try:
            v=_from_obj(json.loads(m.group(0)))
            if v: return {"status":"recovered","verdict":v,"rule":"embedded-json"}
        except Exception: pass
    m=re.search(r"verdict\s*[:=]\s*(accept|reject)", t, re.I)
    if m: return {"status":"recovered","verdict":m.group(1).lower(),"rule":"verdict-line"}
    low=t.lower()
    has_a=bool(re.search(r"\baccept(ed)?\b", low)); has_r=bool(re.search(r"\breject(ed)?\b", low))
    if has_a and has_r: return {"status":"refused","verdict":None,"rule":None,"reason":"ambiguous: both accept and reject signals present"}
    if low in VERDICTS: return {"status":"recovered","verdict":low,"rule":"bare-keyword"}
    return {"status":"refused","verdict":None,"rule":None,"reason":"no stated rule matched"}
def recover_all(rows):
    audit=[]
    for r in rows:
        rec=recover(r.get("output","")); audit.append({"id":r.get("id"), **rec})
    return {"audit":audit,"recovered":sum(1 for x in audit if x["status"]=="recovered"),"parsed":sum(1 for x in audit if x["status"]=="parsed"),"refused":sum(1 for x in audit if x["status"]=="refused"),"certification":"none: recovery is not certification; owner-labelled data required"}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--outputs",required=True)
    a=ap.parse_args(); rep=recover_all(load_jsonl(a.outputs)); print(json.dumps(rep, indent=1)); return 1 if rep["refused"] else 0
if __name__=="__main__": sys.exit(main())
