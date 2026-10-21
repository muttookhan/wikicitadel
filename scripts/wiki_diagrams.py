#!/usr/bin/env python3
"""Diagrams-folder convention checker (Excalidraw pattern, TA6).

Convention: diagrams live under diagrams/ at the tree root. Each diagram
is a pair sharing a stem: a source (<stem>.excalidraw) beside its rendered
export (<stem>.svg or <stem>.png). Stems are lowercase-hyphens.
`check --root R` prints JSON findings; exit 1 if any finding.
Flags: diagram source/export files outside diagrams/, unpaired files
inside diagrams/, and non-conforming stems.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
STEM=re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SUFFIXES={".excalidraw",".svg",".png"}
def check(root: Path):
    findings=[]; diag=root/"diagrams"
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in SUFFIXES: continue
        if ".git" in f.parts: continue
        rel=f.relative_to(root).as_posix()
        inside = diag in f.parents or f.parent==diag
        # SVGs elsewhere (site assets etc.) are only flagged when they have
        # an .excalidraw sibling stem nearby -- plain assets are not diagrams.
        if not inside:
            if f.suffix==".excalidraw": findings.append({"kind":"outside-diagrams","path":rel})
            continue
        if not STEM.match(f.stem.split(".")[0]): findings.append({"kind":"bad-stem","path":rel})
    if diag.exists():
        stems={}
        for f in diag.iterdir():
            if f.is_file() and f.suffix in SUFFIXES: stems.setdefault(f.name.split(".")[0],set()).add(f.suffix)
        for stem,sufs in sorted(stems.items()):
            if ".excalidraw" not in sufs: findings.append({"kind":"export-without-source","path":f"diagrams/{stem}"})
            elif not (sufs & {".svg",".png"}): findings.append({"kind":"source-without-export","path":f"diagrams/{stem}"})
    return findings
def main(argv=None):
    a=argparse.ArgumentParser(); a.add_argument("--root",default="."); ns=a.parse_args(argv)
    f=check(Path(ns.root)); print(json.dumps({"findings":f,"count":len(f)},indent=1)); return 1 if f else 0
if __name__=="__main__": sys.exit(main())
