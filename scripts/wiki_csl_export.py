#!/usr/bin/env python3
"""wiki_csl_export.py — generated CSL-JSON bibliography export.

Marathon R10 lane BB (ideas board R8 deep-dive, Tier A;
Citation.js pattern, MIT — pattern only, implemented in stdlib).
A DERIVED CSL-JSON representation of the citekeys register
(built by scripts/wiki_citekeys.py from literature notes; the
register stays the record). The export is generated into
evaluation/citekeys-csl.json, regeneration is byte-stable
(sorted keys, fixed formatting, no timestamps), and `check`
verifies the export matches the register + note frontmatter.
Fields the record does not carry are OMITTED, never invented:
an entry carries id, type ("document" — the register asserts no
finer CSL type), the note path as `note`, and title / author /
issued only where the note's frontmatter states them.

Usage: build [--out FILE] | check [--out FILE]
Exit 0 ok; 1 check mismatch; 2 usage error. Stdlib only.
"""
import argparse, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evaluation" / "citekeys-csl.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_export(root=None):
    root = Path(root) if root else ROOT
    ck = _load("wiki_citekeys")
    register, _collisions = ck.build_register(
        root / "wiki" / "sources", root)
    entries = []
    for key in sorted(register["citekeys"]):
        rel = register["citekeys"][key]
        entry = {"id": key, "type": "document", "note": rel}
        note = root / rel
        if note.is_file():
            fm = ck.parse_frontmatter(note.read_text(
                encoding="utf-8", errors="replace"))
            title = fm.get("title", "").strip("\"'")
            if title:
                entry["title"] = title
            authors = fm.get("authors", "").strip("[]").strip()
            if authors:
                entry["author"] = [
                    {"family": a.strip().split()[-1],
                     "given": " ".join(a.strip().split()[:-1])}
                    for a in authors.replace(" and ", ",")
                    .split(",") if a.strip()]
            year = fm.get("year", "").strip()
            if year.isdigit():
                entry["issued"] = {"date-parts": [[int(year)]]}
        entries.append(entry)
    return entries


def render(entries):
    return json.dumps(entries, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name)
        p.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = render(build_export())
    if a.cmd == "build":
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}: {len(json.loads(text))} entr(ies)")
        return 0
    cur = Path(a.out)
    if not cur.is_file():
        print(f"missing export: {a.out} (run build)")
        return 1
    if cur.read_text(encoding="utf-8") != text:
        print("export does not match the citekeys register")
        return 1
    print("export matches the citekeys register")
    return 0


if __name__ == "__main__":
    sys.exit(main())
