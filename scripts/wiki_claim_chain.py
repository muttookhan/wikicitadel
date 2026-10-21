#!/usr/bin/env python3
"""Per-claim version-evolution diff-chains (Tier B: Hy Memory pattern, re-implemented from the design).

Builds the ordered version chain for one claim from the append-only registers: evaluation/claim-versions.jsonl ({claim, version, date, text} when present), evaluation/outcomes.jsonl and evaluation/reverify-history.jsonl (events become chain nodes). Consecutive text versions carry a unified diff.
Commands: chain --claim <page-path>. Stdlib only."""
import argparse, difflib, json, sys
from pathlib import Path
def _read_jsonl(p):
    if not Path(p).exists(): return []
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def build_chain(root, claim):
    root=Path(root); nodes=[]
    for r in _read_jsonl(root/"evaluation"/"claim-versions.jsonl"):
        if r.get("claim")==claim: nodes.append({"date":r.get("date",""),"kind":"version","version":r.get("version"),"text":r.get("text","")})
    for r in _read_jsonl(root/"evaluation"/"outcomes.jsonl"):
        if r.get("claim")==claim or r.get("page")==claim: nodes.append({"date":r.get("date",""),"kind":"outcome","outcome":r.get("outcome"),"text":r.get("note","")})
    for r in _read_jsonl(root/"evaluation"/"reverify-history.jsonl"):
        if r.get("claim")==claim or r.get("page")==claim: nodes.append({"date":r.get("date",""),"kind":"reverify","outcome":r.get("outcome"),"text":r.get("note","")})
    nodes.sort(key=lambda n:(n["date"], n["kind"]))
    prev=None
    for n in nodes:
        if n["kind"]=="version":
            n["diff"]=list(difflib.unified_diff((prev or "").splitlines(), n["text"].splitlines(), lineterm="")) if prev is not None else []
            prev=n["text"]
    return {"claim":claim,"versions":nodes,"count":len(nodes)}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent))
    sub=ap.add_subparsers(dest="cmd",required=True); c=sub.add_parser("chain"); c.add_argument("--claim",required=True)
    a=ap.parse_args(argv); print(json.dumps(build_chain(a.root,a.claim),indent=2)); return 0
if __name__=="__main__": sys.exit(main())
