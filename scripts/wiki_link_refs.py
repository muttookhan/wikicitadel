#!/usr/bin/env python3
"""Wikilinks -> Markdown link-reference definitions (Foam pattern).

Marathon R9 lane BB (ideas board R7 research, Tier A): Foam
(MIT) link-reference export option. A page written with
[[wikilinks]] is navigable only with wikilink tooling; this
module renders each wikilink as a standard Markdown reference
link — [label][ref-1] in the text and a definition block at
the end:

    [ref-1]: concepts/example.md

so a static export stays navigable in any Markdown reader.
The conversion is a pure function (convert(text) ->
(new_text, definitions)); fenced code blocks and inline code
spans are never converted (the corpus convention: code never
yields links). Definition targets: a target that already
carries a path/extension is used verbatim (plus .md when it
has a path but no extension); a bare stem becomes
<stem>.md. Anchors are preserved as #anchor on the target.

Used as the --link-refs OPTION (default OFF) on
scripts/wiki_export.py's marp export; also usable standalone:

  python3 scripts/wiki_link_refs.py FILE.md [--out FILE]

Exit 0 ok; 2 usage error. Stdlib only, no network.
"""
import argparse
import re
import sys
from pathlib import Path

WIKILINK_RE = re.compile(
    r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")


def _target_url(target, anchor):
    t = target.strip()
    if "/" in t:
        url = t if "." in t.rsplit("/", 1)[-1] else t + ".md"
    else:
        url = t if t.endswith(".md") else t + ".md"
    if anchor:
        url += "#" + anchor.strip()
    return url


def convert(text):
    """(new_text, [(ref, url), ...]) — definitions in first-
    use order, deduplicated by (target, anchor)."""
    refs = {}
    order = []

    def repl(m):
        target, anchor, label = m.group(1), m.group(2), m.group(3)
        key = (target.strip(), (anchor or "").strip())
        if key not in refs:
            ref = f"ref-{len(order) + 1}"
            refs[key] = ref
            order.append((ref, _target_url(target, anchor)))
        shown = (label or target).strip()
        return f"[{shown}][{refs[key]}]"

    out_lines = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        # Split out inline code spans; convert only prose.
        parts = re.split(r"(`[^`]*`)", line)
        out_lines.append("".join(
            p if p.startswith("`") else WIKILINK_RE.sub(repl, p)
            for p in parts))
    new_text = "\n".join(out_lines)
    if text.endswith("\n"):
        new_text += "\n"
    if order:
        defs = "\n".join(f"[{ref}]: {url}" for ref, url in order)
        new_text = new_text.rstrip("\n") + "\n\n" + defs + "\n"
    return new_text, order


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Render wikilinks as Markdown link references.")
    ap.add_argument("file")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    src = Path(args.file)
    if not src.is_file():
        print(f"wiki_link_refs: no such file: {src}", file=sys.stderr)
        return 2
    new_text, defs = convert(src.read_text(encoding="utf-8"))
    if args.out:
        Path(args.out).write_text(new_text, encoding="utf-8")
    else:
        sys.stdout.write(new_text)
    print(f"wiki_link_refs: {len(defs)} definition(s)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
