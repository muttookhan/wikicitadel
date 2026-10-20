#!/usr/bin/env python3
"""Small bookkeeping helpers for the LLM Wiki.

Commands:
  init-source "Title"   Create a raw source stub to fill in / replace.
  search "terms"        Grep wiki + raw for terms, print matching pages.
  lint                  Report orphans, broken wikilinks, pages missing
                        from wiki/index.md.
No external dependencies.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_SOURCES = ROOT / "raw" / "sources"
WIKI = ROOT / "wiki"


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "untitled"


def init_source(title: str) -> None:
    slug = slugify(title)
    path = RAW_SOURCES / f"{slug}.md"
    if path.exists():
        print(f"Already exists: {path.relative_to(ROOT)}")
        return
    path.write_text(
        f"# {title}\n\n<!-- Replace this stub with the full, unedited source text,\n"
        f"     or drop the original file in raw/sources/ under this name.\n"
        f"     Raw sources are immutable once filled in. -->\n\nSource:\nDate captured:\n\n",
        encoding="utf-8",
    )
    print(f"Created raw source stub: {path.relative_to(ROOT)}")
    print('Now fill it in, then tell your agent: "ingest this source"')


def iter_md(base: Path):
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def search(terms: str) -> None:
    needle = terms.lower()
    hits = 0
    for base in (WIKI, ROOT / "raw"):
        for p in iter_md(base):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if needle in text.lower():
                hits += 1
                print(p.relative_to(ROOT))
    if not hits:
        print("No matches.")


def lint() -> None:
    pages = iter_md(WIKI)
    by_stem = {}
    for p in pages:
        by_stem.setdefault(p.stem, []).append(p)
        # Obsidian-style full-path link target, e.g. wiki/concepts/llm-wiki
        by_stem.setdefault(str(p.relative_to(ROOT).with_suffix("")), []).append(p)

    index_text = ""
    index_path = WIKI / "index.md"
    if index_path.exists():
        index_text = index_path.read_text(encoding="utf-8", errors="ignore")

    inbound = {p: 0 for p in pages}
    broken = []
    link_re = re.compile(r"\[\[([^\]|#]+)")
    for p in pages:
        text = p.read_text(encoding="utf-8", errors="ignore")
        # Strip fenced code blocks and inline code spans first:
        # [[...]] shown as syntax inside code is not a link.
        # (Bug found by the validator, which
        # strips spans and correctly reported 0 broken links.)
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        text = re.sub(r"`[^`\n]*`", "", text)
        for target in link_re.findall(text):
            target = target.strip()
            cand = by_stem.get(target) or by_stem.get(Path(target).name)
            if cand:
                for c in cand:
                    if c != p:
                        inbound[c] += 1
            else:
                broken.append((p.relative_to(ROOT), target))

    print("== Lint report ==")
    print(f"Wiki pages: {len(pages)}")
    orphans = [str(p.relative_to(ROOT)) for p, n in inbound.items()
               if n == 0 and p.name not in ("index.md", "log.md")]
    print(f"\nOrphan pages (no inbound links): {len(orphans)}")
    for o in orphans:
        print(f"  - {o}")
    print(f"\nBroken wikilinks: {len(broken)}")
    for src, tgt in broken:
        print(f"  - {src} -> [[{tgt}]]")
    missing = [str(p.relative_to(ROOT)) for p in pages
               if p.name not in ("index.md", "log.md")
               and p.stem not in index_text and str(p.relative_to(ROOT).with_suffix("")) not in index_text]
    print(f"\nPages missing from index.md: {len(missing)}")
    for m in missing:
        print(f"  - {m}")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "init-source" and len(argv) >= 3:
        init_source(" ".join(argv[2:]))
    elif cmd == "search" and len(argv) >= 3:
        search(" ".join(argv[2:]))
    elif cmd == "lint":
        lint()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
