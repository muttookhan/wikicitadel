#!/usr/bin/env python3
"""Golden-question retrieval benchmark (ai-engineering-spec §1).

The spec's rule: every retrieval or ranking claim in this wiki is
measured, not asserted. This runner scores a search engine against
evaluation/golden-questions.jsonl — deterministically, with no LLM
in the loop — on the retrieval half of the §1.3 rubric:

  - citation coverage: fraction of questions whose must_cite page
    appears in the top-K results (reported @1/@3/@5/@10);
  - hit rate: fraction with a must_cite OR acceptable_cites page
    in the top-K;
  - precision@K: mean fraction of the top-K that is a must/acceptable
    page;
  - MRR of the first must_cite hit.

Answer-level axes (Factuality, Completeness, Restraint) need a
composed answer and stay with the answer pipeline; this runner
measures whether the right page is FINDABLE, which is what a
ranking change can honestly claim.

Usage:
  python3 scripts/wiki_benchmark.py --engine bm25   --label before
  python3 scripts/wiki_benchmark.py --engine hybrid --label after

Results land in evaluation/results/<label>.json. Stdlib only.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "evaluation" / "golden-questions.jsonl"
RESULTS_DIR = ROOT / "evaluation" / "results"

spec = importlib.util.spec_from_file_location(
    "wiki_search", ROOT / "scripts" / "wiki_search.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)


def load_questions(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def rank_paths(engine, terms, docs, adj):
    if engine == "bm25":
        ranked = ws.bm25_rank(terms, docs)
        return [str(p.relative_to(ROOT)) for _s, p, _t in ranked]
    if engine == "hindsight":
        ranked = ws.hindsight_rank(terms, docs, adj)
        return [str(p.relative_to(ROOT)) for _s, p, _t, _d in ranked]
    ranked = ws.hybrid_rank(terms, docs, adj)
    return [str(p.relative_to(ROOT)) for _s, p, _t, _d in ranked]


def score_question(q, paths, top):
    must = set(q.get("must_cite") or [])
    accept = set(q.get("acceptable_cites") or [])
    good = must | accept
    topk = paths[:top]
    must_rank = next((i + 1 for i, p in enumerate(paths) if p in must), None)
    hit_rank = next((i + 1 for i, p in enumerate(topk) if p in good), None)
    return {
        "id": q["id"],
        "route": q.get("route"),
        "must_cite_rank": must_rank,
        "hit_in_topk": hit_rank is not None,
        "must_in_topk": must_rank is not None and must_rank <= top,
        "precision_at_k": (sum(1 for p in topk if p in good) / len(topk)
                           if topk else 0.0),
        "top3": topk[:3],
    }


def main(argv):
    ap = argparse.ArgumentParser(description="Golden-question retrieval benchmark.")
    ap.add_argument("--engine", choices=("bm25", "hybrid", "hindsight"),
                    default="hybrid")
    ap.add_argument("--label", default=None, help="results file label")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    args = ap.parse_args(argv[1:])

    questions = load_questions(args.questions)
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs) if args.engine in ("hybrid", "hindsight") else None

    per_q = []
    for q in questions:
        paths = rank_paths(args.engine, ws.tokenize(q["question"]), docs, adj)
        per_q.append(score_question(q, paths, args.top))

    n = len(per_q) or 1
    cov = {k: sum(1 for r in per_q
                  if r["must_cite_rank"] is not None and r["must_cite_rank"] <= k) / n
           for k in (1, 3, 5, 10)}
    aggregates = {
        "questions": len(per_q),
        "citation_coverage": {f"@{k}": round(v, 4) for k, v in cov.items()},
        "hit_rate_topk": round(sum(1 for r in per_q if r["hit_in_topk"]) / n, 4),
        "mean_precision_at_k": round(
            sum(r["precision_at_k"] for r in per_q) / n, 4),
        "mrr_must_cite": round(sum(
            1.0 / r["must_cite_rank"] for r in per_q
            if r["must_cite_rank"] is not None) / n, 4),
    }
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        head = None
    result = {
        "label": args.label or args.engine,
        "engine": args.engine,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_head": head,
        "corpus": "wiki/ (scope=wiki)",
        "corpus_docs": len(docs),
        "top_k": args.top,
        "aggregates": aggregates,
        "per_question": per_q,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{result['label']}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"engine={args.engine} label={result['label']} "
          f"corpus={len(docs)} docs questions={len(per_q)}")
    print(f"  citation coverage: " +
          "  ".join(f"@{k}={v:.2f}" for k, v in cov.items()))
    print(f"  hit rate @{args.top}: {aggregates['hit_rate_topk']:.2f}   "
          f"mean precision @{args.top}: {aggregates['mean_precision_at_k']:.3f}   "
          f"MRR: {aggregates['mrr_must_cite']:.3f}")
    misses = [r["id"] for r in per_q if not r["must_in_topk"]]
    print(f"  must-cite misses @{args.top}: {', '.join(misses) if misses else 'none'}")
    print(f"  wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
