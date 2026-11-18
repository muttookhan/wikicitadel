#!/usr/bin/env python3
"""Held-out golden set outside the agent-writable tree (TB6 row 9).

Open Ko-LLM Leaderboard practice: the held-out slice lives OUTSIDE
the tree at a stated external path convention
(~/workspace/held-out/<tree-name>/heldout.jsonl); inside the tree
only a HASH MANIFEST (evaluation/heldout-manifest.json) is kept.
The runner refuses unless the external file's SHA-256 matches the
manifest, scores it with a deterministic lexical scorer, and
reports AGGREGATE SCORES ONLY — questions are never copied into
the tree or into the report. This module never creates a real
held-out set from the live golden set. Stdlib only.
Exit: 0 verified+scored, 1 hash mismatch / missing / refused.
"""
import argparse, json, re, sys
from pathlib import Path
STOP=set("the a an of to in is are was were be been it its this that and or for on at by with as from".split())
def toks(s): return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP]
def tset(s): return set(toks(s))
def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
def root_default(): return Path(__file__).resolve().parent.parent

import hashlib
def sha256_file(p): 
    h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
def write_manifest(root, external_path):
    ep=Path(external_path)
    if not ep.exists(): return {"status":"refused","reason":"external held-out file does not exist; not creating one"}
    man={"schema":"heldout-manifest/1","external_path":str(ep),"sha256":sha256_file(ep),"cases":sum(1 for l in ep.read_text(encoding="utf-8").splitlines() if l.strip()),"note":"hash manifest only; the questions live outside the tree and are never copied in"}
    out=Path(root)/"evaluation"/"heldout-manifest.json"; out.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return {"status":"written","manifest":str(out), **man}
def run(root):
    mp=Path(root)/"evaluation"/"heldout-manifest.json"
    if not mp.exists(): return {"status":"refused","reason":"no held-out manifest in tree"}
    man=json.loads(mp.read_text(encoding="utf-8")); ep=Path(man["external_path"])
    if not ep.exists(): return {"status":"refused","reason":"external held-out file missing"}
    actual=sha256_file(ep)
    if actual!=man["sha256"]: return {"status":"refused","reason":"hash mismatch: held-out file changed since manifest; run blocked","expected":man["sha256"],"actual":actual}
    rows=load_jsonl(ep); scored=0
    for r in rows:
        exp=tset(r.get("expected","")); got=tset(r.get("answer",""))
        if exp and len(exp & got)/len(exp) >= 0.5: scored+=1
    return {"status":"scored","cases":len(rows),"passed":scored,"score":round(scored/len(rows),4) if rows else None,"report_contains":"aggregate scores only; no questions, answers or expected text"}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(root_default())); ap.add_argument("--manifest-from",help="external held-out file to hash into a manifest")
    a=ap.parse_args()
    rep = write_manifest(a.root, a.manifest_from) if a.manifest_from else run(a.root)
    print(json.dumps(rep, indent=1)); return 0 if rep["status"] in ("scored","written") else 1
if __name__=="__main__": sys.exit(main())
