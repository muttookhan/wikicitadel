#!/usr/bin/env python3
"""Per-page link-health for the Lens inspector — broken
wikilinks, missing targets and orphan status, computed over
the compiled layer (Marathon Round 3, Tier A row: Quartz /
LeafWiki per-page link-health in the Lens inspector).

Quartz and LeafWiki both surface, per page, whether its links
still resolve and whether anything links back. This tool
computes that report for this wiki's compiled layer and emits
it in two forms from ONE computation, so they can never drift:

  * a human / JSON report (`report`, the default command):
    one record per page — outbound wikilinks (resolved and
    broken, each broken target named), inbound count, orphan
    status (no inbound AND no resolved outbound), and a
    health verdict (ok / broken-links / orphan /
    broken-links+orphan);
  * the Lens-inspector data file (`emit`): the same records
    keyed by page path, written as JSON to
    <out>/link-health.json (default out: tools/lens/data —
    i.e. beside the Lens build's other data files, ready for
    the Lens build to copy into data/link-health.json; see
    the wiring note in this lane's manifest). The file shape
    is {"generated_by", "pages": {rel: record}, "summary"}.

Resolution semantics are the corpus's own, not a new
invention: a wikilink target resolves when it matches a page
by repo-relative path, by path without suffix, by file stem,
or by frontmatter title — the precedence scripts/
wiki_traverse.py (and the validator, search and Lens) use.
Wikilink extraction ignores fenced code blocks and inline
code, and strips heading fragments (#...) and display text
(|...), matching the validator's convention. Links to
non-page targets (raw/ paths that exist on disk) count as
resolved-non-page, not broken: [[raw/...]]-style references
and targets with a file extension that exists under the root
are checked on disk.

Scope: the compiled layer as the lint lanes define it —
wiki/**/*.md excluding wiki/filings/, wiki/talk/,
wiki/index.md and wiki/log.md (structural pages carry no
link-health verdict of their own, but they DO count as
inbound linkers: a page linked only from the index is not
an orphan in any honest sense — index links are counted
from a separate pass over ALL wiki pages including the
structural ones).

This is a report, not a gate: `report` exits 0 even when
broken links exist (they are findings, not tool failures);
exit 2 is a usage error (no wiki layer, bad arguments).
`--strict` makes report exit 1 when any page is unhealthy,
for callers that want a gate.

Usage:
  python3 scripts/wiki_link_health.py [--root PATH] report
      [--page <name-or-path>] [--json]
  python3 scripts/wiki_link_health.py [--root PATH] emit
      [--out DIR]
Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent

EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE_RE = re.compile(r"^```", re.M)


class HealthError(Exception):
    pass


# ------------------------------------------------------------ extraction

def strip_code(text):
    """Remove fenced blocks and inline code spans (the
    validator's convention: code never yields links)."""
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return re.sub(r"`[^`]*`", "", "\n".join(out))


def frontmatter_title(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        m = re.match(r"^title:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def body_of(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def extract_targets(text):
    return [m.group(1).strip()
            for m in LINK_RE.finditer(strip_code(body_of(text)))]


# ------------------------------------------------------------ computation

def iter_all_pages(root):
    wiki = Path(root) / "wiki"
    if not wiki.is_dir():
        raise HealthError(f"no wiki layer under {root}")
    return sorted(p for p in wiki.rglob("*.md") if p.is_file())


def in_scope(rel):
    return rel not in EXCLUDED_FILES and not any(
        rel.startswith(d) for d in EXCLUDED_DIRS)


def compute(root):
    """The one computation both outputs render. Returns
    (records, summary): records is a list of per-page dicts
    in path order."""
    root = Path(root)
    all_pages = iter_all_pages(root)
    keys = {}
    texts = {}
    for p in all_pages:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        texts[rel] = text
        keys.setdefault(rel, rel)
        keys.setdefault(str(Path(rel).with_suffix("")), rel)
        keys.setdefault(Path(rel).stem, rel)
        title = frontmatter_title(text)
        if title:
            keys.setdefault(title, rel)

    def resolve(target):
        """-> (page_rel | 'disk:<rel>' | None)"""
        t = target.strip()
        for cand in (t, t[:-3] if t.endswith(".md") else t,
                     Path(t).name, Path(t).stem):
            if cand in keys:
                return keys[cand]
        disk = root / t
        if disk.is_file():
            return f"disk:{t}"
        return None

    scoped = [p.relative_to(root).as_posix()
              for p in all_pages
              if in_scope(p.relative_to(root).as_posix())]
    outbound = {}
    inbound = {rel: set() for rel in scoped}
    for rel, text in texts.items():
        targets = extract_targets(text)
        resolved_pages = []
        for t in targets:
            r = resolve(t)
            if r and not r.startswith("disk:") and r != rel \
                    and r in inbound:
                inbound[r].add(rel)
            if rel in inbound:  # scoped source: record outbound
                resolved_pages.append((t, r))
        if rel in inbound:
            outbound[rel] = resolved_pages

    records = []
    for rel in scoped:
        outs = outbound.get(rel, [])
        ok = sorted({r for _t, r in outs
                     if r and not r.startswith("disk:")})
        nonpage = sorted({t for t, r in outs
                          if r and r.startswith("disk:")})
        broken = sorted({t for t, r in outs if r is None})
        in_n = len(inbound[rel])
        orphan = in_n == 0 and not ok
        verdict = ("broken-links+orphan" if broken and orphan
                   else "broken-links" if broken
                   else "orphan" if orphan else "ok")
        records.append({
            "page": rel,
            "outbound_resolved": ok,
            "outbound_nonpage": nonpage,
            "broken_targets": broken,
            "broken_count": len(broken),
            "inbound_count": in_n,
            "inbound_from": sorted(inbound[rel]),
            "orphan": orphan,
            "health": verdict,
        })
    summary = {
        "pages": len(records),
        "pages_ok": sum(1 for r in records if r["health"] == "ok"),
        "pages_with_broken_links":
            sum(1 for r in records if r["broken_count"]),
        "broken_links_total": sum(r["broken_count"] for r in records),
        "orphans": sum(1 for r in records if r["orphan"]),
    }
    return records, summary


# ------------------------------------------------------------ commands

def cmd_report(root, args):
    records, summary = compute(root)
    if args.page:
        want = args.page.strip()
        records = [r for r in records
                   if r["page"] == want
                   or Path(r["page"]).stem == want
                   or r["page"].endswith("/" + want)]
        if not records:
            raise HealthError(f"no in-scope page matches {want!r}")
    if args.json:
        print(json.dumps({"summary": summary, "pages": records},
                         indent=2, ensure_ascii=False))
    else:
        print(f"Link health — {summary['pages']} page(s): "
              f"{summary['pages_ok']} ok, "
              f"{summary['pages_with_broken_links']} with broken "
              f"links ({summary['broken_links_total']} target(s)), "
              f"{summary['orphans']} orphan(s)")
        for r in records:
            if r["health"] == "ok" and not args.page:
                continue
            print(f"  {r['page']}: {r['health']} "
                  f"(inbound={r['inbound_count']}, "
                  f"outbound={len(r['outbound_resolved'])})")
            for t in r["broken_targets"]:
                print(f"    broken: [[{t}]]")
    if args.strict and summary["pages_with_broken_links"] \
            or args.strict and summary["orphans"]:
        return 1
    return 0


def cmd_emit(root, args):
    records, summary = compute(root)
    out_dir = Path(args.out) if args.out else \
        Path(root) / "tools" / "lens" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "scripts/wiki_link_health.py emit",
        "inspector_data": True,
        "note": "Per-page link health for the Lens inspector: "
                "keyed by repo-relative page path. The Lens "
                "build copies this file to data/link-health.json "
                "when present (wiring proposed in the build "
                "manifest).",
        "summary": summary,
        "pages": {r["page"]: r for r in records},
    }
    dest = out_dir / "link-health.json"
    dest.write_text(json.dumps(payload, indent=1,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {dest}: {summary['pages']} page(s), "
          f"{summary['broken_links_total']} broken target(s), "
          f"{summary['orphans']} orphan(s)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Per-page link-health report + Lens "
                    "inspector data file.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: the checkout "
                         "holding this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report")
    p.add_argument("--page", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 when any page is unhealthy")
    p.add_argument("--root", default=argparse.SUPPRESS)
    p = sub.add_parser("emit")
    p.add_argument("--out", default=None,
                   help="output dir (default: <root>/tools/lens/data)")
    p.add_argument("--root", default=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root) if getattr(args, "root", None) \
        else DEFAULT_ROOT
    try:
        if args.cmd == "report":
            return cmd_report(root, args)
        if args.cmd == "emit":
            return cmd_emit(root, args)
    except HealthError as exc:
        print(f"wiki_link_health: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
