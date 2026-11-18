#!/usr/bin/env python3
"""wiki_lens_propose.py — proposed lenses from un-filed sources.

Tier A harvest row "exocortex": proposed lenses — when
>= 2 un-filed sources share a tag, a candidate category is
drafted with status "proposed"; only the owner approves /
merges / rejects it (pattern: exocortex, MIT — re-verified
in the 2026-10-19 feature survey; re-implemented here from
the idea, no code copied). The owner's tags are copied
VERBATIM, never synonym-merged.

What this tool does, and only this:

  1. Scan raw/ for sources with NO compiled page. A source
     counts as filed when (a) any wiki page's frontmatter
     `sources:` list names it, or (b) a page exists under
     wiki/sources/ whose file stem matches the source's
     stem. Everything else under raw/ is un-filed.
  2. Group the un-filed sources by each tag they carry
     (frontmatter `tags:` in a Markdown source, verbatim)
     and, for sources with no tags, by their raw/ parent
     directory (the collection they already sit in).
  3. Propose a lens for every group of >= 2: the lens name
     (the tag verbatim, or the directory name), its member
     sources, the grouping basis, and status "proposed".

It NEVER auto-files: with no --out it writes nothing at
all (the report goes to stdout). With --out PATH it writes
exactly that one proposal file (JSON with --format json,
Markdown by default) — wherever the caller points it,
which should be a staging / filings location, never a
compiled page — and nothing else in the tree changes.
Approval, merging and rejection are the owner's acts,
recorded elsewhere; this tool has no verb for them.

    python3 scripts/wiki_lens_propose.py [--root DIR]
            [--out PATH] [--format md|json] [--min-group N]

Exit codes: 0 ok (including "no proposals") · 2 usage error.
Sidecar/annotation files ( *.annotations.jsonl, *.ingest.json )
and hidden files are not sources and are never counted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = (".annotations.jsonl", ".ingest.json")
FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)


def _parse_list_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [v.strip().strip("\"'") for v in inner.split(",")
                if v.strip()]
    if raw in ("", "~", "null", "[]"):
        return []
    return [raw.strip("\"'")]


def parse_frontmatter_lists(text: str, keys=("sources", "tags")):
    """Frontmatter list fields, for both inline `[a, b]` and
    block `- item` spellings. Returns {key: [values]} with
    only the requested keys that are present. Deliberately a
    small reader for these two fields, not a YAML parser."""
    out: dict[str, list] = {}
    m = FM_RE.match(text or "")
    if not m:
        return out
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", lines[i])
        if km and km.group(1) in keys:
            key, rest = km.group(1), km.group(2)
            if rest.strip():
                out[key] = _parse_list_value(rest)
                i += 1
                continue
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                items.append(re.sub(r"^\s+-\s+", "", lines[j])
                             .strip().strip("\"'"))
                j += 1
            out[key] = items
            i = j
            continue
        i += 1
    return out


def compiled_source_refs(root: Path) -> set[str]:
    """Every raw path named in any wiki page's frontmatter
    `sources:`, normalised to a repo-relative posix path."""
    refs = set()
    wiki = root / "wiki"
    if not wiki.exists():
        return refs
    for p in sorted(wiki.rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for value in parse_frontmatter_lists(text).get("sources", []):
            v = str(value).replace("\\", "/").lstrip("./")
            refs.add(v)
    return refs


def scan_unfiled(root: Path) -> list[dict]:
    """All raw sources with no compiled page:
    [{"path", "tags": [...], "collection": parent dir rel}]."""
    raw = root / "raw"
    if not raw.exists():
        return []
    refs = compiled_source_refs(root)
    source_stems = set()
    src_dir = root / "wiki" / "sources"
    if src_dir.exists():
        source_stems = {p.stem for p in src_dir.glob("*.md")}
    out = []
    for p in sorted(raw.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if any(p.name.endswith(s) for s in SKIP_SUFFIXES):
            continue
        rel = p.relative_to(root).as_posix()
        if rel in refs or p.stem in source_stems:
            continue
        tags = []
        if p.suffix.lower() in (".md", ".txt"):
            tags = parse_frontmatter_lists(
                p.read_text(encoding="utf-8", errors="ignore"),
                keys=("tags",)).get("tags", [])
        out.append({"path": rel, "tags": tags,
                    "collection": p.parent.relative_to(root).as_posix()
                    if p.parent != root else "raw"})
    return out


def propose_lenses(unfiled, min_group=2) -> dict:
    """Group un-filed sources into proposed lenses.
    Returns {"proposals": [...], "ungrouped": [...]}.
    A tagged source joins one lens per tag it carries
    (verbatim); an untagged source joins its collection's
    lens. A group smaller than min_group proposes nothing
    and its members are ungrouped (unless another group
    claimed them)."""
    by_tag: dict[str, list] = defaultdict(list)
    by_dir: dict[str, list] = defaultdict(list)
    for item in unfiled:
        if item["tags"]:
            for tag in item["tags"]:
                by_tag[tag].append(item["path"])
        else:
            by_dir[item["collection"]].append(item["path"])
    proposals = []
    claimed = set()
    for tag in sorted(by_tag):
        members = sorted(by_tag[tag])
        if len(members) >= min_group:
            proposals.append({
                "name": tag, "basis": "shared tag (verbatim)",
                "tag": tag, "status": "proposed",
                "members": members,
                "rationale": f"{len(members)} un-filed sources share "
                             f"the tag '{tag}'"})
            claimed.update(members)
    for coll in sorted(by_dir):
        members = sorted(by_dir[coll])
        if len(members) >= min_group:
            name = Path(coll).name or coll
            proposals.append({
                "name": name, "basis": "shared collection (raw directory)",
                "tag": None, "status": "proposed",
                "members": members,
                "rationale": f"{len(members)} un-filed sources sit in "
                             f"{coll}/ with no compiled page"})
            claimed.update(members)
    proposals.sort(key=lambda r: (r["basis"], r["name"]))
    ungrouped = sorted(i["path"] for i in unfiled
                       if i["path"] not in claimed)
    return {"proposals": proposals, "ungrouped": ungrouped}


def build_report(root: Path, min_group=2) -> dict:
    unfiled = scan_unfiled(root)
    grouped = propose_lenses(unfiled, min_group=min_group)
    return {"kind": "lens-proposals", "status": "proposed",
            "note": "Proposals only — nothing is filed by this "
                    "tool; a lens stands only when the owner "
                    "approves it.",
            "unfiled_count": len(unfiled),
            "unfiled": unfiled,
            **grouped}


def render_md(report: dict) -> str:
    lines = ["# Proposed lenses from un-filed sources",
             "",
             report["note"],
             "",
             f"Un-filed sources scanned: {report['unfiled_count']}",
             ""]
    if not report["proposals"]:
        lines += ["No lens proposed: no group of un-filed sources "
                  "reaches the minimum size.", ""]
    for prop in report["proposals"]:
        lines += [f"## Proposed lens: {prop['name']}",
                  "",
                  f"- status: {prop['status']}",
                  f"- basis: {prop['basis']}",
                  f"- rationale: {prop['rationale']}",
                  "- members:"]
        lines += [f"  - {m}" for m in prop["members"]]
        lines.append("")
    if report["ungrouped"]:
        lines += ["## Ungrouped un-filed sources", ""]
        lines += [f"- {u}" for u in report["ungrouped"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None,
                    help="write the proposal file to this path "
                         "(default: print only, write nothing)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--min-group", type=int, default=2)
    args = ap.parse_args(argv)
    if args.min_group < 2:
        print("error: --min-group must be >= 2", file=sys.stderr)
        return 2
    report = build_report(args.root, min_group=args.min_group)
    text = json.dumps(report, indent=1) if args.format == "json" \
        else render_md(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + ("\n" if not text.endswith("\n")
                                    else ""), encoding="utf-8")
        print(f"proposal file written: {args.out} "
              f"({len(report['proposals'])} proposed lens(es), "
              f"{report['unfiled_count']} un-filed source(s)) — "
              f"nothing filed")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
