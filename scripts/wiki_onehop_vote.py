#!/usr/bin/env python3
"""One-hop wikilink expansion vote for hybrid search (W3, 2026-10-22).

The idea (build-list wave 3, sources: Wiki Copilot and
@crewhaus/wiki-store; the half-weight formula is adapted with
credit from the crewhaus pattern — an RRF-shaped corroboration
term — and all code here is our own): a page one wikilink hop
away from a strong lexical hit gains a small, bounded vote,

    gain = VOTE_WEIGHT / (RRF_K + best_seed_rank)
         = 0.5 / (60 + best_seed_rank)

where best_seed_rank is the 1-based rank of the best-ranked
lexical hit (a candidate with bm25 > 0) adjacent to the page in
the wikilink graph. A link CORROBORATES; it never manufactures
relevance: the gain is a single term, not a sum over voters —
however many seeds link to a page, it gains only its best
seed's term — so the maximum lift any page can ever receive is
the supremum at rank 1:

    VOTE_SUPREMUM = 0.5 / 61 = 0.008197...

against final scores that run to ~1.5. The vote can break a
near-tie and can ADMIT a neighbour that no stage recalled (a
bm25 = 0, below-the-PPR-floor page enters the list carrying
only its vote), but it cannot lift a page past a genuine match
that outscores it by more than the supremum.

How the stage composes (it forks nothing):

  * scripts/wiki_search.py hybrid_rank(..., onehop=None)
    removes the stage: the pipeline is the pre-item one
    exactly — pinned by same-process A/B tests and a
    captured-corpus baseline comparison (ab-check below).
    onehop=True (or a {"k":..., "weight":...} dict) runs the
    stage as stage 4c: after the rerank/listwise stages,
    BEFORE severance (stage 5) and governance (stage 6).
  * Placement is deliberate. The vote adds to FINAL scores
    only: no renormalisation follows it, so a page no seed
    links to keeps its score to the last bit — the frozen
    abstention threshold tau (calibrated on the un-voted
    pipeline's absolute scale) is perturbed only for pages
    that actually receive a vote, never globally. (HyDE's
    stage-0 merge, by contrast, rescales every score through
    the blend maximum — its battery-ON failure, AB-008, is
    recorded in evaluation/hyde-expansion-report.md.)
  * Stages 5–6 filter the voted list exactly as they filter
    the un-voted one. A withheld or severed page ADMITTED by
    a vote is removed by the same register lookups; a vote
    whose best seed is a page later withheld still counts
    (the graph walk has always transmitted through such
    pages — PPR seeds include them too), but the withheld
    page itself can never surface. Both directions are
    pinned by test.
  * The stage is NOT wired into the Ask door. Whether the
    battery survives with the vote ON is measured (gate-check
    below) and reported either way; an ON Ask path would be
    a separate, owner-visible act.

Transparency: every voted page's result detail carries a
"onehop_vote" block — the gain, the seed page that cast it,
that seed's rank, how many seeds were adjacent, whether the
page was admitted by the vote, and the W1.8 provenance label
of the edge it travelled over. Search-graph edges are
verbatim body wikilinks of relation type "mentions" (the
graph builder strips code spans/fences and infers no heading
type), so under the W1.8 label model (tools/lens/lenslib.py
edge_label) the label is EXTRACTED at confidence 1.0,
polarity positive, rule "verbatim-link" — the test suite
cross-checks this against lenslib itself. The full vote
record is kept in wiki_search.LAST_ONEHOP, carried in the
evidence pack's "onehop_vote" block, and printed by the CLI
under --explain. A vote that cannot be inspected does not
ship.

Commands:
    votes      print the vote record for a query
    search     one query, default vs voted top-N side by side
    measure    golden + extended (answerable) + directional
               + conflict slices, vote OFF vs ON, named
               wins/losses; writes
               evaluation/onehop-vote-report.{json,md}
    gate-check the pinned abstention battery: plain (stage
               available, default path) and with the vote ON
    ab-check   same-process A/B over the golden + extended +
               conflict questions: no-argument vs onehop=None
               full rankings must be identical; with
               --baseline FILE also against a pre-change
               captured baseline

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Policy constants (stated here, measured in the report).
RRF_K = 60            # the crewhaus formula's rank offset
VOTE_WEIGHT = 0.5     # the "half weight": a vote is half an
                      # RRF term (1 / (k + rank)) for its seed
VOTE_SUPREMUM = VOTE_WEIGHT / (RRF_K + 1)  # best seed rank = 1
TOP = 10              # the house measurement cut


def vote_gain(seed_rank, k=RRF_K, weight=VOTE_WEIGHT):
    """The gain a page receives from its best seed at
    `seed_rank` (1-based). Monotone decreasing in rank;
    vote_gain(1) == VOTE_SUPREMUM is the most any page can
    ever gain from this stage, from any number of voters."""
    if seed_rank is None or seed_rank < 1:
        return 0.0
    return weight / (k + seed_rank)


def edge_label():
    """The W1.8 provenance label of a search-graph edge.

    The search graph (wiki_search.build_link_graph) is built
    from verbatim body wikilinks: code spans and fences are
    stripped before links are read, and no heading type is
    inferred, so every edge is kind "wikilink", type
    "mentions". tools/lens/lenslib.py edge_label assigns
    exactly: EXTRACTED, confidence CONFIDENCE_VERBATIM = 1.0,
    polarity "positive" (mentions does not negate); the
    backfill tool (scripts/wiki_edge_labels.py) names the
    assigning rule "verbatim-link"."""
    return {"kind": "wikilink", "type": "mentions",
            "label": "EXTRACTED", "confidence": 1.0,
            "polarity": "positive", "rule": "verbatim-link"}


def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WS = None


def load_search():
    global _WS
    if _WS is None:
        _WS = _load_sibling("wiki_search_for_onehop", "wiki_search.py")
    return _WS


def relpath(ws, p):
    return str(p.relative_to(ws.ROOT)) if p.is_relative_to(ws.ROOT) \
        else str(p)


# ---------------------------------------------------------------------------
# The vote stage (consumed by wiki_search.hybrid_rank, stage 4c)
# ---------------------------------------------------------------------------

def apply_vote_stage(final, docs, adj, index_of, ppr,
                     k=RRF_K, weight=VOTE_WEIGHT):
    """Apply the one-hop vote to a finished (stage-4) ranking.

    `final`: [(score, path, text, detail)] in ranked order.
    Seeds are the entries whose detail carries bm25 > 0 — the
    lexical hits — ranked by their 1-based position in `final`.
    Every doc adjacent (in the undirected wikilink graph `adj`)
    to at least one seed receives the single gain of its
    best-ranked seed: candidates already in `final` are lifted
    by it; docs not in `final` are ADMITTED carrying the gain
    as their whole score, with an honest detail (bm25 0.0,
    via "vote", rerank 1.0 = no rerank was applied to them,
    title_boost 0 = none was applied). Returns (new_final,
    record); the record names every vote and every admission.
    Deterministic: adjacency lists are sorted, ties for best
    seed break on (rank, doc index), output is re-sorted by
    (-score, path) like every other stage."""
    seed_rank = {}
    for pos, (_s, p, _t, detail) in enumerate(final):
        if detail.get("bm25", 0.0) > 0:
            seed_rank[index_of[p]] = pos + 1
    votes = {}
    if seed_rank:
        for j in sorted(adj):
            best = None  # (rank, seed idx)
            voters = 0
            for i in adj[j]:
                r = seed_rank.get(i)
                if r is None or i == j:
                    continue
                voters += 1
                if best is None or (r, i) < best:
                    best = (r, i)
            if best is not None:
                rank, seed_idx = best
                votes[j] = {
                    "gain": vote_gain(rank, k=k, weight=weight),
                    "seed_idx": seed_idx, "seed_rank": rank,
                    "voting_seeds": voters,
                }
    in_final = {index_of[p] for _s, p, _t, _d in final}
    label = edge_label()
    out = []
    record_votes = {}
    admitted = []
    for score, p, text, detail in final:
        j = index_of[p]
        v = votes.get(j)
        if v is None:
            out.append((score, p, text, detail))
            continue
        block = {"gain": round(v["gain"], 6),
                 "seed": relpath_from(docs, v["seed_idx"]),
                 "seed_rank": v["seed_rank"],
                 "voting_seeds": v["voting_seeds"],
                 "edge": label, "admitted": False}
        record_votes[relpath_from(docs, j)] = block
        out.append((score + v["gain"], p, text,
                    dict(detail, onehop_vote=block)))
    for j in sorted(votes):
        if j in in_final:
            continue
        v = votes[j]
        p, text = docs[j]
        block = {"gain": round(v["gain"], 6),
                 "seed": relpath_from(docs, v["seed_idx"]),
                 "seed_rank": v["seed_rank"],
                 "voting_seeds": v["voting_seeds"],
                 "edge": label, "admitted": True}
        rel = relpath_from(docs, j)
        record_votes[rel] = block
        admitted.append(rel)
        detail = {"bm25": 0.0, "ppr": round(ppr.get(j, 0.0), 6),
                  "via": "vote", "temporal": 0.0, "rerank": 1.0,
                  "title_boost": 0, "title_match": "none",
                  "rank_expression": "hybrid-current",
                  "onehop_vote": block}
        out.append((v["gain"], p, text, detail))
    out.sort(key=lambda r: (-r[0], str(r[1])))
    record = {
        "kind": "onehop-wikilink-vote",
        "formula": "gain = weight / (k + best_seed_rank)",
        "k": k, "weight": weight,
        "supremum": round(weight / (k + 1), 6),
        "seed_count": len(seed_rank),
        "votes": record_votes,
        "admitted": admitted,
        "boosted": sorted(rel for rel, b in record_votes.items()
                          if not b["admitted"]),
    }
    return out, record


def relpath_from(docs, idx):
    """Repo-relative path of docs[idx] when the doc path is
    under the wiki root of THIS module's tree; the string
    path otherwise (fixture corpora on fake roots)."""
    p = docs[idx][0]
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


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


def measure(write=True, out_json=None, out_md=None):
    """Golden + extended-answerable + directional + conflict
    slices, vote OFF vs ON through the production hybrid_rank
    (severance + governance at their defaults in BOTH arms —
    the only difference is the onehop argument). Wins and
    losses are computed from the per-question rows: gained =
    must-cite enters the top-10 under ON, lost = leaves it."""
    ws = load_search()
    wb = _load_sibling("wiki_benchmark_for_onehop", "wiki_benchmark.py")
    ee = _load_sibling("wiki_eval_extended_for_onehop",
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
    for label, questions, scorer in instruments:
        arms = {}
        for arm in ("off", "on"):
            rows = []
            for q in questions:
                terms = ws.tokenize(q["question"])
                ranked = ws.hybrid_rank(
                    terms, docs, adj,
                    onehop=(True if arm == "on" else None))
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
        "item": "W3 One-hop wikilink expansion vote (2026-10-22)",
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "corpus": "wiki/ (scope=wiki)",
        "corpus_docs": len(docs),
        "formula": "gain = 0.5 / (60 + best_seed_rank)",
        "supremum": round(VOTE_SUPREMUM, 6),
        "note": "Both arms run the production hybrid_rank with "
                "severance + governance at their defaults; the ON "
                "arm adds only the one-hop vote (stage 4c). The "
                "vote is graph-proximity evidence: a verbatim "
                "wikilink one hop from a lexical hit. No "
                "embeddings, no LLM.",
        "instruments": report_instruments,
    }
    if write:
        out_json = Path(out_json) if out_json else \
            ROOT / "evaluation" / "onehop-vote-report.json"
        out_md = Path(out_md) if out_md else \
            ROOT / "evaluation" / "onehop-vote-report.md"
        out_json.write_text(json.dumps(report, indent=2) + "\n",
                            encoding="utf-8")
        out_md.write_text(render_measure_md(report), encoding="utf-8")
    return report


def render_measure_md(report):
    lines = [
        "# One-hop wikilink vote — measurement (W3, 2026-10-22)",
        "",
        "Opt-in stage; nothing here changes a production default. "
        f"Corpus: wiki/ ({report['corpus_docs']} docs). Formula: "
        f"{report['formula']} — a single gain per page from its "
        f"best-ranked adjacent lexical hit; supremum "
        f"{report['supremum']}.",
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
    lines.append("Method: the vote is stage 4c of hybrid_rank — "
                 "applied to final scores, before severance and "
                 "governance filter the voted list. Both arms "
                 "pass stages 5-6 unchanged.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Gates: the A/B identity proof and the abstention battery
# ---------------------------------------------------------------------------

def ab_check(baseline_path=None):
    """Same-process A/B over golden + extended + conflict
    questions: hybrid_rank(terms, docs, adj) vs hybrid_rank(...,
    onehop=None) must produce identical (score, path, detail)
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
        b = ws.hybrid_rank(terms, docs, adj, onehop=None)
        ra = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in a]
        rb = [[round(s, 6), relpath(ws, p), d] for s, p, _t, d in b]
        if ra != rb:
            problems.append(f"{q['id']}: no-arg vs onehop=None "
                            "rankings differ")
        if baseline is not None:
            want = baseline.get(q["id"])
            if want is None:
                problems.append(f"{q['id']}: missing from baseline")
            elif ra != want:
                problems.append(f"{q['id']}: no-arg ranking differs "
                                "from the pre-change baseline")
    return not problems, problems


def _run_battery(voted, out_path):
    """The pinned battery via its OWN runner (the W1.12/HyDE
    pattern: import it, wrap its wiki_search copy's hybrid_rank,
    run main). With voted=True the wrapper passes onehop=True
    on every call the runner makes."""
    battery = _load_sibling("wiki_abstention_for_onehop_gate",
                            "wiki_abstention_check.py")
    ws = battery.ws
    orig = ws.hybrid_rank

    def wrapped(terms, docs, adj=None, severance=None, **kw):
        if voted and "onehop" not in kw:
            kw["onehop"] = True
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


def gate_check(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plain = _run_battery(False, out_dir / "battery-off.json")
    on = _run_battery(True, out_dir / "battery-on.json")
    return {
        "plain": {"passed": plain[0], "total": plain[1], "rc": plain[3]},
        "voted": {"passed": on[0], "total": on[1], "rc": on[3]},
        "voted_failures": [r["id"] for r in on[2] if not r["pass"]],
        "plain_failures": [r["id"] for r in plain[2] if not r["pass"]],
        "voted_failure_details": [
            {"id": r["id"], "detail": r.get("detail")}
            for r in on[2] if not r["pass"]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_record(rec):
    if not rec:
        print("one-hop vote: off (no record)")
        return
    print(f"formula: {rec['formula']}  (k={rec['k']}, "
          f"weight={rec['weight']}, supremum={rec['supremum']})")
    print(f"seeds (lexical hits): {rec['seed_count']}; "
          f"votes cast: {len(rec['votes'])} "
          f"(boosted {len(rec['boosted'])}, "
          f"admitted {len(rec['admitted'])})")
    for rel in sorted(rec["votes"]):
        v = rec["votes"][rel]
        print(f"  {rel}: +{v['gain']} from {v['seed']} "
              f"(seed rank {v['seed_rank']}, "
              f"{v['voting_seeds']} voting seed(s), "
              f"edge {v['edge']['label']}@{v['edge']['confidence']}"
              f"{', ADMITTED' if v['admitted'] else ''})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    vp = sub.add_parser("votes", help="print a query's vote record")
    vp.add_argument("query")
    sp = sub.add_parser("search", help="default vs voted top-N")
    sp.add_argument("query")
    sp.add_argument("--top", type=int, default=5)
    mp = sub.add_parser("measure", help="OFF vs ON on the house instruments")
    gp = sub.add_parser("gate-check", help="the pinned battery, plain and ON")
    gp.add_argument("--out-dir", default=None)
    bp = sub.add_parser("ab-check", help="default-path identity proof")
    bp.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    ws = load_search()
    if args.cmd == "votes":
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        ws.hybrid_rank(ws.tokenize(args.query), docs, adj, onehop=True)
        _print_record(ws.LAST_ONEHOP["record"])
        return 0
    if args.cmd == "search":
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize(args.query)
        off = ws.hybrid_rank(terms, docs, adj)
        on = ws.hybrid_rank(terms, docs, adj, onehop=True)
        _print_record(ws.LAST_ONEHOP["record"])
        print("\ndefault:")
        for s, p, _t, _d in off[:args.top]:
            print(f"  {s:8.3f}  {relpath(ws, p)}")
        print("voted:")
        for s, p, _t, d in on[:args.top]:
            d = _d.get("onehop_vote")
            tag = f"  [vote +{d['gain']} from {d['seed']}]" if d else ""
            print(f"  {s:8.3f}  {relpath(ws, p)}{tag}")
        return 0
    if args.cmd == "measure":
        report = measure()
        for label, inst in report["instruments"].items():
            o, n = inst["off"], inst["on"]
            print(f"{label}: cov@10 {o['citation_coverage']['@10']} "
                  f"-> {n['citation_coverage']['@10']}, "
                  f"MRR {o['mrr_must_cite']} -> {n['mrr_must_cite']}, "
                  f"gained {[g['id'] for g in inst['gained_top10']]}, "
                  f"lost {[g['id'] for g in inst['lost_top10']]}")
        print("wrote evaluation/onehop-vote-report.{json,md}")
        return 0
    if args.cmd == "gate-check":
        out_dir = args.out_dir or str(
            ROOT.parent / ".tmp-onehop" / "gate")
        res = gate_check(out_dir)
        print(f"battery plain: {res['plain']['passed']}/"
              f"{res['plain']['total']}")
        print(f"battery voted: {res['voted']['passed']}/"
              f"{res['voted']['total']}")
        if res["voted_failures"]:
            print(f"voted failures: {res['voted_failures']}")
            for f in res["voted_failure_details"]:
                print(f"  {f['id']}: {f['detail']}")
        return 0 if res["plain"]["passed"] == res["plain"]["total"] \
            else 1
    if args.cmd == "ab-check":
        ok, problems = ab_check(args.baseline)
        if ok:
            print("A/B identical: no-arg == onehop=None"
                  + (" == pre-change baseline" if args.baseline
                     else ""))
            return 0
        for p in problems:
            print(f"MISMATCH: {p}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
