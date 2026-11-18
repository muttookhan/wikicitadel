#!/usr/bin/env python3
"""wiki_progressive.py — 3-layer progressive-disclosure retrieval.

Tier A harvest row "claude-mem": the 3-layer progressive-
disclosure read path (compact index -> summary -> full
detail, with the cost of each layer made visible), adapted
from thedotmack/claude-mem (Apache-2.0 — the read-path
design is adapted with credit; the session auto-capture
half of that system is NOT adopted and nothing here
captures anything). Re-implemented from the design; no
code copied. OpenViking's L0/L1/L2 directory summaries
(AGPL — idea only, see the survey) point the same way.

The three layers, over the existing search machinery
(scripts/wiki_search.py: BM25 ranker, tokeniser, title and
snippet helpers; chunks from scripts/wiki_dualroute.py):

  layer 1  compact index hits — path, title, score only.
           The cheapest layer: enough to choose.
  layer 2  page summaries — layer 1 plus, per hit, the
           page's headings and an extractive summary (the
           first non-frontmatter paragraph plus the best
           query-matching line, both verbatim).
  layer 3  full passages — layer 2 plus the ranked full
           passage/chunk texts for each hit page.

A caller asks for ONE layer (--layer 1|2|3, default 1) and
gets every layer up to it, each labelled, each carrying
its visible cost (chars and an approximate token count,
chars/4, stated as an estimate). Layers are cumulative and
monotonic: layer N's hits are exactly layer 1's hits, in
the same order, with more detail attached — so a caller
can stop between layers, re-ask for the next, and never
see a hit change identity or rank underneath them.

    python3 scripts/wiki_progressive.py "<query>" [--layer N]
            [--top N] [--scope wiki|raw|all] [--root DIR]

Exit codes: 0 ok · 1 no searchable terms · 2 usage error.
Output is JSON.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _WS = _load("wiki_search")
    _DR = _load("wiki_dualroute")
    tokenize = _WS.tokenize
except Exception:  # pragma: no cover - neighbours always ship
    _WS = _DR = None

    def tokenize(text: str):
        return [t for t in re.findall(r"[a-z0-9]+", text.lower())
                if len(t) >= 2]


def approx_tokens(text: str) -> int:
    """The visible cost estimate: chars / 4, rounded up. An
    estimate, labelled as one wherever it is shown."""
    return (len(text) + 3) // 4


def page_summary(text: str, terms) -> dict:
    """Layer-2 detail for one page: its headings (verbatim, in
    order) and an extractive summary — the first body paragraph
    plus the best query-matching line, both verbatim from the
    page, never paraphrased."""
    body = text
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:]
    headings = [m.group(2).strip() for m in
                (re.match(r"^(#{1,6})\s+(.*)$", line)
                 for line in body.splitlines()) if m]
    paras = [p.strip() for p in re.split(r"\n\s*\n", body)
             if p.strip() and not p.strip().startswith("#")]
    first = paras[0] if paras else ""
    best = _WS.make_snippet(text, terms) if _WS else ""
    summary = first if (not best or best in first) else \
        (first + " … " + best if first else best)
    return {"headings": headings, "summary": summary[:600]}


def collect_docs(root: Path, scope: str):
    if _DR is not None:
        return _DR.collect_docs(root, scope)
    docs = []  # pragma: no cover
    for name in (("wiki", "raw") if scope == "all" else (scope,)):
        base = root / name
        if base.exists():
            for p in sorted(base.rglob("*.md")):
                docs.append((p, p.read_text(
                    encoding="utf-8", errors="ignore")))
    return docs


def progressive_search(root: Path, query: str, layer=1, top=10,
                       scope="all", docs=None) -> dict:
    """Run layers 1..`layer`. `docs` may inject a fixture corpus
    ([(Path, text)]); otherwise the corpus is collected from
    `root`. Returns {"query", "terms", "layer_reached",
    "next_layer": int|None, "layers": [...]} where each layer is
    {"layer", "name", "chars", "approx_tokens", "hits": [...]}.
    Layer 2/3 hits extend the layer-1 hit for the same page —
    same path, same order, same score."""
    if layer not in (1, 2, 3):
        raise ValueError("layer must be 1, 2 or 3")
    terms = tokenize(query or "")
    result = {"query": query, "terms": terms, "layer_reached": 0,
              "next_layer": None, "layers": []}
    if not terms:
        return result
    if docs is None:
        docs = collect_docs(root, scope)
    ranked = _WS.bm25_rank(terms, docs) if _WS else []
    base_hits = []
    for score, p, text in ranked[:top]:
        rel = p.relative_to(root).as_posix() \
            if isinstance(p, Path) and p.is_relative_to(root) else str(p)
        base_hits.append({"path": rel, "score": round(score, 4),
                          "title": _WS.doc_title(text) if _WS else "",
                          "_text": text})

    def emit(n, name, hits):
        payload = [{k: v for k, v in h.items() if not k.startswith("_")}
                   for h in hits]
        blob = json.dumps(payload, ensure_ascii=False)
        return {"layer": n, "name": name, "chars": len(blob),
                "approx_tokens": approx_tokens(blob), "hits": payload}

    layers = []
    layers.append(emit(1, "compact index", base_hits))
    if layer >= 2:
        hits2 = []
        for h in base_hits:
            detail = page_summary(h["_text"], terms)
            hits2.append({**h, **detail})
        layers.append(emit(2, "page summaries", hits2))
    if layer >= 3:
        hits3 = []
        for h in base_hits:
            detail = page_summary(h["_text"], terms)
            passages = []
            if _DR is not None:
                for passage in _DR.split_passages(h["_text"], h["path"]):
                    s = _DR.score_passage(terms, passage)
                    if s > 0:
                        passages.append({**passage, "score": round(s, 3)})
                passages.sort(key=lambda r: (-r["score"],
                                             r["start_line"]))
            hits3.append({**h, **detail, "passages": passages[:3]})
        layers.append(emit(3, "full passages", hits3))
    result["layers"] = layers
    result["layer_reached"] = layers[-1]["layer"] if layers else 0
    result["next_layer"] = (result["layer_reached"] + 1
                            if result["layer_reached"] < 3 else None)
    result["total_approx_tokens"] = sum(
        l["approx_tokens"] for l in layers)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query")
    ap.add_argument("--layer", type=int, choices=(1, 2, 3), default=1,
                    help="deepest layer to return (default 1: stop "
                         "at the compact index)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--scope", choices=("wiki", "raw", "all"),
                    default="all")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    res = progressive_search(args.root, args.query, layer=args.layer,
                             top=args.top, scope=args.scope)
    print(json.dumps(res, indent=1))
    return 0 if res["terms"] else 1


if __name__ == "__main__":
    sys.exit(main())
