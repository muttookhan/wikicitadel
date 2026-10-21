#!/usr/bin/env python3
"""The stale-context trap bench (Marathon Round 3, lane TA2;
feature survey 2026-10-19, Evaluation item 4 —
stale-context-bench, MIT pattern, re-implemented).

The failure mode this bench measures is this wiki's own design
risk: a confident, always-loaded summary (wiki/overview.md and
the standing context around it) states a claim that a later
record superseded, and the summary's authority SUPPRESSES the
verification search that would have caught it — the answer
repeats the stale claim. A trap case is a question whose stale
answer sits in an old or summary page while the current answer
sits in the record that superseded it.

Cases live BESIDE the golden set, never inside it:
evaluation/stale-context-bench.jsonl (the golden and extended
sets are byte-untouched by this bench). Case format:

  {"id": "SCB-01", "tier": "recency" |
        "rejected_proposal" | "scoped_exception" |
        "multi_hop" | "near_duplicate_draft",
   "question": "...",
   "stale_pages": ["wiki/<old>.md", ...],
   "current_pages": ["wiki/<current>.md", ...],
   "stale_claim_terms": ["..."],   # the stale claim, as terms
   "current_claim_terms": ["..."], # the current claim, as terms
   "summary_page": "wiki/overview.md",
   "note": "where the trap came from"}

Two traps are measured per case, deterministically (no LLM):

  retrieval trap   hybrid search (the production ranker, with
                   the severance list applied, as the pickup
                   runs it) ranks a stale page above every
                   current page, or retrieves a stale page in
                   the top-K while no current page appears —
                   the evidence an answerer packs is the stale
                   one.
  summary trap     the always-loaded summary page itself
                   carries the stale claim's terms and does NOT
                   carry the current claim's terms — an
                   answerer that trusts the summary springs
                   the trap without searching at all. This is
                   the verification-suppression metric: the
                   case also reports whether the sprung answer
                   would cite a page at all (summary claims
                   carry no citation).

trap-spring rate = cases sprung (either trap) / cases, overall
and per tier. A sprung trap is a FINDING about the corpus or
the summary, reported plainly — cases are never weakened to
make the rate green.

Usage:
  python3 scripts/wiki_stale_bench.py [--root DIR]
          [--cases FILE] [--top K] [--out FILE]

Exit 0 = no trap sprang; 1 = at least one trap sprang;
2 = usage error. Stdlib only.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "evaluation" / "stale-context-bench.jsonl"
TIERS = ("recency", "rejected_proposal", "scoped_exception",
         "multi_hop", "near_duplicate_draft")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalise(text):
    return " ".join((text or "").split()).lower()


def terms_present(text, terms):
    norm = normalise(text)
    return all(normalise(t) in norm for t in terms or [])


def load_cases(path):
    header, cases = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            cases.append(obj)
    return header, cases


def first_rank(ranked_paths, targets):
    """1-based rank of the first target in ranked_paths."""
    for i, p in enumerate(ranked_paths):
        if p in targets:
            return i + 1
    return None


def retrieval_trap(ranked_paths, stale_pages, current_pages, top_k):
    """(sprung, detail): stale evidence dominates the top-K."""
    window = ranked_paths[:top_k]
    stale_rank = first_rank(window, set(stale_pages))
    current_rank = first_rank(window, set(current_pages))
    if stale_rank is None:
        return False, (f"no stale page in top-{top_k} "
                       f"(current at {current_rank})")
    if current_rank is None:
        return True, (f"stale page at rank {stale_rank}, no "
                      f"current page in top-{top_k}")
    if stale_rank < current_rank:
        return True, (f"stale page at rank {stale_rank} outranks "
                      f"current page at rank {current_rank}")
    return False, (f"current page at rank {current_rank} beats "
                   f"stale page at rank {stale_rank}")


def summary_trap(summary_text, case):
    """(sprung, detail): the summary carries the stale claim
    and not the current one."""
    if summary_text is None:
        return False, "no summary page"
    stale = terms_present(summary_text,
                          case.get("stale_claim_terms"))
    current = terms_present(summary_text,
                            case.get("current_claim_terms"))
    if stale and not current:
        return True, ("summary carries the stale claim and not "
                      "the current claim — verification "
                      "suppressed")
    if stale and current:
        return False, ("summary carries both forms (the stale "
                       "form is flagged in place)")
    return False, "summary does not carry the stale claim"


def run_cases(cases, root, top_k=10):
    ws = _load("wiki_search", root / "scripts" / "wiki_search.py")
    ws.ROOT = root
    ws.WIKI = root / "wiki"
    ws.RAW = root / "raw"
    sev_list = None
    try:
        severance = _load("ask_severance",
                          root / "tools" / "ask" / "severance.py")
        sev_list = severance.load_severance()
    except Exception:
        sev_list = None
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    summary_cache = {}
    rows = []
    for case in cases:
        ranked = ws.hybrid_rank(ws.tokenize(case["question"]),
                                docs, adj, severance=sev_list)
        ranked_paths = [str(p.relative_to(root))
                        for _s, p, _t, _d in ranked]
        r_sprung, r_detail = retrieval_trap(
            ranked_paths, case.get("stale_pages") or [],
            case.get("current_pages") or [], top_k)
        spage = case.get("summary_page") or "wiki/overview.md"
        if spage not in summary_cache:
            sp = root / spage
            summary_cache[spage] = sp.read_text(
                encoding="utf-8") if sp.is_file() else None
        s_sprung, s_detail = summary_trap(summary_cache[spage],
                                          case)
        rows.append({
            "id": case["id"], "tier": case["tier"],
            "retrieval_trap": r_sprung,
            "summary_trap": s_sprung,
            "sprung": bool(r_sprung or s_sprung),
            "detail": f"retrieval: {r_detail}; summary: "
                      f"{s_detail}",
        })
    by_tier = {}
    for tier in TIERS:
        trows = [r for r in rows if r["tier"] == tier]
        if trows:
            by_tier[tier] = {
                "cases": len(trows),
                "sprung": sum(1 for r in trows if r["sprung"]),
                "trap_spring_rate": round(
                    sum(1 for r in trows if r["sprung"])
                    / len(trows), 4),
            }
    return {
        "cases": len(rows),
        "sprung": sum(1 for r in rows if r["sprung"]),
        "trap_spring_rate": round(
            sum(1 for r in rows if r["sprung"])
            / (len(rows) or 1), 4),
        "retrieval_traps": sum(1 for r in rows
                                if r["retrieval_trap"]),
        "summary_traps": sum(1 for r in rows if r["summary_trap"]),
        "by_tier": by_tier,
        "rows": rows,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="Stale-context trap bench.")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--cases", default=None,
                    help="default: evaluation/stale-context-bench.jsonl")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])

    root = Path(args.root)
    cases_path = Path(args.cases) if args.cases else \
        root / "evaluation" / "stale-context-bench.jsonl"
    if not cases_path.is_file():
        print(f"cases file missing: {cases_path}", file=sys.stderr)
        return 2
    _header, cases = load_cases(cases_path)
    if not cases:
        print("bench has no cases", file=sys.stderr)
        return 2
    report = run_cases(cases, root, top_k=args.top)
    for r in report["rows"]:
        mark = "SPRUNG" if r["sprung"] else "safe  "
        print(f"  [{mark}] {r['id']} ({r['tier']}): {r['detail']}")
    for tier, agg in report["by_tier"].items():
        print(f"  tier {tier}: {agg['sprung']}/{agg['cases']} "
              f"sprung (rate {agg['trap_spring_rate']:.2f})")
    print(f"stale-context bench: trap-spring rate "
          f"{report['trap_spring_rate']:.2f} "
          f"({report['sprung']}/{report['cases']} cases; "
          f"retrieval traps {report['retrieval_traps']}, "
          f"summary traps {report['summary_traps']})")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return 1 if report["sprung"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
