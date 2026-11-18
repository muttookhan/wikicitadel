#!/usr/bin/env python3
"""wiki_citekeys.py — citekey literature notes (Marathon R3, Tier B
bundle "Graph, portal and capture forms", row 10).

Pattern: the Obsidian Citations plugin's citekey literature notes
(MIT; re-implemented from the idea). Literature sources gain
citekeys of the shape author-year-key (e.g. `karpathy-2026-wiki`),
recorded in a citekey register; Pandoc-style `[@citekey]`
references in any page must resolve against the register.

A literature note is a source page whose frontmatter carries
`literature: true` plus `authors:` (list or string) and `year:`.
Its citekey is either declared in frontmatter (`citekey:`) or
derived: first author's surname + year + first significant title
word, slugified. Uniqueness is enforced by the checker; a derived
collision is reported, never silently suffixed in the register —
the register is built by `build-register`, which refuses to write
when a collision exists.

Register format (default `wiki/citekeys.json`, in the files):
    {"citekeys": {"karpathy-2026-wiki": "wiki/sources/....md", ...}}

Subcommands:
    build-register [--sources-dir D] [--out FILE]  print (or write
                       with --out) the register from the notes.
    check [--sources-dir D] [--register FILE] [--pages-dir D]
                       every literature note has a citekey, every
                       citekey in the register resolves to an
                       existing note, citekeys are unique, and every
                       [@key] reference in any page under pages-dir
                       resolves. Exit 1 listing every problem.

CLI: --root defaults to the tree root. Exit 0 ok, 1 check failures,
2 missing inputs.
"""
import argparse
import json
import re
import sys
from pathlib import Path

STOPWORDS = {"the", "a", "an", "of", "on", "in", "for", "and", "to"}


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1).lower()] = m.group(2).strip()
    return fm


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def derive_citekey(fm):
    authors = fm.get("authors", "").strip("[]")
    first = re.split(r",| and ", authors)[0].strip().strip('"\'')
    surname = slug(first.split()[-1]) if first else "anon"
    year = re.sub(r"\D", "", fm.get("year", ""))[:4] or "nd"
    title = fm.get("title", "").strip('"\'')
    word = next((slug(w) for w in re.findall(r"[A-Za-z0-9]+", title)
                 if slug(w) not in STOPWORDS), "work")
    return f"{surname}-{year}-{word}"


def literature_notes(sources_dir, root):
    notes = {}
    for p in sorted(Path(sources_dir).rglob("*.md")):
        fm = parse_frontmatter(p.read_text(encoding="utf-8",
                                           errors="replace"))
        if fm.get("literature", "").lower() != "true":
            continue
        key = fm.get("citekey", "").strip('"\'') or derive_citekey(fm)
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        notes.setdefault(key, []).append(rel)
    return notes


def build_register(sources_dir, root):
    notes = literature_notes(sources_dir, root)
    collisions = {k: v for k, v in notes.items() if len(v) > 1}
    register = {"citekeys": {k: v[0] for k, v in notes.items()
                             if len(v) == 1}}
    return register, collisions


def check(sources_dir, register_path, root, pages_dir=None):
    problems = []
    notes = literature_notes(sources_dir, root)
    for key, paths in notes.items():
        if len(paths) > 1:
            problems.append(f"citekey {key} is not unique: "
                            f"{', '.join(paths)}")
    if not Path(register_path).exists():
        return [f"missing register: {register_path}"] + problems
    register = json.loads(Path(register_path).read_text(
        encoding="utf-8")).get("citekeys", {})
    for key, rel in notes.items():
        if key not in register:
            problems.append(f"literature note {rel[0]} citekey {key} "
                            f"missing from register")
    for key, rel in register.items():
        if not (root / rel).exists():
            problems.append(f"register citekey {key} -> missing {rel}")
        if key not in notes:
            problems.append(f"register citekey {key} has no literature "
                            f"note")
    if pages_dir:
        known = set(register) | set(notes)
        for p in sorted(Path(pages_dir).rglob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            for ref in sorted(set(re.findall(r"\[@([a-z0-9\-]+)\]", text))):
                if ref not in known:
                    problems.append(f"{p}: unresolved reference [@{ref}]")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-register")
    b.add_argument("--sources-dir", default=None)
    b.add_argument("--out", default=None)
    c = sub.add_parser("check")
    c.add_argument("--sources-dir", default=None)
    c.add_argument("--register", default=None)
    c.add_argument("--pages-dir", default=None)
    ns = ap.parse_args(argv)
    root = Path(ns.root)
    sdir = Path(ns.sources_dir) if ns.sources_dir else root / "wiki" / "sources"
    if not sdir.is_dir():
        print(f"missing sources dir: {sdir}", file=sys.stderr)
        return 2
    if ns.cmd == "build-register":
        register, collisions = build_register(sdir, root)
        if collisions:
            print(json.dumps({"collisions": collisions}, indent=2),
                  file=sys.stderr)
            return 1
        text = json.dumps(register, indent=2) + "\n"
        if ns.out:
            Path(ns.out).write_text(text, encoding="utf-8")
        print(text)
        return 0
    register = Path(ns.register) if ns.register else root / "wiki" / "citekeys.json"
    pages = Path(ns.pages_dir) if ns.pages_dir else root / "wiki"
    problems = check(sdir, register, root, pages)
    print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
