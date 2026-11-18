#!/usr/bin/env python3
"""wiki_graphrag.py — GraphRAG-style community summaries.

Marathon Round 3, lane TB7, row 4. Pattern: GraphRAG's
community-summary map-reduce (Microsoft's GraphRAG, MIT —
re-implemented from the idea): the link graph's communities are
detected once (here: the graph export's deterministic label
propagation, scripts/wiki_graph_export.py), then

  MAP    — every member page of a community is summarised
           extractively (the RAPTOR module's extractive
           summariser; no model calls);
  REDUCE — the member summaries of one community are summarised
           again into ONE community summary record, with the
           community's top terms and top pages.

The records are stored as data the search layer can consult
(default: evaluation/community-summaries.json): `consult()`
ranks communities against a query by token overlap over the
summary + top terms + member titles, so a broad question can be
routed to the community that owns the topic before page-level
retrieval runs.

    python3 scripts/wiki_graphrag.py build --root DIR \\
        [--out evaluation/community-summaries.json]
    python3 scripts/wiki_graphrag.py query --file FILE --q "..."

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
DEFAULT_OUT_REL = "evaluation/community-summaries.json"
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are",
        "was", "were", "for", "on", "with", "as", "by", "it", "its",
        "this", "that", "from", "at"}


def tokenize(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def _load_sibling(name):
    path = Path(__file__).with_name(f"{name}.py")
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_graph(root):
    """The graph export's graph dict for `root` (its communities
    are the communities summarised here — one graph, one
    partition, never a second invention)."""
    ge = _load_sibling("wiki_graph_export")
    if ge is None:
        raise SystemExit("wiki_graphrag: scripts/wiki_graph_export.py "
                         "not found beside this tool — the community "
                         "partition is the graph export's and is not "
                         "reinvented here")
    return ge.build_graph(Path(root))


def _summarizer():
    raptor = _load_sibling("wiki_raptor")
    if raptor is not None:
        return raptor.get_summarizer("extractive")
    raise SystemExit("wiki_graphrag: scripts/wiki_raptor.py not found "
                     "beside this tool — the extractive summariser "
                     "is shared with the RAPTOR tree builder")


def strip_frontmatter(text):
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            return text[end + 5:]
    return text


def build_summaries(root, graph=None, page_texts=None):
    """The map-reduce. graph: a wiki_graph_export graph dict
    (built from `root` when omitted). page_texts: {node id: raw
    page text} (read from `root` when omitted). Returns the
    records dict that is stored."""
    root = Path(root)
    if graph is None:
        graph = load_graph(root)
    titles = {n["id"]: n["title"] for n in graph["nodes"]}
    if page_texts is None:
        page_texts = {}
        for nid in titles:
            p = root / nid
            page_texts[nid] = (p.read_text(encoding="utf-8", errors="ignore")
                               if p.is_file() else "")
    summ = _summarizer()
    records = []
    for comm in graph["communities"]:
        # MAP: one extractive summary per member page.
        member_summaries = {}
        for nid in comm["members"]:
            body = strip_frontmatter(page_texts.get(nid, ""))
            member_summaries[nid] = summ.summarize([body])
        # REDUCE: one summary over the member summaries.
        summary = summ.summarize(
            [member_summaries[n] for n in comm["members"]])
        freq = Counter()
        for nid in comm["members"]:
            freq.update(t for t in tokenize(member_summaries[nid])
                        if t not in STOP)
        records.append({
            "id": comm["id"],
            "size": comm["size"],
            "members": list(comm["members"]),
            "member_titles": [titles.get(n, n) for n in comm["members"]],
            "top_pages": comm["top_pages"],
            "member_summaries": member_summaries,
            "summary": summary,
            "top_terms": [t for t, _c in freq.most_common(12)],
        })
    return {"kind": "community-summaries", "version": 1,
            "communities": records,
            "counts": {"communities": len(records),
                       "pages": sum(r["size"] for r in records)}}


def consult(records, query, top=5):
    """Rank stored community records for a query: distinct query
    tokens covered in (summary, top_terms, member titles), in
    that weighting. Returns [{id, score, summary, top_terms,
    top_pages}] sorted by (-score, id); zero-coverage excluded."""
    qset = set(tokenize(query))
    out = []
    for rec in records.get("communities") or []:
        score = (3 * len(qset & set(tokenize(rec.get("summary"))))
                 + 2 * len(qset & set(rec.get("top_terms") or []))
                 + 1 * len(qset & set(tokenize(
                     " ".join(rec.get("member_titles") or [])))))
        if score:
            out.append({"id": rec["id"], "score": score,
                        "summary": rec.get("summary", ""),
                        "top_terms": rec.get("top_terms") or [],
                        "top_pages": rec.get("top_pages") or []})
    out.sort(key=lambda r: (-r["score"], r["id"]))
    return out[:top]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", default=None)
    b.add_argument("--out", default=None)
    q = sub.add_parser("query")
    q.add_argument("--file", default=None)
    q.add_argument("--root", default=None)
    q.add_argument("--q", required=True)
    q.add_argument("--top", type=int, default=5)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        root = Path(args.root).resolve() if args.root else ROOT
        records = build_summaries(root)
        out = Path(args.out) if args.out else root / DEFAULT_OUT_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(records, indent=2, ensure_ascii=False)
                       + "\n", encoding="utf-8")
        c = records["counts"]
        print(f"community summaries: {c['communities']} communities, "
              f"{c['pages']} pages -> {out}")
        return 0
    path = Path(args.file) if args.file else (
        (Path(args.root) if args.root else ROOT) / DEFAULT_OUT_REL)
    records = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(consult(records, args.q, args.top), indent=2,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
