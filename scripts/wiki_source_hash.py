#!/usr/bin/env python3
"""Source-hash staleness lint with transitive propagation
(Marathon R3 lane TB1, row 1).

Pattern: LayerX enterprise LLM Wiki (Japan harvest, 2026-10-20)
— IDEA ONLY (no licence; internal system described in an
article). Re-implemented from the idea; no code or text copied.

What it does
------------
Every wiki page's frontmatter ``sources:`` list names the raw
sources it rests on. This lint keeps a hash register
(``evaluation/source-hashes.json``, written by ``snapshot``):
for each cited raw source, the SHA-256 of its bytes at snapshot
time. ``check`` recomputes the hashes:

- a cited source whose bytes differ from the register is
  CHANGED (direct staleness);
- a cited source missing from disk is MISSING;
- a cited source with no register entry is UNREGISTERED
  (reported; not by itself publish-blocking, so the register
  can be adopted incrementally — run ``snapshot`` to register).

Staleness then PROPAGATES transitively through the citation
graph: a page that wikilinks (``[[...]]``) or claim-cites
(``^[cite: ...]``) a stale page is itself stale, one step at a
time, until the frontier is clean. Each propagated entry names
the path (the chain of pages) that carried the staleness.

Exit codes: ``check`` exits 1 when any publish-blocking
staleness exists (a CHANGED or MISSING source, or any page
stale directly or transitively), 0 when clean, 2 on usage
error. The nightly-sweep wiring is a PROPOSED register line
(see the lane manifest), not an edit made here.

A page may also carry inline ``source_hashes:`` frontmatter
(a mapping of source path -> sha256 hex); those are checked
identically and need no register.

Usage:
  python3 scripts/wiki_source_hash.py snapshot [--root DIR]
          [--register FILE]
  python3 scripts/wiki_source_hash.py check [--root DIR]
          [--register FILE] [--json]

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REGISTER_REL = "evaluation/source-hashes.json"
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)")
LINK_RE = re.compile(r"\[\[([^\]|#]+)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path):
    """SHA-256 hex of *path*'s bytes, or None when unreadable."""
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def parse_frontmatter(text: str):
    """Minimal frontmatter reader: (fields, sources, body).

    ``fields`` maps scalar keys to raw string values;
    ``source_hashes`` (a nested mapping) is returned inside
    fields under the key ``source_hashes`` as a dict.
    Mirrors the tolerant style of scripts/wiki_stale.py.
    """
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, [], text
    fm, body = m.group(1), text[m.end():]
    fields, sources, hashes = {}, [], {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if km:
            name, val = km.group(1), km.group(2).strip()
            if name == "sources":
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        sources = [s.strip().strip("\"'")
                                   for s in inner.split(",") if s.strip()]
                elif val:
                    sources = [val.strip("\"'")]
                else:
                    j = i + 1
                    while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                        sources.append(re.sub(r"^\s+-\s+", "", lines[j])
                                       .strip().strip("\"'"))
                        j += 1
                    i = j - 1
            elif name == "source_hashes":
                if val.startswith("{"):
                    try:
                        parsed = json.loads(val.replace("'", '"'))
                        if isinstance(parsed, dict):
                            hashes = {str(k): str(v) for k, v in parsed.items()}
                    except ValueError:
                        pass
                elif not val:
                    j = i + 1
                    while j < len(lines) and re.match(r"^\s+\S", lines[j]):
                        hm = re.match(r"^\s+([^:]+):\s*(\S+)\s*$", lines[j])
                        if hm:
                            hashes[hm.group(1).strip().strip("\"'")] = hm.group(2)
                        j += 1
                    i = j - 1
                fields["source_hashes"] = hashes
            else:
                fields[name] = val.strip("\"'")
        i += 1
    if hashes and "source_hashes" not in fields:
        fields["source_hashes"] = hashes
    return fields, sources, body


def resolve_source(root: Path, entry: str):
    """Resolve a frontmatter source entry to a path under *root*.

    Entries containing '/' are repo-relative paths; bare slugs
    resolve against raw/sources/ by exact stem match. Returns
    the Path (which may not exist) or None when unresolvable.
    """
    entry = str(entry).strip()
    if not entry:
        return None
    if "/" in entry:
        return root / entry
    raw = root / "raw" / "sources"
    if raw.is_dir():
        for p in raw.rglob("*"):
            if p.is_file() and p.stem == entry:
                return p
        # Token-set fallback (wiki_stale.py's rule): a bare slug
        # whose tokens match exactly one raw file's stem tokens
        # resolves to it (date-first vs date-last naming).
        wanted = set(re.findall(r"[a-z0-9]+", entry.lower()))
        matches = [
            p for p in raw.rglob("*")
            if p.is_file()
            and set(re.findall(r"[a-z0-9]+", p.stem.lower())) == wanted
        ]
        if len(matches) == 1:
            return matches[0]
    return root / "raw" / "sources" / entry


def collect_pages(root: Path):
    """All wiki pages: {repo-relative posix path: record}.

    A record carries its cited sources (resolved repo-relative
    paths), its inline source_hashes, and its outgoing citation
    edges (wikilinks to wiki pages + claim-cite targets that
    are wiki pages).
    """
    wiki = root / "wiki"
    pages = {}
    if not wiki.is_dir():
        return pages
    md_files = sorted(wiki.rglob("*.md"))
    by_stem = {}
    for p in md_files:
        by_stem.setdefault(p.stem, []).append(p)
    for p in md_files:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, sources, body = parse_frontmatter(text)
        resolved = []
        for entry in sources:
            rp = resolve_source(root, entry)
            if rp is not None:
                resolved.append(rp.relative_to(root).as_posix()
                                if rp.is_relative_to(root) else str(entry))
            else:
                resolved.append(str(entry))
        edges = set()
        for target in LINK_RE.findall(body):
            target = target.strip()
            cand = target if target.endswith(".md") else target + ".md"
            cand_path = root / cand if "/" in cand else None
            if cand_path is not None and cand_path.is_file():
                edges.add(cand_path.relative_to(root).as_posix())
            elif "/" not in target:
                matches = by_stem.get(target, [])
                if len(matches) == 1:
                    edges.add(matches[0].relative_to(root).as_posix())
            else:
                wp = root / "wiki" / cand
                if wp.is_file():
                    edges.add(wp.relative_to(root).as_posix())
        for target in CITE_RE.findall(body):
            if target.startswith("wiki/"):
                tp = root / target
                if tp.is_file():
                    edges.add(target)
        edges.discard(rel)
        pages[rel] = {
            "path": rel,
            "sources": resolved,
            "source_hashes": fields.get("source_hashes") or {},
            "edges": sorted(edges),
        }
    return pages


def build_register(root: Path) -> dict:
    """The hash register for every source cited by any page."""
    pages = collect_pages(root)
    hashes = {}
    for page in pages.values():
        for src in page["sources"]:
            p = root / src
            digest = sha256_file(p) if p.is_file() else None
            hashes[src] = digest
    return {"kind": "source-hashes", "version": 1,
            "hashes": dict(sorted(hashes.items()))}


def load_register(path: Path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "source-hashes":
        return None
    return data


def check(root: Path, register=None) -> dict:
    """Run the staleness check under *root*.

    Returns a report dict: ``direct`` findings (per page/source),
    ``stale_pages`` (directly stale), ``propagated`` (transitively
    stale pages with their staleness chain), ``blocking`` (bool)
    and ``summary`` counts.
    """
    pages = collect_pages(root)
    reg_hashes = (register or {}).get("hashes") or {}
    direct = []
    stale_pages = set()
    for rel in sorted(pages):
        page = pages[rel]
        expected = dict(reg_hashes)
        expected.update(page["source_hashes"])
        for src in page["sources"]:
            p = root / src
            if not p.is_file():
                direct.append({"page": rel, "source": src,
                               "status": "missing"})
                stale_pages.add(rel)
                continue
            want = expected.get(src)
            if want is None:
                direct.append({"page": rel, "source": src,
                               "status": "unregistered"})
                continue
            got = sha256_file(p)
            if got != want:
                direct.append({"page": rel, "source": src,
                               "status": "changed",
                               "expected": want, "actual": got})
                stale_pages.add(rel)
    # Transitive propagation over REVERSE citation edges:
    # page Q cites stale page P  =>  Q is stale via P.
    reverse = {}
    for rel, page in pages.items():
        for edge in page["edges"]:
            reverse.setdefault(edge, []).append(rel)
    propagated = {}
    frontier = {rel: [rel] for rel in stale_pages}
    queue = sorted(stale_pages)
    seen = set(stale_pages)
    while queue:
        current = queue.pop(0)
        for dependent in sorted(reverse.get(current, [])):
            if dependent in seen:
                continue
            seen.add(dependent)
            chain = frontier[current] + [dependent]
            propagated[dependent] = chain
            frontier[dependent] = chain
            queue.append(dependent)
    blocking = bool(stale_pages)
    return {
        "kind": "source-hash-staleness",
        "direct": direct,
        "stale_pages": sorted(stale_pages),
        "propagated": [
            {"page": rel, "via": propagated[rel]}
            for rel in sorted(propagated)
        ],
        "blocking": blocking,
        "publish_blocked": blocking,
        "summary": {
            "pages": len(pages),
            "changed_or_missing": sum(
                1 for d in direct if d["status"] in ("changed", "missing")),
            "unregistered": sum(
                1 for d in direct if d["status"] == "unregistered"),
            "stale_pages": len(stale_pages),
            "propagated_pages": len(propagated),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--register", default=None)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="write the hash register")
    sub.add_parser("check", help="recompute + propagate staleness")
    args = ap.parse_args(argv)
    root = Path(args.root)
    reg_path = Path(args.register) if args.register else root / REGISTER_REL
    if args.cmd == "snapshot":
        register = build_register(root)
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(register, indent=2) + "\n",
                            encoding="utf-8")
        print(f"snapshot: {len(register['hashes'])} source hash(es) "
              f"-> {reg_path}")
        return 0
    register = load_register(reg_path)
    report = check(root, register)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"pages={s['pages']} changed/missing="
              f"{s['changed_or_missing']} unregistered={s['unregistered']} "
              f"stale={s['stale_pages']} propagated={s['propagated_pages']}")
        for d in report["direct"]:
            if d["status"] != "unregistered":
                print(f"  {d['status'].upper()}: {d['page']} <- {d['source']}")
        for item in report["propagated"]:
            print(f"  PROPAGATED: {item['page']} via "
                  f"{' -> '.join(item['via'])}")
        print("PUBLISH BLOCKED" if report["blocking"] else "clean")
    return 1 if report["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
