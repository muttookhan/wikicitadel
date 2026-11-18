#!/usr/bin/env python3
"""Per-agent loadout + visibility checker (Tier B: TencentDB pattern, re-implemented from the design; no foreign code copied).

Pages may carry `visibility: [agent, ...]` frontmatter (absent = visible to every agent in the loadout register). Agents carry a loadout in evaluation/loadouts.json: {"agents": [...], "loadouts": {"<agent>": ["wiki/concepts/*", ...]}} — collection patterns are fnmatch globs over repo-relative page paths.
Commands: check (validate every loadout against visibility; exit 1 on violations), list.
Stdlib only."""
import argparse, fnmatch, json, sys
from pathlib import Path
import re
def parse_fm(text):
    if not text.startswith("---"): return {}, text
    end=text.find("\n---",3)
    if end<0: return {}, text
    raw=text[3:end]; body=text[end+4:]
    fields={}
    for line in raw.splitlines():
        m=re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$",line)
        if not m: continue
        k,v=m.group(1),m.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            fields[k]=[x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.startswith("- "): fields[k]=[v[2:]]
        else: fields[k]=v.strip("'\"")
    # multiline list items
    cur=None
    for line in raw.splitlines():
        m=re.match(r"^\s+-\s+(.*)$",line)
        if m and cur:
            if not isinstance(fields.get(cur),list): fields[cur]=[]
            fields[cur].append(m.group(1).strip().strip("'\""))
        else:
            mm=re.match(r"^([A-Za-z_][\w-]*):",line)
            cur=mm.group(1) if mm else cur
    return fields, body

def load_register(root):
    f=Path(root)/"evaluation"/"loadouts.json"
    if not f.exists(): return None
    return json.loads(f.read_text(encoding="utf-8"))
def pages(root):
    w=Path(root)/"wiki"; out=[]
    if w.exists():
        for p in sorted(w.rglob("*.md")): out.append(p)
    return out
def check(root):
    reg=load_register(root)
    if reg is None: return {"error":"evaluation/loadouts.json missing"}, 2
    agents=reg.get("agents",[]); loadouts=reg.get("loadouts",{})
    violations=[]; warnings=[]
    for a in loadouts:
        if a not in agents: violations.append({"agent":a,"kind":"unknown-agent","detail":"loadout for agent not in agents list"})
    for p in pages(root):
        rel=p.relative_to(root).as_posix()
        fields,_=parse_fm(p.read_text(encoding="utf-8",errors="replace"))
        vis=fields.get("visibility")
        if isinstance(vis,str): vis=[vis]
        if vis:
            for v in vis:
                if v not in agents: warnings.append({"page":rel,"kind":"unknown-visibility-agent","detail":v})
        for agent, pats in loadouts.items():
            if any(fnmatch.fnmatch(rel,pat) for pat in pats):
                if vis and agent not in vis and agent!="owner":
                    violations.append({"agent":agent,"page":rel,"kind":"visibility-violation","detail":f"loadout loads page but visibility is {vis}"})
    return {"violations":violations,"warnings":warnings,"agents":agents,"pages_scanned":len(pages(root))}, (1 if violations else 0)
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent))
    sub=ap.add_subparsers(dest="cmd",required=True); sub.add_parser("check"); sub.add_parser("list")
    a=ap.parse_args(argv); res,code=check(a.root)
    if a.cmd=="list": res={"agents":res.get("agents",[]),"loadouts":(load_register(a.root) or {}).get("loadouts",{})}
    print(json.dumps(res,indent=2)); return code
if __name__=="__main__": sys.exit(main())
