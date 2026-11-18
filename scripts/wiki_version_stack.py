#!/usr/bin/env python3
"""Version-stack detection over raw/ (Marathon R3 lane TB1,
row 5).

Pattern adapted with credit from AutoRAG (Marker Inc. /
NomaDamas, Apache-2.0): near-duplicate files ("Spot the
twins") are stacked under one logical document and tagged
Latest / Similar / Identical so retrieval resolves to the
latest version instead of silently citing a superseded draft.

Detection (deterministic, stdlib only):

- **normalised stem** — the filename stem with version noise
  stripped: ``-vN`` / ``_vN`` / `` vN``, ``-final`` /
  ``-final-vN``, trailing `` (N)`` copy markers, trailing
  ``-YYYY-MM-DD`` / ``-YYYYMMDD`` dates, ``-copy`` / ``-draft``
  suffixes, case-folded, separators unified;
- files in the same directory whose normalised stems match
  form a candidate stack;
- inside a stack, byte-identical files (same SHA-256) are
  **Identical**; files whose token 5-shingle Jaccard
  similarity to the latest is >= ``SIMILAR_THRESHOLD`` are
  **Similar**; every other member is still stacked (same
  logical document by name) and tagged by recency;
- **Latest** is the member with the highest explicit version
  number, then the newest embedded date, then the newest
  mtime, then the name — exactly one per stack.

Output: a report (JSON or text) naming each stack, its
members with their tag, hash and similarity evidence, and the
PROPOSED frontmatter tags for each member
(``stack: <id>``, ``stack_role: latest|similar|identical|
superseded``). This tool is REPORT-ONLY: it edits no file and
changes no retrieval behaviour. ``resolve_latest()`` is the
small API a retrieval caller can use to honour the stack;
wiring it into scripts/wiki_search.py is proposed in the lane
manifest, not done here, because the search ranker is
parity-checked against the Lens build and a rank change must
go through that gate deliberately.

Usage:
  python3 scripts/wiki_version_stack.py [--root DIR]
          [--raw DIR] [--json]

Exit 0 = report produced; 2 = usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SIMILAR_THRESHOLD = 0.80
SHINGLE_N = 5

_VERSION_RE = re.compile(r"[-_ ]v(\d+)(?:[-_].*)?$", re.I)
_DATE_RE = re.compile(r"[-_](\d{4}-\d{2}-\d{2}|\d{8})$")
_SUFFIX_RE = re.compile(
    r"([-\s]\(\d+\)|[-_]final(?:[-_]v?\d+)?|[-_]copy|[-_]draft|"
    r"[-_]v\d+|[-_]\d{4}-\d{2}-\d{2}|[-_]\d{8})+$", re.I)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def parse_stem(stem: str):
    """(normalised stem, version int|None, date str|None)."""
    s = stem.strip().lower().replace("_", "-").replace(" ", "-")
    vm = re.search(r"[-]v(\d+)\b", s)
    version = int(vm.group(1)) if vm else None
    dm = _DATE_RE.search(s)
    date_str = dm.group(1) if dm else None
    norm = _SUFFIX_RE.sub("", s)
    norm = re.sub(r"[-]v\d+\b", "", norm)
    norm = re.sub(r"-+", "-", norm).strip("-")
    return norm, version, date_str


def shingles(text: str):
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < SHINGLE_N:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + SHINGLE_N])
            for i in range(len(tokens) - SHINGLE_N + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def scan_stacks(raw_dir: Path):
    """All stacks (size >= 2) under *raw_dir*, deterministic."""
    raw_dir = Path(raw_dir)
    groups = {}
    if not raw_dir.is_dir():
        return []
    for p in sorted(raw_dir.rglob("*")):
        if not p.is_file():
            continue
        norm, version, date_str = parse_stem(p.stem)
        key = (p.parent.relative_to(raw_dir).as_posix(), norm, p.suffix.lower())
        groups.setdefault(key, []).append((p, version, date_str))
    stacks = []
    for (dirname, norm, _suffix), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        records = []
        for p, version, date_str in members:
            data = p.read_bytes()
            records.append({
                "path": p.relative_to(raw_dir.parent).as_posix()
                        if p.is_relative_to(raw_dir.parent) else str(p),
                "name": p.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "version": version,
                "date": date_str,
                "mtime": p.stat().st_mtime,
                "_shingles": shingles(data.decode("utf-8", errors="ignore")),
                "_file": p,
            })
        # Latest: version, then date, then mtime, then name.
        def latest_key(r):
            return (r["version"] or 0, r["date"] or "",
                    r["mtime"], r["name"])
        latest = max(records, key=latest_key)
        stack_id = f"{dirname}/{norm}" if dirname != "." else norm
        members_out = []
        for r in sorted(records, key=lambda r: r["name"]):
            if r is latest:
                role, tag = "latest", "Latest"
                sim = 1.0
            elif r["sha256"] == latest["sha256"]:
                role, tag, sim = "identical", "Identical", 1.0
            else:
                sim = round(jaccard(r["_shingles"], latest["_shingles"]), 4)
                if sim >= SIMILAR_THRESHOLD:
                    role, tag = "similar", "Similar"
                else:
                    role, tag = "superseded", "Superseded"
            members_out.append({
                "path": r["path"], "tag": tag, "role": role,
                "sha256": r["sha256"][:16],
                "similarity_to_latest": sim,
                "version": r["version"], "date": r["date"],
                "proposed_frontmatter": {
                    "stack": stack_id, "stack_role": role},
            })
        stacks.append({"stack": stack_id, "latest": latest["path"]
                       if False else [m["path"] for m in members_out
                                      if m["role"] == "latest"][0],
                       "members": members_out})
    return stacks


def resolve_latest(raw_dir: Path, path) -> str:
    """The stack-latest path for *path*, or *path* itself when
    it is latest or in no stack — the retrieval-honouring API."""
    target = str(path).replace("\\", "/")
    for stack in scan_stacks(raw_dir):
        paths = [m["path"] for m in stack["members"]]
        if any(p.endswith(target) or target.endswith(p) for p in paths):
            return stack["latest"]
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--raw", default=None, help="raw dir (default: <root>/raw)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    raw = Path(args.raw) if args.raw else root / "raw"
    if not raw.is_dir():
        print(f"raw dir not found: {raw}", file=sys.stderr)
        return 2
    stacks = scan_stacks(raw)
    if args.json:
        print(json.dumps({"kind": "version-stacks", "stacks": stacks},
                         indent=2))
    else:
        print(f"{len(stacks)} version stack(s) under {raw}")
        for s in stacks:
            print(f"  stack {s['stack']} (latest: {s['latest']})")
            for m in s["members"]:
                print(f"    {m['tag']:<10} {m['path']} "
                      f"sim={m['similarity_to_latest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
