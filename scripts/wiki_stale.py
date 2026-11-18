#!/usr/bin/env python3
"""Stale check for the LLM Wiki (Link's `stale` idea from the gist
comment thread): flag wiki pages whose cited raw sources have changed
underneath them since the page was last compiled.

For every page under wiki/:
  - parse YAML-ish frontmatter for `updated` and `sources`;
  - for each cited source, resolve it to a repo-relative path
    (bare slugs are resolved against raw/sources/ by exact
    token-set match on the file stem);
  - MISSING: the cited path does not exist on disk;
  - STALE:   `git log -1 --format=%cI -- <path>` shows the source's
             last change DATE is after the page's `updated` date
             (day granularity — frontmatter carries dates, not times);
  - NO-DATE: the page has no `updated` field, so staleness cannot
             be judged (its sources are still existence-checked).

Usage:  python3 scripts/wiki_stale.py
Exit code is always 0 — this is a report, not a gate.
Stdlib only.
"""
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
RAW_SOURCES = ROOT / "raw" / "sources"


def parse_frontmatter(text: str):
    """Return (fields dict, sources list) or (None, []) if no frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, []
    fm = m.group(1)
    fields = {}
    sources = []
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        key = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if key:
            name, val = key.group(1), key.group(2).strip()
            if name == "sources":
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        sources = [s.strip().strip("\"'") for s in inner.split(",")]
                elif val.startswith("- "):
                    sources = [val[2:].strip().strip("\"'")]
                elif val:
                    sources = [val.strip("\"'")]
                else:
                    # Block list: following indented "- item" lines.
                    j = i + 1
                    while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                        sources.append(
                            re.sub(r"^\s+-\s+", "", lines[j]).strip().strip("\"'"))
                        j += 1
                    i = j - 1
            else:
                fields[name] = val.strip("\"'")
        i += 1
    return fields, sources


def slug_tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def resolve_source(entry: str):
    """Resolve a frontmatter source entry to a repo-relative Path.

    Entries containing '/' are taken as paths. Bare slugs are matched
    against raw/sources/ files whose stem has the same token set
    (handles date-first vs date-last naming). Returns None when the
    entry cannot be resolved to an existing-or-once-existing path.
    """
    if "/" in entry:
        return Path(entry)
    if RAW_SOURCES.exists():
        for p in sorted(RAW_SOURCES.rglob("*")):
            if p.is_file() and slug_tokens(p.stem) == slug_tokens(entry):
                return p.relative_to(ROOT)
    return None


_git_cache = {}


def git_last_change_date(rel_path: Path):
    """Date of the last commit touching rel_path, or None."""
    key = str(rel_path)
    if key in _git_cache:
        return _git_cache[key]
    out = None
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%cI", "--", key],
            capture_output=True, text=True, timeout=30)
        txt = r.stdout.strip()
        if txt:
            out = date.fromisoformat(txt[:10])
    except Exception:
        out = None
    _git_cache[key] = out
    return out


def main(argv):
    pages = sorted(p for p in WIKI.rglob("*.md") if p.is_file())
    rows = []          # (status, page_rel, [detail lines])
    counts = {"OK": 0, "STALE": 0, "MISSING": 0, "NO-DATE": 0, "SKIP": 0}

    for p in pages:
        rel_page = p.relative_to(ROOT)
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, sources = parse_frontmatter(text)
        if fields is None:
            counts["SKIP"] += 1
            rows.append(("SKIP", rel_page, ["no frontmatter"]))
            continue
        if not sources:
            counts["SKIP"] += 1
            rows.append(("SKIP", rel_page, ["no sources cited"]))
            continue

        updated = None
        if fields.get("updated"):
            try:
                updated = date.fromisoformat(fields["updated"][:10])
            except ValueError:
                updated = None

        details = []
        has_missing = False
        has_stale = False
        for entry in sources:
            resolved = resolve_source(entry)
            if resolved is None:
                has_missing = True
                details.append(f"MISSING  {entry} (unresolvable citation)")
                continue
            if not (ROOT / resolved).exists():
                has_missing = True
                details.append(f"MISSING  {resolved} (not on disk)")
                continue
            if updated is not None:
                changed = git_last_change_date(resolved)
                if changed is not None and changed > updated:
                    has_stale = True
                    details.append(
                        f"STALE    {resolved} changed {changed} > page updated {updated}")
                elif changed is None:
                    details.append(f"NOTE     {resolved} (no git history found)")

        if has_missing:
            status = "MISSING"
        elif has_stale:
            status = "STALE"
        elif updated is None:
            status = "NO-DATE"
            details.append("page has no `updated` date — staleness not judged")
        else:
            status = "OK"
        counts[status] += 1
        if status != "OK":
            rows.append((status, rel_page, details))

    print("== Wiki stale check ==")
    print(f"Pages scanned: {len(pages)}\n")
    print(f"{'STATUS':<8} {'PAGE':<58} DETAIL")
    print("-" * 100)
    for status, rel_page, details in rows:
        first = details[0] if details else ""
        print(f"{status:<8} {str(rel_page):<58} {first}")
        for extra in details[1:]:
            print(f"{'':<8} {'':<58} {extra}")
    print("-" * 100)
    print("Summary: " + "  ".join(
        f"{k}={counts[k]}" for k in ("OK", "STALE", "MISSING", "NO-DATE", "SKIP")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
