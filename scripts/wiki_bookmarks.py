#!/usr/bin/env python3
"""wiki_bookmarks.py — browser-bookmarks importer
(Marathon R7, lane BB).

Board line (wiki/ideas.md, Round-5 Tier A): "A browser-bookmarks
importer — reads a bookmark file the owner hands it (Chrome
Bookmarks JSON / Netscape HTML / Firefox backup), stages
templated capture drafts (never straight into wiki/),
URL-deduped against a register; manual-first — no automatic
sync (Bookmarks Sync design, MIT)".

MANUAL-FIRST, BY CONSTRUCTION:
  * Input is a FILE PATH the owner hands the tool. Nothing
    here opens a browser, reads a browser profile directory,
    polls anything, or syncs. A URL given as the input is
    refused — there is no fetch code in this module at all.
  * Output is capture drafts in staging/bookmarks/ ONLY.
    Nothing is written to wiki/, raw/ or anywhere else except
    the dedupe register's append. A draft becomes wiki content
    only through the normal ingest act, like every capture.
  * No network: a bookmark's URL is recorded, never fetched.

FORMATS (auto-detected by content, extension as a hint):
  chrome    Chrome/Chromium `Bookmarks` JSON
            (roots -> children trees, type url/folder)
  firefox   Firefox bookmark backup JSON
            (type text/x-moz-place / -container trees)
  netscape  Netscape bookmark HTML export (the DOCTYPE
            NETSCAPE-Bookmark-file-1 format every browser
            exports): <DT><A HREF=... ADD_DATE=...>title</A>
            inside <DL>/<H3> folder nesting.

DEDUPE. The register evaluation/bookmarks-register.jsonl is
append-only (header + one `imported` event per staged URL).
Identity is the NORMALISED URL: scheme/host lowercased,
default port and fragment dropped, a single trailing slash
dropped — tracking parameters are NOT stripped
here (that is lane BA's clip-path concern; a bookmark register
must not silently rewrite the owner's saved URL beyond the
structural normalisation above, and the draft keeps the URL
exactly as bookmarked). A URL already in the register is
skipped and reported as a duplicate, however many files it
arrives in; the same URL twice in one file stages once.

DRAFTS. One draft per new bookmark, rendered from
templates/capture/bookmark.md when present (the capture
template grammar's static shape — this tool fills title, url,
folder and date directly; it does not run wiki_capture.py's
prompt grammar, because a bookmark carries no Why to prompt
for yet: the draft's Why section is an explicit prompt for
the ingest act). File name: staging/bookmarks/<slug>-<hash8>.md
— the hash suffix makes re-imports collision-free by
construction on top of the register's dedupe.

    python3 scripts/wiki_bookmarks.py [--root DIR]
        import <file> [--dry-run] [--json]
        list [--json]

Exit: 0 ok (duplicates are not failures) · 1 unreadable or
unrecognised input file · 2 usage. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = Path("evaluation/bookmarks-register.jsonl")
STAGING_REL = Path("staging/bookmarks")
TEMPLATE_REL = Path("templates/capture/bookmark.md")
HEADER = {
    "kind": "header", "register": "bookmarks", "version": 1,
    "created": "2026-10-21",
    "purpose": "Append-only dedupe register for the bookmarks "
               "importer: one imported event per staged URL "
               "(Bookmarks Sync design, MIT, re-implemented; "
               "Marathon R7 lane BB).",
    "maintenance": "Append-only via scripts/wiki_bookmarks.py; "
                   "never rewritten.",
}

FALLBACK_TEMPLATE = """---
title: "{title}"
capture_kind: bookmark
captured: {captured}
capture_date: {date}
captured_by: bookmarks-importer
source_file: "{source_file}"
bookmark_url: "{url}"
bookmark_folder: "{folder}"
bookmark_added: "{added}"
status: draft
confidence: observed
sources: []
tags: [bookmark]
sensitivity: TODO
compiled_prompt:
compiled_converter:
compiled_date:
---

# Bookmark — {title}

**URL:** {url}
**Folder:** {folder}
**Bookmarked:** {added}
**Imported from:** {source_file}

## Why

[prompt: Why — why this bookmark belongs in the wiki; \
answered at ingest, never invented by the importer]
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "bookmark").lower()).strip("-")
    return (slug[:limit].strip("-") or "bookmark")


def normalise_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if parts.username:
        netloc = parts.username + "@" + netloc
    if port and not ((scheme == "http" and port == 80)
                     or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    path = parts.path
    if path == "/":
        path = ""
    elif len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def url_id(url: str) -> str:
    return hashlib.sha256(normalise_url(url).encode()).hexdigest()


# ------------------------------------------------------------ parsers
# Each returns [{title, url, folder, added}] in file order.
# `folder` is the "/"-joined folder path ("" at the root);
# `added` is an ISO date string or "" when the file has none.

def _epoch_to_iso(value) -> str:
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return ""
    # Chrome counts microseconds since 1601; values that large
    # are recognised by magnitude, everything else is Unix.
    if ts > 10**17:
        ts = ts // 1_000_000 - 11644473600
    elif ts > 10**12:
        ts = ts // 1000
    try:
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def parse_chrome(data: dict) -> list[dict]:
    out = []

    def walk(node, folder):
        if not isinstance(node, dict):
            return
        ntype = node.get("type")
        if ntype == "url":
            out.append({"title": node.get("name", ""),
                        "url": node.get("url", ""),
                        "folder": folder,
                        "added": _epoch_to_iso(node.get("date_added"))})
            return
        name = node.get("name", "")
        child_folder = "/".join(x for x in (folder, name) if x) \
            if ntype == "folder" else folder
        for child in node.get("children", []) or []:
            walk(child, child_folder)

    roots = data.get("roots", {})
    if isinstance(roots, dict):
        for root_node in roots.values():
            walk(root_node, "")
    return [b for b in out if b["url"]]


def parse_firefox(data: dict) -> list[dict]:
    out = []

    def walk(node, folder):
        if not isinstance(node, dict):
            return
        ntype = node.get("type", "")
        if ntype == "text/x-moz-place" and node.get("uri"):
            out.append({"title": node.get("title", ""),
                        "url": node["uri"], "folder": folder,
                        "added": _epoch_to_iso(
                            (node.get("dateAdded") or 0) // 1_000_000)})
            return
        title = node.get("title", "")
        child_folder = "/".join(x for x in (folder, title) if x) \
            if "container" in ntype else folder
        for child in node.get("children", []) or []:
            walk(child, child_folder)

    walk(data, "")
    return [b for b in out
            if b["url"] and not b["url"].startswith("place:")]


def parse_netscape(text: str) -> list[dict]:
    out = []
    folder_stack: list[str] = []
    pending_folder = None
    token_re = re.compile(
        r"<H3[^>]*>(.*?)</H3>|<DL>|</DL>|"
        r"<A\s+[^>]*HREF=\"([^\"]*)\"[^>]*>(.*?)</A>",
        re.I | re.S)
    # ADD_DATE rides on the same <A> tag; capture it in a
    # second pass keyed by match position.
    add_date_re = re.compile(r"ADD_DATE=\"(\d+)\"", re.I)
    a_tag_re = re.compile(r"<A\s+[^>]*>", re.I)
    a_tags = [(m.start(), add_date_re.search(m.group(0)))
              for m in a_tag_re.finditer(text)]
    a_dates = {pos: (m.group(1) if m else None) for pos, m in a_tags}
    a_positions = sorted(a_dates)
    for m in token_re.finditer(text):
        if m.group(1) is not None:
            pending_folder = html.unescape(
                re.sub(r"<[^>]+>", "", m.group(1))).strip()
        elif m.group(0).upper() == "<DL>":
            folder_stack.append(pending_folder or "")
            pending_folder = None
        elif m.group(0).upper() == "</DL>":
            if folder_stack:
                folder_stack.pop()
        elif m.group(2) is not None:
            added = ""
            prior = [p for p in a_positions if p <= m.start()]
            if prior and a_dates[prior[-1]]:
                added = _epoch_to_iso(a_dates[prior[-1]])
            out.append({
                "title": html.unescape(
                    re.sub(r"<[^>]+>", "", m.group(3))).strip(),
                "url": html.unescape(m.group(2)),
                "folder": "/".join(x for x in folder_stack if x),
                "added": added})
    return [b for b in out if b["url"]]


def detect_and_parse(path: Path) -> tuple[str, list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict) and "roots" in data:
            return "chrome", parse_chrome(data)
        if isinstance(data, dict) and "x-moz" in json.dumps(data)[:2000] \
                or (isinstance(data, dict)
                    and data.get("type", "").startswith("text/x-moz")):
            return "firefox", parse_firefox(data)
        if isinstance(data, dict) and "children" in data:
            return "firefox", parse_firefox(data)
        raise ValueError("JSON file is neither a Chrome Bookmarks "
                         "file nor a Firefox backup")
    if "NETSCAPE-Bookmark" in text[:2000] or "<DL>" in text[:2000].upper():
        return "netscape", parse_netscape(text)
    raise ValueError("unrecognised bookmark file format")


# ------------------------------------------------------------ register

def read_register(root: Path) -> dict[str, dict]:
    p = root / REGISTER_REL
    known: dict[str, dict] = {}
    if not p.is_file():
        return known
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("kind") == "imported" and obj.get("id"):
            known[obj["id"]] = obj
    return known


def append_register(root: Path, event: dict) -> None:
    p = root / REGISTER_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    need_header = not p.is_file() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8") as fh:
        if need_header:
            fh.write(json.dumps(HEADER, sort_keys=True) + "\n")
        fh.write(json.dumps(event, sort_keys=True) + "\n")
        fh.flush()
        import os
        os.fsync(fh.fileno())


# ------------------------------------------------------------ import

def render_draft(root: Path, bookmark: dict, source_name: str,
                 now: datetime) -> str:
    template_path = root / TEMPLATE_REL
    template = template_path.read_text(encoding="utf-8") \
        if template_path.is_file() else FALLBACK_TEMPLATE

    def esc(v: str) -> str:
        return (v or "").replace("\\", "\\\\").replace('"', '\\"')

    return template.format(
        title=esc(bookmark["title"]) or "untitled",
        url=esc(bookmark["url"]), folder=esc(bookmark["folder"]),
        added=bookmark["added"] or "unknown",
        source_file=esc(source_name),
        captured=now.isoformat(timespec="seconds"),
        date=now.date().isoformat())


def import_file(root: Path, path: Path, dry_run: bool = False) -> dict:
    fmt, bookmarks = detect_and_parse(path)
    known = read_register(root)
    seen_this_run: set[str] = set()
    staged, duplicates = [], []
    staging_dir = root / STAGING_REL
    now = _now()
    for bm in bookmarks:
        iid = url_id(bm["url"])
        if iid in known or iid in seen_this_run:
            duplicates.append({"url": bm["url"], "title": bm["title"],
                               "id": iid})
            continue
        seen_this_run.add(iid)
        name = f"{slugify(bm['title'])}-{iid[:8]}.md"
        rel = f"{STAGING_REL}/{name}"
        if not dry_run:
            staging_dir.mkdir(parents=True, exist_ok=True)
            (staging_dir / name).write_text(
                render_draft(root, bm, path.name, now), encoding="utf-8")
            append_register(root, {
                "kind": "imported", "id": iid,
                "url": bm["url"], "normalised": normalise_url(bm["url"]),
                "title": bm["title"], "folder": bm["folder"],
                "format": fmt, "source_file": path.name,
                "draft": rel, "ts": now.isoformat(timespec="seconds")})
        staged.append({"url": bm["url"], "title": bm["title"],
                       "id": iid, "draft": rel})
    return {"tool": "scripts/wiki_bookmarks.py",
            "kind": "bookmarks-import-report", "format": fmt,
            "source_file": path.name, "dry_run": dry_run,
            "stats": {"parsed": len(bookmarks),
                      "staged": len(staged),
                      "duplicates": len(duplicates)},
            "staged": staged, "duplicates": duplicates}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    ip = sub.add_parser("import")
    ip.add_argument("file")
    ip.add_argument("--dry-run", action="store_true")
    ip.add_argument("--json", action="store_true")
    lp = sub.add_parser("list")
    lp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "list":
        known = read_register(root)
        items = sorted(known.values(), key=lambda e: e["id"])
        if args.json:
            print(json.dumps({"items": items}, indent=2, sort_keys=True))
        else:
            for e in items:
                print(f"{e['id'][:12]} {e.get('url', '')} "
                      f"-> {e.get('draft', '')}")
            print(f"{len(items)} registered URL(s)")
        return 0
    path = Path(args.file)
    if "://" in args.file or not path.is_file():
        print("wiki_bookmarks: input must be a local bookmark FILE "
              "the owner hands the tool (no URLs, no sync, no "
              "browser access)", file=sys.stderr)
        return 2 if "://" in args.file else 1
    try:
        report = import_file(root, path, dry_run=args.dry_run)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"wiki_bookmarks: door failure: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        st = report["stats"]
        print(f"bookmarks ({report['format']}): {st['parsed']} parsed, "
              f"{st['staged']} staged to {STAGING_REL}, "
              f"{st['duplicates']} duplicate(s) skipped"
              + (" (dry run — nothing written)" if args.dry_run else ""))
        for d in report["duplicates"]:
            print(f"  DUPLICATE: {d['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
