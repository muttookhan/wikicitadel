#!/usr/bin/env python3
"""wiki_memo.py — the Memos-shaped capture store (Marathon R4, lane C).

Pattern: usememos/memos (MIT) — re-implemented in our own code:
ONE timeline inbox, tags as the ONLY structure, and read access
from day one. A memo is a short text plus zero or more tags;
there are no folders, no categories, no hierarchy to file it
under. The store is an append-only JSONL file at
staging/memos.jsonl (one JSON object per memo, in capture
order); `timeline` reads it newest-first.

This is the store behind the `memo` capture kind in
scripts/wiki_capture.py (the capture pipeline renders the memo
draft with its schema frontmatter and its tags); this CLI is
the fast door over the same shape:

    python3 scripts/wiki_memo.py add "text" [--tags a,b] [--by NAME]
    python3 scripts/wiki_memo.py list [--tag TAG] [--json]
    python3 scripts/wiki_memo.py timeline [--tag TAG] [--json]

Read access also stands in the existing doors, additively:
scripts/wiki_traverse.py `memos` and the MCP read door's
wiki_memos tool both list this store and write nothing.

Exit codes: 0 ok · 1 refusal · 2 usage error. Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE_REL = Path("staging/memos.jsonl")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class MemoError(Exception):
    pass


def normalize_tags(tags):
    """Tags are the only structure, so they are kept strict:
    lowercase slug tokens, de-duplicated, order preserved."""
    out = []
    for raw in tags or []:
        for piece in str(raw).split(","):
            tag = piece.strip().lower().lstrip("#")
            if not tag:
                continue
            if not TAG_RE.match(tag):
                raise MemoError(
                    "tag %r is not a slug tag (lowercase letters, "
                    "digits, hyphens)" % tag)
            if tag not in out:
                out.append(tag)
    return out


def store_path(root=ROOT, store=None):
    if store:
        return Path(store)
    return Path(root) / STORE_REL


def load_memos(root=ROOT, store=None):
    """All memos in store (capture) order; [] when no store yet.
    A malformed line is a MemoError, never silently dropped."""
    path = store_path(root, store)
    if not path.exists():
        return []
    memos = []
    for n, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            raise MemoError("%s line %d is not JSON" % (path, n))
        if not isinstance(rec, dict) or rec.get("kind") != "memo":
            raise MemoError("%s line %d is not a memo record"
                            % (path, n))
        memos.append(rec)
    return memos


def add_memo(text, tags=(), by="agent", now=None, root=ROOT,
             store=None):
    """Append one memo to the store and return its record."""
    if not text or not text.strip():
        raise MemoError("a memo needs text")
    now = now or datetime.now().astimezone()
    captured = now.isoformat(timespec="seconds")
    digest = hashlib.sha256(
        (captured + "\n" + text.strip()).encode("utf-8")
    ).hexdigest()[:8]
    rec = {
        "kind": "memo",
        "id": "memo-%s-%s" % (now.strftime("%Y%m%d"), digest),
        "captured": captured,
        "date": now.strftime("%Y-%m-%d"),
        "text": text.strip(),
        "tags": normalize_tags(tags),
        "by": by,
    }
    path = store_path(root, store)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_memos(root=ROOT, store=None, tag=None):
    """Memos in capture order (oldest first), optionally
    filtered to one tag."""
    memos = load_memos(root, store)
    if tag:
        tag = normalize_tags([tag])[0]
        memos = [m for m in memos if tag in m.get("tags", [])]
    return memos


def timeline(root=ROOT, store=None, tag=None):
    """The timeline inbox: newest first (the Memos shape)."""
    return list(reversed(list_memos(root, store, tag)))


def _fmt(rec):
    tags = " ".join("#" + t for t in rec.get("tags", []))
    return "%s · %s · %s%s" % (
        rec.get("captured", ""), rec.get("by", ""),
        rec.get("text", ""), (" · " + tags) if tags else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--store", type=Path, default=None,
                    help="memo store file (default: "
                         "<root>/staging/memos.jsonl)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("text")
    p.add_argument("--tags", default="",
                   help="comma-separated slug tags — the only "
                        "structure a memo carries")
    p.add_argument("--by", default="agent")
    for name in ("list", "timeline"):
        q = sub.add_parser(name)
        q.add_argument("--tag")
        q.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "add":
            rec = add_memo(args.text, tags=args.tags.split(","),
                           by=args.by, root=args.root,
                           store=args.store)
            print("memo: %s" % rec["id"])
            print(_fmt(rec))
        else:
            fn = list_memos if args.cmd == "list" else timeline
            memos = fn(root=args.root, store=args.store,
                       tag=args.tag)
            if args.json:
                print(json.dumps({"memos": memos,
                                  "count": len(memos)}, indent=1))
            else:
                print("memos: %d" % len(memos))
                for rec in memos:
                    print("- " + _fmt(rec))
    except MemoError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
