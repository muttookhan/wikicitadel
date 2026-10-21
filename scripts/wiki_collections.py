#!/usr/bin/env python3
"""Three-collection census (EU-N2, Marathon R3 TA6).

Vocabulary (idea from Cheshire Cat's declarative/episodic/procedural
taxonomy, GPL source -- IDEAS ONLY, re-implemented): every page in the
wiki belongs to exactly one of three collections:
  sources    -- raw and compiled source material (raw/, wiki/sources/)
  compiled   -- the compiled knowledge layer (wiki entities, concepts,
                syntheses, queries, overview and other wiki pages)
  governance -- the rules that govern the wiki (AGENTS.md, wiki/rules/,
                wiki/access/, structural registers index/log)
`census --root R` prints JSON {counts, by_collection, unclassified}.
Exit 0 when nothing is unclassified, 1 otherwise.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
GOV_DIRS={"rules","access"}; STRUCT={"index.md","log.md"}
def classify(rel: str) -> str:
    p=rel.replace("\\","/")
    if p=="AGENTS.md": return "governance"
    if p.startswith("raw/"): return "sources"
    if p.startswith("wiki/sources/"): return "sources"
    parts=p.split("/")
    if p.startswith("wiki/") and len(parts)>2 and parts[1] in GOV_DIRS: return "governance"
    if p.startswith("wiki/") and parts[-1] in STRUCT and len(parts)==2: return "governance"
    if p.startswith("wiki/"): return "compiled"
    return "unclassified"
def census(root: Path):
    files=[]
    for base in ("wiki","raw"):
        d=root/base
        if d.exists(): files += [f.relative_to(root).as_posix() for f in sorted(d.rglob("*.md"))]
    if (root/"AGENTS.md").exists(): files.append("AGENTS.md")
    out={"sources":[],"compiled":[],"governance":[],"unclassified":[]}
    for f in files: out[classify(f)].append(f)
    return {"counts":{k:len(v) for k,v in out.items()},"by_collection":out,
            "unclassified":out["unclassified"]}
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); ns=a.parse_args(argv)
    r=census(Path(ns.root)); print(json.dumps(r,indent=1))
    return 1 if r["unclassified"] else 0
if __name__=="__main__": sys.exit(main())
