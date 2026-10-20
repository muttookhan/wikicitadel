#!/usr/bin/env python3
"""Compiled-layer tombstones + the relation-vocabulary census.

WikiCitadel v1. Two patterns,
re-implemented:

  - DataCite tombstone practice (the survey —
    docs/research-notes.md, find 2): withdrawal is a
    three-step ritual — de-index, repoint the identifier at a
    tombstone carrying the last metadata, record a Withdrawn
    date with the reason. Nothing is deleted; the resolution
    target changes from the thing to the account of the
    thing. Here the identifier is the page path: a retired
    compiled page keeps its path and becomes its tombstone,
    so every existing [[link]] to it resolves to an
    explanation instead of a hole.
  - The closed relation vocabulary
    (wiki/rules/relation-vocabulary.md; DataCite relationType
    + CiTO, restated in our words — same survey file, find 3):
    the `relations` subcommand censuses the corpus against
    it — the batch-3.1 typed edges (tools/lens/lenslib.py,
    imported in-process) and frontmatter relation
    declarations — and counts what falls outside.

Commands:

  tombstone --page wiki/<...>.md --reason "..."
            [--replaced-by wiki/<...>.md] [--apply] [--date D]
      Convert a retired page to its tombstone form:
      frontmatter preserved and extended (status: tombstoned,
      tombstoned: <date>, tombstone_reason:, replaced_by: when
      given, updated:), body replaced by the tombstone notice.
      DELIBERATELY defaults to --dry-run: the transformation
      discards the page body from the working tree (git keeps
      it), so it only runs with an explicit --apply AND a
      --reason. Structural pages (wiki/index.md, wiki/log.md)
      and anything outside wiki/ are refused; an already-
      tombstoned page is refused.
  list      Every tombstoned page, with its date, reason and
            replacement.
  relations Census the typed edges + frontmatter relation
            declarations against the closed vocabulary and
            print the counts (the filing under wiki/filings/
            records a run).

Stdlib only (lenslib imported in-process for the census).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter = _wv.parse_frontmatter


def _load_lenslib():
    spec = importlib.util.spec_from_file_location(
        "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- The closed vocabulary ---------------------------------------------------
# Canonical terms (wiki/rules/relation-vocabulary.md). Frontmatter
# spellings are the snake_case field names in use; the census maps
# each observed spelling to its canonical term and verdict.
VOCABULARY = (
    "supersedes", "is-superseded-by", "cites", "is-cited-by",
    "corrects", "is-corrected-by", "extends", "contradicts",
    "derives-from", "replaces-part-of",
)

FM_RELATIONS = {
    # spelling -> (canonical term, in_vocabulary, note)
    "supersedes": ("supersedes", True, ""),
    "superseded_by": ("is-superseded-by", True, ""),
    "superseded-by": ("is-superseded-by", True, ""),
    "replaces": ("supersedes", True, "accepted spelling variant"),
    "replaced_by": ("is-superseded-by", True,
                    "accepted spelling variant"),
    "cites": ("cites", True, ""),
    "cited_by": ("is-cited-by", True, ""),
    "corrects": ("corrects", True, ""),
    "corrected_by": ("is-corrected-by", True, ""),
    "extends": ("extends", True, ""),
    "extended_by": (None, False,
                    "no inverse of extends was adopted"),
    "contradicts": ("contradicts", True, "self-inverse"),
    "derives_from": ("derives-from", True, ""),
    "derived_from": ("derives-from", True,
                     "accepted spelling variant"),
    "replaces_part_of": ("replaces-part-of", True, ""),
    "based_on": (None, False,
                 "near-match to derives-from; not the adopted term"),
    "part_of": (None, False,
                "part/whole was not adopted (replaces-part-of is a"
                " different, narrower claim)"),
    "has_part": (None, False, "part/whole was not adopted"),
    "see_also": (None, False, "untyped association (≈ mentions)"),
    "related": (None, False, "untyped association (≈ mentions)"),
}
STRUCTURAL_FM = {"about"}  # talk pages: a pointer, not a relation

EDGE_VOCABULARY = {
    # lenslib LINK_TYPES -> (canonical term or None, in_vocabulary)
    "contradicts": ("contradicts", True),
    "supersedes": ("supersedes", True),
    "extends": ("extends", True),
    "grounds": (None, False),      # evidence relation; not adopted
    "exemplifies": (None, False),  # example relation; not adopted
    "mentions": (None, False),     # the untyped default
}


# -- Frontmatter editing -----------------------------------------------------

def _fmt_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./\- ]+", value) \
            and not value.startswith((" ", "- ")):
        return value
    return json.dumps(value, ensure_ascii=False)


def set_fm_fields(text: str, updates: dict, inserts: dict) -> str:
    """Set existing scalar fields in place; append new fields
    before the closing fence. Everything else is preserved
    byte-for-byte. (Modelled on scripts/wiki_claims.py's
    _set_fm_fields.)"""
    m = re.match(r"^(---\n)(.*?)(\n---\n?)", text, re.S)
    if not m:
        raise ValueError("page has no frontmatter block")
    head, fm, tail = m.group(1), m.group(2), m.group(3)
    lines = fm.split("\n")
    remaining_updates = dict(updates)
    for i, line in enumerate(lines):
        km = re.match(r"^([A-Za-z_]+):", line)
        if km and km.group(1) in remaining_updates:
            key = km.group(1)
            lines[i] = f"{key}: {_fmt_scalar(str(remaining_updates.pop(key)))}"
    # Fields being set that the page does not carry yet are
    # appended (in update order), ahead of the pure inserts.
    for key, val in remaining_updates.items():
        lines.append(f"{key}: {_fmt_scalar(str(val))}")
    for key, val in inserts.items():
        if key not in updates:
            lines.append(f"{key}: {_fmt_scalar(str(val))}")
    return head + "\n".join(lines) + tail + text[m.end():]


def page_stem_link(rel: str) -> str:
    """wiki/concepts/new-page.md -> [[concepts/new-page]]"""
    stem = rel[len("wiki/"):-len(".md")] if rel.startswith("wiki/") \
        and rel.endswith(".md") else rel
    return f"[[{stem}]]"


# -- Tombstone ---------------------------------------------------------------

def build_tombstone(text: str, rel: str, date_s: str, reason: str,
                    replaced_by: str | None) -> str:
    fields, _body = parse_frontmatter(text)
    if not fields:
        raise ValueError(f"{rel}: no frontmatter — not a compiled page")
    if str(fields.get("status")) == "tombstoned":
        raise ValueError(f"{rel}: already tombstoned "
                         f"({fields.get('tombstoned')})")
    title = str(fields.get("title") or Path(rel).stem)
    new_text = set_fm_fields(
        text,
        {"status": "tombstoned", "updated": date_s},
        {"tombstoned": date_s, "tombstone_reason": reason,
         **({"replaced_by": replaced_by} if replaced_by else {})})
    fm_end = new_text.index("\n---", 3) + len("\n---\n")
    if replaced_by:
        relation_line = (
            f"Its replacement is {page_stem_link(replaced_by)} — in"
            f" the relation vocabulary"
            f" ([[relation-vocabulary]]), this page"
            f" **is-superseded-by** that page.")
        callout_replacement = \
            f"> What replaced it: {page_stem_link(replaced_by)}\n"
    else:
        relation_line = ("It was retired without a replacement.")
        callout_replacement = ""
    body = f"""
# {title}

> [!warning] Tombstone — this page was retired on {date_s}
> {reason}
{callout_replacement}
This page is a **tombstone**. Its path is kept so that links
to it resolve to this account of what happened, instead of to
a hole. {relation_line}

The full prior text is preserved in this repository's git
history (the version immediately before this tombstone) and
the sources it compiled remain in the raw layer. Nothing was
deleted.
"""
    return new_text[:fm_end] + body


def cmd_tombstone(args, root):
    page = (root / args.page)
    try:
        rel = page.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        print(f"tombstone: {args.page} is outside the repo")
        return 2
    if not rel.startswith("wiki/") or not rel.endswith(".md"):
        print(f"tombstone: {rel} is not a compiled wiki page"
              " (wiki/**/*.md only)")
        return 2
    if rel in STRUCTURAL:
        print(f"tombstone: {rel} is structural — it carries the"
              " catalogue/log and is never tombstoned")
        return 2
    if not page.is_file():
        print(f"tombstone: no such page: {rel}")
        return 2
    if args.apply and not (args.reason or "").strip():
        print("tombstone: --apply requires --reason (the Withdrawn"
              " record carries the reason, per tombstone practice)")
        return 2
    date_s = args.date or date.today().isoformat()
    if _wv.parse_date(date_s) is None:
        print(f"tombstone: bad --date {date_s!r}")
        return 2
    text = page.read_text(encoding="utf-8")
    try:
        new_text = build_tombstone(text, rel, date_s,
                                   args.reason or "(no reason given"
                                   " — dry run only)",
                                   args.replaced_by)
    except ValueError as exc:
        print(f"tombstone: {exc}")
        return 2
    if not args.apply:
        print("== DRY RUN — nothing written ==")
        print(f"Would tombstone {rel} on {date_s}:")
        print("--- begin would-be page ---")
        print(new_text, end="")
        print("--- end would-be page ---")
        return 0
    page.write_text(new_text, encoding="utf-8")
    print(f"tombstoned {rel} on {date_s}"
          + (f" — replaced by {args.replaced_by}"
             if args.replaced_by else ""))
    return 0


def cmd_list(args, root):
    wiki = root / "wiki"
    rows = []
    if wiki.exists():
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel.startswith("wiki/access/"):
                continue
            fields, _b = parse_frontmatter(
                p.read_text(encoding="utf-8", errors="ignore"))
            if fields and str(fields.get("status")) == "tombstoned":
                rows.append((rel, fields))
    if not rows:
        print("no tombstoned pages")
        return 0
    for rel, fields in rows:
        print(f"{rel}  tombstoned {fields.get('tombstoned')}"
              f"  reason: {fields.get('tombstone_reason')}"
              f"  replaced_by: {fields.get('replaced_by') or '—'}")
    print(f"{len(rows)} tombstone(s)")
    return 0


# -- Relation census ---------------------------------------------------------

def compiled_pages(root: Path):
    wiki = root / "wiki"
    out = []
    if wiki.exists():
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel.startswith("wiki/access/"):
                continue
            out.append((rel, p))
    return out


def census(root: Path) -> dict:
    lenslib = _load_lenslib()
    edge_counts = Counter()
    edge_pages = Counter()
    fm_counts = {}   # key -> {instances, pages:set, canonical, in_vocab, note}
    structural_counts = Counter()
    source_refs = 0
    pages = compiled_pages(root)
    for rel, p in pages:
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, body = parse_frontmatter(text)
        page_types = set()
        for _t, _a, _l, _h, ltype in lenslib.extract_wikilinks_typed(body):
            edge_counts[ltype] += 1
            page_types.add(ltype)
        for ltype in page_types:
            edge_pages[ltype] += 1
        if fields:
            for key, (canon, in_vocab, note) in FM_RELATIONS.items():
                if key in fields and fields[key] not in (None, "", "null"):
                    value = fields[key]
                    n = len(value) if isinstance(value, list) else 1
                    row = fm_counts.setdefault(
                        key, {"instances": 0, "pages": set(),
                              "canonical": canon, "in_vocab": in_vocab,
                              "note": note})
                    row["instances"] += n
                    row["pages"].add(rel)
            for key in STRUCTURAL_FM:
                if key in fields and fields[key] not in (None, ""):
                    structural_counts[key] += 1
            sources = fields.get("sources")
            if isinstance(sources, list):
                source_refs += len(sources)
            elif sources:
                source_refs += 1
    return {"pages": len(pages), "edges": edge_counts,
            "edge_pages": edge_pages, "fm": fm_counts,
            "structural": structural_counts, "source_refs": source_refs}


def cmd_relations(args, root):
    c = census(root)
    edges = c["edges"]
    total_edges = sum(edges.values())
    in_edges = sum(n for t, n in edges.items()
                   if EDGE_VOCABULARY.get(t, (None, False))[1])
    print(f"== Relation census — {c['pages']} compiled pages"
          f" (wiki/**, access excluded) ==")
    print("\nTyped edges (batch-3.1 table, tools/lens/lenslib.py):")
    for ltype in sorted(edges):
        canon, in_vocab = EDGE_VOCABULARY.get(ltype, (None, False))
        verdict = f"in vocabulary as {canon}" if in_vocab \
            else "OUTSIDE the adopted vocabulary"
        print(f"  {ltype:<14} {edges[ltype]:>5} edge(s) on"
              f" {c['edge_pages'][ltype]:>3} page(s) — {verdict}")
    print(f"  {'TOTAL':<14} {total_edges:>5} edge(s) —"
          f" {in_edges} in vocabulary,"
          f" {total_edges - in_edges} outside")
    print("\nFrontmatter relation declarations:")
    if not c["fm"]:
        print("  (none — no page declares a relation in frontmatter)")
    fm_in = fm_out = 0
    for key in sorted(c["fm"]):
        row = c["fm"][key]
        if row["in_vocab"]:
            fm_in += row["instances"]
            verdict = f"in vocabulary as {row['canonical']}"
        else:
            fm_out += row["instances"]
            verdict = "OUTSIDE the adopted vocabulary"
        note = f" ({row['note']})" if row["note"] else ""
        print(f"  {key:<16} {row['instances']:>3} instance(s) on"
              f" {len(row['pages'])} page(s) — {verdict}{note}")
    print(f"  TOTAL {fm_in + fm_out} instance(s) — {fm_in} in"
          f" vocabulary, {fm_out} outside")
    for key, n in sorted(c["structural"].items()):
        print(f"\nStructural frontmatter (a pointer, not a relation):"
              f" {key}: {n} page(s)")
    print(f"\nPage->source references via `sources:` frontmatter:"
          f" {c['source_refs']} — the field itself is the cites"
          " relation, typed by the citation lockfile machinery;"
          " counted separately, never as a violation.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compiled-layer tombstones + relation census.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="command", required=True)
    p_t = sub.add_parser("tombstone", help="convert a retired page"
                                           " to its tombstone form")
    p_t.add_argument("--page", required=True,
                     help="repo-relative page path (wiki/**/*.md)")
    p_t.add_argument("--reason", default="",
                     help="why the page is retired (required with"
                          " --apply; recorded on the tombstone)")
    p_t.add_argument("--replaced-by", default=None,
                     help="repo-relative path of the replacing page")
    p_t.add_argument("--apply", action="store_true",
                     help="write the tombstone (default: dry run)")
    p_t.add_argument("--date", default=None,
                     help="tombstone date YYYY-MM-DD (default: today)")
    sub.add_parser("list", help="list tombstoned pages")
    sub.add_parser("relations", help="census typed edges + frontmatter"
                                     " relations against the vocabulary")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.command == "tombstone":
        return cmd_tombstone(args, root)
    if args.command == "list":
        return cmd_list(args, root)
    if args.command == "relations":
        return cmd_relations(args, root)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
