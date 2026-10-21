#!/usr/bin/env python3
"""wiki_kag.py — KAG-pattern mutual indexing + logical-form retrieval.

Marathon Round 3, lane TB7, row 9. Pattern: KAG's knowledge<->chunk
mutual indexing with logical-form-guided retrieval (re-implemented
from the idea): every page is indexed BY its concepts and every
concept BY its pages — the index is MUTUAL, both directions stored
and validated against each other — and retrieval accepts a
LOGICAL FORM: a (subject, predicate, object) pattern in which any
slot may be a literal, `*` (any), or `?name` (a variable whose
bindings the answer returns).

The stated triple vocabulary (page -> concept):
  links_to    — the page wikilinks to the concept's page stem;
  tagged      — the page carries the tag;
  titled      — the page's title IS the concept (object = the
                page's own title text, lowercased);
  appears_on  — the reverse reading of links_to/tagged from the
                concept side: (concept, appears_on, page).

A query matches triples of both stored directions, so
"?p links_to gamma", "gamma appears_on ?p" and "* tagged agents"
are all answerable from the one index. Results are the matched
triples with their variable bindings, sorted deterministically.

    python3 scripts/wiki_kag.py build --root DIR --out index.json
    python3 scripts/wiki_kag.py query --index index.json \\
        --form "?p links_to gamma"
    python3 scripts/wiki_kag.py check --index index.json

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[\[([^\]|#]+)")
TITLE_RE = re.compile(r"^title:\s*\"?([^\"\n]+)\"?\s*$", re.M)
TAGS_RE = re.compile(r"^tags:\s*\[([^\]]*)\]\s*$", re.M)


def _norm(value):
    return " ".join(str(value).strip().lower().split())


def page_triples(rel, text):
    """The forward triples of one page (see module docstring)."""
    triples = []
    title_m = TITLE_RE.search(text[:3000])
    title = title_m.group(1).strip() if title_m else Path(rel).stem
    triples.append((rel, "titled", _norm(title)))
    for target in LINK_RE.findall(text):
        triples.append((rel, "links_to", _norm(Path(target).name)))
    tags_m = TAGS_RE.search(text[:3000])
    if tags_m:
        for tag in tags_m.group(1).split(","):
            tag = tag.strip().strip("\"'")
            if tag:
                triples.append((rel, "tagged", _norm(tag)))
    return sorted(set(triples))


def build_index(root):
    """The mutual index over wiki/**.md:
    {"kind": "mutual-index",
     "pages":    {page: {"concepts": [...], "triples": [[s,p,o]]}},
     "concepts": {concept: {"pages": [...], "triples": [[s,p,o]]}},
     "triples":  [[s,p,o], ...]  (both directions)}
    Forward triples are stored under their page; reverse
    (concept, appears_on, page) triples under their concept; the
    flat list holds both. Mutual means: concept c is in page p's
    concepts iff p is in c's pages — check_index() pins it."""
    root = Path(root)
    pages, concepts, flat = {}, {}, []
    for p in sorted((root / "wiki").rglob("*.md")):
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="ignore")
        triples = page_triples(rel, text)
        page_concepts = sorted({o for _s, pred, o in triples
                                if pred in ("links_to", "tagged")})
        pages[rel] = {"concepts": page_concepts,
                      "triples": [list(t) for t in triples]}
        flat.extend(list(t) for t in triples)
        for _s, pred, obj in triples:
            if pred not in ("links_to", "tagged"):
                continue
            entry = concepts.setdefault(obj, {"pages": [], "triples": []})
            if rel not in entry["pages"]:
                entry["pages"].append(rel)
            rev = [obj, "appears_on", rel]
            if rev not in entry["triples"]:
                entry["triples"].append(rev)
            if rev not in flat:
                flat.append(rev)
    for entry in concepts.values():
        entry["pages"].sort()
        entry["triples"].sort()
    flat.sort()
    return {"kind": "mutual-index", "version": 1, "pages": pages,
            "concepts": concepts, "triples": flat}


def check_index(index):
    """Mutuality validation: every page->concept edge has its
    concept->page twin and vice versa. Returns a list of
    violation strings ([] = the index is mutual)."""
    violations = []
    pages, concepts = index.get("pages") or {}, index.get("concepts") or {}
    for page, entry in pages.items():
        for concept in entry.get("concepts") or []:
            if page not in (concepts.get(concept) or {}).get("pages", []):
                violations.append(
                    f"{page} lists concept {concept!r} but the concept "
                    f"does not list the page")
    for concept, entry in concepts.items():
        for page in entry.get("pages") or []:
            if concept not in (pages.get(page) or {}).get("concepts", []):
                violations.append(
                    f"concept {concept!r} lists {page} but the page "
                    f"does not list the concept")
    return violations


def parse_form(form):
    """'S P O' -> the three slots (literals normalised; `*` and
    `?var` pass through). Raises ValueError on a wrong arity."""
    parts = (form or "").split()
    if len(parts) != 3:
        raise ValueError(
            f"logical form must have exactly 3 slots (subject "
            f"predicate object), got {len(parts)}: {form!r}")
    return tuple(p if p == "*" or p.startswith("?")
                 else _norm(p) for p in parts)


def _slot_matches(slot, value, bindings):
    if slot == "*":
        return True
    if slot.startswith("?"):
        name = slot[1:]
        if name in bindings:
            return bindings[name] == value
        bindings[name] = value
        return True
    return slot == value


def query_index(index, form):
    """Match a logical form against the index's flat triple list
    (both directions). Returns [{"triple": [s,p,o], "bindings":
    {var: value}}] sorted by triple."""
    s_slot, p_slot, o_slot = parse_form(form)
    out = []
    for triple in index.get("triples") or []:
        bindings = {}
        if (_slot_matches(s_slot, triple[0], bindings)
                and _slot_matches(p_slot, triple[1], bindings)
                and _slot_matches(o_slot, triple[2], bindings)):
            out.append({"triple": list(triple), "bindings": bindings})
    out.sort(key=lambda r: r["triple"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", default=None)
    b.add_argument("--out", required=True)
    q = sub.add_parser("query")
    q.add_argument("--index", required=True)
    q.add_argument("--form", required=True)
    c = sub.add_parser("check")
    c.add_argument("--index", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        root = Path(args.root).resolve() if args.root else ROOT
        index = build_index(root)
        Path(args.out).write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"mutual index: {len(index['pages'])} pages, "
              f"{len(index['concepts'])} concepts, "
              f"{len(index['triples'])} triples -> {args.out}")
        return 0
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    if args.cmd == "check":
        violations = check_index(index)
        print(json.dumps({"kind": "mutual-index-check",
                          "violations": violations}))
        return 1 if violations else 0
    try:
        results = query_index(index, args.form)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
