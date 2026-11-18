#!/usr/bin/env python3
"""wiki_citation_scope.py — per-file permission-scoped citations.

Marathon Round 3, lane TB7, row 6. Pattern: bisheng's per-file
permission scoping (re-implemented from the idea): a citation is
not just a pointer, it carries the SOURCE FILE's permission
scope, and an answer or export may only show citations whose
scope the reader holds. A citation outside the reader's scope
is REDACTED TO A SCOPE NOTE — the reader learns that evidence
exists under a scope they do not hold, and nothing else (no
path, no line range, no snippet).

Scope model (stated, deliberately small):
  * the register is evaluation/citation-scopes.json:
    {"kind": "citation-scopes", "default_scope": "internal",
     "files": {"raw/...": "personal", ...}}
  * a file with no register entry carries the default scope;
  * a reader is a SET of scopes (their clearance); a citation is
    visible iff its file's scope is in the reader's set. There
    is no implicit hierarchy — holding "personal" does not imply
    "internal"; the set is the grant, stated in full.

Surfaces:
  * filter_citations(citations, allowed) — the export-layer
    filter: citation records in, the same list out with
    out-of-scope records replaced by redaction records.
  * filter_text(text, scopes, allowed) — answer text: inline
    ^[cite: path#...] markers out of scope are replaced by the
    scope-note marker (citation withheld — scope 'X').
  * CLI check — scans the compiled layer for citations and
    reports, per page, how many a given reader may NOT see;
    the checker half. Exit 1 when any violation is found in
    --strict mode, else 0 (a report, not a gate, by default).

    python3 scripts/wiki_citation_scope.py check --root DIR \\
        --allow public,internal [--strict]
    python3 scripts/wiki_citation_scope.py filter --file A.md \\
        --allow public,internal

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/citation-scopes.json"
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)(#[^\]]*)?\]")


def load_scopes(root):
    """The scope register for a tree; an absent register means
    every file carries the built-in default scope."""
    p = Path(root) / REGISTER_REL
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) \
                    and data.get("kind") == "citation-scopes":
                return {"default_scope": data.get("default_scope")
                        or "internal",
                        "files": data.get("files") or {}}
        except (ValueError, OSError):
            pass
    return {"default_scope": "internal", "files": {}}


def scope_of(path, scopes):
    return (scopes.get("files") or {}).get(str(path),
                                           scopes.get("default_scope")
                                           or "internal")


def scope_note(scope):
    return (f"citation withheld — the source carries scope "
            f"'{scope}', which is outside the reader's scope")


def extract_citations(text):
    """Citation records from a page's text: inline ^[cite: ...]
    markers, in first-seen order: [{"path", "anchor"}]."""
    out, seen = [], set()
    for m in CITE_RE.finditer(text or ""):
        key = (m.group(1), m.group(2) or "")
        if key not in seen:
            seen.add(key)
            out.append({"path": m.group(1), "anchor": m.group(2) or ""})
    return out


def filter_citations(citations, scopes, allowed):
    """The export-layer filter. Returns a list of the same
    length and order: in-scope citations pass through with their
    scope attached; out-of-scope citations are replaced by a
    redaction record carrying ONLY the scope note + scope."""
    allowed = set(allowed or [])
    out = []
    for cite in citations:
        scope = scope_of(cite["path"], scopes)
        if scope in allowed:
            out.append(dict(cite, scope=scope, redacted=False))
        else:
            out.append({"redacted": True, "scope": scope,
                        "scope_note": scope_note(scope)})
    return out


def filter_text(text, scopes, allowed):
    """Answer-text filtering: out-of-scope ^[cite: ...] markers
    are replaced by the scope note; in-scope markers pass
    unchanged. Returns (filtered_text, n_redacted)."""
    allowed = set(allowed or [])
    n = 0

    def sub(m):
        nonlocal n
        scope = scope_of(m.group(1), scopes)
        if scope in allowed:
            return m.group(0)
        n += 1
        return f"^[{scope_note(scope)}]"

    return CITE_RE.sub(sub, text or ""), n


def check_tree(root, allowed):
    """The checker: per compiled page, the citations a reader
    with `allowed` scopes may not see. Returns
    {"pages": [{path, total, withheld: [{path, scope}]}],
     "totals": {...}} — withheld paths are shown HERE because
    the checker runs for the corpus owner, not for the reader
    the filter protects against."""
    root = Path(root)
    scopes = load_scopes(root)
    pages = []
    tot_c = tot_w = 0
    wiki = root / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            cites = extract_citations(
                p.read_text(encoding="utf-8", errors="ignore"))
            withheld = [{"path": c["path"],
                         "scope": scope_of(c["path"], scopes)}
                        for c in cites
                        if scope_of(c["path"], scopes)
                        not in set(allowed or [])]
            if cites:
                pages.append({
                    "path": str(p.relative_to(root)),
                    "total": len(cites), "withheld": withheld})
                tot_c += len(cites)
                tot_w += len(withheld)
    return {"kind": "citation-scope-check",
            "allowed": sorted(allowed or []),
            "pages": pages,
            "totals": {"citations": tot_c, "withheld": tot_w}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--root", default=None)
    c.add_argument("--allow", default="public,internal",
                   help="comma-separated reader scopes")
    c.add_argument("--strict", action="store_true",
                   help="exit 1 when any citation would be withheld")
    f = sub.add_parser("filter")
    f.add_argument("--file", required=True)
    f.add_argument("--root", default=None)
    f.add_argument("--allow", default="public,internal")
    args = ap.parse_args(argv)
    allowed = [s.strip() for s in args.allow.split(",") if s.strip()]
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "check":
        report = check_tree(root, allowed)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if (args.strict and report["totals"]["withheld"]) else 0
    scopes = load_scopes(root)
    text = Path(args.file).read_text(encoding="utf-8", errors="ignore")
    filtered, n = filter_text(text, scopes, allowed)
    sys.stdout.write(filtered)
    print(f"wiki_citation_scope: {n} citation(s) withheld",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
