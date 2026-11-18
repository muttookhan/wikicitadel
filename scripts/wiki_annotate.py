#!/usr/bin/env python3
"""Annotation layer over raw: the owner's marks, beside the source.

WikiCitadel v1. Pattern: Readwise's annotation layer over immutable
content — the owner's highlights and notes live in a separate
file; the underlying text is never touched. Assessed in
docs/research-notes.md (frontier
products): "an annotation layer over immutable raw (Readwise —
the owner's marks compile first, raw untouched)".

Data model
----------
For a raw source at raw/<path>, its marks live at
raw/<path>.annotations.jsonl — one JSON object per mark:

    {"id": "a0001",
     "locator": {"start": 12, "end": 14,
                 "quote": "the exact words marked"},
     "kind": "highlight" | "note" | "question" | "correction",
     "text": "the owner's words (empty only for a bare highlight)",
     "by": "owner",
     "created": "2030-01-01"}

The locator is cite-lock-compatible: 1-based line ranges over the
source's lines exactly as scripts/wiki_cite_lock.py counts them
(splitlines), plus an optional verbatim quote anchor, checked with
that script's normalisation (whitespace and smart quotes only).
A mark is added only when its locator RESOLVES against the current
source: the range must be in bounds and the quote must be found
(inside the range, when both are given). An unresolvable locator
is refused — a mark that cannot find its place is not recorded.

The marks file is append-only, like the wiki's other registers:
marks are never edited or deleted by this tool. (Deleting a marks
file is a raw/ deletion like any other — the memory guard
requires an erasure certificate for it, exactly as for its
source.)

Addressing
----------
`correction` and `question` marks are ACTIONABLE: an ingest that
compiles the source must account for every one — apply it, answer
it, or carry it as an open note on the compiled page (AGENTS.md,
Operation: Ingest). A page accounts for a mark by citing it with
the mark reference

    ^[mark: raw/<path>#a0001]

placed where the mark is dealt with (the correction applied, the
answer given, or the open note carried). This tool scans wiki/
for those references; the lint lanes surface every actionable
mark no page has accounted for (scripts/wiki_lint_lanes.py).
Authorship is by convention — every mark records `by: owner`;
there is no fake auth layer.

Guard interaction: a marks file is a NEW file under raw/ (diff
status A). The memory guard (scripts/wiki_memory_guard.py)
refuses MODIFICATIONS and uncertified DELETIONS under raw/; an
addition is neither, so annotating a source passes the guard
unchanged — verified by scripts/tests/test_wiki_annotate.py,
which stages a marks file in a fixture repo and runs the real
guard. Note the provenance manifest (scripts/wiki_provenance.py)
will list a new marks file as an added raw file until its next
regeneration — the same bookkeeping every new source gets.

Usage:
  python3 scripts/wiki_annotate.py add <source> --kind KIND
      [--text TEXT] [--lines A[-B]] [--quote TEXT]
      [--created YYYY-MM-DD]
  python3 scripts/wiki_annotate.py list <source>
  python3 scripts/wiki_annotate.py export <source>
  python3 scripts/wiki_annotate.py unaddressed
      (every actionable mark no compiled page accounts for)

<source> is the repo-relative path, e.g. raw/sources/foo.md.
Stdlib only (wiki_cite_lock / wiki_validate imported in-process,
the reuse the other scripts make).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"

ANNOT_SUFFIX = ".annotations.jsonl"
KINDS = ("highlight", "note", "question", "correction")
ACTIONABLE_KINDS = ("correction", "question")
MARK_RE = re.compile(r"\^\[mark:\s*([^]#\s]+)#(a\d{4})\s*\]")
QUOTE_WINDOW = 5  # lines a quote anchor may span when resolving


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


citelock = _load("wiki_cite_lock")
validate = _load("wiki_validate")
normalize_text = citelock.normalize_text
parse_frontmatter = validate.parse_frontmatter


# -- Paths and reading ---------------------------------------------------------

def annotations_rel(source_rel):
    """The marks file's repo-relative path for a source path."""
    return source_rel + ANNOT_SUFFIX


def _source_lines(source_rel):
    """The source's lines (splitlines, cite-lock convention),
    or None when the file is not on disk."""
    path = ROOT / source_rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8",
                         errors="ignore").splitlines()


def read_marks(source_rel):
    """Every mark recorded for a source, in file (id) order."""
    path = ROOT / annotations_rel(source_rel)
    if not path.is_file():
        return []
    marks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            marks.append(json.loads(line))
    return marks


def all_annotated_sources():
    """Every source (repo-relative) that carries a marks file."""
    raw = ROOT / "raw"
    if not raw.is_dir():
        return []
    out = []
    for path in sorted(raw.rglob("*" + ANNOT_SUFFIX)):
        rel = path.relative_to(ROOT).as_posix()
        out.append(rel[:-len(ANNOT_SUFFIX)])
    return out


# -- Locator resolution ----------------------------------------------------------

def _find_quote(lines, needle, lo=0, hi=None):
    """Locate a quote anchor in `lines[lo:hi]`: returns the
    (start, end) 1-based line range whose normalised text contains
    the normalised quote, or None. A quote may sit on one line or
    span up to QUOTE_WINDOW consecutive lines; the smallest
    containing window starting earliest wins (deterministic)."""
    if hi is None:
        hi = len(lines)
    needle = normalize_text(needle)
    if not needle:
        return None
    normed = [normalize_text(ln) for ln in lines]
    for i in range(lo, hi):
        for j in range(i, min(i + QUOTE_WINDOW, hi)):
            joined = " ".join(normed[i:j + 1])
            if needle not in joined:
                continue
            # The window must be minimal: dropping its first or
            # its last line must break containment, so the range
            # names the lines the quote actually spans — not an
            # earlier window that merely grew to include it.
            if j > i and needle in " ".join(normed[i + 1:j + 1]):
                continue
            if j > i and needle in " ".join(normed[i:j]):
                continue
            return (i + 1, j + 1)
    return None


def resolve_locator(lines, start=None, end=None, quote=None):
    """Resolve a proposed locator against the source's lines.
    Returns (start, end). Raises ValueError with the reason when
    the locator does not resolve — the caller refuses the mark."""
    if lines is None:
        raise ValueError("source is not on disk")
    n = len(lines)
    if start is not None:
        if end is None:
            end = start
        if start < 1 or end < start or end > n:
            raise ValueError(
                f"line range L{start}-L{end} is out of bounds:"
                f" the source has {n} lines")
    if quote:
        if start is not None:
            found = _find_quote(lines, quote, start - 1, end)
            if found is None:
                raise ValueError(
                    f"quote anchor not found within"
                    f" L{start}-L{end} of the source")
        else:
            found = _find_quote(lines, quote)
            if found is None:
                raise ValueError(
                    "quote anchor not found in the source")
            start, end = found
    if start is None:
        raise ValueError("a locator needs --lines and/or --quote")
    return start, end


# -- Adding marks ------------------------------------------------------------------

def add_mark(source_rel, kind, text="", start=None, end=None,
             quote=None, created=None):
    """Validate and append one mark. Returns the mark dict.
    Raises ValueError (nothing written) on any refusal."""
    if not source_rel.startswith("raw/"):
        raise ValueError(
            f"source must live under raw/: {source_rel}")
    if kind not in KINDS:
        raise ValueError(
            f"kind must be one of {', '.join(KINDS)}: {kind!r}")
    text = (text or "").strip()
    if kind != "highlight" and not text:
        raise ValueError(
            f"a {kind} mark needs the owner's words (--text);"
            " only a bare highlight may be empty")
    lines = _source_lines(source_rel)
    if lines is None:
        raise ValueError(f"source not on disk: {source_rel}")
    start, end = resolve_locator(lines, start, end, quote)
    marks = read_marks(source_rel)
    mark = {
        "id": f"a{len(marks) + 1:04d}",
        "locator": {"start": start, "end": end,
                    "quote": quote or ""},
        "kind": kind,
        "text": text,
        "by": "owner",
        "created": created or date.today().isoformat(),
    }
    path = ROOT / annotations_rel(source_rel)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(mark, ensure_ascii=False) + "\n")
    return mark


# -- Addressing ----------------------------------------------------------------------

def scan_addressed():
    """{(source_rel, mark_id)} accounted for anywhere in wiki/.
    A reference inside a fenced code block is syntax on display,
    not an accounting (the cite-lock convention)."""
    found = set()
    if not WIKI.is_dir():
        return found
    for path in sorted(WIKI.rglob("*.md")):
        in_fence = False
        for line in path.read_text(
                encoding="utf-8", errors="ignore").splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in MARK_RE.finditer(line):
                found.add((Path(m.group(1)).as_posix(),
                           m.group(2)))
    return found


def compiled_pages_for_source(source_rel):
    """Compiled pages (repo-relative) whose frontmatter `sources`
    list names this source. Filings and talk pages are proposal /
    dispute areas, not compiled knowledge — excluded, as in the
    lanes — as are the structural index and log."""
    excluded_dirs = ("wiki/filings/", "wiki/talk/")
    excluded_files = {"wiki/index.md", "wiki/log.md"}
    pages = []
    if not WIKI.is_dir():
        return pages
    for path in sorted(WIKI.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in excluded_files or rel.startswith(excluded_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fields, _body = parse_frontmatter(text)
        if not fields:
            continue
        sources = fields.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        if source_rel in [Path(s).as_posix() for s in sources]:
            pages.append(rel)
    return pages


def unaddressed_marks():
    """Actionable marks (correction / question) no page accounts
    for: [{source, mark, pages}] in deterministic order, where
    pages are the compiled pages citing that source (empty when
    no compiled page cites it yet — the marks are then waiting on
    the ingest itself)."""
    addressed = scan_addressed()
    out = []
    for source_rel in all_annotated_sources():
        pages = None
        for mark in read_marks(source_rel):
            if mark.get("kind") not in ACTIONABLE_KINDS:
                continue
            if (source_rel, mark.get("id")) in addressed:
                continue
            if pages is None:
                pages = compiled_pages_for_source(source_rel)
            out.append({"source": source_rel, "mark": mark,
                        "pages": pages})
    out.sort(key=lambda r: (r["source"], r["mark"]["id"]))
    return out


# -- Rendering -------------------------------------------------------------------------

def _locator_text(source_rel, mark):
    loc = mark["locator"]
    text = f"{source_rel}#L{loc['start']}-L{loc['end']}"
    return text


def export_markdown(source_rel):
    """The marks for one source as markdown (owner-readable)."""
    marks = read_marks(source_rel)
    addressed = scan_addressed()
    lines = [f"# Owner's marks — {source_rel}", ""]
    if not marks:
        lines += ["No marks recorded for this source.", ""]
        return "\n".join(lines)
    lines += [f"{len(marks)} mark(s), from"
              f" `{annotations_rel(source_rel)}` (raw source"
              " untouched).", ""]
    for mark in marks:
        head = (f"## {mark['id']} — {mark['kind']}"
                f" · {_locator_text(source_rel, mark)}"
                f" · {mark['created']}")
        lines += [head, ""]
        quote = mark["locator"].get("quote")
        if quote:
            lines += [f"> {quote}", ""]
        if mark["text"]:
            lines += [mark["text"], ""]
        state = ("addressed" if (source_rel, mark["id"]) in addressed
                 else "not yet addressed")
        lines += [f"_State: {state}._", ""]
    return "\n".join(lines)


# -- CLI ---------------------------------------------------------------------------------

def _parse_lines(spec):
    if not spec:
        return None, None
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    return int(spec), int(spec)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Annotation layer over raw: the owner's"
                    " marks beside each raw source (raw itself"
                    " is never written).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser(
        "add", help="record one mark (refused when its locator"
                    " does not resolve against the source)")
    p_add.add_argument("source", help="repo-relative source"
                                      " path under raw/")
    p_add.add_argument("--kind", required=True,
                       help="/".join(KINDS))
    p_add.add_argument("--text", default="",
                       help="the owner's words (required except"
                            " for a bare highlight)")
    p_add.add_argument("--lines", default=None, metavar="A[-B]",
                       help="1-based line range, cite-lock style")
    p_add.add_argument("--quote", default=None,
                       help="verbatim quote anchor from the source")
    p_add.add_argument("--created", default=None,
                       help="mark date (default: today)")

    p_list = sub.add_parser("list", help="list a source's marks")
    p_list.add_argument("source")

    p_export = sub.add_parser(
        "export", help="a source's marks as markdown")
    p_export.add_argument("source")

    sub.add_parser(
        "unaddressed",
        help="every actionable mark no compiled page accounts for")

    args = ap.parse_args(argv[1:])

    if args.cmd == "add":
        try:
            start, end = _parse_lines(args.lines)
            mark = add_mark(args.source, args.kind, args.text,
                            start, end, args.quote, args.created)
        except ValueError as exc:
            print(f"refused: {exc}")
            return 1
        print(f"recorded {mark['id']} ({mark['kind']}) at"
              f" {_locator_text(args.source, mark)} in"
              f" {annotations_rel(args.source)}")
        return 0

    if args.cmd == "list":
        marks = read_marks(args.source)
        addressed = scan_addressed()
        if not marks:
            print(f"no marks recorded for {args.source}")
            return 0
        for mark in marks:
            state = ("addressed"
                     if (args.source, mark["id"]) in addressed
                     else "unaddressed")
            print(f"{mark['id']} {mark['kind']:<10}"
                  f" {_locator_text(args.source, mark)}"
                  f" {mark['created']} [{state}]"
                  f" {mark['text'][:60]}")
        return 0

    if args.cmd == "export":
        print(export_markdown(args.source))
        return 0

    if args.cmd == "unaddressed":
        rows = unaddressed_marks()
        if not rows:
            print("no unaddressed actionable marks")
            return 0
        for row in rows:
            mark = row["mark"]
            pages = (", ".join(row["pages"]) if row["pages"]
                     else "no compiled page cites this source yet")
            print(f"{row['source']} {mark['id']} ({mark['kind']}):"
                  f" {mark['text'][:60]} — compiled by: {pages}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
