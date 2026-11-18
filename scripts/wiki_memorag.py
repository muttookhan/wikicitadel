#!/usr/bin/env python3
"""wiki_memorag.py — MemoRAG-pattern clue-generation pass.

Marathon Round 3, lane TB7, row 7. Pattern: MemoRAG's
clue-generation pass over a global corpus view (re-implemented
from the idea; MemoRAG uses a trained memory model — this
implementation is DETERMINISTIC and corpus-derived, no model
calls, per the unwired-router gate):

Before retrieval, a CLUE PASS reads the corpus's own statistics
and generates search clues for the query:

  * original   — the query itself, unchanged;
  * likely-title — page titles sharing a stemmed token with the
    query (the pages the query is probably ABOUT);
  * entity     — capitalised heading phrases from pages that
    share a query token (named things the corpus connects to
    the query);
  * synonym    — corpus co-occurrence neighbours: content tokens
    that appear in pages containing a query term, ranked by
    co-occurrence strength — the corpus's own vocabulary for
    the same topic, which the query may not have used.

Retrieval then runs PER CLUE through the standard hybrid
ranker, and the per-clue rankings are merged by reciprocal
rank fusion, each hit carrying the clues that found it. A page
the bare query misses surfaces when a clue's vocabulary
reaches it — and the clue list is printed, so the expansion is
never silent.

    python3 scripts/wiki_memorag.py clues --root DIR --q "..."
    python3 scripts/wiki_memorag.py search --root DIR --q "..." [--top 10]

Stdlib only.
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
RRF_K = 60
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are",
        "was", "were", "for", "on", "with", "as", "by", "it", "its",
        "this", "that", "from", "at", "be", "has", "have", "had",
        "what", "when", "where", "which", "who", "how", "why"}
# Frontmatter field names are structure, not vocabulary: they
# appear on every page and would otherwise dominate the
# co-occurrence neighbours (a "title" synonym clue matches the
# whole corpus's frontmatter).
STRUCTURAL = {"title", "type", "created", "updated", "sources",
              "tags", "stage", "status", "planted", "tended"}
HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
CAP_PHRASE_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def _load_search():
    spec = importlib.util.spec_from_file_location(
        "wiki_search_for_memorag", Path(__file__).with_name("wiki_search.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load_search()


def generate_clues(query, docs, max_titles=3, max_entities=3,
                   max_synonyms=5):
    """The deterministic clue pass. docs: [(path, text)].
    Returns [{"kind", "clue", "terms"}] in a fixed order:
    original, likely-titles (by shared-stem count, then path),
    entities (by frequency, then name), synonyms (by strength,
    then term)."""
    q_terms = ws.tokenize(query)
    q_stems = {ws.stem_token(t) for t in q_terms}
    clues = [{"kind": "original", "clue": query, "terms": q_terms}]

    titles = []       # (shared stems, path, title)
    entities = Counter()
    cooc = Counter()
    df = Counter()
    for p, text in docs:
        toks = ws.tokenize(text)
        df.update(set(toks))
        title = ws.doc_title(text)
        shared = len(q_stems & {ws.stem_token(t)
                                 for t in ws.tokenize(title)})
        if title and shared:
            titles.append((-shared, str(p), title))
        if q_stems & {ws.stem_token(t) for t in toks}:
            for heading in HEADING_RE.findall(text):
                for phrase in CAP_PHRASE_RE.findall(heading):
                    entities[phrase] += 1
            present = {t for t in set(toks)
                       if t not in STOP and t not in STRUCTURAL
                       and len(t) >= 3}
            for t in present:
                if ws.stem_token(t) not in q_stems:
                    cooc[t] += 1
    titles.sort()
    for _s, _p, title in titles[:max_titles]:
        clues.append({"kind": "likely-title", "clue": title,
                      "terms": ws.tokenize(title) + q_terms})
    for phrase, _c in sorted(entities.items(),
                             key=lambda kv: (-kv[1], kv[0]))[:max_entities]:
        clues.append({"kind": "entity", "clue": phrase,
                      "terms": ws.tokenize(phrase) + q_terms})
    # Synonym strength: co-occurrence count discounted by the
    # neighbour's own document frequency — a term everywhere is
    # nobody's synonym.
    scored = []
    for term, c in cooc.items():
        if c >= 2:
            scored.append((-(c * c) / (df[term] + 1), term))
    scored.sort()
    for _s, term in scored[:max_synonyms]:
        clues.append({"kind": "synonym", "clue": term,
                      "terms": list(q_terms) + [term]})
    return clues


def search_with_clues(query, docs, adj=None, top=10, **clue_kw):
    """Per-clue hybrid retrieval + RRF merge. Returns
    (clues, [{"path", "score", "clues": [kinds]}]) — the merged
    ranking with each hit's clue provenance."""
    clues = generate_clues(query, docs, **clue_kw)
    if adj is None:
        adj = ws.build_link_graph(docs)
    fused = {}
    for clue in clues:
        ranked = ws.hybrid_rank(clue["terms"], docs, adj,
                                severance=False)
        for rank, (_s, p, _t, _d) in enumerate(ranked, start=1):
            key = str(p)
            entry = fused.setdefault(
                key, {"path": key, "score": 0.0, "clues": []})
            entry["score"] += 1.0 / (RRF_K + rank)
            if clue["kind"] not in entry["clues"]:
                entry["clues"].append(clue["kind"])
    out = sorted(fused.values(), key=lambda r: (-r["score"], r["path"]))
    return clues, out[:top]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--q", required=True)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("cmd", choices=("clues", "search"))
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    old = ws.ROOT
    ws.ROOT = root
    try:
        docs = []
        wiki = root / "wiki"
        for p in sorted(wiki.rglob("*.md")):
            docs.append((p, p.read_text(encoding="utf-8",
                                        errors="ignore")))
        if args.cmd == "clues":
            print(json.dumps(generate_clues(args.q, docs),
                             indent=2, ensure_ascii=False))
        else:
            clues, hits = search_with_clues(args.q, docs, top=args.top)
            print(json.dumps({"query": args.q, "clues": clues,
                              "hits": hits}, indent=2,
                             ensure_ascii=False))
    finally:
        ws.ROOT = old
    return 0


if __name__ == "__main__":
    sys.exit(main())
