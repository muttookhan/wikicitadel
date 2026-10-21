#!/usr/bin/env python3
"""Citation-gated advisory retrieval memory (Tier B: AutoRAG pattern, re-implemented).

Store: evaluation/advisory-memory.jsonl, append-only, one JSON object per line: {"id","note","citation","created"}. An entry is REFUSED at add time unless `citation` names a page that exists under wiki/ (citation-gated: no citation, no memory). `check` re-validates every stored entry; `query` returns only entries whose citation still resolves.
Stdlib only."""
import argparse, json, sys
from pathlib import Path
def store_path(root): return Path(root)/"evaluation"/"advisory-memory.jsonl"
def citation_ok(root, citation):
    if not citation: return False
    return (Path(root)/citation).exists() or (Path(root)/"wiki"/citation).exists()
def add_entry(root, note, citation, created=""):
    if not citation_ok(root, citation): return {"error":"refused: entry must cite an existing wiki page","citation":citation}, 1
    entries=load_entries(root); eid=f"am{len(entries)+1:04d}"
    rec={"id":eid,"note":note,"citation":citation,"created":created}
    p=store_path(root); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as fh: fh.write(json.dumps(rec)+"\n")
    return rec, 0
def load_entries(root):
    p=store_path(root)
    if not p.exists(): return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
def check(root):
    bad=[e for e in load_entries(root) if not citation_ok(root, e.get("citation"))]
    return {"entries":len(load_entries(root)),"invalid":bad}, (1 if bad else 0)
def query(root, text):
    words={w.lower() for w in text.split() if len(w)>2}
    out=[e for e in load_entries(root) if citation_ok(root,e.get("citation")) and words & {w.lower().strip(".,") for w in e.get("note","").split()}]
    return {"results":out}, 0
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent))
    sub=ap.add_subparsers(dest="cmd",required=True)
    a1=sub.add_parser("add"); a1.add_argument("--note",required=True); a1.add_argument("--citation",default=""); a1.add_argument("--created",default="")
    sub.add_parser("check"); sub.add_parser("list")
    q=sub.add_parser("query"); q.add_argument("text")
    a=ap.parse_args(argv)
    if a.cmd=="add": res,code=add_entry(a.root,a.note,a.citation,a.created)
    elif a.cmd=="check": res,code=check(a.root)
    elif a.cmd=="list": res,code={"entries":load_entries(a.root)},0
    else: res,code=query(a.root,a.text)
    print(json.dumps(res,indent=2)); return code
if __name__=="__main__": sys.exit(main())
