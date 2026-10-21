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

Link-type tally (Marathon R12 lane BA, ideas board line
182): the `tally` command extends this machinery with a
corpus-wide count by link TYPE, recomputed from the files
on every run (nothing is stored or carried forward):

  * internal-wikilink — a [[...]] wikilink occurrence in an
    in-scope page (the extraction above), with resolved /
    broken occurrence subcounts under this tool's own
    resolution semantics;
  * external-dereferenceable — an external URL occurrence
    (a Markdown [text](url) target or a bare URL) that is
    dereferenceable AS WRITTEN: an absolute http(s) URL
    whose parse yields a plausible host. This is a
    syntactic judgement only — no network is touched, and
    dereferenceable does not claim the target is alive;
  * external-unresolved — an external reference that cannot
    be dereferenced as written: a malformed or hostless
    http(s) reference, a protocol-relative //host reference,
    or a Markdown link target in the external shape (carries
    "://" or starts "www.") that fails the parse above.

`tally` is a report in the same idiom: exit 0 whenever the
tally is produced, exit 2 on usage error.

Usage:
  python3 scripts/wiki_link_health.py [--root PATH] report
      [--page <name-or-path>] [--json]
  python3 scripts/wiki_link_health.py [--root PATH] emit
      [--out DIR]
  python3 scripts/wiki_link_health.py [--root PATH] tally
      [--json]
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


# ------------------------------------------------------------ link-type tally

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BARE_URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]+(?::\d+)?$")


def classify_external(url):
    """-> 'external-dereferenceable' | 'external-unresolved'.

    Syntactic only (no network): dereferenceable means an
    absolute http(s) URL whose parse yields a host that
    could be resolved — a dotted host name, localhost, or
    an IPv4 literal. Anything else external-shaped (no
    scheme, no host, a host with no dot, stray characters)
    is unresolved as written."""
    from urllib.parse import urlparse
    u = url.strip().strip("<>")
    if not u or any(ch.isspace() for ch in u):
        return "external-unresolved"
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return "external-unresolved"
    host = parsed.hostname or ""
    if not host or not HOST_RE.match(parsed.netloc.split("@")[-1]):
        return "external-unresolved"
    if host == "localhost" or "." in host:
        return "external-dereferenceable"
    return "external-unresolved"


def extract_external(text):
    """External URL occurrences in a page body (code stripped
    by the house convention, as for wikilinks). Markdown link
    targets are taken first and their spans removed, so a
    Markdown-linked URL is counted once, never again as a
    bare URL. A Markdown target counts as external when it
    carries '://', starts 'www.', or starts '//'; a bare
    occurrence counts when it is an http(s) URL or a
    protocol-relative //host reference."""
    body = strip_code(body_of(text))
    found = []
    spans = []
    for m in MD_LINK_RE.finditer(body):
        target = m.group(1).strip()
        if "://" in target or target.startswith("www.") \
                or target.startswith("//"):
            found.append(target)
            spans.append(m.span(1))
    chars = list(body)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    rest = "".join(chars)
    for m in BARE_URL_RE.finditer(rest):
        found.append(m.group(0).rstrip(".,;:!?"))
    for m in re.finditer(r"(?<![\w/:])//[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
                         r"(?:/[^\s<>\)\]\"']*)?", rest):
        found.append(m.group(0))
    return found


def compute_tally(root):
    """The link-type tally, recomputed from the files.
    Returns (tally, per_page): tally holds the three type
    counts plus internal resolved/broken subcounts and the
    pages scanned; per_page is a list of per-page dicts in
    path order (in-scope pages only, as in compute())."""
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
        t = target.strip()
        for cand in (t, t[:-3] if t.endswith(".md") else t,
                     Path(t).name, Path(t).stem):
            if cand in keys:
                return keys[cand]
        if (root / t).is_file():
            return f"disk:{t}"
        return None

    scoped = [p.relative_to(root).as_posix() for p in all_pages
              if in_scope(p.relative_to(root).as_posix())]
    tally = {"internal-wikilink": 0,
             "internal-wikilink-resolved": 0,
             "internal-wikilink-broken": 0,
             "external-dereferenceable": 0,
             "external-unresolved": 0,
             "pages_scanned": len(scoped)}
    per_page = []
    for rel in scoped:
        page = {"page": rel, "internal-wikilink": 0,
                "external-dereferenceable": 0,
                "external-unresolved": 0}
        for t in extract_targets(texts[rel]):
            tally["internal-wikilink"] += 1
            page["internal-wikilink"] += 1
            if resolve(t):
                tally["internal-wikilink-resolved"] += 1
            else:
                tally["internal-wikilink-broken"] += 1
        for u in extract_external(texts[rel]):
            kind = classify_external(u)
            tally[kind] += 1
            page[kind] += 1
        per_page.append(page)
    return tally, per_page


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


def cmd_tally(root, args):
    tally, per_page = compute_tally(root)
    if args.json:
        print(json.dumps({"tally": tally, "pages": per_page},
                         indent=2, ensure_ascii=False))
    else:
        print(f"Link-type tally — {tally['pages_scanned']} "
              f"in-scope page(s), recomputed from files:")
        print(f"  internal-wikilink: "
              f"{tally['internal-wikilink']} "
              f"(resolved {tally['internal-wikilink-resolved']}, "
              f"broken {tally['internal-wikilink-broken']})")
        print(f"  external-dereferenceable: "
              f"{tally['external-dereferenceable']}")
        print(f"  external-unresolved: "
              f"{tally['external-unresolved']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Per-page link-health report + Lens "
                    "inspector data file.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: the checkout "
                         "holding this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tally")
    p.add_argument("--json", action="store_true")
    p.add_argument("--root", default=argparse.SUPPRESS)
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
        if args.cmd == "tally":
            return cmd_tally(root, args)
    except HealthError as exc:
        print(f"wiki_link_health: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
