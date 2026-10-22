#!/usr/bin/env python3
"""Iterative retrieval passes for hybrid search (W3, 2026-10-22).

The build-list item boards five pipeline patterns from the
iterative-retrieval literature — Self-RAG, FLARE, IRCoT, Astute
RAG, Think-on-Graph — as "prompt-level forms ... behind the
abstention/conflict battery gate", licence route: clean
re-implementation, idea only. This module is the RETRIEVAL-level
form, the one this wiki's serving path can actually run: there
is no LLM endpoint and no embedding store on this machine, so
there is no generation step for a critique pass (Self-RAG) or a
confidence trigger (FLARE) to attach to, and no answer text for
a consolidation pass (Astute) to consolidate. What exists is
retrieval, and the interleaved form (IRCoT: retrieval woven
into the reasoning chain, here woven into the pipeline itself)
has an honest lexical realisation:

  pass 1   the standing hybrid pipeline, unchanged — stages
           0-6 exactly as the caller configured them;
  refine   characteristic terms are extracted from pass 1's
           OWN governed output (the top seeds' lead passages,
           scored draft_tf x corpus idf, the HyDE lane's
           lexical method) — the corpus speaking its own
           vocabulary back to the query;
  pass 2+  the pipeline re-run with those terms merged into
           stage-0 recall at a stated weight below the
           original terms' 1.0 (plus the caller's own expansion
           terms, when the caller passed any);
  fuse     the passes' rankings are merged by reciprocal-rank
           fusion (k = 60, the house constant), every result
           carrying its per-pass ranks.

Bounds, stated: at most MAX_PASSES passes (default
DEFAULT_MAX_PASSES = 2, hard cap HARD_MAX_PASSES = 3), and the
loop stops early when a pass yields no refinement terms
("no-refinement-terms"), when a pass's top-10 set equals the
previous pass's ("stable-top10"), or when pass 1 is empty
("empty-first-pass"). The stop reason is on the record.

Governance composition — the strongest form, pinned by test:
the refinement draft is built from the list hybrid_rank
RETURNS, which has already passed severance (stage 5) and
governance (stage 6). A withheld or severed page is not in
that list, so its text never enters the draft vocabulary —
and each later pass re-runs stages 5-6 on its own output, so
a page the refinement terms happen to match is filtered
again. Iteration cannot resurrect what governance withheld:
the draft cannot speak its words, and even if it could, the
filters stand at every pass.

Scale honesty: fusing re-bases the scores onto the RRF scale,
so with the stage ON the absolute score scale the abstention
threshold tau was calibrated on does NOT survive (the HyDE
lane's battery-ON lesson, AB-008). That is measured and
reported by gate-check, not tuned away. The stage is NOT
wired into the Ask door; an ON Ask path would need its own
calibration as a separate, owner-visible act.

How the stage composes (it forks nothing):

  * scripts/wiki_search.py hybrid_rank(..., iterate=None)
    removes the stage: the pipeline is the pre-item one
    exactly — pinned by same-process A/B tests and a
    captured-corpus baseline comparison (ab-check below).
    iterate=True (or a {"max_passes":..., "weight":...}
    dict) runs the loop after stage 6 and returns the fused
    ranking.
  * A single pass (pass 1 empty, no refinement terms, or
    max_passes=1) returns pass 1's list UNCHANGED — no fusion
    is applied to one ranking, so a stopped-early query keeps
    the calibrated scale exactly.

Transparency: the iteration record — per pass: the stage-0
terms that pass ran with, the refinement that produced them
(seed passages, every term with draft_tf / df / idf), the
pass's result count, its top-10, and the pages its top-10
newly surfaced — plus the stop reason, is kept in
wiki_search.LAST_ITERATION, carried in the evidence pack's
"iteration" block, and printed by the CLI under --explain.
An iteration that cannot be inspected does not ship.

Commands:
    passes     print the iteration record for a query
    search     one query, default vs iterated top-N side by
               side
    measure    golden + extended (answerable) + directional
               + conflict slices, iteration OFF vs ON, named
               wins/losses; writes
               evaluation/iterative-retrieval-report.{json,md}
    gate-check the pinned abstention battery: plain (stage
               available, default path) and with iteration ON
    ab-check   same-process A/B over the golden + extended +
               conflict questions: no-argument vs iterate=None
               full rankings must be identical; with
               --baseline FILE also against a pre-change
               captured baseline

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
DEFAULT_MAX_PASSES = 2   # the brief's bound: pass 1 + one
                         # refinement pass, by default
HARD_MAX_PASSES = 3      # no configuration iterates further
REFINE_SEEDS = 5         # top governed hits whose leads form
                         # the refinement draft
MAX_REFINE_TERMS = 8     # terms a pass may contribute
REFINE_WEIGHT = 0.5      # refinement terms vs originals' 1.0
MAX_DF_SHARE = 0.5       # terms in > half the corpus are
                         # stopwords (the HyDE lane's filter)
RRF_K = 60               # reciprocal-rank fusion offset (the
                         # house constant: dense trial, one-hop)
TOP = 10                 # the house measurement cut


def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WS = None


def load_search():
    """This module's own copy of wiki_search (the refinement
    builder uses its tokenize / lead-window conventions
    read-only; hybrid_rank itself is always the CALLER's copy,
    reached through the seam or through rank_fn)."""
    global _WS
    if _WS is None:
        _WS = _load_sibling("wiki_search_for_iterate",
                            "wiki_search.py")
    return _WS


def relpath(ws, p):
    return str(p.relative_to(ws.ROOT)) if p.is_relative_to(ws.ROOT) \
        else str(p)


def clamp_max_passes(value):
    """The pass bound, clamped to [1, HARD_MAX_PASSES];
    a non-integer or missing value is the default."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_PASSES
    return max(1, min(HARD_MAX_PASSES, n))


# ---------------------------------------------------------------------------
# The refinement builder — terms from a pass's governed output
# ---------------------------------------------------------------------------

def build_refinement(ws, query_terms, ranked, docs,
                     weight=REFINE_WEIGHT,
                     max_terms=MAX_REFINE_TERMS,
                     seed_count=REFINE_SEEDS):
    """Extract the next pass's terms from THIS pass's output.

    `ranked` is a finished hybrid_rank list — in the seam,
    the list AFTER severance (stage 5) and governance
    (stage 6): the draft reads only what the governed
    pipeline surfaced. The draft is the lead window
    (ws.RERANK_LEAD_TOKENS tokens — the house lead) of the
    top `seed_count` results; candidate terms are the
    draft's terms that are not already query terms and are
    not corpus-stopwords (df share > MAX_DF_SHARE), each
    scored draft_tf x idf with the SAME Robertson idf
    wiki_search.bm25_rank uses; the top `max_terms` are
    taken, ties broken by term, so the record is
    deterministic.

    Returns the refinement record (plain dict). An empty
    terms list is an honest outcome — no results, or a
    draft that adds no vocabulary — and the loop stops on
    it ("no-refinement-terms")."""
    record = {
        "kind": "iterative-refinement",
        "method": "lexical refinement (W3): the next pass's "
                  "terms are extracted from the previous "
                  "pass's governed top hits' lead passages "
                  "(pseudo-relevance feedback, deterministic; "
                  "no LLM, no embeddings); terms scored "
                  "draft_tf x corpus idf",
        "weight": weight,
        "terms": [],
        "draft": {"seed_paths": [], "seed_count": 0, "tokens": 0},
    }
    if not query_terms or not ranked or not docs:
        return record
    text_of = {str(p): t for p, t in docs}
    seeds = []
    for _s, p, _t, _d in ranked:
        seeds.append((p, text_of.get(str(p), _t)))
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
        record["terms"].append({
            "term": term,
            "weight": weight,
            "draft_tf": tf,
            "df": df.get(term, 0),
            "idf": round(idf(term), 4),
            "score": round(-neg_score, 4),
        })
    return record


def merge_expansion(caller_expansion, refinement):
    """The stage-0 record a refinement pass runs with: the
    caller's own expansion terms (when the caller passed an
    expansion record) PLUS the refinement terms. On a term
    collision the caller's entry wins — the caller's stage
    was configured first, and the merged record names both
    sources."""
    terms = []
    seen = set()
    for e in (caller_expansion or {}).get("expansion_terms") or []:
        terms.append(dict(e))
        seen.add(e["term"])
    for e in refinement.get("terms") or []:
        if e["term"] in seen:
            continue
        terms.append({"term": e["term"], "weight": e["weight"],
                      "draft_tf": e["draft_tf"], "df": e["df"],
                      "idf": e["idf"], "score": e["score"],
                      "source": "iterative-refinement"})
        seen.add(e["term"])
    return {
        "kind": "iterative-refinement-pass",
        "method": "stage-0 terms for a refinement pass: the "
                  "caller's expansion terms (if any) plus the "
                  "previous pass's refinement terms",
        "expansion_terms": terms,
    }


# ---------------------------------------------------------------------------
# Fusion — reciprocal rank over the passes' rankings
# ---------------------------------------------------------------------------

def fuse_passes(pass_lists):
    """Merge the passes' ranked lists by reciprocal-rank
    fusion: a page's fused score is the sum over passes of
    1 / (RRF_K + its 1-based rank in that pass). The page's
    detail is its EARLIEST pass's detail (pass 1's is the
    unperturbed pipeline's) plus an "iteration" attribution
    block: the fused score, its rank in every pass it
    appears in, and the first pass that surfaced it.
    Returns (fused, attribution) with attribution keyed by
    string path. Deterministic: ties break on path, the
    house sort."""
    fused_score = {}
    ranks_of = {}
    first_entry = {}
    for pi, ranked in enumerate(pass_lists, start=1):
        for rank0, (s, p, t, d) in enumerate(ranked):
            key = str(p)
            fused_score[key] = fused_score.get(key, 0.0) \
                + 1.0 / (RRF_K + rank0 + 1)
            ranks_of.setdefault(key, {})[pi] = rank0 + 1
            if key not in first_entry:
                first_entry[key] = (p, t, d)
    out = []
    for key, fs in fused_score.items():
        p, t, d = first_entry[key]
        ranks = ranks_of[key]
        detail = dict(d, iteration={
            "fused_score": round(fs, 6),
            "pass_ranks": {str(k): v
                           for k, v in sorted(ranks.items())},
            "first_seen_pass": min(ranks),
        })
        out.append((fs, p, t, detail))
    out.sort(key=lambda r: (-r[0], str(r[1])))
    return out, ranks_of


# ---------------------------------------------------------------------------
# The loop — passes, stopping rule, the iteration record
# ---------------------------------------------------------------------------

def _top10(ranked):
    return [str(p) for _s, p, _t, _d in ranked[:TOP]]


def _disp(ws, key):
    """Display form of a string path key: repo-relative when
    the path lives under the wiki root, the string itself
    otherwise (fixture corpora on fake roots)."""
    return relpath(ws, Path(key))


def run_iteration(rank_fn, query_terms, docs, first_pass,
                  caller_expansion=None,
                  max_passes=DEFAULT_MAX_PASSES,
                  weight=REFINE_WEIGHT):
    """Run the bounded iteration loop.

    `rank_fn(expansion_record)` re-runs the caller's
    pipeline for one more pass; `first_pass` is pass 1's
    finished (governed) ranking, already computed by the
    caller — the loop never re-runs pass 1. Returns
    (ranking, record): the fused ranking when 2+ passes
    ran, pass 1's list UNCHANGED when the loop stopped
    after one pass."""
    ws = load_search()
    max_passes = clamp_max_passes(max_passes)
    caller_terms = [dict(e) for e in
                    (caller_expansion or {}).get(
                        "expansion_terms") or []]
    pass_lists = [first_pass]
    pass_records = [{
        "pass": 1,
        "stage0_terms": caller_terms,
        "refinement_from": None,
        "results": len(first_pass),
        "top10": [_disp(ws, k) for k in _top10(first_pass)],
        "new_in_top10": None,
    }]
    stop_reason = None
    if not first_pass:
        stop_reason = "empty-first-pass"
    seen_top10 = [{str(p) for _s, p, _t, _d in first_pass[:TOP]}]
    last_refinement = None
    while stop_reason is None and len(pass_lists) < max_passes:
        rec = build_refinement(ws, query_terms, pass_lists[-1],
                               docs, weight=weight)
        last_refinement = rec
        if not rec["terms"]:
            stop_reason = "no-refinement-terms"
            break
        nxt = rank_fn(merge_expansion(caller_expansion, rec))
        pass_lists.append(nxt)
        top10 = {str(p) for _s, p, _t, _d in nxt[:TOP]}
        new = sorted(top10 - set().union(*seen_top10))
        seen_top10.append(top10)
        pass_records.append({
            "pass": len(pass_lists),
            "stage0_terms": merge_expansion(
                caller_expansion, rec)["expansion_terms"],
            "refinement_from": {
                "seed_paths": rec["draft"]["seed_paths"],
                "terms": rec["terms"],
            },
            "results": len(nxt),
            "top10": [relpath(ws, p)
                      for _s, p, _t, _d in nxt[:TOP]],
            "new_in_top10": [_disp(ws, k) for k in new],
        })
        if top10 == seen_top10[-2]:
            stop_reason = "stable-top10"
    if stop_reason is None:
        stop_reason = "max-passes"
    if len(pass_lists) == 1:
        ranking = first_pass
        fused = False
    else:
        ranking, _ranks = fuse_passes(pass_lists)
        fused = True
    record = {
        "kind": "iterative-retrieval",
        "method": "bounded iterative retrieval (W3): pass 1 "
                  "is the standing pipeline; each later pass "
                  "re-runs it with refinement terms drawn "
                  "from the previous pass's GOVERNED output; "
                  "passes fused by reciprocal rank (k=60)",
        "max_passes": max_passes,
        "weight": weight,
        "passes_run": len(pass_lists),
        "stop_reason": stop_reason,
        "fused": fused,
        "fusion": ("reciprocal-rank, k=60, over the passes' "
                   "rankings" if fused else None),
        "passes": pass_records,
        "results_total": len(ranking),
    }
    return ranking, record


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


def _load_questions(filename, questions_only=False):
    out = []
    for line in (ROOT / "evaluation" / filename).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if questions_only and "question" not in row:
                continue
            out.append(row)
    return out


def measure(write=True, out_json=None, out_md=None,
            max_passes=DEFAULT_MAX_PASSES, weight=REFINE_WEIGHT):
    """Golden + extended-answerable + directional + conflict
    slices, iteration OFF vs ON through the production
    hybrid_rank (severance + governance at their defaults in
    BOTH arms — the only difference is the iterate
    argument). Wins and losses are computed from the
    per-question rows: gained = must-cite enters the top-10
    under ON, lost = leaves it. The ON arm also records the
    per-question iteration statistics (passes run, stop
    reasons, new pages in the fused top-10)."""
    ws = load_search()
    wb = _load_sibling("wiki_benchmark_for_iterate",
                       "wiki_benchmark.py")
    ee = _load_sibling("wiki_eval_extended_for_iterate",
                       "wiki_eval_extended.py")
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)

    golden = _load_questions("golden-questions.jsonl")
    extended = _load_questions("extended-questions.jsonl")
    conflict = _load_questions("conflict-questions.jsonl",
                               questions_only=True)
    instruments = [
        ("golden", golden, "benchmark"),
        ("extended_answerable",
         [q for q in extended if not q.get("expected_abstain")],
         "extended"),
        ("directional_slice",
         [q for q in extended if q.get("slice") == "directional"],
         "extended"),
        ("conflict_slice", conflict, "extended"),
    ]
    report_instruments = {}
    iter_stats = {}
    for label, questions, scorer in instruments:
        arms = {}
        stats = []
        for arm in ("off", "on"):
            rows = []
            for q in questions:
                terms = ws.tokenize(q["question"])
                if arm == "off":
                    ranked = ws.hybrid_rank(terms, docs, adj)
                else:
                    ranked = ws.hybrid_rank(
                        terms, docs, adj,
                        iterate={"max_passes": max_passes,
                                 "weight": weight})
                    rec = ws.LAST_ITERATION["record"] or {}
                    last = (rec.get("passes") or [{}])[-1]
                    stats.append({
                        "id": q["id"],
                        "passes_run": rec.get("passes_run"),
                        "stop_reason": rec.get("stop_reason"),
                        "new_in_top10": last.get("new_in_top10"),
                    })
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
        iter_stats[label] = stats
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
        "item": "W3 Iterative retrieval passes (2026-10-22)",
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "corpus": "wiki/ (scope=wiki)",
        "corpus_docs": len(docs),
        "max_passes": max_passes,
        "weight": weight,
        "refine_seeds": REFINE_SEEDS,
        "max_refine_terms": MAX_REFINE_TERMS,
        "fusion": "reciprocal-rank, k=60, over the passes' rankings",
        "note": "Both arms run the production hybrid_rank with "
                "severance + governance at their defaults; the ON "
                "arm adds only the iteration stage. Refinement "
                "is lexical and corpus-derived — there is no "
                "LLM and no embedding endpoint on this machine.",
        "instruments": report_instruments,
        "iteration_stats": iter_stats,
    }
    if write:
        out_json = Path(out_json) if out_json else \
            ROOT / "evaluation" / "iterative-retrieval-report.json"
        out_md = Path(out_md) if out_md else \
            ROOT / "evaluation" / "iterative-retrieval-report.md"
        out_json.write_text(json.dumps(report, indent=2) + "\n",
                            encoding="utf-8")
        out_md.write_text(render_measure_md(report), encoding="utf-8")
    return report


def render_measure_md(report):
    lines = [
        "# Iterative retrieval passes — measurement (W3, 2026-10-22)",
        "",
        "Opt-in stage; nothing here changes a production default. "
        f"Corpus: wiki/ ({report['corpus_docs']} docs). At most "
        f"{report['max_passes']} passes; refinement terms at "
        f"weight {report['weight']} (original terms weigh 1.0), "
        f"drafted from each pass's governed top "
        f"{report['refine_seeds']} hits' leads, up to "
        f"{report['max_refine_terms']} terms; passes fused by "
        "reciprocal rank (k=60).",
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
        stats = report["iteration_stats"][label]
        stops = Counter(s["stop_reason"] for s in stats)
        lines.append("Iteration (ON arm): passes run "
                     + ", ".join(
                         f"{s['id']}={s['passes_run']}"
                         for s in stats if s["passes_run"] != 2)
                     + " (all others 2); stop reasons: "
                     + ", ".join(f"{k} x{v}"
                                 for k, v in sorted(stops.items())))
        lines.append("")
    lines.append("Method: bounded iterative retrieval — pass 1 "
                 "is the standing pipeline; later passes re-run "
                 "it with terms drawn from the previous pass's "
                 "governed output; passes fused by reciprocal "
                 "rank. Both arms pass severance + governance "
                 "unchanged, at every pass.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Gates: the A/B identity proof and the abstention battery
# ---------------------------------------------------------------------------

def ab_check(baseline_path=None):
    """Same-process A/B over golden + extended + conflict
    questions: hybrid_rank(terms, docs, adj) vs hybrid_rank(...,
    iterate=None) must produce identical (score, path, detail)
    rankings; with `baseline_path` (a JSON captured from the
    pre-change pipeline), the no-argument arm must also match
    it exactly. Returns (ok, problems)."""
    ws = load_search()
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    questions = _load_questions("golden-questions.jsonl") \
        + _load_questions("extended-questions.jsonl") \
        + _load_questions("conflict-questions.jsonl",
                          questions_only=True)
    baseline = None
    if baseline_path:
        baseline = json.loads(Path(baseline_path).read_text(
            encoding="utf-8"))
    problems = []
    for q in questions:
        terms = ws.tokenize(q["question"])
        a = ws.hybrid_rank(terms, docs, adj)
        b = ws.hybrid_rank(terms, docs, adj, iterate=None)
        ra = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in a]
        rb = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in b]
        if ra != rb:
            problems.append(f"{q['id']}: no-arg vs iterate=None "
                            "rankings differ")
        if baseline is not None:
            want = baseline.get(q["id"])
            if want is None:
                problems.append(f"{q['id']}: missing from baseline")
            elif ra != want:
                problems.append(f"{q['id']}: no-arg ranking differs "
                                "from the pre-change baseline")
    return not problems, problems


def make_injecting_wrapper(orig, **inject):
    """Wrap a hybrid_rank so the OUTERMOST call gains the
    given keyword arguments; re-entrant calls pass through
    untouched. The guard is load-bearing, not decorative:
    this stage's own seam re-enters hybrid_rank by its
    module-global name for passes 2+, so a wrapper that
    injects `iterate` unconditionally recurses without
    bound (the first gate-check run died exactly that way,
    RecursionError inside the ON arm). The battery case
    must iterate once, at the top; the passes that make up
    that iteration are part of the same act."""
    state = {"depth": 0}

    def wrapped(terms, docs, adj=None, severance=None, **kw):
        if state["depth"] == 0:
            for key, value in inject.items():
                kw.setdefault(key, value)
        state["depth"] += 1
        try:
            return orig(terms, docs, adj, severance=severance,
                        **kw)
        finally:
            state["depth"] -= 1

    return wrapped


def _run_battery(iterated, out_path):
    """The pinned battery via its OWN runner (the W1.12/HyDE
    pattern: import it, wrap its wiki_search copy's hybrid_rank,
    run main). With iterated=True the wrapper passes
    iterate=True on the outermost call of every case the
    runner makes (make_injecting_wrapper guards the seam's
    own re-entries)."""
    battery = _load_sibling("wiki_abstention_for_iterate_gate",
                            "wiki_abstention_check.py")
    ws = battery.ws
    orig = ws.hybrid_rank
    wrapped = make_injecting_wrapper(
        orig, **({"iterate": True} if iterated else {}))

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


def gate_check(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plain = _run_battery(False, out_dir / "battery-off.json")
    on = _run_battery(True, out_dir / "battery-on.json")
    return {
        "plain": {"passed": plain[0], "total": plain[1], "rc": plain[3]},
        "iterated": {"passed": on[0], "total": on[1], "rc": on[3]},
        "iterated_failures": [
            r["id"] for r in on[2] if not r["pass"]],
        "plain_failures": [r["id"] for r in plain[2] if not r["pass"]],
        "iterated_failure_details": [
            {"id": r["id"], "detail": r.get("detail"),
             "top_score": r.get("top_score")}
            for r in on[2] if not r["pass"]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_record(rec):
    if not rec:
        print("iterative retrieval: off (no record)")
        return
    print(f"passes run: {rec['passes_run']} of at most "
          f"{rec['max_passes']}; stop: {rec['stop_reason']}; "
          f"fused: {rec['fused']}")
    for prec in rec["passes"]:
        print(f"  pass {prec['pass']}: {prec['results']} result(s)")
        ref = prec.get("refinement_from")
        if ref:
            print(f"    drafted from: {ref['seed_paths']}")
            for e in ref["terms"]:
                print(f"    + {e['term']} (weight {e['weight']}, "
                      f"draft_tf {e['draft_tf']}, df {e['df']}, "
                      f"idf {e['idf']})")
        if prec.get("new_in_top10"):
            print(f"    new in top-10: {prec['new_in_top10']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("passes", help="print a query's iteration record")
    pp.add_argument("query")
    pp.add_argument("--max-passes", type=int,
                    default=DEFAULT_MAX_PASSES)
    sp = sub.add_parser("search", help="default vs iterated top-N")
    sp.add_argument("query")
    sp.add_argument("--max-passes", type=int,
                    default=DEFAULT_MAX_PASSES)
    sp.add_argument("--top", type=int, default=5)
    mp = sub.add_parser("measure", help="OFF vs ON on the house instruments")
    mp.add_argument("--max-passes", type=int,
                    default=DEFAULT_MAX_PASSES)
    gp = sub.add_parser("gate-check", help="the pinned battery, plain and ON")
    gp.add_argument("--out-dir", default=None)
    bp = sub.add_parser("ab-check", help="default-path identity proof")
    bp.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    ws = load_search()
    if args.cmd == "passes":
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        ws.hybrid_rank(ws.tokenize(args.query), docs, adj,
                       iterate={"max_passes": args.max_passes})
        _print_record(ws.LAST_ITERATION["record"])
        return 0
    if args.cmd == "search":
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize(args.query)
        off = ws.hybrid_rank(terms, docs, adj)
        on = ws.hybrid_rank(terms, docs, adj,
                            iterate={"max_passes": args.max_passes})
        _print_record(ws.LAST_ITERATION["record"])
        print("\ndefault:")
        for s, p, _t, _d in off[:args.top]:
            print(f"  {s:8.3f}  {relpath(ws, p)}")
        print("iterated:")
        for s, p, _t, d in on[:args.top]:
            it = d.get("iteration") or {}
            tag = (f"  [passes {it.get('pass_ranks')}]"
                   if it else "")
            print(f"  {s:8.3f}  {relpath(ws, p)}{tag}")
        return 0
    if args.cmd == "measure":
        report = measure(max_passes=args.max_passes)
        for label, inst in report["instruments"].items():
            o, n = inst["off"], inst["on"]
            print(f"{label}: cov@10 {o['citation_coverage']['@10']} "
                  f"-> {n['citation_coverage']['@10']}, "
                  f"MRR {o['mrr_must_cite']} -> {n['mrr_must_cite']}, "
                  f"gained {[g['id'] for g in inst['gained_top10']]}, "
                  f"lost {[g['id'] for g in inst['lost_top10']]}")
        print("wrote evaluation/iterative-retrieval-report.{json,md}")
        return 0
    if args.cmd == "gate-check":
        out_dir = args.out_dir or str(
            ROOT.parent / ".tmp-iterate" / "gate")
        res = gate_check(out_dir)
        print(f"battery plain:    {res['plain']['passed']}/"
              f"{res['plain']['total']}")
        print(f"battery iterated: {res['iterated']['passed']}/"
              f"{res['iterated']['total']}")
        if res["iterated_failures"]:
            print(f"iterated failures: {res['iterated_failures']}")
            for f in res["iterated_failure_details"]:
                print(f"  {f['id']}: {f['detail']}")
        return 0 if res["plain"]["passed"] == res["plain"]["total"] \
            else 1
    if args.cmd == "ab-check":
        ok, problems = ab_check(args.baseline)
        if ok:
            print("A/B identical: no-arg == iterate=None"
                  + (" == pre-change baseline" if args.baseline
                     else ""))
            return 0
        for p in problems:
            print(f"MISMATCH: {p}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
