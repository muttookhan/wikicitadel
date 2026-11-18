#!/usr/bin/env python3
"""wiki_consolidate.py — topic-segmented sleep-time consolidation.

Marathon Round 3, Lane TA5 (Tier A). Pattern: LightMem's
sleep-time consolidation, re-implemented from the idea (no
code copied): while the wiki "sleeps" (the nightly-sweep
seam), raw material that was captured but never compiled is
grouped by TOPIC SEGMENT and one consolidation PROPOSAL is
filed per segment — the proposal lists the segment's
uncompiled files with sizes, the compiled pages nearest the
segment, and a suggested target page. Nothing is compiled,
moved or deleted by this tool; a compiler (human or agent,
in a later, directed pass) works from the proposals.

Definitions (stated, deterministic):
  uncompiled  a raw file under raw/ whose repo-relative path
              appears in NO compiled page's frontmatter
              `sources:` (the wiki's own compile record);
  segment     the file's first directory under raw/sources/
              when it lives there (raw/sources/<segment>/…),
              else its first directory under raw/, else
              "unsorted".

Output: one filing pair per segment under wiki/filings/ —
consolidate-<segment>-<date>.md / .json (manifest kind
"consolidation-proposals", holding every segment's entry) —
plus a JSON summary on stdout with --json. Standalone and
cron-safe: no network, no model calls, exit 0 on a clean
pass (including "nothing uncompiled"), 2 on usage error.

    python3 scripts/wiki_consolidate.py [--root DIR]
                                        [--date YYYY-MM-DD]
                                        [--dry-run] [--json]

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter, as_list = _wv.parse_frontmatter, _wv.as_list

TOKEN_RE = re.compile(r"[a-z0-9]+")


def compiled_sources(root: Path) -> set[str]:
    """Every raw path any compiled page claims in `sources:`."""
    out = set()
    wiki = Path(root) / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            fields, _ = parse_frontmatter(
                p.read_text(encoding="utf-8", errors="ignore"))
            for s in as_list((fields or {}).get("sources")):
                out.add(str(s))
    return out


def segment_of(rel: str) -> str:
    """The topic segment of a raw-relative path."""
    parts = Path(rel).parts          # e.g. raw/sources/<seg>/f.md
    if len(parts) >= 3 and parts[0] == "raw" and parts[1] == "sources":
        return parts[2] if len(parts) > 3 else "sources-root"
    if len(parts) >= 3 and parts[0] == "raw":
        return parts[1]
    return "unsorted"


def uncompiled_by_segment(root: Path) -> dict[str, list[dict]]:
    """Uncompiled raw files grouped by segment, each entry
    {path, bytes}; segments and files sorted."""
    root = Path(root)
    compiled = compiled_sources(root)
    groups: dict[str, list[dict]] = {}
    raw = root / "raw"
    if not raw.is_dir():
        return groups
    for p in sorted(raw.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if rel in compiled:
            continue
        groups.setdefault(segment_of(rel), []).append(
            {"path": rel, "bytes": p.stat().st_size})
    return {k: groups[k] for k in sorted(groups)}


def segment_tokens(segment: str) -> set[str]:
    return set(TOKEN_RE.findall(segment.lower()))


def nearest_pages(root: Path, segment: str, limit: int = 5) -> list[str]:
    """Compiled pages whose stem/title shares a token with
    the segment name — the proposal's suggested neighbourhood."""
    toks = segment_tokens(segment)
    if not toks:
        return []
    out = []
    wiki = Path(root) / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            fields, _ = parse_frontmatter(
                p.read_text(encoding="utf-8", errors="ignore"))
            name_toks = set(TOKEN_RE.findall(p.stem.lower())) | set(
                TOKEN_RE.findall(str((fields or {}).get("title")
                                     or "").lower()))
            if toks & name_toks:
                out.append(str(p.relative_to(root)))
    return out[:limit]


def analyse(root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    groups = uncompiled_by_segment(root)
    segments = []
    for segment, files in groups.items():
        slug = re.sub(r"[^a-z0-9]+", "-", segment.lower()).strip("-")
        segments.append({
            "segment": segment,
            "files": files,
            "file_count": len(files),
            "total_bytes": sum(f["bytes"] for f in files),
            "nearest_pages": nearest_pages(root, segment),
            "suggested_target": f"wiki/sources/{slug}.md",
            "status": "proposed",
        })
    return {
        "tool": "scripts/wiki_consolidate.py",
        "kind": "consolidation-proposals",
        "pattern": "LightMem sleep-time consolidation — "
                   "per-topic proposals only; nothing compiled",
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "date": today.isoformat(),
        "stats": {"segments": len(segments),
                  "uncompiled_files": sum(s["file_count"]
                                           for s in segments)},
        "segments": segments,
    }


def render_filing(manifest: dict, segment_entry: dict) -> str:
    d = manifest["date"]
    s = segment_entry
    lines = [
        "---",
        f"title: Consolidation proposal — {s['segment']} ({d})",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources: []",
        "tags: [consolidation, proposal, filings]",
        "status: draft",
        "stage: seedling",
        f"planted: {d}",
        f"tended: {d}",
        "work_type: record",
        "---",
        "",
        f"# Consolidation proposal — topic segment `{s['segment']}`",
        "",
        "> [!warning] PROPOSAL ONLY — nothing has been compiled",
        "> Filed by the sleep-time consolidation pass "
        "(`scripts/wiki_consolidate.py`, Marathon R3 TA5; "
        "LightMem pattern). A directed compile pass works "
        "from this list; this tool compiled, moved and "
        "deleted nothing.",
        "",
        f"{s['file_count']} uncompiled file(s), "
        f"{s['total_bytes']} bytes. Suggested target page: "
        f"`{s['suggested_target']}`.",
        "",
        "Nearest compiled pages: "
        + (", ".join(f"`{p}`" for p in s["nearest_pages"]) or "none"),
        "",
        "## Uncompiled files",
        "",
    ]
    lines += [f"- `{f['path']}` ({f['bytes']} bytes)" for f in s["files"]]
    lines.append("")
    return "\n".join(lines)


def write_filings(root: Path, manifest: dict) -> list[Path]:
    written = []
    filings = Path(root) / "wiki" / "filings"
    filings.mkdir(parents=True, exist_ok=True)
    for s in manifest["segments"]:
        slug = re.sub(r"[^a-z0-9]+", "-", s["segment"].lower()).strip("-")
        base = filings / f"consolidate-{slug}-{manifest['date']}"
        md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")
        md_path.write_text(render_filing(manifest, s), encoding="utf-8")
        json_path.write_text(json.dumps(
            {"tool": manifest["tool"], "kind": manifest["kind"],
             "date": manifest["date"], "segment_entry": s},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written += [md_path, json_path]
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the manifest JSON; write nothing")
    ap.add_argument("--json", action="store_true",
                    help="print the manifest JSON as the summary")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    today = date.fromisoformat(args.date) if args.date else date.today()
    manifest = analyse(root, today=today)
    if args.dry_run or args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    written = write_filings(root, manifest)
    st = manifest["stats"]
    print(f"consolidation: {st['uncompiled_files']} uncompiled "
          f"file(s) in {st['segments']} segment(s) -> "
          f"{len(written) // 2} proposal filing(s)")
    for s in manifest["segments"]:
        print(f"  {s['segment']}: {s['file_count']} file(s), "
              f"suggested target {s['suggested_target']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
