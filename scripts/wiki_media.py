#!/usr/bin/env python3
"""wiki_media.py — media fidelity report for a wiki tree.

    python3 scripts/wiki_media.py [--root <tree>] [--list-media]

Two deterministic, report-only checks:

1. INVENTORY — every media file under raw/, classified by
   extension as image / audio / video.

2. PAGE REFERENCES — for every compiled page under wiki/, every
   markdown image reference ![alt](target) is checked:
   * the target resolves to a real file (external http(s) and
     data: targets are out of scope and skipped), and
   * the reference carries alt text: a non-empty alt in the
     brackets, OR an adjacent caption line — the line immediately
     after the image line, either a single italic line
     (*caption* / _caption_) or a line starting "Caption:".

Violations are reported as kind + page path + line ONLY:

    missing-alt: wiki/concepts/example.md:12
    missing-file: wiki/concepts/example.md:12

This tool NEVER edits a page and never writes anything.
Stdlib only. Exit codes: 0 no violations · 1 violations found ·
2 usage error.
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

MEDIA_EXTS = {
    # image
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".bmp": "image", ".tif": "image", ".tiff": "image",
    ".avif": "image", ".heic": "image", ".ico": "image",
    # audio
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".ogg": "audio", ".flac": "audio", ".aac": "audio",
    ".opus": "audio",
    # video
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".mkv": "video", ".avi": "video", ".m4v": "video",
}

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_CAPTION_RE = re.compile(
    r"^\s*(?:\*(?P<i1>[^*]+)\*|_(?P<i2>[^_]+)_|Caption:\s*(?P<i3>.+))\s*$")


def media_kind(path):
    return MEDIA_EXTS.get(Path(path).suffix.lower())


def inventory_media(root):
    """All media files under raw/, sorted by repo-relative path.
    Returns [{"path": rel, "kind": kind, "bytes": n}, ...]."""
    root = Path(root)
    raw = root / "raw"
    out = []
    if raw.is_dir():
        for p in sorted(raw.rglob("*")):
            if p.is_file():
                kind = media_kind(p)
                if kind:
                    out.append({"path": str(p.relative_to(root)),
                                "kind": kind,
                                "bytes": p.stat().st_size})
    return out


def is_caption_line(line):
    """The caption convention: a single italic line or a line
    starting 'Caption:', with non-empty caption text."""
    m = _CAPTION_RE.match(line or "")
    if not m:
        return False
    return bool((m.group("i1") or m.group("i2")
                 or m.group("i3") or "").strip())


def _target_path(raw_target):
    """The path part of a markdown image target: drops an
    optional <...> wrap, an optional title, and any fragment."""
    t = raw_target.strip()
    if t.startswith("<") and ">" in t:
        t = t[1:t.index(">")]
    else:
        t = t.split()[0] if t.split() else ""
    t = t.split("#", 1)[0]
    return unquote(t)


def resolve_target(root, page_path, target):
    """Resolve an image target to a filesystem path, or None for
    out-of-scope targets (external / data / empty). Relative
    targets resolve against the page's directory first, then
    against the tree root."""
    if not target or re.match(r"^(https?://|data:|mailto:)", target):
        return None
    rel = _target_path(target)
    if not rel:
        return None
    root = Path(root)
    if rel.startswith("/"):
        return root / rel.lstrip("/")
    cand = Path(page_path).parent / rel
    if cand.exists():
        return cand
    alt = root / rel
    return alt if alt.exists() else cand


def check_pages(root):
    """Violations over every wiki/**/*.md page, sorted by
    (page path, line, kind). Each is {"kind", "path", "line"}
    — nothing else is ever reported about a reference."""
    root = Path(root)
    wiki = root / "wiki"
    violations = []
    if not wiki.is_dir():
        return violations
    for page in sorted(wiki.rglob("*.md")):
        if not page.is_file():
            continue
        lines = page.read_text(encoding="utf-8",
                               errors="replace").splitlines()
        rel = str(page.relative_to(root))
        for idx, line in enumerate(lines):
            for m in IMAGE_REF_RE.finditer(line):
                alt, target = m.group(1), m.group(2)
                resolved = resolve_target(root, page, target)
                if resolved is not None and not resolved.is_file():
                    violations.append({"kind": "missing-file",
                                       "path": rel, "line": idx + 1})
                has_alt = bool(alt.strip())
                if not has_alt and idx + 1 < len(lines):
                    has_alt = is_caption_line(lines[idx + 1])
                if not has_alt:
                    violations.append({"kind": "missing-alt",
                                       "path": rel, "line": idx + 1})
    violations.sort(key=lambda v: (v["path"], v["line"], v["kind"]))
    return violations


def build_report(root, list_media=False):
    """The deterministic report text (no timestamps, sorted
    everywhere)."""
    media = inventory_media(root)
    violations = check_pages(root)
    counts = {"image": 0, "audio": 0, "video": 0}
    for item in media:
        counts[item["kind"]] += 1
    out = ["media inventory (raw/): image %d, audio %d, video %d, "
           "total %d" % (counts["image"], counts["audio"],
                         counts["video"], len(media))]
    if list_media:
        for item in media:
            out.append("  %s: %s" % (item["kind"], item["path"]))
    out.append("violations: %d" % len(violations))
    for v in violations:
        out.append("%s: %s:%d" % (v["kind"], v["path"], v["line"]))
    return "\n".join(out) + "\n", violations


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--list-media", action="store_true",
                    help="also list every inventoried media path")
    args = ap.parse_args(argv)
    text, violations = build_report(args.root,
                                    list_media=args.list_media)
    sys.stdout.write(text)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
