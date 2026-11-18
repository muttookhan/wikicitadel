#!/usr/bin/env python3
"""wiki_stamp.py — the prompt/converter version stamp on
compiled pages (the visible form of the converter identity).

Every compiled page's frontmatter carries three flat scalar
keys:

    compiled_prompt: <prompt/template id that produced it>
    compiled_converter: <converter identity, or "none">
    compiled_date: <YYYY-MM-DD of the compile>

Why flat keys and not a nested `compiled:` block: this wiki's
own frontmatter parser (scripts/wiki_validate.py
parse_frontmatter) reads top-level scalars and lists only — a
nested block's subkeys are silently dropped by it, so a nested
stamp would be invisible to the wiki's own tooling. Flat
scalars are read by that parser, and the OKF exporter
(scripts/wiki_okf_export.py) carries unmapped top-level keys
into its namespace section, so the stamp round-trips the
export. A footer line was rejected: it is body text, separable
from the compile event by any later edit, and no tool reads it.

Honesty rule: the stamp records what actually produced the
page. Pages compiled by agent passes before versioned prompt
templates existed are stamped `unversioned-agent-pass` —
never an invented version. The mechanism exists so future
compiles stamp the real template id + version at compile
time (the converter-identity discipline of
scripts/wiki_convert.py, extended from raw conversion to the
compile step).

    python3 scripts/wiki_stamp.py stamp <page> \
        --prompt <id> --converter <id> [--date YYYY-MM-DD]
    python3 scripts/wiki_stamp.py show <page>

Exit codes: 0 ok · 1 refusal · 2 usage error.
"""
import argparse
import re
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ("compiled_prompt", "compiled_converter", "compiled_date")
UNVERSIONED = "unversioned-agent-pass"


class StampError(Exception):
    pass


def _frontmatter_span(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise StampError("page has no frontmatter block")
    return m


def stamp_page(page_rel, prompt, converter, on=None, root=ROOT):
    if not prompt or not prompt.strip():
        raise StampError("stamp requires --prompt (use %r when "
                         "no versioned template produced the "
                         "page)" % UNVERSIONED)
    if converter is None or not str(converter).strip():
        raise StampError("stamp requires --converter "
                         "('none' when no converter ran)")
    page = root / page_rel
    if not page.exists():
        raise StampError("no such page: %s" % page_rel)
    text = page.read_text(encoding="utf-8")
    m = _frontmatter_span(text)
    fm = m.group(1)
    values = {
        "compiled_prompt": prompt.strip(),
        "compiled_converter": str(converter).strip(),
        "compiled_date": on or _date.today().isoformat(),
    }
    lines = fm.split("\n")
    seen = set()
    out = []
    for line in lines:
        km = re.match(r"^(compiled_prompt|compiled_converter|"
                      r"compiled_date):", line)
        if km:
            key = km.group(1)
            if key in seen:
                continue  # drop a duplicate stamp key
            seen.add(key)
            out.append("%s: %s" % (key, values[key]))
        else:
            out.append(line)
    for key in KEYS:
        if key not in seen:
            out.append("%s: %s" % (key, values[key]))
    new = (text[:m.start(1)] + "\n".join(out) + text[m.end(1):])
    page.write_text(new, encoding="utf-8")
    return values


def show_stamp(page_rel, root=ROOT):
    page = root / page_rel
    if not page.exists():
        raise StampError("no such page: %s" % page_rel)
    text = page.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    stamp = {}
    for line in m.group(1).split("\n"):
        km = re.match(r"^(compiled_\w+):\s*(.*)$", line)
        if km:
            stamp[km.group(1)] = km.group(2).strip()
    return stamp or None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stamp")
    p.add_argument("page")
    p.add_argument("--prompt", required=True)
    p.add_argument("--converter", required=True)
    p.add_argument("--date")
    p = sub.add_parser("show")
    p.add_argument("page")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "stamp":
            v = stamp_page(args.page, args.prompt, args.converter,
                           on=args.date, root=args.root)
            print("stamped %s: prompt=%s converter=%s date=%s"
                  % (args.page, v["compiled_prompt"],
                     v["compiled_converter"], v["compiled_date"]))
        else:
            s = show_stamp(args.page, root=args.root)
            if s is None:
                print("%s: no stamp" % args.page)
            else:
                print("%s: %s" % (args.page, s))
    except StampError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
