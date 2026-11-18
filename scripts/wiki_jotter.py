#!/usr/bin/env python3
"""wiki_jotter.py — the Jotter pattern (Marathon R7, lane BB).

Board line (wiki/ideas.md, Round-5 Tier A): "The Jotter pattern
for source records — re-implemented only (GPL): source records
embedded in frontmatter so they travel with the page; a
reverse-citation ('cited-by') listing over the corpus; an
unconnected-notes report for index health (Jotter, Codeberg,
GPL-3.0-or-later — pattern only, no code)".

LICENCE DISCIPLINE: Jotter is GPL-3.0-or-later. NOTHING here is
copied from it — no code, no text, no file layout. Only the
three IDEAS are re-implemented in our own idiom (stdlib,
report-only tools, JSON-on-stdout like the rest of scripts/):

(a) SOURCE RECORDS IN FRONTMATTER. A page may carry a
    `source_record:` block in its frontmatter — the page's own
    bibliographic record, travelling with the page instead of
    living in a separate database. The stated shape is declared
    as data in evaluation/source-record-schema.json and is:

        source_record:
          title: "..."            (required)
          authors: [Name, ...]    (optional list or string)
          year: 2026              (optional, 4-digit)
          venue: "..."            (optional: journal/site/publisher)
          url: "https://..."      (one of url/doi/raw required)
          doi: "10...."           (one of url/doi/raw required)
          raw: "raw/sources/..."  (one of url/doi/raw required)
          accessed: YYYY-MM-DD    (optional)
          language: en            (optional)

    `validate` checks every page carrying a block against the
    shape: required title, at least one locator, a sane year,
    an ISO accessed date. Report only.

(b) REVERSE CITATIONS. `cited-by [--target PAGE]` builds the
    citation graph from frontmatter `sources:` lists,
    `^[cite: ...]` markers and `[[wikilinks]]`, then inverts
    it: for each target, the pages that cite it. Without a
    target it reports every target with at least one citer.

(c) UNCONNECTED NOTES. `unconnected` is the standalone report
    form of the machinery the Lens briefing already computes
    inline (orphans in tools/lens/build_lens.py): pages with
    NO graph neighbours (no links in or out) and/or pages
    absent from wiki/index.md. Two distinct findings — a page
    can be indexed yet unconnected, or linked yet unindexed —
    reported separately, never merged into one count.

All three subcommands are REPORT ONLY: nothing is edited.

    python3 scripts/wiki_jotter.py [--root DIR] validate [--plain]
    python3 scripts/wiki_jotter.py [--root DIR] cited-by [--target P] [--plain]
    python3 scripts/wiki_jotter.py [--root DIR] unconnected [--plain]

Exit: validate 0 clean / 1 problems; cited-by 0 always (a
listing); unconnected 0 none / 1 any unconnected or unindexed.
2 = usage. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_REL = Path("evaluation/source-record-schema.json")
REQUIRED_FIELDS = ("title",)
LOCATOR_FIELDS = ("url", "doi", "raw")
KNOWN_FIELDS = {"title", "authors", "year", "venue", "url",
                "doi", "raw", "accessed", "language"}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)")


# ------------------------------------------------------------ frontmatter

def split_frontmatter(text: str):
    """(frontmatter_lines, body) — frontmatter_lines is None
    when the page has none."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    return text[3:end].splitlines(), text[end + 4:]


def parse_source_record(fm_lines) -> dict | None:
    """Parse the indented `source_record:` block (a small,
    stated YAML subset: `key: value` lines indented under the
    block key; flow lists [a, b]). None when absent."""
    if fm_lines is None:
        return None
    record = None
    for line in fm_lines:
        if re.match(r"^source_record:\s*$", line):
            record = {}
            continue
        if record is not None:
            if line and not line[0].isspace():
                break  # next top-level key ends the block
            m = re.match(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$", line)
            if m:
                record[m.group(1).lower()] = m.group(2).strip()
    return record


def parse_sources_list(fm_lines) -> list[str]:
    if fm_lines is None:
        return []
    out = []
    in_sources = False
    for line in fm_lines:
        if re.match(r"^sources:\s*$", line):
            in_sources = True
            continue
        if re.match(r"^sources:\s*\[(.*)\]\s*$", line):
            inner = re.match(r"^sources:\s*\[(.*)\]\s*$", line).group(1)
            return [s.strip().strip("\"'") for s in inner.split(",")
                    if s.strip()]
        if in_sources:
            m = re.match(r"^\s*-\s+(.+)$", line)
            if m:
                out.append(m.group(1).strip().strip("\"'"))
                continue
            if line and not line[0].isspace():
                break
    return out


def _pages(root: Path):
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    return sorted(wiki.rglob("*.md"))


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)) if p.is_relative_to(root) else str(p)


# ------------------------------------------------------------ (a) validate

def validate_record(record: dict) -> list[str]:
    problems = []
    for f in REQUIRED_FIELDS:
        if not record.get(f, "").strip("\"'"):
            problems.append(f"source_record missing required field: {f}")
    if not any(record.get(f, "").strip("\"'") for f in LOCATOR_FIELDS):
        problems.append("source_record has no locator "
                        "(one of url / doi / raw is required)")
    for f in record:
        if f not in KNOWN_FIELDS:
            problems.append(f"source_record unknown field: {f}")
    year = record.get("year", "").strip("\"'")
    if year and not re.fullmatch(r"\d{4}", year):
        problems.append(f"source_record year is not YYYY: {year}")
    accessed = record.get("accessed", "").strip("\"'")
    if accessed and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", accessed):
        problems.append(f"source_record accessed is not YYYY-MM-DD: {accessed}")
    doi = record.get("doi", "").strip("\"'")
    if doi and not doi.startswith("10."):
        problems.append(f"source_record doi does not look like a DOI: {doi}")
    return problems


def validate(root: Path) -> dict:
    pages = []
    total_problems = 0
    for p in _pages(root):
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _ = split_frontmatter(text)
        record = parse_source_record(fm)
        if record is None:
            continue
        problems = validate_record(record)
        pages.append({"page": _rel(root, p), "record": record,
                      "problems": problems})
        total_problems += len(problems)
    return {"tool": "scripts/wiki_jotter.py", "kind": "jotter-validate",
            "schema": str(SCHEMA_REL),
            "stats": {"pages_with_records": len(pages),
                      "problems": total_problems},
            "pages": pages}


# ------------------------------------------------------------ (b) cited-by

def _normalise_target(raw: str, root: Path) -> str:
    t = raw.strip().strip("\"'")
    if t.startswith("raw/"):
        return t
    if not t.endswith(".md"):
        t += ".md"
    if not t.startswith("wiki/"):
        t = "wiki/" + t
    return t


def citation_graph(root: Path) -> dict[str, set[str]]:
    """target (repo-relative path) -> set of citing pages."""
    graph: dict[str, set[str]] = {}
    stems = {}
    for p in _pages(root):
        stems[p.stem] = _rel(root, p)
    for p in _pages(root):
        rel = _rel(root, p)
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        targets = set()
        for s in parse_sources_list(fm):
            targets.add(s if s.startswith("raw/") else _normalise_target(s, root))
        for m in CITE_RE.finditer(text):
            targets.add(m.group(1))
        for m in WIKILINK_RE.finditer(body):
            link = m.group(1).strip()
            if link in stems:
                targets.add(stems[link])
            elif "/" in link:
                targets.add(_normalise_target(link, root))
        targets.discard(rel)
        for t in targets:
            graph.setdefault(t, set()).add(rel)
    return graph


def cited_by(root: Path, target: str | None = None) -> dict:
    graph = citation_graph(root)
    if target:
        t = _normalise_target(target, root)
        # A raw/ target or bare stem may need the stem lookup.
        citers = sorted(graph.get(t, set()))
        if not citers and "/" not in target and not target.startswith("raw/"):
            for k, v in graph.items():
                if Path(k).stem == target:
                    citers = sorted(v)
                    t = k
                    break
        return {"tool": "scripts/wiki_jotter.py", "kind": "jotter-cited-by",
                "target": t, "cited_by": citers, "count": len(citers)}
    listing = [{"target": t, "cited_by": sorted(v), "count": len(v)}
               for t, v in sorted(graph.items()) if v]
    return {"tool": "scripts/wiki_jotter.py", "kind": "jotter-cited-by",
            "targets": listing,
            "stats": {"targets_with_citers": len(listing),
                      "citation_edges": sum(x["count"] for x in listing)}}


# ------------------------------------------------------------ (c) unconnected

def _index_targets(root: Path) -> set[str]:
    index = root / "wiki" / "index.md"
    if not index.is_file():
        return set()
    text = index.read_text(encoding="utf-8", errors="replace")
    stems = {p.stem: _rel(root, p) for p in _pages(root)}
    out = set()
    for m in WIKILINK_RE.finditer(text):
        link = m.group(1).strip()
        if link in stems:
            out.add(stems[link])
    return out


def unconnected(root: Path) -> dict:
    graph = citation_graph(root)
    cited = set(graph.keys())
    citing = set()
    for v in graph.values():
        citing |= v
    indexed = _index_targets(root)
    no_neighbours, not_indexed = [], []
    for p in _pages(root):
        rel = _rel(root, p)
        if rel in ("wiki/index.md", "wiki/log.md"):
            continue
        if rel not in cited and rel not in citing:
            no_neighbours.append(rel)
        if rel not in indexed:
            not_indexed.append(rel)
    return {"tool": "scripts/wiki_jotter.py",
            "kind": "jotter-unconnected-report",
            "stats": {"pages": len(_pages(root)),
                      "no_neighbours": len(no_neighbours),
                      "not_in_index": len(not_indexed)},
            "no_neighbours": sorted(no_neighbours),
            "not_in_index": sorted(not_indexed)}


# ------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--plain", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "cited-by", "unconnected"):
        sp = sub.add_parser(name)
        sp.add_argument("--plain", action="store_true",
                        default=argparse.SUPPRESS)
        if name == "cited-by":
            sp.add_argument("--target", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "validate":
        report = validate(root)
        if args.plain:
            st = report["stats"]
            print(f"jotter validate: {st['pages_with_records']} record(s), "
                  f"{st['problems']} problem(s)")
            for pg in report["pages"]:
                for prob in pg["problems"]:
                    print(f"  {pg['page']}: {prob}")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["stats"]["problems"] else 0
    if args.cmd == "cited-by":
        report = cited_by(root, args.target)
        if args.plain:
            if "target" in report:
                print(f"{report['target']}: cited by {report['count']} page(s)")
                for c in report["cited_by"]:
                    print(f"  {c}")
            else:
                for t in report["targets"]:
                    print(f"{t['target']}: {t['count']} citer(s)")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    report = unconnected(root)
    if args.plain:
        st = report["stats"]
        print(f"unconnected: {st['no_neighbours']} with no neighbours; "
              f"{st['not_in_index']} not in index (of {st['pages']} pages)")
        for p in report["no_neighbours"]:
            print(f"  NO-NEIGHBOURS: {p}")
        for p in report["not_in_index"]:
            print(f"  NOT-IN-INDEX: {p}")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if (report["no_neighbours"] or report["not_in_index"]) else 0


if __name__ == "__main__":
    sys.exit(main())
