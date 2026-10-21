#!/usr/bin/env python3
"""Extended eval harness (WikiCitadel v1).

Scores the EXTENDED question set (evaluation/extended-questions.jsonl)
against the wiki search engine. The golden set
(evaluation/golden-questions.jsonl, 15 questions, the owner's
decision) is untouched and keeps its own runner
(scripts/wiki_benchmark.py); this set is a separate, larger
instrument built alongside it.

Classes in the extended set:
  standard    single-page factual questions;
  temporal    the answer changed over time - expected_answer is the
              CURRENT ruling and forbidden_claims carry the
              superseded answer;
  no_answer   the wiki holds no answer - the correct behaviour is
              to abstain;
  multi_page  answerable only by combining two pages (must_cite
              lists both; full hit = both in top-K).

LEADERBOARD AXES + DIRECTIONAL SLICE (Marathon R2 lane B2):
  questions may carry `axes: [...]` tags from the closed vocabulary
  (governance | safety | privacy | personalisation). Tags are
  conservative editorial metadata: untagged is a valid outcome and
  an unknown tag is reported in the result's "axes_invalid", never
  silently dropped. When any answerable question carries a valid
  tag, the report adds "by_axis" aggregates per axis. Questions
  carrying `slice: "directional"` form the DIRECTIONAL slice:
  supersession fixtures (an A form superseded by B; the expected
  answer must follow B, and forbidden_claims carry A's form). When
  any exist, the report adds "by_slice" aggregates and a printed
  directional line. Directional questions keep class "temporal"
  so the existing class aggregates include them.

The conflict slice (evaluation/conflict-questions.jsonl)
runs through this same harness with --questions: its questions
carry class "conflict" and score on the deterministic axes here;
their ISE behaviour axes (Identify / Solve / Escalate over
composed answers) are scored by scripts/wiki_conflict_score.py
against the rubric in that file's header.

DETERMINISTIC axes (scored here, no LLM in the loop):
  retrieval   citation coverage @1/@3/@5/@10, hit rate, MRR -
              the same definitions as wiki_benchmark.py;
  multi       full-hit / partial-hit rates for multi_page;
  abstention  for no_answer questions, the top-1 retrieval score:
              an answer pipeline can only abstain honestly when
              retrieval confidence is low, so the harness reports
              the score distribution and, once a threshold exists
              (evaluation/extended-baseline.json, self-calibrated at
              baseline time as the median answerable top-1 score),
              the fraction of no_answer questions under it;
  citation    whether the must-cite pages themselves carry
              provenance: non-empty frontmatter `sources`, and
              inline ^[cite:] markers.

JUDGEMENT axes (NOT scored here): whether a composed answer states
the key_facts, avoids forbidden_claims, and abstains in words on
no_answer questions. Those need composed answers and a judge; the
set carries expected_answer / key_facts / forbidden_claims fields
for that future pass, and this harness never pretends otherwise.

Usage:
  python3 scripts/wiki_eval_extended.py [--engine hybrid]
          [--label extended-latest] [--questions FILE]
          [--abstain-threshold T] [--predict]
  python3 scripts/wiki_eval_extended.py --label extended-baseline \
          --emit-baseline        # also (re)write the gate baseline

--predict is the preregistration pre-flight
(scripts/wiki_predict.py): it checks
evaluation/predictions.jsonl for an OPEN prediction under
this runner's subject key ("extended-eval") and WARNS —
prints, never blocks — when none is registered, so a run's
results are read against a prior belief, not hindsight.
Either way the report records the open prediction ids it
found ("prediction_ids"), the ids a later scoring names.

--no_context (Marathon Round 3, lane TA2; LongBench pattern,
MIT) adds the CONTROL ARM: the same questions answered with no
retrieved context at all, separating genuine context use from
parametric memory. Answers come from --no-context-answers
(a JSONL of answer records) or, without one, from the null
answerer that abstains on everything — the honest floor for a
corpus no model memorised. The report gains "no_context_arm"
(per-question rows + accuracy, abstention accuracy, and
protocol violations — a no-context answer that cites pages it
never saw) and "context_lift" (with-context hit rate minus
no-context accuracy, with the proxy caveat stated in the
report itself).

The gate baseline (evaluation/extended-baseline.json) is what the
gateway's eval gate compares future runs against; --emit-baseline
is the deliberate act that moves it. Nightly wiring (not installed;
the sweep owner's call): add a sweep step running
  python3 scripts/wiki_eval_extended.py --label extended-latest
after the lint lanes.

Results land in evaluation/results/<label>.json. Stdlib only.
"""
import argparse
import importlib.util
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evaluation" / "extended-questions.jsonl"
RESULTS_DIR = ROOT / "evaluation" / "results"
BASELINE_PATH = ROOT / "evaluation" / "extended-baseline.json"

# Regression epsilon for the gateway eval gate: a gated metric may
# fall at most this far below its baseline before promotion blocks.
EPSILON = 0.02
GATED_METRICS = ("citation_coverage@10", "hit_rate_topk",
                 "mrr_must_cite", "abstention_rate")

# Leaderboard axes (Marathon R2 lane B2): the closed vocabulary a
# question's `axes` tags may draw from.
ALLOWED_AXES = ("governance", "safety", "privacy", "personalisation")


def question_axes(q):
    """The question's VALID axis tags, in vocabulary order."""
    tags = q.get("axes") or []
    return [a for a in ALLOWED_AXES if a in tags]


def invalid_axes(questions):
    """{question id: [unknown tags]} — surfaced, never dropped."""
    out = {}
    for q in questions:
        bad = [t for t in (q.get("axes") or []) if t not in ALLOWED_AXES]
        if bad:
            out[q["id"]] = bad
    return out

def load_no_context_answers(path):
    """{id: record} from a no-context answers JSONL file.

    A record is {"id": ..., "answer": "...", "citations": [...],
    "abstained": bool} — an answer produced WITHOUT retrieved
    context (the LongBench --no_context control arm; Marathon
    Round 3, lane TA2). Records are answers a model (or the null
    answerer) gave from parametric memory alone."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") != "header":
            out[obj["id"]] = obj
    return out


def score_no_context_answer(q, record):
    """Deterministic score for one no-context answer record.

    Abstention = the record declares it, or the answer text is
    empty. An answerable question is correct when every key_fact
    appears and no forbidden_claim appears; a no_answer question
    is correct exactly when the arm abstains. A no-context answer
    carrying citations is a protocol violation (there was no
    context to cite) — reported, and the answer cannot score
    correct."""
    if record is None:
        # No record: the null answerer abstains — correct exactly
        # on the questions whose expected behaviour is abstention.
        return {"id": q["id"],
                "correct": bool(q.get("expected_abstain")),
                "abstained": True,
                "detail": "no record — the null answerer abstains"}
    answer = record.get("answer") or ""
    abstained = bool(record.get("abstained")) or not answer.strip()
    cited = bool(record.get("citations"))
    norm = " ".join(answer.split()).lower()
    if q.get("expected_abstain"):
        ok = abstained
        return {"id": q["id"], "correct": ok, "abstained": abstained,
                "cited_with_no_context": cited,
                "detail": "abstained as expected" if ok
                          else "answered a no_answer question "
                               "from parametric memory"}
    if abstained:
        return {"id": q["id"], "correct": False, "abstained": True,
                "cited_with_no_context": cited,
                "detail": "abstained on an answerable question"}
    facts_ok = all(" ".join(f.split()).lower() in norm
                   for f in q.get("key_facts") or [])
    forbidden_hit = any(" ".join(f.split()).lower() in norm
                        for f in q.get("forbidden_claims") or [])
    ok = facts_ok and not forbidden_hit and not cited
    detail = (f"key_facts_ok={facts_ok} "
              f"forbidden_hit={forbidden_hit} "
              f"cited_with_no_context={cited}")
    return {"id": q["id"], "correct": ok, "abstained": False,
            "cited_with_no_context": cited, "detail": detail}


def no_context_arm(questions, answers):
    """The control arm's aggregates over the question set.

    answers=None is the NULL answerer: it abstains on every
    question — the honest floor for a corpus whose facts are
    not in any model's parametric memory (and, for the public
    tree, are fictional by construction)."""
    rows = [score_no_context_answer(q, (answers or {}).get(q["id"]))
            for q in questions]
    ans = [r for r, q in zip(rows, questions)
           if not q.get("expected_abstain")]
    noans = [r for r, q in zip(rows, questions)
             if q.get("expected_abstain")]
    return {
        "answerer": ("supplied answers file" if answers is not None
                     else "null answerer (abstains on everything)"),
        "questions": len(rows),
        "accuracy": round(sum(1 for r in rows if r["correct"])
                          / (len(rows) or 1), 4),
        "answerable_accuracy": (round(
            sum(1 for r in ans if r["correct"]) / len(ans), 4)
            if ans else None),
        "no_answer_accuracy": (round(
            sum(1 for r in noans if r["correct"]) / len(noans), 4)
            if noans else None),
        "protocol_violations": sum(
            1 for r in rows if r.get("cited_with_no_context")),
        "rows": rows,
    }


spec = importlib.util.spec_from_file_location(
    "wiki_search", ROOT / "scripts" / "wiki_search.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)

PREDICTIONS = ROOT / "evaluation" / "predictions.jsonl"
PREDICTION_SUBJECT_KEY = "extended-eval"


def predict_preflight(register_path=PREDICTIONS,
                      subject_key=PREDICTION_SUBJECT_KEY):
    """(open prediction ids, warning-or-None) for a run.

    The preregistration check: an eval run should
    be scored against a belief filed BEFORE it ran. This is
    a warning surface only — it never blocks, and any
    problem reading the register degrades to 'none found'
    with the warning saying so.
    """
    ids = []
    try:
        pspec = importlib.util.spec_from_file_location(
            "wiki_predict", ROOT / "scripts" / "wiki_predict.py")
        wp = importlib.util.module_from_spec(pspec)
        pspec.loader.exec_module(wp)
        ids = [s["id"] for s in wp.open_predictions(
            Path(register_path), subject_key)]
    except Exception:
        ids = []
    if ids:
        return ids, None
    return ids, (f"WARNING: no open preregistered prediction "
                 f"for subject '{subject_key}' in "
                 f"evaluation/predictions.jsonl — this run's "
                 f"results will be read against hindsight. "
                 f"File one first with scripts/wiki_predict.py "
                 f"add . Warning only; the run "
                 f"proceeds.")


def load_questions(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    # A set file may open with a {"kind": "header"} line (the
    # conflict slice does — its header carries the ISE rubric);
    # header lines are metadata, not questions.
    return [r for r in rows if r.get("kind") != "header"]


def rank_with_scores(engine, terms, docs, adj):
    if engine == "bm25":
        ranked = ws.bm25_rank(terms, docs)
        return [(s, str(p.relative_to(ROOT))) for s, p, _t in ranked]
    ranked = ws.hybrid_rank(terms, docs, adj)
    return [(s, str(p.relative_to(ROOT))) for s, p, _t, _d in ranked]


def page_provenance(rel):
    """(declares_sources, has_inline_cite) for a wiki page."""
    try:
        text = (ROOT / rel).read_text(encoding="utf-8")
    except OSError:
        return (False, False)
    declares = False
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        fm = m.group(1)
        sm = re.search(r"^sources:\s*(.*)$", fm, re.M)
        if sm:
            inline = sm.group(1).strip()
            if inline and inline not in ("[]",):
                declares = True
            else:
                rest = fm[sm.end():]
                declares = bool(re.match(r"\s+-\s+\S", rest))
    return (declares, "^[cite:" in text)


def score_answerable(q, ranked, top):
    paths = [p for _s, p in ranked]
    must = set(q.get("must_cite") or [])
    accept = set(q.get("acceptable_cites") or [])
    good = must | accept
    topk = paths[:top]
    must_rank = next((i + 1 for i, p in enumerate(paths) if p in must), None)
    return {
        "id": q["id"], "class": q["class"],
        "axes": question_axes(q),
        "slice": q.get("slice"),
        "must_cite_rank": must_rank,
        "hit_in_topk": any(p in good for p in topk),
        "must_in_topk": must_rank is not None and must_rank <= top,
        "all_must_in_topk": all(any(p == m for p in topk) for m in must),
        "precision_at_k": (sum(1 for p in topk if p in good) / len(topk)
                           if topk else 0.0),
        "top1_score": ranked[0][0] if ranked else 0.0,
        "top3": topk[:3],
    }


def aggregates(rows):
    n = len(rows) or 1
    cov = {k: sum(1 for r in rows
                  if r["must_cite_rank"] is not None and r["must_cite_rank"] <= k) / n
           for k in (1, 3, 5, 10)}
    return {
        "questions": len(rows),
        "citation_coverage": {f"@{k}": round(v, 4) for k, v in cov.items()},
        "hit_rate_topk": round(sum(1 for r in rows if r["hit_in_topk"]) / n, 4),
        "mean_precision_at_k": round(sum(r["precision_at_k"] for r in rows) / n, 4),
        "mrr_must_cite": round(sum(1.0 / r["must_cite_rank"] for r in rows
                                   if r["must_cite_rank"] is not None) / n, 4),
    }


def main(argv):
    ap = argparse.ArgumentParser(description="Extended eval harness (WikiCitadel v1).")
    ap.add_argument("--engine", choices=("bm25", "hybrid"), default="hybrid")
    ap.add_argument("--label", default="extended-latest")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--abstain-threshold", type=float, default=None,
                    help="top-1 score under which a no_answer question counts "
                         "as abstainable; default: the baseline file's value")
    ap.add_argument("--emit-baseline", action="store_true",
                    help="also write evaluation/extended-baseline.json from this run")
    ap.add_argument("--predict", action="store_true",
                    help="preregistration pre-flight : warn "
                         "when no open prediction is registered for "
                         "this run; never blocks")
    ap.add_argument("--no_context", action="store_true",
                    help="also run the --no_context control arm "
                         "(LongBench pattern): the same questions "
                         "answered with NO retrieved context, so "
                         "context lift = with-context hit rate "
                         "minus no-context accuracy is measured, "
                         "not assumed")
    ap.add_argument("--no-context-answers", default=None,
                    help="JSONL of no-context answer records for "
                         "the control arm; without it the null "
                         "answerer (abstains on everything) is "
                         "the arm's floor")
    args = ap.parse_args(argv[1:])

    prediction_ids, prediction_warning = predict_preflight()
    if args.predict:
        if prediction_warning:
            print(prediction_warning)
        else:
            print(f"  preregistration: open prediction(s) "
                  f"{', '.join(prediction_ids)} registered for "
                  f"'{PREDICTION_SUBJECT_KEY}' — this run is "
                  f"scored against them.")

    questions = load_questions(args.questions)
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs) if args.engine == "hybrid" else None

    threshold = args.abstain_threshold
    if threshold is None and BASELINE_PATH.exists():
        try:
            threshold = json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get(
                "abstain_threshold")
        except (OSError, json.JSONDecodeError):
            threshold = None

    per_q, answerable_rows, noanswer_rows = [], [], []
    prov_cache = {}
    for q in questions:
        ranked = rank_with_scores(args.engine, ws.tokenize(q["question"]), docs, adj)
        if q.get("expected_abstain"):
            row = {"id": q["id"], "class": q["class"],
                   "axes": question_axes(q),
                   "slice": q.get("slice"),
                   "top1_score": ranked[0][0] if ranked else 0.0,
                   "top1_path": ranked[0][1] if ranked else None,
                   "top3": [p for _s, p in ranked[:3]]}
            noanswer_rows.append(row)
            per_q.append(row)
            continue
        row = score_answerable(q, ranked, args.top)
        prov = []
        for cite in q.get("must_cite") or []:
            if cite not in prov_cache:
                prov_cache[cite] = page_provenance(cite)
            prov.append(prov_cache[cite])
        row["must_cite_declares_sources"] = all(p[0] for p in prov) if prov else False
        row["must_cite_has_inline_cite"] = any(p[1] for p in prov) if prov else False
        answerable_rows.append(row)
        per_q.append(row)

    agg = aggregates(answerable_rows)
    by_class = {}
    for cls in ("standard", "temporal", "multi_page", "conflict"):
        rows = [r for r in answerable_rows if r["class"] == cls]
        if rows:
            by_class[cls] = aggregates(rows)
    multi_rows = [r for r in answerable_rows if r["class"] == "multi_page"]
    if multi_rows:
        by_class["multi_page"]["full_hit_rate"] = round(
            sum(1 for r in multi_rows if r["all_must_in_topk"]) / len(multi_rows), 4)
    temporal_rows = [r for r in answerable_rows if r["class"] == "temporal"]
    if temporal_rows:
        by_class["temporal"]["current_page_hit_rate"] = by_class["temporal"]["hit_rate_topk"]

    by_axis = {}
    for axis in ALLOWED_AXES:
        rows = [r for r in answerable_rows if axis in (r.get("axes") or [])]
        if rows:
            by_axis[axis] = aggregates(rows)
    by_slice = {}
    dir_rows = [r for r in answerable_rows if r.get("slice") == "directional"]
    if dir_rows:
        by_slice["directional"] = aggregates(dir_rows)
        by_slice["directional"]["current_page_hit_rate"] = (
            by_slice["directional"]["hit_rate_topk"])

    ans_top1 = [r["top1_score"] for r in answerable_rows]
    noans_top1 = [r["top1_score"] for r in noanswer_rows]
    abstention = {
        "questions": len(noanswer_rows),
        "top1_score_mean": round(statistics.mean(noans_top1), 4) if noans_top1 else None,
        "top1_score_median": round(statistics.median(noans_top1), 4) if noans_top1 else None,
        "answerable_top1_median": round(statistics.median(ans_top1), 4) if ans_top1 else None,
        "threshold": threshold,
        "abstention_rate": (round(sum(1 for s in noans_top1 if s < threshold)
                                  / len(noans_top1), 4)
                            if threshold is not None and noans_top1 else None),
    }
    citation = {
        "answerable_questions": len(answerable_rows),
        "source_declaration_rate": round(
            sum(1 for r in answerable_rows if r["must_cite_declares_sources"])
            / (len(answerable_rows) or 1), 4),
        "inline_cite_rate": round(
            sum(1 for r in answerable_rows if r["must_cite_has_inline_cite"])
            / (len(answerable_rows) or 1), 4),
    }
    nc_arm, context_lift = None, None
    if args.no_context:
        nc_answers = load_no_context_answers(args.no_context_answers) \
            if args.no_context_answers else None
        nc_arm = no_context_arm(questions, nc_answers)
        context_lift = {
            "with_context_hit_rate_topk": agg["hit_rate_topk"],
            "no_context_accuracy": nc_arm["accuracy"],
            "lift": round(agg["hit_rate_topk"]
                          - nc_arm["accuracy"], 4),
            "note": ("The with-context figure is this harness's "
                     "retrieval proxy (must/acceptable cite in "
                     "top-k); the no-context figure is answer "
                     "accuracy under the deterministic key-fact "
                     "score. The lift is the gap between them — "
                     "reported, never collapsed into one number."),
        }

    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        head = None
    result = {
        "label": args.label,
        "set": "extended",
        "engine": args.engine,
        "generated_at": __import__("datetime").datetime.now().astimezone()
                        .isoformat(timespec="seconds"),
        "git_head": head,
        "prediction_ids": prediction_ids,
        "corpus": "wiki/ (scope=wiki)",
        "corpus_docs": len(docs),
        "top_k": args.top,
        "aggregates": agg,
        "by_class": by_class,
        "by_axis": by_axis,
        "by_slice": by_slice,
        "axes_invalid": invalid_axes(questions),
        "abstention": abstention,
        "no_context_arm": nc_arm,
        "context_lift": context_lift,
        "citation_presence": citation,
        "judgement_axes_not_scored": (
            "Answer factuality vs key_facts, forbidden-claim avoidance on "
            "temporal questions, and verbal abstention on no_answer questions "
            "require composed answers and a judge; this harness scores "
            "retrieval, abstention headroom, and citation presence only."),
        "per_question": per_q,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{args.label}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    if args.emit_baseline:
        # Self-calibrated threshold: the median answerable top-1 score
        # of THIS run. Documented in the baseline file itself.
        tau = round(statistics.median(ans_top1), 4) if ans_top1 else None
        gated = {
            "citation_coverage@10": agg["citation_coverage"]["@10"],
            "hit_rate_topk": agg["hit_rate_topk"],
            "mrr_must_cite": agg["mrr_must_cite"],
            "abstention_rate": (round(sum(1 for s in noans_top1 if s < tau)
                                          / len(noans_top1), 4)
                                if tau is not None and noans_top1 else None),
        }
        baseline = {
            "schema": "extended-eval-baseline/1",
            "recorded_at": result["generated_at"],
            "git_head": head,
            "results_file": f"evaluation/results/{args.label}.json",
            "set": "evaluation/extended-questions.jsonl",
            "set_questions": len(questions),
            "engine": args.engine,
            "epsilon": EPSILON,
            "gated_metrics": gated,
            "abstain_threshold": tau,
            "threshold_note": ("Self-calibrated at baseline time: the median "
                               "top-1 hybrid score of the answerable questions "
                               "in this run. A no_answer question counts as "
                               "abstainable when its top-1 score falls below it."),
            "note": ("The gateway eval gate (tools/gateway/gateway/evalgate.py) "
                     "blocks promotion when the latest extended-latest report "
                     "shows any gated metric more than epsilon below these "
                     "values. Moving this baseline is a deliberate act: "
                     "re-run with --emit-baseline."),
        }
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        print(f"  wrote {BASELINE_PATH.relative_to(ROOT)} (tau={tau})")

    print(f"engine={args.engine} label={args.label} corpus={len(docs)} docs "
          f"questions={len(questions)} (answerable {len(answerable_rows)}, "
          f"no_answer {len(noanswer_rows)})")
    print(f"  citation coverage: " +
          "  ".join(f"@{k}={v:.2f}" for k, v in agg['citation_coverage'].items()))
    print(f"  hit rate @{args.top}: {agg['hit_rate_topk']:.2f}   "
          f"MRR: {agg['mrr_must_cite']:.3f}   "
          f"abstention rate: {abstention['abstention_rate']}")
    if nc_arm is not None:
        print(f"  no-context arm ({nc_arm['answerer']}): "
              f"accuracy {nc_arm['accuracy']:.2f} "
              f"(answerable {nc_arm['answerable_accuracy']}, "
              f"no_answer {nc_arm['no_answer_accuracy']}, "
              f"protocol violations "
              f"{nc_arm['protocol_violations']}) — "
              f"context lift {context_lift['lift']:+.2f}")
    print(f"  citation presence: sources {citation['source_declaration_rate']:.2f}   "
          f"inline cites {citation['inline_cite_rate']:.2f}")
    for axis, aagg in by_axis.items():
        print(f"  axis {axis}: n={aagg['questions']}  "
              f"coverage@10={aagg['citation_coverage']['@10']:.2f}  "
              f"MRR={aagg['mrr_must_cite']:.3f}")
    if by_slice:
        dagg = by_slice["directional"]
        print(f"  slice directional: n={dagg['questions']}  "
              f"coverage@10={dagg['citation_coverage']['@10']:.2f}  "
              f"current-page hit={dagg['current_page_hit_rate']:.2f}")
    bad_axes = invalid_axes(questions)
    if bad_axes:
        print(f"  WARNING: unknown axis tags ignored: {bad_axes}")
    misses = [r["id"] for r in answerable_rows if not r["must_in_topk"]]
    print(f"  must-cite misses @{args.top}: {', '.join(misses) if misses else 'none'}")
    print(f"  wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
