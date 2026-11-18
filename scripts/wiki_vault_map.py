#!/usr/bin/env python3
"""The standing vault map — one JSON Lines artefact for the whole wiki.

Pattern: Vault Map (Obsidian plugin, MIT) — one JSON Lines index
of every note's frontmatter, links, embeds, backlinks, broken
links, duplicate titles and orphans, so scripts and agents never
rescan the vault. Re-implemented in our own code over this
tree's conventions: the map covers the compiled layer (wiki/),
is generated deterministically by this script (never hand-edited),
and lands at evaluation/vault-map.jsonl — a header line, then
one line per page, pages sorted by path, every list sorted, so
two runs over an unchanged tree are byte-identical.

Before this artefact the same territory was exposed only as
queries (the traversal door): search / neighbours / path /
census. The map is the standing file those queries — and any
outside script — can read without opening a single page.

A page record:
  path            repo-relative page path (wiki/...)
  title           frontmatter title, else the first H1, else stem
  type            frontmatter type (null when the page has none)
  tags            frontmatter tags, as written
  sources         the page's frontmatter `sources` list, as written
  outlinks        resolved page paths this page links to ([[...]])
  embeds          [{target, resolved}] — ![[...]] and ![..](..);
                  resolved is a repo-relative path or null
  backlinks       resolved page paths that link to this page
  broken_links    [[...]] targets that resolve to no page
  duplicate_title true when another page carries the same title
  orphan          true when no other page links here (structural
                  pages — the index and the log — are never orphans)

Commands: build (write the artefact) / check (exit 1 when the
artefact is missing or stale against the current tree) / show
(print one page's record). Stdlib only, no network.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evaluation" / "vault-map.jsonl"
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}

WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
EMBED_LINK_RE = re.compile(r"!\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
EMBED_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
KEYVAL_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")
LISTITEM_RE = re.compile(r"^\s+-\s+(.*)$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)


def parse_frontmatter(text):
    """Small reader for this tree's frontmatter shapes: scalar
    `key: value`, inline lists `key: [a, b]`, and block lists
    (`key:` then indented `- item` lines). Returns (fm, body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm, key = {}, None
    for line in m.group(1).splitlines():
        kv = KEYVAL_RE.match(line)
        if kv and not line.startswith((" ", "\t")):
            key = kv.group(1)
            val = kv.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip("'\"") for v in
                           val[1:-1].split(",") if v.strip()]
            elif val:
                fm[key] = val.strip("'\"")
            else:
                fm[key] = []
            continue
        li = LISTITEM_RE.match(line)
        if li and key is not None and isinstance(fm.get(key), list):
            fm[key].append(li.group(1).strip().strip("'\""))
    return fm, text[m.end():]


def page_title(fm, body, path):
    if fm.get("title"):
        return str(fm["title"])
    h1 = H1_RE.search(body)
    if h1:
        return h1.group(1)
    return Path(path).stem


def build_map(root):
    root = Path(root)
    wiki_dir = root / "wiki"
    pages = sorted(p.relative_to(root).as_posix()
                   for p in wiki_dir.rglob("*.md"))
    by_path, by_nopath, by_stem = {}, {}, {}
    for rel in pages:
        by_path[rel] = rel
        by_nopath[rel[:-3] if rel.endswith(".md") else rel] = rel
        by_stem.setdefault(Path(rel).stem, []).append(rel)

    def resolve_link(target):
        t = target.strip()
        if not t:
            return None
        cands = [t, t + ".md", "wiki/" + t, "wiki/" + t + ".md"]
        for c in cands:
            if c in by_path:
                return by_path[c]
            if c in by_nopath:
                return by_nopath[c]
        stem_hits = by_stem.get(Path(t).stem, [])
        if len(stem_hits) == 1 and Path(t).name == Path(t).stem:
            return stem_hits[0]
        if len(stem_hits) == 1 and "/" not in t:
            return stem_hits[0]
        return None

    records = {}
    for rel in pages:
        text = (root / rel).read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        outlinks, broken = set(), set()
        for target in WIKILINK_RE.findall(body):
            hit = resolve_link(target)
            if hit:
                if hit != rel:
                    outlinks.add(hit)
            else:
                broken.add(target.strip())
        embeds = []
        embed_targets = [t for t in EMBED_LINK_RE.findall(body)]
        embed_targets += [t for t in EMBED_MD_RE.findall(body)
                          if not t.startswith(("http://", "https://"))]
        for target in sorted(set(embed_targets)):
            t = target.strip()
            resolved = resolve_link(t)
            if resolved is None:
                for cand in (t, (Path(rel).parent / t).as_posix()):
                    if (root / cand).exists():
                        resolved = cand
                        break
            embeds.append({"target": t, "resolved": resolved})
        tags = fm.get("tags") if isinstance(fm.get("tags"), list) else \
            ([fm["tags"]] if fm.get("tags") else [])
        sources = fm.get("sources") if isinstance(fm.get("sources"), list) \
            else ([fm["sources"]] if fm.get("sources") else [])
        records[rel] = {
            "kind": "page", "path": rel,
            "title": page_title(fm, body, rel),
            "type": fm.get("type") if isinstance(fm.get("type"), str) else None,
            "tags": tags, "sources": sources,
            "outlinks": sorted(outlinks), "embeds": embeds,
            "backlinks": [], "broken_links": sorted(broken),
            "duplicate_title": False,
            "orphan": False,
        }
    titles = {}
    for rel, rec in records.items():
        titles.setdefault(rec["title"], []).append(rel)
        for target in rec["outlinks"]:
            records[target]["backlinks"].append(rel)
    for rel, rec in records.items():
        rec["backlinks"] = sorted(set(rec["backlinks"]))
        rec["duplicate_title"] = len(titles[rec["title"]]) > 1
        rec["orphan"] = (not rec["backlinks"]) and rel not in STRUCTURAL
    header = {
        "kind": "header", "register": "vault-map", "version": 1,
        "generated_by": "scripts/wiki_vault_map.py",
        "pages": len(records),
        "broken_links": sum(len(r["broken_links"]) for r in records.values()),
        "orphans": sum(1 for r in records.values() if r["orphan"]),
        "duplicate_titles": sum(1 for r in records.values()
                                if r["duplicate_title"]),
        "note": "Generated deterministically from wiki/ by "
                "scripts/wiki_vault_map.py — never hand-edit; "
                "regenerate with `build`, verify with `check`.",
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    for rel in pages:
        lines.append(json.dumps(records[rel], ensure_ascii=False))
    return "\n".join(lines) + "\n", header, records


def main(argv=None):
    ap = argparse.ArgumentParser(description="Standing vault map (JSONL).")
    sub = ap.add_subparsers(dest="command")
    for name in ("build", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=None)
        sp.add_argument("--out", default=None)
    ss = sub.add_parser("show")
    ss.add_argument("path")
    ss.add_argument("--root", default=None)
    ss.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "build"
    root = Path(args.root) if getattr(args, "root", None) else ROOT
    out = Path(args.out) if getattr(args, "out", None) else OUT
    text, header, records = build_map(root)
    if cmd == "build":
        out.write_text(text, encoding="utf-8")
        print(f"vault-map: wrote {out} — {header['pages']} page(s), "
              f"{header['broken_links']} broken link(s), "
              f"{header['orphans']} orphan(s), "
              f"{header['duplicate_titles']} duplicate title(s)")
        return 0
    if cmd == "check":
        if not out.is_file():
            print(f"vault-map: MISSING ({out})", file=sys.stderr)
            return 1
        current = out.read_text(encoding="utf-8")
        if current == text:
            print(f"vault-map: current ({header['pages']} page(s))")
            return 0
        print("vault-map: STALE — the tree has moved since the map "
              "was built; regenerate with `build`", file=sys.stderr)
        return 1
    if cmd == "show":
        rec = records.get(args.path)
        if rec is None:
            print(f"vault-map: no page {args.path!r}", file=sys.stderr)
            return 2
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
