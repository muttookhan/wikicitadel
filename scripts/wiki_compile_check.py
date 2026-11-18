#!/usr/bin/env python3
"""Knowledge-compilation templates + conformance checker
(Marathon R3, Tier B row TB3-3; RAGFlow pattern).

Pattern: RAGFlow's per-document-type compilation templates
— each source type compiles through a stated template with
a fixed section grammar, so compiled pages of a kind are
uniformly checkable. Re-implemented from the idea; the
templates under templates/compilation/ are this wiki's own.

Each template file carries its grammar as data in its
frontmatter:

    template_for: paper | repo | transcript | filing
    required_frontmatter: [title, type, created, updated,
                           sources, tags]
    required_sections: ["## Summary", "## Claims", ...]

(the grammar is the ORDERED list of `## ` headings a
compiled page of that type must carry — extra sections are
allowed, missing or out-of-order ones are not).

Usage:
  python3 scripts/wiki_compile_check.py check PAGE --type paper
  python3 scripts/wiki_compile_check.py list

Exit codes: check 0 = conforms, 1 = violations found,
2 = usage error (unknown type, unreadable page). Output is
JSON. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR_REL = "templates/compilation"
TYPES = ("paper", "repo", "transcript", "filing")


def parse_frontmatter(text: str):
    """(frontmatter dict of simple scalars/lists, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm, body = {}, text[3:end]
    key = None
    for line in body.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip("'\"") for v in
                           val[1:-1].split(",") if v.strip()]
            elif val:
                fm[key] = val.strip("'\"")
            else:
                fm[key] = []
        elif key and line.strip().startswith("- "):
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(line.strip()[2:].strip().strip("'\""))
    return fm, text[end + 4:]


def load_template(root: Path, type_: str):
    path = root / TEMPLATE_DIR_REL / f"{type_}.md"
    if not path.is_file():
        return None
    fm, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return fm


def check_page(root: Path, page: Path, type_: str):
    """List of violation strings ([] = conforms)."""
    tmpl = load_template(root, type_)
    if tmpl is None:
        return None
    text = page.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    violations = []
    for field in tmpl.get("required_frontmatter", []):
        if field not in fm or fm[field] in ("", []):
            violations.append(f"missing frontmatter: {field}")
    required = tmpl.get("required_sections", [])
    headings = [ln.strip() for ln in body.splitlines()
                if ln.startswith("## ")]
    pos = -1
    for want in required:
        try:
            idx = headings.index(want, pos + 1)
        except ValueError:
            if want in headings:
                violations.append(f"section out of order: {want}")
            else:
                violations.append(f"missing section: {want}")
            continue
        pos = idx
    return violations


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check", help="check a page against its template")
    pc.add_argument("page")
    pc.add_argument("--type", required=True, choices=TYPES)
    sub.add_parser("list", help="list compilation templates + grammars")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "list":
        out = {}
        for t in TYPES:
            tmpl = load_template(root, t)
            if tmpl:
                out[t] = {"required_frontmatter":
                          tmpl.get("required_frontmatter", []),
                          "required_sections":
                          tmpl.get("required_sections", [])}
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    page = Path(args.page)
    if not page.is_file():
        print(f"no such page: {page}", file=sys.stderr)
        return 2
    violations = check_page(root, page, args.type)
    if violations is None:
        print(f"no template for type {args.type}", file=sys.stderr)
        return 2
    print(json.dumps({"page": str(page), "type": args.type,
                      "conforms": not violations,
                      "violations": violations},
                     indent=2, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
