#!/usr/bin/env python3
"""wiki_page_history.py — Lens per-page History/Diff data (Row TB4-9).
Per-page history from git log + latest diff, emitted as JSON data for the portal. Runner injectable for tests.
Usage: python3 scripts/wiki_page_history.py [--root DIR] [--out FILE] Exit 0."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
def git_log(root, rel, runner=None):
    runner=runner or (lambda cmd: subprocess.run(cmd,capture_output=True,text=True).stdout)
    out=runner(["git","-C",str(root),"log","--follow","--format=%H%x09%aI%x09%an%x09%s","--",rel])
    rows=[]
    for line in out.splitlines():
        parts=line.split("\t")
        if len(parts)>=4: rows.append({"commit":parts[0],"date":parts[1],"author":parts[2],"subject":parts[3]})
    return rows
def git_diff(root, rel, runner=None):
    runner=runner or (lambda cmd: subprocess.run(cmd,capture_output=True,text=True).stdout)
    return runner(["git","-C",str(root),"log","-p","-1","--format=","--",rel])
def build(root, runner=None):
    root=Path(root); pages=sorted((root/"wiki").rglob("*.md")) if (root/"wiki").exists() else []
    data={}
    for p in pages:
        rel=str(p.relative_to(root)); hist=git_log(root,rel,runner)
        data[rel]={"history":hist,"commits":len(hist),"latest_diff":git_diff(root,rel,runner) if hist else ""}
    return {"kind":"page-history","pages":data}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default=str(Path(__file__).resolve().parent.parent)); ap.add_argument("--out"); a=ap.parse_args(argv)
    d=build(a.root); txt=json.dumps(d,indent=2)
    if a.out: Path(a.out).write_text(txt,encoding="utf-8")
    else: print(txt)
    return 0
if __name__=="__main__": sys.exit(main())
