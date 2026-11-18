#!/usr/bin/env python3
"""wiki_ingest_buffer.py — ingest buffer / flush batching
(Marathon Round 3, lane TA4; row: "ingest buffer/flush
batching", pattern: Memobase's buffered ingest — idea
re-implemented, no code copied).

Capture is deliberate and one-at-a-time; ingest work is not.
This buffer sits between them: captured items are STAGED into
a buffer directory cheaply (a payload copy + a small JSON
entry, written atomically), and a later FLUSH pushes the whole
batch through the existing capture path
(scripts/wiki_clip.py's clip_file / clip_url — the same
converter defences, the same staged drafts) in one run.

Buffer layout (default staging/ingest-buffer/):

    <id>.json            a pending entry (the manifest)
    <id>.payload         the item's bytes (file entries)
    <id>.json.flushing   an entry claimed by a running flush

CRASH SAFETY — a killed flush loses nothing:
- adding an entry writes the payload first, then the entry
  JSON via a temp file + atomic rename, so a buffer never
  holds an entry whose payload is half-written;
- flush CLAIMS an entry by renaming its JSON to
  `<id>.json.flushing` before processing it, and deletes the
  entry only AFTER the clip path has staged its draft;
- a flush that starts and finds `.flushing` entries treats
  them as crash survivors: they are re-processed in that run
  (reported under "recovered"). Re-processing is safe because
  the clip path is idempotent at the raw layer and refuses to
  overwrite a staged draft — if the draft already exists, the
  item demonstrably WAS flushed before the kill, and the
  entry is retired as "already-flushed" instead of failing;
- an entry whose processing FAILS (unreadable payload,
  unsupported format) is renamed back to pending and reported
  under "failed" with the reason; the flush continues with
  the rest of the batch, and exits 1 if anything failed.

Nothing here files or compiles: a flush produces exactly
what a manual clip produces — preserved sources + staged
drafts — just batched.

    python3 scripts/wiki_ingest_buffer.py add <file>
        [--sensitivity CLASS] [--title "..."] [--root DIR]
    python3 scripts/wiki_ingest_buffer.py add-url <url>
        [--sensitivity CLASS] [--title "..."] [--root DIR]
    python3 scripts/wiki_ingest_buffer.py list [--root DIR]
    python3 scripts/wiki_ingest_buffer.py flush [--limit N]
        [--root DIR]

Exit codes: 0 ok · 1 a flush left failures pending · 2 usage.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wiki_clip as clip  # noqa: E402  (the existing capture path)

ROOT = Path(__file__).resolve().parent.parent
BUFFER_DIR = Path("staging/ingest-buffer")


class BufferError(Exception):
    pass


def _slug(title):
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug[:48].strip("-") or "item"


def buffer_dir(root):
    return Path(root) / BUFFER_DIR


def _write_entry(root, meta):
    bdir = buffer_dir(root)
    bdir.mkdir(parents=True, exist_ok=True)
    tmp = bdir / (meta["id"] + ".json.tmp")
    final = bdir / (meta["id"] + ".json")
    if final.exists() or Path(str(final) + ".flushing").exists():
        raise BufferError("buffer entry already exists: %s"
                          % meta["id"])
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.rename(final)  # atomic: the entry appears whole or not at all
    return final


def add_file(path, sensitivity=None, title=None, root=ROOT, now=None):
    src = Path(path)
    if not src.is_file():
        raise BufferError("no such file: %s" % src)
    data = src.read_bytes()
    now = now or datetime.now().astimezone()
    digest = hashlib.sha256(data).hexdigest()[:8]
    entry_id = "%s-%s-%s" % (now.strftime("%Y-%m-%d"),
                             _slug(title or src.stem), digest)
    bdir = buffer_dir(root)
    bdir.mkdir(parents=True, exist_ok=True)
    payload = bdir / (entry_id + ".payload")
    if payload.exists():
        raise BufferError("buffer entry already exists: %s"
                          % entry_id)
    payload.write_bytes(data)  # payload first, entry second
    meta = {"id": entry_id, "kind": "file",
            "source_name": src.name, "suffix": src.suffix.lower(),
            "title": title, "sensitivity": sensitivity,
            "sha256": hashlib.sha256(data).hexdigest(),
            "buffered": now.strftime("%Y-%m-%d %H:%M %Z")}
    try:
        _write_entry(root, meta)
    except Exception:
        payload.unlink(missing_ok=True)
        raise
    return meta


def add_url(url, sensitivity=None, title=None, root=ROOT, now=None):
    if not re.match(r"^https?://", url or "", re.I):
        raise BufferError("a buffered URL must be http(s), got %r"
                          % url)
    now = now or datetime.now().astimezone()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    entry_id = "%s-url-%s-%s" % (now.strftime("%Y-%m-%d"),
                                 _slug(title or "clip"), digest)
    meta = {"id": entry_id, "kind": "url", "url": url,
            "title": title, "sensitivity": sensitivity,
            "buffered": now.strftime("%Y-%m-%d %H:%M %Z")}
    _write_entry(root, meta)
    return meta


def list_entries(root=ROOT):
    bdir = buffer_dir(root)
    out = []
    if not bdir.is_dir():
        return out
    for path in sorted(bdir.glob("*.json*")):
        if path.suffix not in (".json", ".flushing"):
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {"id": path.stem, "kind": "unreadable"}
        meta = dict(meta)
        meta["state"] = "flushing" if path.name.endswith(".flushing") \
            else "pending"
        out.append(meta)
    return out


def _process(meta, root, fetcher=None, now=None):
    """Push one entry through the existing clip path."""
    if meta["kind"] == "url":
        return clip.clip_url(meta["url"],
                             sensitivity=meta.get("sensitivity"),
                             title=meta.get("title"), root=root,
                             fetcher=fetcher, now=now)
    payload = buffer_dir(root) / (meta["id"] + ".payload")
    if not payload.is_file():
        raise BufferError("entry %s has no payload file"
                          % meta["id"])
    # clip_file needs a real suffix to route the conversion;
    # stage the payload under its original name in the buffer.
    staged = buffer_dir(root) / (meta["id"] + "-src"
                                 + (meta.get("suffix") or ""))
    staged.write_bytes(payload.read_bytes())
    try:
        return clip.clip_file(staged,
                              sensitivity=meta.get("sensitivity"),
                              title=meta.get("title"), root=root,
                              now=now)
    finally:
        staged.unlink(missing_ok=True)


def flush(root=ROOT, limit=None, fetcher=None, now=None):
    """Flush pending entries in id order. Returns
    {"flushed": [...], "already_flushed": [...],
     "recovered": [...], "failed": [{id, error}]}.
    Crash survivors (.flushing) are re-processed first and
    named in "recovered" (or "already_flushed" when the kill
    happened after their draft was staged)."""
    root = Path(root)
    bdir = buffer_dir(root)
    result = {"flushed": [], "already_flushed": [],
              "recovered": [], "failed": []}
    if not bdir.is_dir():
        return result
    claimed = sorted(bdir.glob("*.json.flushing"))
    pending = sorted(p for p in bdir.glob("*.json")
                     if p.name.endswith(".json"))
    queue = [(p, True) for p in claimed] + [(p, False)
                                           for p in pending]
    if limit is not None:
        queue = queue[:limit]
    for entry_path, was_claimed in queue:
        entry_id = entry_path.name.replace(".json.flushing", "") \
            .replace(".json", "")
        live = entry_path
        if not was_claimed:
            live = Path(str(entry_path) + ".flushing")
            entry_path.rename(live)  # claim before processing
        try:
            meta = json.loads(live.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            live.rename(bdir / (entry_id + ".json"))
            result["failed"].append(
                {"id": entry_id, "error": "unreadable entry: %s"
                 % exc})
            continue
        try:
            res = _process(meta, root, fetcher=fetcher, now=now)
        except clip.ClipError as exc:
            if "already exists" in str(exc):
                # The draft was staged before the kill (or a
                # previous flush): the item IS captured; retire
                # the entry rather than losing or duplicating it.
                live.unlink(missing_ok=True)
                (bdir / (entry_id + ".payload")).unlink(
                    missing_ok=True)
                result["already_flushed"].append(
                    {"id": entry_id})
                if was_claimed:
                    result["recovered"].append(entry_id)
                continue
            live.rename(bdir / (entry_id + ".json"))
            result["failed"].append(
                {"id": entry_id, "error": str(exc)})
            continue
        except BufferError as exc:
            live.rename(bdir / (entry_id + ".json"))
            result["failed"].append(
                {"id": entry_id, "error": str(exc)})
            continue
        # Success — only now is the entry retired.
        live.unlink(missing_ok=True)
        (bdir / (entry_id + ".payload")).unlink(missing_ok=True)
        result["flushed"].append({"id": entry_id,
                                  "draft": res.get("draft"),
                                  "kind": res.get("kind")})
        if was_claimed:
            result["recovered"].append(entry_id)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("file")
    p.add_argument("--sensitivity")
    p.add_argument("--title")
    p = sub.add_parser("add-url")
    p.add_argument("url")
    p.add_argument("--sensitivity")
    p.add_argument("--title")
    sub.add_parser("list")
    p = sub.add_parser("flush")
    p.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "add":
            meta = add_file(args.file, sensitivity=args.sensitivity,
                            title=args.title, root=args.root)
            print("buffered: %s (flush with: wiki_ingest_buffer.py "
                  "flush)" % meta["id"])
        elif args.cmd == "add-url":
            meta = add_url(args.url, sensitivity=args.sensitivity,
                           title=args.title, root=args.root)
            print("buffered: %s (flush with: wiki_ingest_buffer.py "
                  "flush)" % meta["id"])
        elif args.cmd == "list":
            entries = list_entries(args.root)
            if not entries:
                print("ingest buffer: empty")
            for e in entries:
                print("%s [%s] %s" % (e["id"], e["state"],
                                      e.get("source_name")
                                      or e.get("url") or ""))
        else:
            result = flush(root=args.root, limit=args.limit)
            print(json.dumps(result, indent=2, sort_keys=True))
            if result["failed"]:
                return 1
    except BufferError as exc:
        print("wiki_ingest_buffer: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
