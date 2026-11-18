#!/usr/bin/env python3
"""wiki_raptor.py — RAPTOR-style recursive summary trees.

Marathon Round 3, lane TB7, row 3. Pattern: RAPTOR (recursive
abstractive processing for tree-organised retrieval; Sarthi et
al., 2024 — re-implemented from the idea): a cluster of pages is
organised as a tree — leaf PASSAGES at level 0, CLUSTER SUMMARIES
above them, up to a single ROOT summary — and retrieval can
answer from ANY tree level (a broad question from the root, a
specific one from the leaves).

No model calls: the summariser is an interface (the model slot)
with a deterministic EXTRACTIVE default — a summary is the
highest-centrality sentences of its children, verbatim, in
original order. A future model summariser registers under
SUMMARIZERS without changing the tree shape or the retrieval
surface; the router stays unwired, so no such summariser ships.

Clustering is deterministic greedy: passages in id order join
the first cluster whose token-union Jaccard similarity clears
the threshold, else start a new cluster — same corpus, same
tree, byte for byte.

    python3 scripts/wiki_raptor.py build --root DIR --out tree.json
    python3 scripts/wiki_raptor.py query --tree tree.json \\
        --q "broad question" [--level 2]

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_RE = re.compile(r"[a-z0-9]+")
SENT_RE = re.compile(r"(?<=[.!?])\s+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are",
        "was", "were", "for", "on", "with", "as", "by", "it", "its",
        "this", "that", "from", "at", "be", "has", "have", "had"}


def tokenize(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def split_sentences(text):
    out = []
    for para in re.split(r"\n\s*\n", text or ""):
        para = " ".join(para.split())
        if not para:
            continue
        for sent in SENT_RE.split(para):
            sent = sent.strip().lstrip("#> -*")
            if sent:
                out.append(sent)
    return out


def split_passages(text):
    """Leaf passages: one per non-empty paragraph, frontmatter
    stripped, heading markers kept as plain text."""
    body = text or ""
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            body = body[end + 5:]
    passages = []
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split()).strip()
        if para:
            passages.append(para)
    return passages


# ---------------------------------------------------------------------------
# The summariser slot (interface + extractive default; no model calls)
# ---------------------------------------------------------------------------

class Summarizer:
    """The model slot: anything with summarize(texts) -> str may
    be registered in SUMMARIZERS. The extractive default is the
    only implementation that ships (router unwired)."""

    name = "base"

    def summarize(self, texts):  # pragma: no cover - interface
        raise NotImplementedError


class ExtractiveSummarizer(Summarizer):
    """Deterministic extractive summary: score every sentence by
    the summed corpus frequency of its content tokens (centrality),
    take the top `max_sentences`, emit them in original order."""

    name = "extractive"

    def __init__(self, max_sentences=3):
        self.max_sentences = max_sentences

    def summarize(self, texts):
        sentences = []
        for text in texts:
            sentences.extend(split_sentences(text))
        if not sentences:
            return ""
        freq = Counter()
        for sent in sentences:
            freq.update(t for t in tokenize(sent) if t not in STOP)
        scored = []
        for i, sent in enumerate(sentences):
            toks = [t for t in tokenize(sent) if t not in STOP]
            score = sum(freq[t] for t in set(toks))
            scored.append((-score, i, sent))
        keep = sorted(scored)[: self.max_sentences]
        return " ".join(sent for _s, _i, sent in sorted(keep, key=lambda r: r[1]))


SUMMARIZERS = {"extractive": ExtractiveSummarizer()}


def get_summarizer(name="extractive"):
    if name not in SUMMARIZERS:
        raise ValueError(f"unknown summarizer {name!r}; "
                         f"known: {sorted(SUMMARIZERS)}")
    return SUMMARIZERS[name]


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------

def cluster_items(items, threshold=0.12):
    """Greedy deterministic clustering by token-union Jaccard.
    items: [{"id", "text"}] in fixed order -> [[ids], ...]."""
    clusters = []  # list of (id list, token union set)
    for item in items:
        toks = set(tokenize(item["text"]))
        placed = False
        for ids, union in clusters:
            inter = len(toks & union)
            denom = len(toks | union) or 1
            if toks and inter / denom >= threshold:
                ids.append(item["id"])
                union |= toks
                placed = True
                break
        if not placed:
            clusters.append(([item["id"]], set(toks)))
    return [ids for ids, _u in clusters]


def build_tree(pages, summarizer="extractive", threshold=0.12,
               max_levels=6):
    """pages: [{"path", "title", "text"}] -> the tree dict:
    {"kind": "raptor-tree", "summarizer": name, "levels": n,
     "nodes": [{id, level, kind, text, children, paths}]}.
    Level 0 = passages; each higher level summarises clusters of
    the level below; the top is a single root node whenever more
    than one cluster survives (its children are the top nodes)."""
    summ = get_summarizer(summarizer)
    nodes = []
    current = []
    seq = 0
    for page in pages:
        for passage in split_passages(page["text"]):
            nid = f"L0-{seq:04d}"
            seq += 1
            node = {"id": nid, "level": 0, "kind": "passage",
                    "text": passage, "children": [],
                    "paths": [page["path"]]}
            nodes.append(node)
            current.append(node)
    by_id = {n["id"]: n for n in nodes}
    level = 0
    while len(current) > 1 and level < max_levels:
        level += 1
        groups = cluster_items(current, threshold)
        if len(groups) >= len(current) and level > 1:
            groups = [[n["id"] for n in current]]  # force the root merge
        nxt = []
        for gi, group in enumerate(groups):
            children = [by_id[i] for i in group]
            nid = f"L{level}-{gi:04d}"
            node = {"id": nid, "level": level,
                    "kind": "root" if len(groups) == 1 else "summary",
                    "text": summ.summarize([c["text"] for c in children]),
                    "children": list(group),
                    "paths": sorted({p for c in children
                                      for p in c["paths"]})}
            nodes.append(node)
            by_id[nid] = node
            nxt.append(node)
        current = nxt
    if current:
        current[0]["kind"] = "root"
    return {"kind": "raptor-tree", "summarizer": summarizer,
            "levels": level + 1 if nodes else 0,
            "nodes": nodes}


def query_tree(tree, query, level=None, top=10):
    """Answer from any tree level: score nodes (at `level`, or
    every level when None) by distinct query-token coverage,
    then total occurrences. Returns [{id, level, kind, score,
    text, paths}] sorted by (-score, id); score 0 excluded."""
    q = tokenize(query)
    qset = set(q)
    out = []
    for node in tree.get("nodes") or []:
        if level is not None and node["level"] != level:
            continue
        toks = tokenize(node["text"])
        distinct = len(qset & set(toks))
        if not distinct:
            continue
        score = distinct * 100 + sum(1 for t in toks if t in qset)
        out.append({"id": node["id"], "level": node["level"],
                    "kind": node["kind"], "score": score,
                    "text": node["text"], "paths": node["paths"]})
    out.sort(key=lambda r: (-r["score"], r["id"]))
    return out[:top]


def collect_pages(root):
    wiki = Path(root) / "wiki"
    pages = []
    for p in sorted(wiki.rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        title = p.stem
        m = re.search(r"^title:\s*\"?([^\"\n]+)", text, re.M)
        if m:
            title = m.group(1).strip()
        pages.append({"path": str(p.relative_to(root)),
                      "title": title, "text": text})
    return pages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", default=None)
    b.add_argument("--out", required=True)
    b.add_argument("--summarizer", default="extractive")
    b.add_argument("--threshold", type=float, default=0.12)
    q = sub.add_parser("query")
    q.add_argument("--tree", required=True)
    q.add_argument("--q", required=True)
    q.add_argument("--level", type=int, default=None)
    q.add_argument("--top", type=int, default=10)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        root = Path(args.root).resolve() if args.root else ROOT
        tree = build_tree(collect_pages(root), args.summarizer,
                          args.threshold)
        Path(args.out).write_text(
            json.dumps(tree, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"raptor tree: {len(tree['nodes'])} nodes, "
              f"{tree['levels']} levels -> {args.out}")
        return 0
    tree = json.loads(Path(args.tree).read_text(encoding="utf-8"))
    print(json.dumps(query_tree(tree, args.q, args.level, args.top),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
