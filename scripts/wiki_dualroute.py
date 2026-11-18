#!/usr/bin/env python3
"""wiki_dualroute.py — dual-level retrieval routing (CN5b).

Tier A harvest row CN5b, from the china harvest (LightRAG,
HKUDS, MIT — dual-level (low/high) retrieval design adapted
with credit; cite HKUDS/LightRAG and the EMNLP 2025 paper.
Re-implemented here from the idea; no LightRAG code copied).

A query is routed, by DETERMINISTIC rules stated in code
below, to one of:

  page     — page-level search: whole pages are the unit
             (entity / definition / overview / theme hunts);
  passage  — passage/chunk-level search: heading sections
             and paragraph chunks are the unit (pinpoint
             facts, quoted wording, dated / numbered claims);
  both     — the query shape is genuinely ambiguous, so
             both levels run and both result lists are
             returned, labelled — never silently merged.

The router is a pure function of the query string
(classify_query); the search side runs over the existing
machinery in scripts/wiki_search.py (its BM25 ranker,
tokeniser, title and snippet helpers) and returns page hits
or ranked passages built by splitting the BM25 candidate
pages into chunks. No new ranker is invented and the golden
set's measured hybrid ranking is untouched: this tool is a
routing layer, not a replacement engine.

    python3 scripts/wiki_dualroute.py route "<query>"
    python3 scripts/wiki_dualroute.py search "<query>" [--top N]
            [--scope wiki|raw|all] [--root DIR]
    # explicit prefixes page: / passage: / chunk: force a level

Exit codes: 0 ok · 1 no searchable terms / no results for a
route command is still 0 with an empty list · 2 usage error.
Machine-readable output is JSON with --json (search defaults
to JSON; route prints one plain line without it).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_search():
    path = Path(__file__).resolve().parent / "wiki_search.py"
    spec = importlib.util.spec_from_file_location("wiki_search", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _WS = _load_search()
    tokenize = _WS.tokenize
except Exception:  # pragma: no cover - wiki_search always ships beside us
    _WS = None

    def tokenize(text: str):
        return [t for t in re.findall(r"[a-z0-9]+", text.lower())
                if len(t) >= 2]


# ---------------------------------------------------------------------------
# The routing rules — stated here, applied in this exact order.
# The first rule that fires decides; every decision records the
# rule id so fixtures (and callers) can pin WHY a query routed
# where it did. Rules R1..R8:
#
#  R1 explicit   a leading "page:" / "pages:" prefix -> page;
#                a leading "passage:" / "chunk:" prefix -> passage.
#  R2 quoted     a double-quoted phrase in the query -> passage
#                (the caller is hunting exact wording).
#  R3 pinpoint-id  any term that is a year (19xx/20xx), carries a
#                digit, or is an ISO-date fragment -> passage
#                (a dated / numbered fact lives in a chunk).
#  R4 overview   an overview cue term (overview, summary,
#                summarise/summarize, compare, comparison,
#                relationship, theme(s), landscape, survey,
#                list, map) -> page (the answer is a whole page
#                or a synthesis of pages).
#  R5 definition a leading what-is / who-is / what-are / define
#                shape, or a short query (<= 3 terms) -> page
#                (entity / title hunt).
#  R6 pinpoint-cue  a pinpoint cue term (exact, quote, passage,
#                section, when, where, which, said, says,
#                mention, mentions, mentioned) -> passage.
#  R7 long       >= 7 terms -> passage (a specific, qualified
#                question; its evidence is a chunk, not a page).
#  R8 default    anything else -> both (ambiguous shape; run
#                both levels, labelled, never merged silently).
# ---------------------------------------------------------------------------

OVERVIEW_CUES = {
    "overview", "summary", "summarise", "summarize", "compare",
    "comparison", "relationship", "relationships", "theme",
    "themes", "landscape", "survey", "list", "map",
}
PINPOINT_CUES = {
    "exact", "quote", "quoted", "passage", "section", "when",
    "where", "which", "said", "says", "mention", "mentions",
    "mentioned",
}
DEFINITION_LEADS = (
    ("what", "is"), ("what", "are"), ("who", "is"), ("who", "are"),
    ("define",),
)
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
PREFIX_RE = re.compile(r"^(page|pages|passage|chunk)\s*:\s*", re.I)
MAX_CHUNK_CHARS = 1200


def classify_query(query: str) -> dict:
    """Route one query. Returns {"route": "page"|"passage"|"both",
    "rule": "R1".."R8", "reason": str, "terms": [...],
    "query": the query with any R1 prefix stripped}."""
    q = (query or "").strip()
    m = PREFIX_RE.match(q)
    if m:
        level = "page" if m.group(1).lower().startswith("page") else "passage"
        stripped = q[m.end():].strip()
        return {"route": level, "rule": "R1",
                "reason": f"explicit '{m.group(1).lower()}:' prefix",
                "terms": tokenize(stripped), "query": stripped}
    terms = tokenize(q)
    if not terms:
        return {"route": "both", "rule": "R8",
                "reason": "no searchable terms; no level can be chosen",
                "terms": [], "query": q}
    if '"' in q:
        return {"route": "passage", "rule": "R2",
                "reason": "quoted phrase: exact-wording hunt",
                "terms": terms, "query": q}
    if any(YEAR_RE.match(t) or any(c.isdigit() for c in t) for t in terms):
        return {"route": "passage", "rule": "R3",
                "reason": "dated/numbered term: pinpoint fact",
                "terms": terms, "query": q}
    if set(terms) & OVERVIEW_CUES:
        return {"route": "page", "rule": "R4",
                "reason": "overview cue term: whole-page/theme hunt",
                "terms": terms, "query": q}
    if tuple(terms[:2]) in DEFINITION_LEADS or \
            tuple(terms[:1]) in DEFINITION_LEADS or len(terms) <= 3:
        return {"route": "page", "rule": "R5",
                "reason": "definition shape or short entity query",
                "terms": terms, "query": q}
    if set(terms) & PINPOINT_CUES:
        return {"route": "passage", "rule": "R6",
                "reason": "pinpoint cue term: chunk-level fact",
                "terms": terms, "query": q}
    if len(terms) >= 7:
        return {"route": "passage", "rule": "R7",
                "reason": "long qualified question (>= 7 terms)",
                "terms": terms, "query": q}
    return {"route": "both", "rule": "R8",
            "reason": "ambiguous shape: both levels, labelled",
            "terms": terms, "query": q}


# ---------------------------------------------------------------------------
# Passage splitting + ranking (the chunk level)
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def split_passages(text: str, rel: str = "") -> list[dict]:
    """Split one document into passages: one per heading section,
    with any section longer than MAX_CHUNK_CHARS further split
    into paragraph groups. Each passage: {"path", "heading",
    "start_line", "end_line", "text"} (1-based lines)."""
    sections = []          # (heading, start_idx, [lines])
    heading = ""
    start = 0
    buf: list[str] = []
    lines = text.splitlines()

    def flush(end_idx):
        if buf or heading:
            sections.append((heading, start, list(buf)))

    for i, line in enumerate(lines):
        hm = HEADING_RE.match(line)
        if hm:
            flush(i - 1)
            heading = hm.group(2).strip()
            start = i
            buf = [line]
        else:
            if not sections and not buf and heading == "":
                start = i
            buf.append(line)
    flush(len(lines) - 1)

    out = []
    for heading, s_idx, sec_lines in sections:
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue
        if len(sec_text) <= MAX_CHUNK_CHARS:
            out.append({"path": rel, "heading": heading,
                        "start_line": s_idx + 1,
                        "end_line": s_idx + len(sec_lines),
                        "text": sec_text})
            continue
        # Split an over-long section on paragraph boundaries.
        chunk: list[str] = []
        chunk_start = s_idx
        pos = s_idx
        for para in re.split(r"\n\s*\n", sec_text):
            plen = len(para)
            if chunk and sum(len(c) for c in chunk) + plen > MAX_CHUNK_CHARS:
                out.append({"path": rel, "heading": heading,
                            "start_line": chunk_start + 1,
                            "end_line": pos,
                            "text": "\n\n".join(chunk).strip()})
                chunk = []
                chunk_start = pos
            chunk.append(para)
            pos += para.count("\n") + 2
        if chunk:
            out.append({"path": rel, "heading": heading,
                        "start_line": chunk_start + 1,
                        "end_line": s_idx + len(sec_lines),
                        "text": "\n\n".join(chunk).strip()})
    return [p for p in out if p["text"]]


def score_passage(terms, passage: dict) -> float:
    """Deterministic chunk score: 10 per distinct query term in
    the chunk text, 1 per occurrence, +5 per distinct term in
    the heading. Zero means no query term at all."""
    qset = set(terms)
    toks = tokenize(passage["text"])
    have = qset & set(toks)
    if not have:
        return 0.0
    counts = Counter(t for t in toks if t in qset)
    head_have = qset & set(tokenize(passage.get("heading") or ""))
    return 10.0 * len(have) + float(sum(counts.values())) \
        + 5.0 * len(head_have)


def rank_passages(terms, docs, top=10, candidate_pages=10):
    """Rank chunks over the BM25 candidate pages (the existing
    ranker picks the pages; this level picks the chunk inside
    them). docs: [(Path, text)]. Returns passage dicts with a
    "score", sorted by (-score, path, start_line)."""
    if _WS is not None:
        ranked = _WS.bm25_rank(terms, docs)
        candidates = ranked[:candidate_pages] if ranked else docs[:0]
        # When BM25 finds nothing there is nothing to chunk.
        pool = [(p, t) for _s, p, t in candidates]
    else:  # pragma: no cover
        pool = docs
    scored = []
    for p, text in pool:
        rel = str(p)
        for passage in split_passages(text, rel):
            s = score_passage(terms, passage)
            if s > 0:
                scored.append({**passage, "score": round(s, 3)})
    scored.sort(key=lambda r: (-r["score"], r["path"], r["start_line"]))
    return scored[:top]


def collect_docs(root: Path, scope: str):
    docs = []
    bases = []
    if scope in ("wiki", "all"):
        bases.append(root / "wiki")
    if scope in ("raw", "all"):
        bases.append(root / "raw")
    for base in bases:
        if base.exists():
            for p in sorted(base.rglob("*.md")):
                if p.is_file():
                    docs.append((p, p.read_text(
                        encoding="utf-8", errors="ignore")))
    return docs


def rel_of(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)


def search(root: Path, query: str, top=10, scope="all") -> dict:
    """Classify, then run the routed level(s). Page hits carry
    path/title/score/snippet; passage hits carry path/heading/
    line range/score/text."""
    decision = classify_query(query)
    terms = decision["terms"]
    result = {"query": decision["query"], "route": decision["route"],
              "rule": decision["rule"], "reason": decision["reason"],
              "terms": terms, "pages": [], "passages": []}
    if not terms:
        return result
    docs = collect_docs(root, scope)
    # Re-key docs by repo-relative path for stable output.
    docs = [(root / rel_of(root, p), t) for p, t in docs]
    if decision["route"] in ("page", "both"):
        if _WS is not None:
            ranked = _WS.bm25_rank(terms, docs)
        else:  # pragma: no cover
            ranked = []
        for score, p, text in ranked[:top]:
            result["pages"].append({
                "path": rel_of(root, p), "score": round(score, 4),
                "title": _WS.doc_title(text) if _WS else "",
                "snippet": _WS.make_snippet(text, terms) if _WS else ""})
    if decision["route"] in ("passage", "both"):
        passages = rank_passages(terms, docs, top=top)
        for passage in passages:
            passage = dict(passage)
            # rank_passages keyed paths by str(path); normalise.
            try:
                passage["path"] = rel_of(root, Path(passage["path"]))
            except Exception:
                pass
            result["passages"].append(passage)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("route", "search"):
        p = sub.add_parser(name)
        p.add_argument("query")
        p.add_argument("--top", type=int, default=10)
        p.add_argument("--scope", choices=("wiki", "raw", "all"),
                       default="all")
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "route":
        d = classify_query(args.query)
        if args.json:
            print(json.dumps(d, indent=1))
        else:
            print(f"{d['route']} ({d['rule']}: {d['reason']})")
        return 0
    res = search(args.root, args.query, top=args.top, scope=args.scope)
    print(json.dumps(res, indent=1))
    return 0 if res["terms"] else 1


if __name__ == "__main__":
    sys.exit(main())
