#!/usr/bin/env python3
"""HyDE-style lexical query expansion (W3, 2026-10-22).

HyDE (Gao, Ma, Lin & Callan 2022, "Precise Zero-Shot Dense
Retrieval without Relevance Labels") answers a query by first
drafting a HYPOTHETICAL answer passage with an LLM, then
retrieving against the draft's embedding — the draft speaks the
documents' vocabulary, so vocabulary mismatch between question
and corpus stops mattering. This wiki's serving path has no LLM
endpoint and no embedding store, so the dense form is not
adopted. This module is the LEXICAL form, clean
re-implementation from the method's description (no code
carried): the hypothetical answer is drafted deterministically
from the corpus itself — the lead passages of the query's own
top BM25 hits are assembled as the draft (the pseudo-relevance
draft) — its characteristic terms are extracted, and those
terms join the recall query at a weight below the original
terms' 1.0. Everything is labelled for what it is: the draft is
a corpus excerpt, not a generated answer; the terms are
lexical, not semantic.

How the stage composes (it forks nothing):

  * scripts/wiki_search.py hybrid_rank(..., expansion=RECORD)
    merges the record's terms into stage-1 BM25 recall ONLY,
    each at its recorded weight (BM25 there is a plain sum over
    term contributions, so a document's merged recall score is
    its original score plus weight x its expansion score).
    PPR seeds follow the merged recall; coverage, title match,
    temporal intent and the severance query-match keep reading
    the ORIGINAL query terms; stage 5 (severance) and stage 6
    (governance, W1.5) filter the expanded list exactly as
    they filter the unexpanded one.
  * expansion=None (the default everywhere) removes the stage:
    hybrid_rank is the pre-W3 pipeline exactly — pinned by
    same-process A/B tests and a captured-corpus comparison.
  * Draft seeds never include pages the caller excludes;
    build_expansion's default caller path (this module's CLI,
    the battery gate, wiki_search --expand) excludes
    governance-withheld and page-severed paths via
    default_exclusions(). The filters would catch those pages
    in the results anyway — the exclusion keeps their text out
    of the draft too. It is a caller courtesy, not the
    guarantee; the guarantee is stages 5-6, and a test pins
    it with an expansion built WITHOUT exclusions.

Transparency: the expansion record — original terms, every
expansion term with its weight and its draft evidence
(draft_tf, corpus df, idf), and the seed passages the draft
was assembled from — is written to wiki_search.LAST_EXPANSION
by hybrid_rank on every expanded call, carried in the
evidence pack's "expansion" block, and printed by the CLI
under --explain. An expansion that cannot be inspected does
not ship.

Commands:
    expand     print the expansion record for a query
    search     one query, default vs expanded top-N side by side
    measure    golden + extended (answerable) + directional
               slice, expansion OFF vs ON, named wins/losses;
               writes evaluation/hyde-expansion-report.{json,md}
    gate-check the pinned abstention battery: plain (stage
               available, default path) and with expansion ON
    ab-check   same-process A/B over the golden + extended
               questions: no-argument vs expansion=None full
               rankings must be identical; with --baseline FILE
               also against a pre-change captured baseline

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Policy constants (stated here, measured in the report).
DEFAULT_WEIGHT = 0.5     # expansion terms vs original terms' 1.0
DRAFT_SEEDS = 5          # top BM25 hits whose leads form the draft
MAX_EXPANSION_TERMS = 8  # terms the draft may contribute
MAX_DF_SHARE = 0.5       # terms in > half the corpus are stopwords
TOP = 10                 # the house measurement cut


def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WS = None


def load_search():
    """This module's own copy of wiki_search (drafting uses its
    tokenize / bm25_rank / idf conventions read-only; the
    expansion record itself is plain data and crosses into any
    other copy's hybrid_rank unchanged)."""
    global _WS
    if _WS is None:
        _WS = _load_sibling("wiki_search_for_hyde", "wiki_search.py")
    return _WS


def relpath(ws, p):
    return str(p.relative_to(ws.ROOT)) if p.is_relative_to(ws.ROOT) \
        else str(p)


# ---------------------------------------------------------------------------
# The expansion builder
# ---------------------------------------------------------------------------

def build_expansion(ws, query_terms, docs, weight=DEFAULT_WEIGHT,
                    max_terms=MAX_EXPANSION_TERMS,
                    seed_count=DRAFT_SEEDS, exclude_paths=frozenset()):
    """Draft the hypothetical answer and extract its terms.

    The draft: the lead window (ws.RERANK_LEAD_TOKENS tokens —
    the house lead) of the top `seed_count` BM25 hits for the
    original query, skipping `exclude_paths`. Candidate terms
    are the draft's terms that are not already query terms and
    are not corpus-stopwords (df share > MAX_DF_SHARE); each is
    scored draft_tf x idf with the SAME Robertson idf
    wiki_search.bm25_rank uses, and the top `max_terms` are
    taken, ties broken by term so the record is deterministic.

    Returns the expansion record (plain dict; see the module
    docstring). An empty expansion_terms list is an honest
    outcome — no draft, or a draft that adds no vocabulary —
    and hybrid_rank treats it as the stage being off."""
    record = {
        "kind": "hyde-lexical-expansion",
        "method": "lexical HyDE (W3): hypothetical answer drafted "
                  "as the lead passages of the query's own top "
                  "BM25 hits (pseudo-relevance draft, deterministic; "
                  "no LLM, no embeddings); terms scored draft_tf "
                  "x corpus idf",
        "original_terms": list(query_terms),
        "weight": weight,
        "expansion_terms": [],
        "draft": {"seed_paths": [], "seed_count": 0, "tokens": 0},
    }
    if not query_terms or not docs:
        return record
    base = ws.bm25_rank(query_terms, docs)
    if not base:
        return record
    seeds = []
    for _s, p, text in base:
        if relpath(ws, p) in exclude_paths:
            continue
        seeds.append((p, text))
        if len(seeds) >= seed_count:
            break
    if not seeds:
        return record
    draft_tokens = []
    for _p, text in seeds:
        draft_tokens.extend(ws.tokenize(text)[:ws.RERANK_LEAD_TOKENS])
    record["draft"] = {
        "seed_paths": [relpath(ws, p) for p, _t in seeds],
        "seed_count": len(seeds),
        "tokens": len(draft_tokens),
    }
    n = len(docs)
    df = Counter()
    for _p, text in docs:
        for term in set(ws.tokenize(text)):
            df[term] += 1

    def idf(term):
        d = df.get(term, 0)
        return math.log(1.0 + (n - d + 0.5) / (d + 0.5))

    qset = set(query_terms)
    draft_tf = Counter(draft_tokens)
    scored = []
    for term, tf in draft_tf.items():
        if term in qset:
            continue
        if df.get(term, 0) / n > MAX_DF_SHARE:
            continue
        scored.append((-(tf * idf(term)), term, tf))
    scored.sort()
    for neg_score, term, tf in scored[:max_terms]:
        record["expansion_terms"].append({
            "term": term,
            "weight": weight,
            "draft_tf": tf,
            "df": df.get(term, 0),
            "idf": round(idf(term), 4),
            "score": round(-neg_score, 4),
        })
    return record


def expansion_terms_of(record):
    """[(term, weight)] from an expansion record — the shape
    hybrid_rank's stage 0 consumes."""
    if not record:
        return []
    return [(e["term"], float(e["weight"]))
            for e in record.get("expansion_terms") or []]


def default_exclusions(ws):
    """Repo-relative paths kept out of the DRAFT: pages the
    governance artefact withholds and pages carrying a
    page-level severance entry. Results are filtered by stages
    5-6 regardless; this keeps withheld text out of the draft
    vocabulary too."""
    out = set()
    gov = ws.load_governance()
    if gov:
        for rel, rec in (gov.get("pages") or {}).items():
            if rec.get("state") == "withheld":
                out.add(rel)
    sev = ws.load_severance()
    if sev:
        for entry in sev.get("entries") or []:
            if entry.get("kind") == "page" and entry.get("page"):
                out.add(entry["page"])
    return out


# ---------------------------------------------------------------------------
# Measurement — the house harnesses' own scoring, OFF vs ON
# ---------------------------------------------------------------------------

def _benchmark_aggregates(per_q):
    """wiki_benchmark.py's aggregate formula, verbatim in effect
    (the dense trial's copy, W1.2)."""
    n = len(per_q) or 1
    cov = {k: sum(1 for r in per_q
                  if r["must_cite_rank"] is not None
                  and r["must_cite_rank"] <= k) / n
           for k in (1, 3, 5, 10)}
    return {
        "questions": len(per_q),
        "citation_coverage": {f"@{k}": round(v, 4)
                              for k, v in cov.items()},
        "hit_rate_topk": round(
            sum(1 for r in per_q if r["hit_in_topk"]) / n, 4),
        "mean_precision_at_k": round(
            sum(r["precision_at_k"] for r in per_q) / n, 4),
        "mrr_must_cite": round(sum(
            1.0 / r["must_cite_rank"] for r in per_q
            if r["must_cite_rank"] is not None) / n, 4),
    }


def _load_questions(filename):
    out = []
    for line in (ROOT / "evaluation" / filename).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def measure(weight=DEFAULT_WEIGHT, write=True,
            out_json=None, out_md=None):
    """Golden + extended-answerable + directional slice,
    expansion OFF vs ON through the production hybrid_rank
    (severance + governance at their defaults in BOTH arms —
    the only difference is the expansion argument). Wins and
    losses are computed from the per-question rows: gained =
    must-cite enters the top-10 under ON, lost = leaves it."""
    ws = load_search()
    wb = _load_sibling("wiki_benchmark_for_hyde", "wiki_benchmark.py")
    ee = _load_sibling("wiki_eval_extended_for_hyde",
                       "wiki_eval_extended.py")
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    exclusions = default_exclusions(ws)

    golden = _load_questions("golden-questions.jsonl")
    extended = _load_questions("extended-questions.jsonl")
    instruments = [
        ("golden", golden, "benchmark"),
        ("extended_answerable",
         [q for q in extended if not q.get("expected_abstain")],
         "extended"),
        ("directional_slice",
         [q for q in extended if q.get("slice") == "directional"],
         "extended"),
    ]
    report_instruments = {}
    for label, questions, scorer in instruments:
        arms = {}
        for arm in ("off", "on"):
            rows = []
            for q in questions:
                terms = ws.tokenize(q["question"])
                if arm == "off":
                    ranked = ws.hybrid_rank(terms, docs, adj)
                else:
                    rec = build_expansion(
                        ws, terms, docs, weight=weight,
                        exclude_paths=exclusions)
                    ranked = ws.hybrid_rank(terms, docs, adj,
                                            expansion=rec)
                paths = [relpath(ws, p) for _s, p, _t, _d in ranked]
                if scorer == "benchmark":
                    rows.append(wb.score_question(q, paths, TOP))
                else:
                    rows.append(ee.score_answerable(
                        q, [(s, rp) for (s, _p, _t, _d), rp
                            in zip(ranked, paths)], TOP))
            agg = (_benchmark_aggregates(rows)
                   if scorer == "benchmark" else ee.aggregates(rows))
            arms[arm] = {"aggregates": agg, "per_question": rows}
        off_rows = {r["id"]: r for r in arms["off"]["per_question"]}
        on_rows = {r["id"]: r for r in arms["on"]["per_question"]}
        gained, lost, moved = [], [], []
        for qid in sorted(off_rows):
            b = off_rows[qid]["must_cite_rank"]
            f = on_rows[qid]["must_cite_rank"]
            b_in = b is not None and b <= TOP
            f_in = f is not None and f <= TOP
            if f_in and not b_in:
                gained.append({"id": qid, "off_rank": b, "on_rank": f})
            elif b_in and not f_in:
                lost.append({"id": qid, "off_rank": b, "on_rank": f})
            elif b != f:
                moved.append({"id": qid, "off_rank": b, "on_rank": f})
        report_instruments[label] = {
            "off": arms["off"]["aggregates"],
            "on": arms["on"]["aggregates"],
            "gained_top10": gained,
            "lost_top10": lost,
            "rank_moved_within_or_outside_top10": moved,
            "per_question": {
                qid: {"off_rank": off_rows[qid]["must_cite_rank"],
                      "on_rank": on_rows[qid]["must_cite_rank"]}
                for qid in sorted(off_rows)},
        }
    report = {
        "item": "W3 HyDE-style lexical query expansion (2026-10-22)",
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "corpus": "wiki/ (scope=wiki)",
        "corpus_docs": len(docs),
        "weight": weight,
        "draft_seeds": DRAFT_SEEDS,
        "max_expansion_terms": MAX_EXPANSION_TERMS,
        "max_df_share": MAX_DF_SHARE,
        "draft_exclusions_applied": sorted(exclusions),
        "note": "Both arms run the production hybrid_rank with "
                "severance + governance at their defaults; the ON "
                "arm adds only the expansion record. The "
                "embedders are lexical by construction — there "
                "is no LLM draft and no dense retrieval here.",
        "instruments": report_instruments,
    }
    if write:
        out_json = Path(out_json) if out_json else \
            ROOT / "evaluation" / "hyde-expansion-report.json"
        out_md = Path(out_md) if out_md else \
            ROOT / "evaluation" / "hyde-expansion-report.md"
        out_json.write_text(json.dumps(report, indent=2) + "\n",
                            encoding="utf-8")
        out_md.write_text(render_measure_md(report), encoding="utf-8")
    return report


def render_measure_md(report):
    lines = [
        "# HyDE lexical query expansion — measurement (W3, 2026-10-22)",
        "",
        "Opt-in stage; nothing here changes a production default. "
        f"Corpus: wiki/ ({report['corpus_docs']} docs). Expansion "
        f"weight {report['weight']} (original terms weigh 1.0), "
        f"draft = top {report['draft_seeds']} BM25 hits' leads, "
        f"up to {report['max_expansion_terms']} terms.",
        "",
    ]
    for label, inst in report["instruments"].items():
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| arm | cov@1 | cov@3 | cov@5 | cov@10 | "
                     "hit@10 | MRR |")
        lines.append("|---|---|---|---|---|---|---|")
        for arm in ("off", "on"):
            a = inst[arm]
            c = a["citation_coverage"]
            lines.append(
                f"| {arm} | {c['@1']} | {c['@3']} | {c['@5']} | "
                f"{c['@10']} | {a['hit_rate_topk']} | "
                f"{a['mrr_must_cite']} |")
        lines.append("")
        for key, title in (("gained_top10", "Gained at top-10"),
                           ("lost_top10", "Lost at top-10")):
            rows = inst[key]
            lines.append(f"{title}: " + (
                ", ".join(f"{r['id']} ({r['off_rank']} -> "
                          f"{r['on_rank']})" for r in rows)
                if rows else "none"))
        moved = inst["rank_moved_within_or_outside_top10"]
        lines.append("Rank moved (no top-10 crossing): " + (
            ", ".join(f"{r['id']} ({r['off_rank']} -> {r['on_rank']})"
                      for r in moved) if moved else "none"))
        lines.append("")
    lines.append("Method: lexical HyDE — the hypothetical answer "
                 "is drafted from the corpus's own top BM25 hits; "
                 "no LLM and no embeddings exist on this machine. "
                 "Both arms pass severance + governance unchanged.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Gates: the A/B identity proof and the abstention battery
# ---------------------------------------------------------------------------

def ab_check(baseline_path=None):
    """Same-process A/B over golden + extended questions:
    hybrid_rank(terms, docs, adj) vs hybrid_rank(..., 
    expansion=None) must produce identical (score, path, detail)
    rankings; with `baseline_path` (a JSON captured from the
    pre-change pipeline), the no-argument arm must also match
    it exactly. Returns (ok, problems)."""
    ws = load_search()
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    questions = _load_questions("golden-questions.jsonl") \
        + _load_questions("extended-questions.jsonl")
    baseline = None
    if baseline_path:
        baseline = json.loads(Path(baseline_path).read_text(
            encoding="utf-8"))
    problems = []
    for q in questions:
        terms = ws.tokenize(q["question"])
        a = ws.hybrid_rank(terms, docs, adj)
        b = ws.hybrid_rank(terms, docs, adj, expansion=None)
        ra = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in a]
        rb = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in b]
        if ra != rb:
            problems.append(f"{q['id']}: no-arg vs expansion=None "
                            "rankings differ")
        if baseline is not None:
            want = baseline.get(q["id"])
            if want is None:
                problems.append(f"{q['id']}: missing from baseline")
            elif ra != want:
                problems.append(f"{q['id']}: no-arg ranking differs "
                                "from the pre-change baseline")
    return not problems, problems


def _run_battery(expanded, out_path, weight=DEFAULT_WEIGHT):
    """The pinned battery via its OWN runner (the W1.12 pattern:
    import it, wrap its wiki_search copy's hybrid_rank, run
    main). With expanded=True the wrapper injects an expansion
    record built per query over the runner's own docs."""
    battery = _load_sibling("wiki_abstention_for_hyde_gate",
                            "wiki_abstention_check.py")
    ws = battery.ws
    exclusions = default_exclusions(ws)
    cache = {}
    orig = ws.hybrid_rank

    def wrapped(terms, docs, adj=None, severance=None, **kw):
        if expanded and "expansion" not in kw:
            key = tuple(terms)
            if key not in cache:
                cache[key] = build_expansion(
                    ws, list(terms), docs, weight=weight,
                    exclude_paths=exclusions)
            kw["expansion"] = cache[key]
        return orig(terms, docs, adj, severance=severance, **kw)

    ws.hybrid_rank = wrapped
    try:
        argv = ["wiki_abstention_check.py"]
        if out_path:
            argv += ["--out", str(out_path)]
        rc = battery.main(argv)
    finally:
        ws.hybrid_rank = orig
    results = []
    if out_path and Path(out_path).is_file():
        results = json.loads(Path(out_path).read_text(
            encoding="utf-8"))["results"]
    passed = sum(1 for r in results if r["pass"])
    return passed, len(results), results, rc


def gate_check(out_dir, weight=DEFAULT_WEIGHT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plain = _run_battery(False, out_dir / "battery-off.json")
    on = _run_battery(True, out_dir / "battery-on.json", weight=weight)
    return {
        "plain": {"passed": plain[0], "total": plain[1], "rc": plain[3]},
        "expanded": {"passed": on[0], "total": on[1], "rc": on[3]},
        "expanded_failures": [
            r["id"] for r in on[2] if not r["pass"]],
        "plain_failures": [r["id"] for r in plain[2] if not r["pass"]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_record(rec):
    print(f"original terms: {rec['original_terms']}")
    print(f"draft seeds: {rec['draft']['seed_paths']} "
          f"({rec['draft']['tokens']} tokens)")
    if rec["expansion_terms"]:
        print(f"expansion terms (weight {rec['weight']} vs originals' 1.0):")
        for e in rec["expansion_terms"]:
            print(f"  {e['term']:<24} draft_tf={e['draft_tf']} "
                  f"df={e['df']} idf={e['idf']} score={e['score']}")
    else:
        print("expansion terms: none (no draft vocabulary to add)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ep = sub.add_parser("expand", help="print a query's expansion record")
    ep.add_argument("query")
    ep.add_argument("--weight", type=float, default=DEFAULT_WEIGHT)
    sp = sub.add_parser("search", help="default vs expanded top-N")
    sp.add_argument("query")
    sp.add_argument("--weight", type=float, default=DEFAULT_WEIGHT)
    sp.add_argument("--top", type=int, default=5)
    mp = sub.add_parser("measure", help="OFF vs ON on the house instruments")
    mp.add_argument("--weight", type=float, default=DEFAULT_WEIGHT)
    gp = sub.add_parser("gate-check", help="the pinned battery, plain and ON")
    gp.add_argument("--weight", type=float, default=DEFAULT_WEIGHT)
    gp.add_argument("--out-dir", default=None)
    bp = sub.add_parser("ab-check", help="default-path identity proof")
    bp.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    ws = load_search()
    if args.cmd == "expand":
        docs = ws.collect_docs("wiki")
        rec = build_expansion(ws, ws.tokenize(args.query), docs,
                              weight=args.weight,
                              exclude_paths=default_exclusions(ws))
        _print_record(rec)
        return 0
    if args.cmd == "search":
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize(args.query)
        rec = build_expansion(ws, terms, docs, weight=args.weight,
                              exclude_paths=default_exclusions(ws))
        _print_record(rec)
        off = ws.hybrid_rank(terms, docs, adj)
        on = ws.hybrid_rank(terms, docs, adj, expansion=rec)
        print("\ndefault:")
        for s, p, _t, _d in off[:args.top]:
            print(f"  {s:8.3f}  {relpath(ws, p)}")
        print("expanded:")
        for s, p, _t, _d in on[:args.top]:
            print(f"  {s:8.3f}  {relpath(ws, p)}")
        return 0
    if args.cmd == "measure":
        report = measure(weight=args.weight)
        for label, inst in report["instruments"].items():
            o, n = inst["off"], inst["on"]
            print(f"{label}: cov@10 {o['citation_coverage']['@10']} "
                  f"-> {n['citation_coverage']['@10']}, "
                  f"MRR {o['mrr_must_cite']} -> {n['mrr_must_cite']}, "
                  f"gained {[g['id'] for g in inst['gained_top10']]}, "
                  f"lost {[g['id'] for g in inst['lost_top10']]}")
        print("wrote evaluation/hyde-expansion-report.{json,md}")
        return 0
    if args.cmd == "gate-check":
        out_dir = args.out_dir or str(
            ROOT.parent / ".tmp-hyde" / "gate")
        res = gate_check(out_dir, weight=args.weight)
        print(f"battery plain:    {res['plain']['passed']}/"
              f"{res['plain']['total']}")
        print(f"battery expanded: {res['expanded']['passed']}/"
              f"{res['expanded']['total']}")
        if res["expanded_failures"]:
            print(f"expanded failures: {res['expanded_failures']}")
        return 0 if res["plain"]["passed"] == res["plain"]["total"] \
            else 1
    if args.cmd == "ab-check":
        ok, problems = ab_check(args.baseline)
        if ok:
            print("A/B identical: no-arg == expansion=None"
                  + (" == pre-change baseline" if args.baseline
                     else ""))
            return 0
        for p in problems:
            print(f"MISMATCH: {p}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
