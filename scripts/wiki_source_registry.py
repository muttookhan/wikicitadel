#!/usr/bin/env python3
"""A Korpora-style registry over raw/sources (Marathon Round 4,
lane B).

Pattern: ko-nlp/Korpora (package CC-BY-4.0) -- one registry over
scattered source collections, each collection carrying its
metadata (licence included) in the registry and ONE fetch/load
entry point a consumer uses for every collection. Re-implemented
in our own code for this wiki's raw layer; no code copied.

What a collection is here: each immediate subdirectory of
raw/sources/ is one collection; the loose files sitting directly
in raw/sources/ form one more collection, named "loose-files".
The registry (evaluation/source-catalog.json) records, per
collection:

  name             directory name, or "loose-files"
  path             repo-relative collection root
  path_pattern     the glob a consumer matches ("raw/sources/<name>/**",
                   or "raw/sources/*" for the loose files)
  file_count       files in the collection (recursive)
  total_bytes      sum of file sizes
  licence          the licence AS RECORDED IN THE COLLECTION'S
                   OWN RECORDS -- a LICENSE/COPYING/NOTICE file's
                   first licence line, or a licence/license field
                   in one of its text records -- or null when the
                   collection records none. Never inferred, never
                   defaulted: an unrecorded licence is null, the
                   same discipline as this wiki's sensitivity
                   classes (unclassified is a state, not a guess).
  licence_source   the repo-relative file the licence was read
                   from, or null
  load_entry_point the one command a consumer runs to fetch the
                   collection's file list:
                   python3 scripts/wiki_source_registry.py load <name>

Commands:
  build [--out FILE] [--page FILE]
        scan raw/sources and write the registry JSON (default
        evaluation/source-catalog.json); with --page, also
        write the compiled summary page (a normal wiki page
        with full frontmatter) at the given path.
  load <collection>
        print the collection's file list, one repo-relative
        path per line, sorted. Exit 2 for an unknown collection
        (the known names are listed on stderr).

Exit codes: 0 ok, 1 build failure, 2 usage error / unknown
collection. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_REL = "evaluation/source-catalog.json"
LOOSE_NAME = "loose-files"
LICENCE_FILE_NAMES = {"license", "license.md", "license.txt",
                      "licence", "licence.md", "licence.txt",
                      "copying", "copying.md", "notice", "notice.md"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".rst", ".yaml", ".yml"}
LICENCE_FIELD_RE = re.compile(
    r"(?:^|[\s{,])[\"']?(?:licence|license)[\"']?\s*[:=]"
    r"\s*[\"']?([^\n\"',}]+)",
    re.I | re.M)
LICENCE_LINE_RE = re.compile(
    r"(MIT License|Apache License(?:,? Version 2\.0)?|"
    r"GNU (?:AFFERO |LESSER )?GENERAL PUBLIC LICENSE|"
    r"BSD \d-Clause License|CC[- ]BY[- ][\w.]+|"
    r"Creative Commons[^.\n]{0,60}|Mozilla Public License[^\n]{0,20})",
    re.I)
MAX_LICENCE_SCAN_BYTES = 262144
LICENCE_CANON_RES = [
    re.compile(r"CC[- ]BY(?:[- ](SA|NC|ND|NC-SA|NC-ND))?"
               r"(?:[- ]\d\.\d)?", re.I),
    re.compile(r"Apache(?: License)?(?:,? Version \d\.\d)?", re.I),
    re.compile(r"(?:A|L)?GPL(?:v\d)?(?: License)?", re.I),
    re.compile(r"BSD \d-Clause", re.I),
    re.compile(r"Mozilla Public License(?: \d\.\d)?", re.I),
    re.compile(r"Creative Commons[^;,\n]{0,40}", re.I),
    re.compile(r"MIT\b", re.I),
    re.compile(r"CC0\b", re.I),
    re.compile(r"ISC\b", re.I),
    re.compile(r"Unlicense\b", re.I),
    re.compile(r"NOASSERTION\b", re.I),
    re.compile(r"Proprietary\b", re.I),
    re.compile(r"All rights reserved\b", re.I),
]


def collection_dirs(sources_dir: Path):
    """[(name, path, recursive)] for every collection: each
    immediate subdirectory (recursive), plus the loose files."""
    out = []
    if not sources_dir.is_dir():
        return out
    for p in sorted(sources_dir.iterdir()):
        if p.is_dir():
            out.append((p.name, p, True))
    if any(p.is_file() for p in sources_dir.iterdir()):
        out.append((LOOSE_NAME, sources_dir, False))
    return out


def collection_files(path: Path, recursive: bool):
    if recursive:
        files = [p for p in path.rglob("*") if p.is_file()]
    else:
        files = [p for p in path.iterdir() if p.is_file()]
    return sorted(files)


def detect_licence(root: Path, files):
    """The licence recorded in the collection's own records, or
    (None, None). Deterministic: licence FILES first (sorted),
    then licence/license fields in text records (sorted). A
    value counts only when it names a recognisable licence --
    a prose sentence that merely mentions licensing is not a
    recorded licence, and an unrecorded licence stays null."""
    def rel(p):
        return p.relative_to(root).as_posix()

    def acceptable(value):
        """Canonical short licence name when *value* starts
        with one, else None: the registry records the licence
        NAME a record states, never the sentence around it."""
        value = value.strip()
        if not value or len(value) > 120:
            return None
        for rx in LICENCE_CANON_RES:
            m = rx.match(value)
            if m:
                return m.group(0).strip()
        return None

    for p in files:
        if p.name.lower() in LICENCE_FILE_NAMES:
            try:
                text = p.read_text(encoding="utf-8",
                                   errors="ignore")[
                                       :MAX_LICENCE_SCAN_BYTES]
            except OSError:
                continue
            for line in text.splitlines():
                m = LICENCE_LINE_RE.search(line)
                if m:
                    return m.group(0).strip(), rel(p)
    for p in files:
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if p.stat().st_size > MAX_LICENCE_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in LICENCE_FIELD_RE.finditer(text):
            value = acceptable(m.group(1))
            if value:
                return value, rel(p)
    return None, None


def build_registry(root: Path) -> dict:
    sources_dir = root / "raw" / "sources"
    collections = []
    for name, path, recursive in collection_dirs(sources_dir):
        files = collection_files(path, recursive)
        licence, licence_source = detect_licence(root, files)
        pattern = ("raw/sources/*" if name == LOOSE_NAME
                   else f"raw/sources/{name}/**")
        collections.append({
            "name": name,
            "path": ("raw/sources" if name == LOOSE_NAME
                     else f"raw/sources/{name}"),
            "path_pattern": pattern,
            "file_count": len(files),
            "total_bytes": sum(p.stat().st_size for p in files),
            "licence": licence,
            "licence_source": licence_source,
            "load_entry_point": "python3 scripts/wiki_source_registry.py "
                                f"load {name}",
        })
    return {
        "kind": "source-registry",
        "version": 1,
        "generated_at": date.today().isoformat(),
        "root": "raw/sources",
        "collections": collections,
        "totals": {
            "collections": len(collections),
            "files": sum(c["file_count"] for c in collections),
            "bytes": sum(c["total_bytes"] for c in collections),
        },
    }


def load_collection(root: Path, name: str):
    """The collection's sorted repo-relative file list, or None
    when *name* is not a collection."""
    sources_dir = root / "raw" / "sources"
    for cname, path, recursive in collection_dirs(sources_dir):
        if cname == name:
            return [p.relative_to(root).as_posix()
                    for p in collection_files(path, recursive)]
    return None


def collection_names(root: Path):
    return [n for n, _p, _r in
            collection_dirs(root / "raw" / "sources")]


def render_page(registry: dict) -> str:
    """The compiled summary page for a registry dict. Pure
    function of the registry, so the page can never drift from
    the JSON it summarises."""
    today = registry.get("generated_at") or date.today().isoformat()
    lines = [
        "---",
        'title: "Source registry — one manifest over raw/sources"',
        "type: synthesis",
        f"created: {today}",
        f"updated: {today}",
        "sources:",
        "  - raw/sources/provenance-manifest.json",
        "tags: [sources, registry, evaluation]",
        "stage: budding",
        f"planted: {today}",
        f"tended: {today}",
        "work_type: synthesis",
        "methods: Generated by scripts/wiki_source_registry.py "
        "from evaluation/source-catalog.json; every number on "
        "this page is read from that registry, never hand-counted.",
        "---",
        "",
        "# Source registry — one manifest over raw/sources",
        "",
        "One registry over the scattered source collections under",
        "`raw/sources/` (the Korpora pattern: per-collection "
        "metadata,",
        "licence included, behind one load entry point). The "
        "machine",
        "record is `evaluation/source-catalog.json`, built by",
        "`scripts/wiki_source_registry.py build`; any collection "
        "below",
        "is fetched with its own `load` command. A licence shown "
        "as",
        "*not recorded* means the collection's own records state",
        "none — the registry never infers one.",
        "",
        f"Collections: {registry['totals']['collections']} · "
        f"files: {registry['totals']['files']} · "
        f"bytes: {registry['totals']['bytes']}",
        "",
        "| Collection | Pattern | Files | Bytes | Licence | Load |",
        "|---|---|---:|---:|---|---|",
    ]
    for c in registry["collections"]:
        lic = c["licence"] if c["licence"] else "*not recorded*"
        lines.append(
            f"| {c['name']} | `{c['path_pattern']}` | "
            f"{c['file_count']} | {c['total_bytes']} | {lic} | "
            f"`{c['load_entry_point']}` |")
    lines += [
        "",
        "The registry is rebuilt, never hand-edited: re-run the",
        "build command after any ingest that adds a collection.",
        "See the wiki overview page for the wiki as a whole.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Korpora-style registry over raw/sources.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the registry JSON")
    b.add_argument("--out", default=None)
    b.add_argument("--page", default=None,
                   help="also write the compiled summary page here")
    ld = sub.add_parser("load", help="print a collection's files")
    ld.add_argument("collection")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.cmd == "build":
        registry = build_registry(root)
        out = Path(args.out) if args.out else root / REGISTRY_REL
        if not out.is_absolute():
            out = root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(registry, indent=1,
                                  ensure_ascii=False) + "\n",
                       encoding="utf-8")
        print(f"registry: {registry['totals']['collections']} "
              f"collection(s), {registry['totals']['files']} "
              f"file(s) -> {out}")
        if args.page:
            page = Path(args.page)
            if not page.is_absolute():
                page = root / page
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(render_page(registry), encoding="utf-8")
            print(f"page: -> {page}")
        return 0
    if args.cmd == "load":
        files = load_collection(root, args.collection)
        if files is None:
            print(f"unknown collection {args.collection!r}; known: "
                  + ", ".join(collection_names(root)),
                  file=sys.stderr)
            return 2
        for f in files:
            print(f)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
