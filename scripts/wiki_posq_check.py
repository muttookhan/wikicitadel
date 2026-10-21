#!/usr/bin/env python3
"""wiki_posq_check.py — a PosQ-style positional-bias slice
for the ranker (Marathon Round 6, lane BA, item 4).

Pattern: positional-bias probing in the PosQ / "Lost in
the Middle" family (Liu et al.; the RAG-Retrieval Myopic
Trap study's position-sensitivity shape, MIT) —
re-implemented here in our own code, stdlib only, no code
copied, no model calls.

THE SLICE (evaluation/posq-slice.json). One query; one
relevant passage; three carrier pages that are IDENTICAL
except the passage sits at the START, MIDDLE or END of a
long filler body; plus distractor pages carrying a single
partial query term, so the ranked list is not
carriers-only. The carriers are generated deterministically
from the slice file's passage/filler parameters — the
fixture texts live in the slice definition, not the corpus,
and the golden set is never read.

THE CHECK runs the REAL ranker — scripts/wiki_search.py's
hybrid_rank (the named expression hybrid-current), with
severance disabled because the fixture set is not the
corpus — and REPORTS, per position: the carrier's rank,
its score, its BM25 component and its stage-4 rerank
multiplier, plus the score ratio against the best
position. The verdict applies the slice's recorded
collapse criteria (rank must stay within max_rank and the
score must not fall below min_score_ratio of the best
position). A collapse, if one is measured, is a FINDING
printed plainly in the report: this tool never retunes,
patches or special-cases the ranker — ranker changes are
battery-gated and are not this lane's call.

Commands:
  check [--slice F]   validate the slice definition
  run   [--slice F]   build the fixtures, run the ranker,
                      print the positional report
                      (exit 1 iff the slice's collapse
                      criteria are met — a measured
                      finding, reported, not fixed here)

Exit codes: 0 ok / no collapse, 1 check problems or a
measured collapse, 2 usage error.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SLICE = ROOT / "evaluation" / "posq-slice.json"
POSITIONS = ("start", "middle", "end")


def _load_search():
    spec = importlib.util.spec_from_file_location(
        "wiki_search", ROOT / "scripts" / "wiki_search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_slice(path=DEFAULT_SLICE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_slice(data):
    """Validate a slice dict; returns problem strings."""
    problems = []
    if data.get("kind") != "posq-positional-bias-slice":
        problems.append(f"kind is {data.get('kind')!r}, expected "
                        f"'posq-positional-bias-slice'")
    if not data.get("query"):
        problems.append("query is missing or empty")
    if not data.get("relevant_passage"):
        problems.append("relevant_passage is missing or empty")
    carrier = data.get("carrier") or {}
    for field in ("title", "filler_sentence"):
        if not carrier.get(field):
            problems.append(f"carrier.{field} is missing")
    if list(carrier.get("positions") or []) != list(POSITIONS):
        problems.append(f"carrier.positions must be exactly "
                        f"{list(POSITIONS)}")
    crit = data.get("collapse_criteria") or {}
    if not isinstance(crit.get("max_rank"), int) \
            or crit.get("max_rank", 0) < 1:
        problems.append("collapse_criteria.max_rank must be a "
                        "positive integer")
    ratio = crit.get("min_score_ratio")
    if not isinstance(ratio, (int, float)) \
            or not 0 < float(ratio) <= 1:
        problems.append("collapse_criteria.min_score_ratio must "
                        "be in (0, 1]")
    return problems


def build_fixtures(data):
    """The deterministic fixture docs: [(Path, text)] — three
    carriers (passage at start/middle/end) plus distractors.
    Carriers have identical token multisets by construction:
    only the passage's position differs."""
    carrier = data["carrier"]
    filler_block = (carrier["filler_sentence"] + " ") \
        * int(carrier["filler_repeats_per_block"])
    passage_block = (data["relevant_passage"] + " ") \
        * int(carrier["passage_repeats"])
    docs = []
    for pos in POSITIONS:
        blocks = [filler_block] * int(carrier["filler_blocks"])
        if pos == "start":
            blocks.insert(0, passage_block)
        elif pos == "middle":
            blocks.insert(len(blocks) // 2, passage_block)
        else:
            blocks.append(passage_block)
        text = f"# {carrier['title']}\n\n" + "\n\n".join(blocks)
        docs.append((Path(f"carrier-{pos}.md"), text))
    n_distr = int((data.get("distractors") or {}).get("count", 0))
    partial = data["query"].split()[-1]
    for i in range(n_distr):
        text = (f"# Ordinary page {i}\n\n"
                + (carrier["filler_sentence"] + " ") * 4
                + f"A note about the harbour {partial} shelf.\n")
        docs.append((Path(f"distractor-{i}.md"), text))
    return docs


def run_slice(data, search=None):
    """Run the real ranker over the fixtures. Returns the
    positional report dict (verdict included)."""
    search = search or _load_search()
    docs = build_fixtures(data)
    query_terms = search.tokenize(data["query"])
    ranked = search.hybrid_rank(query_terms, docs,
                                 severance=False)
    order = [str(p) for _s, p, _t, *_rest in ranked]
    by_path = {}
    for idx, row in enumerate(ranked):
        score, p, _t = row[0], row[1], row[2]
        detail = row[3] if len(row) > 3 else {}
        by_path[str(p)] = {"rank": idx + 1, "score": round(score, 4),
                           "bm25": detail.get("bm25"),
                           "rerank": detail.get("rerank")}
    positions = {}
    for pos in POSITIONS:
        name = f"carrier-{pos}.md"
        entry = by_path.get(name)
        positions[pos] = entry or {"rank": None, "score": 0.0,
                                    "bm25": None, "rerank": None}
    best = max((e["score"] for e in positions.values()),
               default=0.0)
    crit = data["collapse_criteria"]
    failures = []
    for pos, entry in positions.items():
        entry["score_ratio"] = round(entry["score"] / best, 4) \
            if best else 0.0
        if entry["rank"] is None or entry["rank"] > crit["max_rank"]:
            failures.append(
                f"{pos}: carrier rank {entry['rank']} exceeds "
                f"max_rank {crit['max_rank']} (or is absent)")
        elif entry["score_ratio"] < crit["min_score_ratio"]:
            failures.append(
                f"{pos}: score ratio {entry['score_ratio']} "
                f"below min_score_ratio "
                f"{crit['min_score_ratio']}")
    return {
        "query": data["query"],
        "query_terms": query_terms,
        "ranked": order,
        "positions": positions,
        "best_score": round(best, 4),
        "verdict": "collapse" if failures else "no-collapse",
        "failures": failures,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slice", default=str(DEFAULT_SLICE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    rn = sub.add_parser("run")
    rn.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)

    data = load_slice(ns.slice)
    if ns.cmd == "check":
        problems = check_slice(data)
        for prob in problems:
            print(prob)
        print(f"{len(problems)} problem(s)")
        return 1 if problems else 0
    report = run_slice(data)
    if ns.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"query: {report['query']!r} "
              f"(terms {report['query_terms']})")
        for pos in POSITIONS:
            e = report["positions"][pos]
            print(f"  {pos:6s} rank={e['rank']} "
                  f"score={e['score']} bm25={e['bm25']} "
                  f"rerank={e['rerank']} "
                  f"ratio={e['score_ratio']}")
        print(f"verdict: {report['verdict']}")
        for failure in report["failures"]:
            print(f"  FINDING {failure}")
    return 1 if report["verdict"] == "collapse" else 0


if __name__ == "__main__":
    raise SystemExit(main())
