#!/usr/bin/env python3
"""wiki_preview.py — the preview-and-edit capture checkpoint
(Marathon Round 3, lane TA4; row: "preview-and-edit capture
checkpoint", pattern: MarkDownload's preview-before-save —
idea re-implemented, no code copied).

A clip normally stages its capture draft straight into
staging/captures/. The checkpoint inserts one deliberate step
before that: with `wiki_clip.py clip ... --preview`, the draft
lands in staging/previews/ instead, carrying the frontmatter
line `capture_state: preview-unfiled`. A preview is NOT a
filed capture: it is the place the owner (or the agent, on
the owner's word) reads the captured content, fixes the
title, trims the datamarked body, answers the sensitivity
TODO — edits the file in place, by hand or by any editor.

Filing happens ONLY on the explicit confirm step here:

    python3 scripts/wiki_preview.py list [--root DIR]
    python3 scripts/wiki_preview.py confirm <preview-file>
        [--root DIR]
    python3 scripts/wiki_preview.py discard <preview-file>
        [--root DIR]

confirm moves the (possibly edited) preview into
staging/captures/ under the same file name, flips its
capture_state line to `filed (confirmed <date>)`, and leaves
a receipt at staging/previews/<name>.confirmed.json recording
the preview's sha256 AT CONFIRM TIME (the edited bytes are
what was filed — the receipt proves which version crossed
the checkpoint). It refuses: a file that is not a preview
(no capture_state: preview-unfiled line), a destination that
already exists (never overwrite a filed draft), and a name
that tries to escape the previews directory. discard moves
a preview aside to staging/previews/discarded/ — nothing is
deleted at the checkpoint either.

Exit codes: 0 ok · 1 refusal · 2 usage error.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW_DIR = Path("staging/previews")
CAPTURE_DIR = Path("staging/captures")
PREVIEW_STATE = "capture_state: preview-unfiled"


class PreviewError(Exception):
    pass


def _preview_path(root, name):
    if Path(name).is_absolute() or "/" in name or "\\" in name \
            or ".." in name:
        raise PreviewError("a preview is named by its bare file "
                           "name in %s — got %r" % (PREVIEW_DIR, name))
    return Path(root) / PREVIEW_DIR / name


def list_previews(root=ROOT):
    pdir = Path(root) / PREVIEW_DIR
    if not pdir.is_dir():
        return []
    return sorted(p.name for p in pdir.glob("*.md")
                  if p.is_file())


def confirm(name, root=ROOT, now=None):
    """File a preview: move it into staging/captures/ and flip
    its state line. Returns the filed draft's repo-relative
    path. The preview's edited content is filed as-is."""
    root = Path(root)
    src = _preview_path(root, name)
    if not src.is_file():
        raise PreviewError("no such preview: %s" % src)
    text = src.read_text(encoding="utf-8")
    if PREVIEW_STATE not in text:
        raise PreviewError(
            "%s is not an unfiled preview (no %r line) — "
            "refusing to file it through the checkpoint"
            % (src, PREVIEW_STATE))
    dest_dir = root / CAPTURE_DIR
    dest = dest_dir / src.name
    if dest.exists():
        raise PreviewError("a filed draft already exists: %s — "
                           "refusing to overwrite it" % dest)
    now = now or datetime.now().astimezone()
    filed_text = text.replace(
        PREVIEW_STATE,
        "capture_state: filed (confirmed %s)"
        % now.strftime("%Y-%m-%d"), 1)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(filed_text, encoding="utf-8")
    receipt = {"preview": str(PREVIEW_DIR / src.name),
               "filed_as": str(CAPTURE_DIR / src.name),
               "confirmed": now.strftime("%Y-%m-%d %H:%M %Z"),
               "sha256_at_confirm": hashlib.sha256(
                   filed_text.encode("utf-8")).hexdigest(),
               "note": "the sha256 is of the EDITED preview "
                       "bytes as filed — the version that "
                       "crossed the checkpoint"}
    receipt_path = root / PREVIEW_DIR / (src.name + ".confirmed.json")
    receipt_path.write_text(json.dumps(receipt, indent=2,
                                       sort_keys=True) + "\n",
                            encoding="utf-8")
    src.unlink()
    return str(CAPTURE_DIR / src.name)


def discard(name, root=ROOT):
    """Move a preview aside (never delete it). Returns the
    repo-relative path it was moved to."""
    root = Path(root)
    src = _preview_path(root, name)
    if not src.is_file():
        raise PreviewError("no such preview: %s" % src)
    aside_dir = root / PREVIEW_DIR / "discarded"
    aside_dir.mkdir(parents=True, exist_ok=True)
    dest = aside_dir / src.name
    if dest.exists():
        raise PreviewError("already discarded once: %s" % dest)
    src.rename(dest)
    return str(PREVIEW_DIR / "discarded" / src.name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("confirm")
    p.add_argument("name")
    p = sub.add_parser("discard")
    p.add_argument("name")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            names = list_previews(args.root)
            if not names:
                print("previews: none waiting at the checkpoint")
            for name in names:
                print("preview (unfiled): %s" % name)
                print("  edit it in place, then: wiki_preview.py "
                      "confirm %s" % name)
        elif args.cmd == "confirm":
            rel = confirm(args.name, root=args.root)
            print("filed: %s — the edited preview is now a "
                  "staged capture draft" % rel)
        else:
            rel = discard(args.name, root=args.root)
            print("discarded (moved aside, not deleted): %s" % rel)
    except PreviewError as exc:
        print("wiki_preview: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
