#!/usr/bin/env python3
"""CN6a — nightly index re-derivation / fixity comparison.

Item: CN6a (EverOS cascade sketch, from the project's
global-landscape research notes):
every index is a derived, rebuildable artefact, and a nightly
fixity job re-derives one index from source and compares it —
divergence is a preservation incident, not a sync bug.

This tool re-derives `wiki/index.md` from the pages on disk
(each page's stem, category from its directory, and a summary
from its frontmatter title / first body line), then diffs the
re-derivation against the filed index:

  - pages on disk with no index entry (unfiled pages);
  - index entries naming no page on disk (stale entries);
  - entries filed under a different section than the page's
    directory derives (misplaced; a compound filed heading
    such as "Queries / lint reports" or "Access & Black Box"
    is read by its first component, the category it names
    first — the rest of the heading is curation, not drift);
  - entries whose filed summary differs from the derived one
    (summary drift — the filed summary is hand-written, so
    this class is informational: it shows where the hand
    summary and the page have moved apart);
  - duplicate index entries, and overall entry order.

Report-only by default: the tool NEVER overwrites the filed
index. `--write PATH` emits the re-derived index as a separate
proposal file for a human/agent to review and file through the
normal governed path; `--write` refuses to target the filed
index itself.

Exit codes: 0 = no structural drift (unfiled / stale /
misplaced / duplicate all zero), 1 = structural drift found,
2 = usage error (no wiki dir, no filed index, bad --write).

Usage:
  python3 scripts/wiki_index_fixity.py [--root DIR] [--json]
  python3 scripts/wiki_index_fixity.py --write /tmp/index-proposal.md

Stdlib only.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_STEMS = {"index", "log"}

CATEGORY_ORDER = [
    "Overview", "Sources", "Entities", "Concepts", "Syntheses",
    "Rules", "Queries", "Filings", "Access", "Talk", "Pages",
]
DIR_CATEGORY = {
    "sources": "Sources", "entities": "Entities",
    "concepts": "Concepts", "syntheses": "Syntheses",
    "rules": "Rules", "queries": "Queries", "filings": "Filings",
    "access": "Access", "talk": "Talk",
}
ENTRY_RE = re.compile(
    r"^\s*-\s+\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]\s*"
    r"(?:\u2014|--|-)?\s*(.*?)\s*$")
HEADING_RE = re.compile(r"^##\s+(.*?)\s*$")


def _load_validate():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def category_for(rel_to_wiki):
    """Category (index section) a page derives, from its path
    relative to wiki/."""
    parts = rel_to_wiki.parts
    if len(parts) == 1:
        return "Overview" if rel_to_wiki.stem == "overview" else "Pages"
    head = parts[0]
    if head in DIR_CATEGORY:
        return DIR_CATEGORY[head]
    return head.replace("-", " ").replace("_", " ").title()


def derive_summary(body, fields):
    """One-line summary derived from a page: the first plain
    body line (headings, callouts, tables, fences skipped),
    markdown decoration stripped, capped; falls back to the
    frontmatter title, then the stem."""
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ">", "|", "```", "---", "![", "<")):
            continue
        s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
        s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = s.replace("**", "").replace("`", "").strip()
        if not s:
            continue
        if len(s) > 160:
            s = s[:157].rstrip() + "\u2026"
        return s
    if fields and fields.get("title"):
        return str(fields["title"])
    return ""


def scan_pages(root):
    """[{stem, page, category, summary}] for every wiki page
    except the index and log themselves, deterministically
    ordered by (category order, stem)."""
    wiki = root / "wiki"
    pages = []
    if not wiki.is_dir():
        return pages
    validate = _load_validate()
    for path in sorted(wiki.rglob("*.md")):
        if path.stem in EXCLUDED_STEMS and path.parent == wiki:
            continue
        rel = path.relative_to(wiki)
        text = path.read_text(encoding="utf-8", errors="ignore")
        fields, body = validate.parse_frontmatter(text)
        pages.append({
            "stem": path.stem,
            "page": path.relative_to(root).as_posix(),
            "category": category_for(rel),
            "summary": derive_summary(body, fields),
        })

    def key(p):
        cat = p["category"]
        rank = (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER
                else len(CATEGORY_ORDER))
        return (rank, cat, p["stem"])

    pages.sort(key=key)
    return pages


def render_index(pages):
    """The re-derived index text, in this tool's canonical
    section order. No date is embedded: the same tree must
    derive the same bytes, or the fixity comparison is noise."""
    lines = [
        "# Index",
        "",
        "Catalog of every page in the wiki, re-derived from the"
        " pages on disk by `scripts/wiki_index_fixity.py` (CN6a"
        " proposal form — review before filing; the filed index"
        " is hand-maintained and is never overwritten by the"
        " tool).",
        "",
    ]
    current = None
    for p in pages:
        if p["category"] != current:
            current = p["category"]
            lines += [f"## {current}", ""]
        suffix = f" \u2014 {p['summary']}" if p["summary"] else ""
        lines.append(f"- [[{p['stem']}]]{suffix}")
    lines.append("")
    return "\n".join(lines)


def parse_index(text):
    """Parse a filed index: {stem: [{section, summary, line}]},
    plus the stem sequence in file order."""
    entries = {}
    sequence = []
    section = ""
    for lineno, line in enumerate(text.splitlines(), 1):
        h = HEADING_RE.match(line)
        if h:
            section = h.group(1)
            continue
        m = ENTRY_RE.match(line)
        if m:
            stem = m.group(1).strip()
            entries.setdefault(stem, []).append(
                {"section": section, "summary": m.group(2),
                 "line": lineno})
            sequence.append(stem)
    return entries, sequence


def compare(root, index_path=None):
    """The drift report (see module docstring)."""
    root = Path(root)
    index_path = Path(index_path) if index_path else root / "wiki" / "index.md"
    pages = scan_pages(root)
    derived_text = render_index(pages)
    filed_text = index_path.read_text(encoding="utf-8", errors="ignore")
    filed, sequence = parse_index(filed_text)
    on_disk = {p["stem"]: p for p in pages}

    unfiled = sorted(set(on_disk) - set(filed))
    stale = sorted(set(filed) - set(on_disk))
    duplicates = sorted(s for s, v in filed.items() if len(v) > 1)
    misplaced, summary_drift = [], []
    for stem in sorted(set(on_disk) & set(filed)):
        first = filed[stem][0]
        page = on_disk[stem]
        filed_key = re.split(r"[/&]", first["section"])[0].strip()
        if first["section"] and filed_key != page["category"]:
            misplaced.append({"stem": stem,
                              "filed_section": first["section"],
                              "derived_section": page["category"]})
        if first["summary"] != page["summary"]:
            summary_drift.append({"stem": stem,
                                  "filed_summary": first["summary"],
                                  "derived_summary": page["summary"]})
    common_filed = [s for s in sequence if s in on_disk]
    common_derived = [p["stem"] for p in pages if p["stem"] in filed]
    structural = bool(unfiled or stale or misplaced or duplicates)
    return {
        "tool": "wiki_index_fixity",
        "pages_on_disk": len(pages),
        "index_entries": sum(len(v) for v in filed.values()),
        "filed_sha256": hashlib.sha256(
            filed_text.encode("utf-8")).hexdigest(),
        "derived_sha256": hashlib.sha256(
            derived_text.encode("utf-8")).hexdigest(),
        "identical": filed_text == derived_text,
        "order_differs": common_filed != common_derived,
        "unfiled_pages": [{"stem": s, "page": on_disk[s]["page"],
                           "category": on_disk[s]["category"]}
                          for s in unfiled],
        "stale_entries": stale,
        "duplicate_entries": duplicates,
        "misplaced": misplaced,
        "summary_drift": summary_drift,
        "summary_drift_count": len(summary_drift),
        "structural_drift": structural,
        "derived_text": derived_text,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="Re-derive wiki/index.md from the pages on "
                    "disk and diff it against the filed index (CN6a).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--index", default=None,
                    help="filed index path (default: <root>/wiki/index.md)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", default=None, metavar="PATH",
                    help="write the re-derived index to PATH as a "
                         "proposal file (never the filed index itself)")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    if not (root / "wiki").is_dir():
        print(f"error: no wiki/ at {root}", file=sys.stderr)
        return 2
    index_path = (Path(args.index) if args.index
                  else root / "wiki" / "index.md")
    if not index_path.is_file():
        print(f"error: filed index not found: {index_path}",
              file=sys.stderr)
        return 2
    if args.write and Path(args.write).resolve() == index_path.resolve():
        print("error: --write may not target the filed index; "
              "the proposal is a separate file, reviewed before filing",
              file=sys.stderr)
        return 2
    report = compare(root, index_path)
    if args.write:
        Path(args.write).write_text(report["derived_text"],
                                    encoding="utf-8")
    if args.json:
        out = {k: v for k, v in report.items() if k != "derived_text"}
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print("== Index fixity (CN6a) ==")
        print(f"pages on disk: {report['pages_on_disk']}   "
              f"index entries: {report['index_entries']}   "
              f"identical: {report['identical']}")
        print(f"unfiled pages: {len(report['unfiled_pages'])}   "
              f"stale entries: {len(report['stale_entries'])}   "
              f"misplaced: {len(report['misplaced'])}   "
              f"duplicates: {len(report['duplicate_entries'])}   "
              f"summary drift: {report['summary_drift_count']}   "
              f"order differs: {report['order_differs']}")
        for p in report["unfiled_pages"]:
            print(f"  unfiled: {p['page']} (derives under {p['category']})")
        for s in report["stale_entries"]:
            print(f"  stale entry: [[{s}]] names no page on disk")
        for m in report["misplaced"]:
            print(f"  misplaced: [[{m['stem']}]] filed under "
                  f"{m['filed_section']!r}, derives under "
                  f"{m['derived_section']!r}")
        for s in report["duplicate_entries"]:
            print(f"  duplicate entry: [[{s}]]")
        if args.write:
            print(f"proposal written: {args.write} "
                  f"(filed index untouched)")
    return 1 if report["structural_drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
