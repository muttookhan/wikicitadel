#!/usr/bin/env python3
"""wiki_suggest_filing.py — suggested filing at ingest
(Marathon Round 3, lane TA4; row: "DEVONthink Classify —
suggested filing at ingest", Tier A half only; pattern:
DEVONthink's Classify — proprietary, IDEA ONLY).

At capture/ingest time this tool SUGGESTS a destination for an
item — the existing wiki page or section it most resembles —
from title/tag similarity over the existing index
(wiki/index.md, read index-first per the house protocol; when
a tree has no index, wiki/**/*.md page titles are the
fallback). It is a suggestion seam only:

- it NEVER files, moves, creates or edits anything — the tool
  has no write path at all, and its tests pin that the tree is
  byte-identical after a run;
- the heavier classifier (the boarded Tier B half) is another
  lane's row; this module is the deterministic similarity the
  suggestion stands on, so any later classifier replaces the
  scoring, not the seam.

Scoring is transparent token overlap, stated in the output:
title tokens shared with a page's title weigh 2, shared with
its index summary weigh 1, a shared tag weighs 3. Stopwords
and tokens shorter than 3 characters carry no signal and are
dropped. Only positive scores are suggested, best first, at
most --limit of them. No overlap is a stated empty result,
never a forced suggestion.

    python3 scripts/wiki_suggest_filing.py suggest
        --title "..." [--tags a,b] [--limit 3] [--root DIR]

Exit codes: 0 ok (including "no suggestions") · 2 usage error.
Output is JSON: {"title", "suggestions": [{page, title, score,
matched_terms, matched_tags}]}.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = Path("wiki/index.md")

STOPWORDS = {"the", "a", "an", "and", "or", "of", "for", "to",
             "in", "on", "at", "by", "with", "from", "how",
             "what", "why", "is", "are", "was", "were", "this",
             "that", "it", "its", "as", "be", "into", "about"}
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*[—-]?\s*(.*)")
FRONTMATTER_TITLE_RE = re.compile(r"^title:\s*\"?([^\"\n]+)\"?",
                                  re.M)
FRONTMATTER_TAGS_RE = re.compile(r"^tags:\s*\[([^\]]*)\]", re.M)


def _tokens(text):
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) >= 3 and t not in STOPWORDS}


def index_entries(root):
    """Candidate destinations from wiki/index.md: every
    [[wikilink]] line gives a page path (as written in the
    link, with .md appended when the link omits it) plus the
    line's summary text. When no index exists, falls back to
    scanning wiki/**/*.md frontmatter titles + tags."""
    root = Path(root)
    entries = []
    index = root / INDEX
    if index.is_file():
        section = ""
        for line in index.read_text(encoding="utf-8",
                                    errors="replace").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            m = LINK_RE.search(line)
            if not m:
                continue
            target = m.group(1).strip()
            page = target if target.endswith(".md") \
                else target + ".md"
            if not page.startswith("wiki/"):
                page = "wiki/" + page.lstrip("/")
            title = Path(target).stem.replace("-", " ")
            entries.append({"page": page, "title": title,
                            "summary": m.group(2).strip(),
                            "section": section, "tags": []})
        if entries:
            return entries
    wiki = root / "wiki"
    if wiki.is_dir():
        for path in sorted(wiki.rglob("*.md")):
            text = path.read_text(encoding="utf-8",
                                  errors="replace")[:4000]
            tm = FRONTMATTER_TITLE_RE.search(text)
            gm = FRONTMATTER_TAGS_RE.search(text)
            tags = [t.strip().strip("\"'")
                    for t in (gm.group(1).split(",") if gm else [])
                    if t.strip()]
            entries.append({
                "page": str(path.relative_to(root)),
                "title": tm.group(1).strip() if tm
                else path.stem.replace("-", " "),
                "summary": "", "section": "", "tags": tags})
    return entries


def suggest(root, title, tags=None, limit=3):
    """Ranked destination suggestions for an item with this
    title/tags. Suggestion only — reads the index, writes
    nothing, files nothing."""
    title_tokens = _tokens(title)
    want_tags = {t.strip().lower() for t in (tags or [])
                 if t.strip()}
    scored = []
    for entry in index_entries(root):
        matched_terms = sorted(
            title_tokens & (_tokens(entry["title"])
                            | _tokens(entry["summary"])))
        title_hits = title_tokens & _tokens(entry["title"])
        summary_hits = set(matched_terms) - title_hits
        matched_tags = sorted(want_tags
                              & {t.lower() for t in entry["tags"]})
        score = 2 * len(title_hits) + len(summary_hits) \
            + 3 * len(matched_tags)
        if score <= 0:
            continue
        scored.append({"page": entry["page"],
                       "title": entry["title"],
                       "section": entry["section"],
                       "score": score,
                       "matched_terms": matched_terms,
                       "matched_tags": matched_tags})
    scored.sort(key=lambda s: (-s["score"], s["page"]))
    return scored[:limit]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("suggest")
    p.add_argument("--title", required=True)
    p.add_argument("--tags", default="",
                   help="comma-separated tags the item carries")
    p.add_argument("--limit", type=int, default=3)
    args = ap.parse_args(argv)
    tags = [t for t in args.tags.split(",") if t.strip()]
    out = {"title": args.title, "tags": tags,
           "suggestion_only": True,
           "note": "suggestions only — nothing was filed, "
                   "moved or created by this tool",
           "suggestions": suggest(args.root, args.title,
                                  tags=tags, limit=args.limit)}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
