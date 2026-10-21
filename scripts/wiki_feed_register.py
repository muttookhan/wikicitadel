#!/usr/bin/env python3
"""wiki_feed_register.py — feed-clip identity + tri-state
register (Marathon R7, lane BB).

Board line (wiki/ideas.md, Round-5 Tier A): "The feed-clip
identity + tri-state register — an append-only register beside
the ingest queue recording each feed item's stable identity and
staged / dismissed / ingested state, consulted before staging;
per-feed cleanup re-runnable over imported notes (RSS Importer
design, MIT — the register design re-implemented)".

SEAM WITH LANE BA: BA works on tracking-stripping in the clip
path (scripts/wiki_clip.py). This module does NOT touch
wiki_clip.py. It is a SEPARATE module the clip path (or a human
driving it) consults: `should-stage` before staging an item,
`stage` once its draft exists, `dismiss` / `ingest` as its
state moves. Wiring it into wiki_clip.py's feed loop is a
one-call seam at the point each item is staged — left unwired
here so the two lanes compose without editing the same file.

Register: evaluation/feed-clips.jsonl — append-only, beside
evaluation/ingest-queue.jsonl, in that register's discipline:
a header line, then one JSON event per line; an item's current
state is COMPUTED by folding events in order; the file is
never rewritten. Events:

    {"kind": "staged",    "id": ..., "feed": ..., "key": ...,
     "title": ..., "link": ..., "draft": ..., "ts": ...}
    {"kind": "dismissed", "id": ..., "ts": ..., "reason": ...}
    {"kind": "ingested",  "id": ..., "ts": ..., "page": ...}

States: staged / dismissed / ingested. The register's whole
point is the transitions' memory:
  * re-clipping a feed re-offers only items with NO event —
    a staged item is not re-staged, an ingested item is not
    re-offered;
  * a DISMISSED item stays dismissed: `should-stage` answers
    no for it forever, unless a human appends a fresh `staged`
    event deliberately (the fold takes the LATEST event, so
    the remedy exists and is itself on the record).

IDENTITY. An item's stable identity is
    id = sha256(feed_identity + "|" + item_key)
where feed_identity is the feed URL normalised (scheme/host
lowercased, default ports and trailing slash removed,
fragment dropped — query KEPT, it can distinguish feeds) and
item_key is the FIRST available of: the item's guid (with
isPermaLink=false honoured by using it verbatim), its link,
or `title|published`. The same item re-clipped from the same
feed therefore hashes identically however often it is seen;
the same link under a different feed is a different item.

CLEANUP. `cleanup --feed F [--notes-dir D]` is re-runnable
over imported notes: it scans the staged drafts recorded for
a feed, reports drafts missing on disk, register entries in
`staged` whose draft was never recorded, and notes on disk
naming the feed that the register does not know. It REPORTS
only — it deletes nothing, and running it twice gives the
same report for the same state (idempotent).

    python3 scripts/wiki_feed_register.py [--root DIR]
        should-stage --feed F [--guid G] [--link L]
                     [--title T] [--published P]
        stage --feed F ... [--draft PATH] [--title T] [--link L]
        dismiss --feed F ... [--reason ...]
        ingest --feed F ... [--page PATH]
        list [--feed F] [--state staged|dismissed|ingested] [--json]
        cleanup --feed F [--notes-dir DIR] [--json]

Exit: should-stage 0 = stage it, 1 = do not (already known),
2 = usage. Others 0 ok, 2 usage/refusal. Stdlib only; no
network anywhere in this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = Path("evaluation/feed-clips.jsonl")
STATES = ("staged", "dismissed", "ingested")
HEADER = {
    "kind": "header", "register": "feed-clips", "version": 1,
    "created": "2026-10-21",
    "purpose": "Append-only tri-state register for feed-clipped "
               "items: stable identity + staged/dismissed/"
               "ingested state, consulted before staging so "
               "re-clipping never re-stages and a dismissal "
               "sticks (RSS Importer design, MIT, re-implemented; "
               "Marathon R7 lane BB).",
    "maintenance": "Append-only via scripts/wiki_feed_register.py; "
                   "states computed by folding events in order; "
                   "never rewritten.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_feed(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80)
                     or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def item_key(guid=None, link=None, title=None, published=None) -> str:
    if guid and guid.strip():
        return "guid:" + guid.strip()
    if link and link.strip():
        return "link:" + link.strip()
    return "tp:" + (title or "").strip() + "|" + (published or "").strip()


def item_id(feed: str, guid=None, link=None, title=None,
            published=None) -> str:
    feed_id = normalise_feed(feed)
    key = item_key(guid, link, title, published)
    return hashlib.sha256(f"{feed_id}|{key}".encode()).hexdigest()


# ------------------------------------------------------------ register IO

def register_path(root: Path) -> Path:
    return root / REGISTER_REL


def read_events(root: Path) -> list[dict]:
    p = register_path(root)
    if not p.is_file():
        return []
    events = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn final line tolerated, ingest-queue discipline
        if obj.get("kind") != "header":
            events.append(obj)
    return events


def fold(events: list[dict]) -> dict[str, dict]:
    items: dict[str, dict] = {}
    for ev in events:
        iid = ev.get("id")
        if not iid:
            continue
        cur = items.setdefault(iid, {"id": iid})
        cur.update({k: ev[k] for k in ("feed", "key", "title", "link")
                    if k in ev})
        kind = ev.get("kind")
        if kind == "staged":
            cur["state"] = "staged"
            if "draft" in ev:
                cur["draft"] = ev["draft"]
        elif kind == "dismissed":
            cur["state"] = "dismissed"
            cur["reason"] = ev.get("reason")
        elif kind == "ingested":
            cur["state"] = "ingested"
            if "page" in ev:
                cur["page"] = ev["page"]
        cur["last_ts"] = ev.get("ts")
    return items


def append_event(root: Path, event: dict) -> None:
    p = register_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    need_header = not p.is_file() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8") as fh:
        if need_header:
            fh.write(json.dumps(HEADER, sort_keys=True) + "\n")
        fh.write(json.dumps(event, sort_keys=True) + "\n")
        fh.flush()
        import os
        os.fsync(fh.fileno())


def current_state(root: Path, iid: str) -> str | None:
    item = fold(read_events(root)).get(iid)
    return item["state"] if item else None


def should_stage(root: Path, iid: str) -> bool:
    """The consultation the register exists for: stage only
    items the register has never seen."""
    return current_state(root, iid) is None


# ------------------------------------------------------------ cleanup

def cleanup(root: Path, feed: str, notes_dir: Path | None = None) -> dict:
    feed_id = normalise_feed(feed)
    items = [it for it in fold(read_events(root)).values()
             if normalise_feed(it.get("feed", "")) == feed_id]
    notes_dir = notes_dir or (root / "staging" / "captures")
    missing_drafts, unrecorded_drafts = [], []
    for it in items:
        if it.get("state") == "staged" and it.get("draft"):
            if not (root / it["draft"]).is_file():
                missing_drafts.append(
                    {"id": it["id"], "draft": it["draft"]})
        if it.get("state") == "staged" and not it.get("draft"):
            unrecorded_drafts.append({"id": it["id"]})
    unknown_notes = []
    if notes_dir.is_dir():
        known_drafts = {it.get("draft") for it in items}
        for note in sorted(notes_dir.rglob("*.md")):
            text = note.read_text(encoding="utf-8", errors="replace")
            if feed_id in text or feed in text:
                rel = str(note.relative_to(root)) \
                    if note.is_relative_to(root) else str(note)
                if rel not in known_drafts:
                    unknown_notes.append(rel)
    return {"tool": "scripts/wiki_feed_register.py",
            "kind": "feed-cleanup-report", "feed": feed_id,
            "stats": {"register_items": len(items),
                      "missing_drafts": len(missing_drafts),
                      "unrecorded_drafts": len(unrecorded_drafts),
                      "unknown_notes": len(unknown_notes)},
            "missing_drafts": missing_drafts,
            "unrecorded_drafts": unrecorded_drafts,
            "unknown_notes": unknown_notes}


# ------------------------------------------------------------ CLI

def _identity_args(ap):
    ap.add_argument("--feed", required=True)
    ap.add_argument("--guid", default=None)
    ap.add_argument("--link", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--published", default=None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("should-stage", "stage", "dismiss", "ingest"):
        _identity_args(sub.add_parser(name))
    sub.choices["stage"].add_argument("--draft", default=None)
    sub.choices["dismiss"].add_argument("--reason", default=None)
    sub.choices["ingest"].add_argument("--page", default=None)
    lp = sub.add_parser("list")
    lp.add_argument("--feed", default=None)
    lp.add_argument("--state", choices=STATES, default=None)
    lp.add_argument("--json", action="store_true")
    cp = sub.add_parser("cleanup")
    cp.add_argument("--feed", required=True)
    cp.add_argument("--notes-dir", default=None)
    cp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.cmd == "list":
        items = fold(read_events(root))
        out = [it for it in items.values()
               if (not args.feed
                   or normalise_feed(it.get("feed", ""))
                   == normalise_feed(args.feed))
               and (not args.state or it.get("state") == args.state)]
        out.sort(key=lambda it: it["id"])
        if args.json:
            print(json.dumps({"items": out}, indent=2, sort_keys=True))
        else:
            for it in out:
                print(f"{it['id'][:12]} {it.get('state', '?'):9} "
                      f"{it.get('title') or it.get('link') or ''}")
            print(f"{len(out)} item(s)")
        return 0
    if args.cmd == "cleanup":
        report = cleanup(root, args.feed,
                         Path(args.notes_dir) if args.notes_dir else None)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            st = report["stats"]
            print(f"cleanup {report['feed']}: {st['register_items']} "
                  f"register item(s); {st['missing_drafts']} missing "
                  f"draft(s); {st['unrecorded_drafts']} unrecorded; "
                  f"{st['unknown_notes']} unknown note(s)")
        return 0

    iid = item_id(args.feed, args.guid, args.link, args.title,
                  args.published)
    key = item_key(args.guid, args.link, args.title, args.published)
    if args.cmd == "should-stage":
        state = current_state(root, iid)
        if state is None:
            print(f"stage: {iid} is new")
            return 0
        print(f"do-not-stage: {iid} already {state}")
        return 1
    base = {"id": iid, "feed": normalise_feed(args.feed), "key": key,
            "ts": _now()}
    if args.title:
        base["title"] = args.title
    if args.link:
        base["link"] = args.link
    if args.cmd == "stage":
        if current_state(root, iid) is not None:
            print(f"refused: {iid} already {current_state(root, iid)}; "
                  "not re-staged", file=sys.stderr)
            return 2
        ev = {**base, "kind": "staged"}
        if args.draft:
            ev["draft"] = args.draft
        append_event(root, ev)
        print(f"staged {iid}")
        return 0
    if args.cmd == "dismiss":
        ev = {**base, "kind": "dismissed", "reason": args.reason}
        append_event(root, ev)
        print(f"dismissed {iid}")
        return 0
    if args.cmd == "ingest":
        ev = {**base, "kind": "ingested"}
        if args.page:
            ev["page"] = args.page
        append_event(root, ev)
        print(f"ingested {iid}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
