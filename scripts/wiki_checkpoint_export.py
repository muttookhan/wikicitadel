#!/usr/bin/env python3
"""wiki_checkpoint_export.py — a handoff package for selected pages.

Bundles the pages named on the command line into one package
directory a reader (or another agent) can pick up cold:

    <out>/
      pages/<repo-relative path>   the selected pages, verbatim
      COVERAGE.md                  what the selection covers:
                                   the pages, the raw sources
                                   each page rests on, and the
                                   date range their frontmatter
                                   spans
      OMISSIONS.md                 what a reader would expect
                                   that is NOT in the package:
                                   every outbound wikilink from
                                   a selected page whose target
                                   page exists in the tree but
                                   was not selected, plus the raw
                                   sources the pages cite (raw
                                   is never bundled)
      manifest.json                per-file sha256 + bytes for
                                   every bundled page, in
                                   deterministic (sorted) order

Deterministic: page order, omission order, and manifest order
are all sorted; the outputs carry no run timestamp, so two
exports of the same selection from the same tree are
byte-identical.

Nothing in the source tree is written — the package is built
entirely under --out, which must lie OUTSIDE the wiki tree.

Usage:
  python3 scripts/wiki_checkpoint_export.py --out DIR \
      wiki/<page>.md [wiki/<page>.md ...] [--root ROOT]

Exit codes: 0 ok · 2 usage error (unknown page, --out inside
the tree, no pages named).

Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def parse_frontmatter(text):
    """Minimal frontmatter reader for the fields this tool
    needs (title / created / updated / sources list). Returns
    {} when the page carries no frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    current_list = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            current_list = None
            if key == "sources":
                fields["sources"] = []
                current_list = "sources"
                if value.startswith("[") and value.endswith("]"):
                    fields["sources"] = [v.strip().strip("'\"")
                                          for v in value[1:-1].split(",")
                                          if v.strip()]
                    current_list = None
                elif value:
                    fields["sources"] = [value.strip("'\"")]
            elif key in ("title", "created", "updated"):
                fields[key] = value.strip("'\"")
            continue
        m = re.match(r"^\s+-\s+(.*)$", line)
        if m and current_list == "sources":
            fields["sources"].append(m.group(1).strip().strip("'\""))
    return fields


def page_index(root):
    """{resolution key: repo-relative page path} over wiki/**,
    resolving by path, by stem, and by title-less path without
    suffix — the wiki's usual precedence, reduced to pages."""
    wiki = root / "wiki"
    keys = {}
    pages = []
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            pages.append(rel)
            keys.setdefault(rel, rel)
            keys.setdefault(str(Path(rel).with_suffix("")), rel)
            keys.setdefault(Path(rel).stem, rel)
    return pages, keys


def resolve_link(keys, target):
    target = target.strip()
    for cand in (target, target + ".md" if not target.endswith(".md")
                 else target, Path(target).name,
                 Path(target).stem):
        if cand in keys:
            return keys[cand]
    return None


def build_package(root, out, selected):
    """Build the package; `selected` is a sorted list of
    repo-relative page paths that all exist under wiki/.
    Returns the manifest dict."""
    _all_pages, keys = page_index(root)
    records = []
    all_sources = []
    dates = []
    omissions = {}   # omitted page -> sorted list of linking pages
    for rel in selected:
        text = (root / rel).read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        for d in (fields.get("created"), fields.get("updated")):
            if d:
                dates.append(d)
        for s in fields.get("sources", []):
            if s not in all_sources:
                all_sources.append(s)
        for target in WIKILINK_RE.findall(text):
            dst = resolve_link(keys, target)
            if dst and dst not in selected and dst != rel:
                omissions.setdefault(dst, set()).add(rel)
        data = (root / rel).read_bytes()
        dest = out / "pages" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        records.append({"path": rel,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                        "title": fields.get("title", ""),
                        "sources": fields.get("sources", [])})
    all_sources.sort()
    date_range = (f"{min(dates)} to {max(dates)}" if dates
                  else "no dated pages in the selection")

    coverage = ["# Coverage — checkpoint export", "",
                f"Pages bundled: {len(records)}", "",
                "## Pages", ""]
    for r in records:
        title = f" — {r['title']}" if r["title"] else ""
        coverage.append(f"- `{r['path']}`{title}")
    coverage += ["", "## Sources the selection rests on", ""]
    if all_sources:
        coverage += [f"- `{s}`" for s in all_sources]
    else:
        coverage.append("- (no raw sources declared in frontmatter)")
    coverage += ["", f"## Date range (frontmatter created/updated)",
                 "", f"- {date_range}", ""]
    (out / "COVERAGE.md").write_text("\n".join(coverage),
                                     encoding="utf-8")

    omission_lines = ["# Omissions — NOT in this package", "",
                      "Pages a selected page links to that exist "
                      "in the tree but were not selected:", ""]
    if omissions:
        for dst in sorted(omissions):
            linked = ", ".join(f"`{p}`"
                               for p in sorted(omissions[dst]))
            omission_lines.append(f"- `{dst}` (linked from {linked})")
    else:
        omission_lines.append("- (none — the selection is "
                                "link-closed over the tree)")
    omission_lines += ["", "Raw sources cited by the selection "
                       "(raw is never bundled):", ""]
    if all_sources:
        omission_lines += [f"- `{s}`" for s in all_sources]
    else:
        omission_lines.append("- (none declared)")
    omission_lines.append("")
    (out / "OMISSIONS.md").write_text("\n".join(omission_lines),
                                      encoding="utf-8")

    manifest = {"tool": "wiki_checkpoint_export",
                "pages": records,
                "omitted_pages": sorted(omissions),
                "sources_referenced": all_sources,
                "date_range": date_range}
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main(argv):
    ap = argparse.ArgumentParser(
        description="Bundle selected wiki pages into a handoff "
                    "package (pages + COVERAGE + OMISSIONS + "
                    "manifest with hashes).")
    ap.add_argument("--out", required=True, type=Path,
                    help="package directory to create (outside "
                         "the wiki tree)")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repo root (default: this tool's repo)")
    ap.add_argument("pages", nargs="+",
                    help="repo-relative page paths (wiki/...)")
    args = ap.parse_args(argv[1:])
    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else \
        (Path.cwd() / args.out)
    out = out.resolve()
    if out == root or root in out.parents:
        print("error: --out must lie outside the wiki tree",
              file=sys.stderr)
        return 2
    selected = []
    for name in args.pages:
        rel = name.replace("\\", "/").lstrip("/")
        if not rel.startswith("wiki/") or \
                not (root / rel).is_file():
            print(f"error: no page at '{name}'", file=sys.stderr)
            return 2
        if rel not in selected:
            selected.append(rel)
    selected.sort()
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_package(root, out, selected)
    print(f"exported {len(manifest['pages'])} page(s) to {out}")
    print(f"omitted linked pages: "
          f"{len(manifest['omitted_pages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
