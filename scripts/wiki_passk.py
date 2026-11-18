#!/usr/bin/env python3
"""pass^k runner for the Ask evaluation (WikiCitadel v1).

Pattern: τ-bench's pass^k — **a task counts as passed only if ALL
k trials pass**. pass^1 flatters a flaky system (one lucky run);
pass^k measures the reliability a user actually experiences when
they ask the same kind of question k times.

Two trial sources:

1. **Retrieval trials (default).** Each extended-eval question is
   scored by the deterministic retrieval harness
   (``scripts/wiki_eval_extended.py``): answerable questions pass
   when the must-cite set is covered in the top-k window;
   no-answer questions pass when the top score sits below the
   abstention threshold τ. The system under test is deterministic,
   so all k trials are identical and **pass^k == pass^1 by
   construction** — the runner says so in its output rather than
   dressing the number up. Its value here is the shape: the moment
   a stochastic answerer is scored (mode 2), the same counting
   applies.

2. **Recorded answer trials (``--answers FILE``).** FILE is JSONL,
   one row per question: ``{"question_id": ..., "trials":
   [<answer record>, ...]}``. Each trial record is judged by the
   judge-calibration stub judge against the eval set's gold
   expectation for that question. This is the mode that measures a
   real answering agent's consistency.

Usage:
  python3 scripts/wiki_passk.py [--k 3] [--label NAME]
  python3 scripts/wiki_passk.py --answers trials.jsonl [--k 3]

Exit code 0. The report (with ``--label``) lands in
``evaluation/results/passk-<label>.json``. Stdlib only.
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evaluation" / "extended-questions.jsonl"
RESULTS_DIR = ROOT / "evaluation" / "results"
JC_DIR = ROOT / "evaluation" / "judge-calibration"
WIKI = ROOT / "wiki"


def load_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def passk_counts(outcomes: dict) -> dict:
    """pass^k counting over per-question trial outcomes.

    *outcomes*: ``{question_id: [bool, ...]}`` — one bool per
    trial. A question passes pass^k iff it has at least k trials
    and its first k trials ALL pass. ``pass1`` is the first trial
    alone, reported for contrast. Questions with fewer than k
    trials are counted under ``insufficient`` and excluded from
    the pass^k rate (never silently passed or failed).
    """
    per_question = {}
    for qid, trials in outcomes.items():
        trials = list(trials)
        per_question[qid] = {
            "trials": len(trials),
            "passes": sum(1 for t in trials if t),
            "pass1": bool(trials and trials[0]),
            "passk": None,  # filled by summarise for a given k
            "_trials": trials,
        }
    return per_question


def summarise(outcomes: dict, k: int) -> dict:
    """Aggregate pass^k / pass^1 rates for *outcomes* at *k*."""
    per = passk_counts(outcomes)
    scored = 0
    passk = 0
    pass1 = 0
    insufficient = []
    for qid, row in per.items():
        if row["trials"] < k:
            insufficient.append(qid)
            row["passk"] = None
            continue
        row["passk"] = all(row["_trials"][:k])
        scored += 1
        passk += 1 if row["passk"] else 0
        pass1 += 1 if row["pass1"] else 0
    return {
        "k": k,
        "questions": len(per),
        "scored": scored,
        "insufficient": insufficient,
        "passk": passk,
        "pass1": pass1,
        "passk_rate": round(passk / scored, 4) if scored else None,
        "pass1_rate": round(pass1 / scored, 4) if scored else None,
        "per_question": {
            qid: {key: row[key]
                  for key in ("trials", "passes", "pass1", "passk")}
            for qid, row in per.items()
        },
    }


def retrieval_outcomes(questions, k):
    """Deterministic retrieval trials: the same trial, k times.

    Reuses ``wiki_eval_extended``'s own machinery (its ``ws``
    engine, ``rank_with_scores``, ``score_answerable``): an
    answerable question passes when ALL its must-cite pages land
    in the top-10 window; a no-answer question passes when the
    top-1 score sits below the baseline abstention threshold τ.
    The harness has no randomness, so each question's k trials are
    k copies of one outcome — the degeneracy is stated in the
    report, not hidden.
    """
    ev = load_module("wiki_eval_extended",
                     ROOT / "scripts" / "wiki_eval_extended.py")
    ws = ev.ws
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    threshold = None
    baseline_path = ROOT / "evaluation" / "extended-baseline.json"
    if baseline_path.is_file():
        threshold = json.loads(
            baseline_path.read_text(encoding="utf-8")
        ).get("abstain_threshold")
    outcomes = {}
    for q in questions:
        ranked = ev.rank_with_scores(
            "hybrid", ws.tokenize(q["question"]), docs, adj
        )
        if q.get("expected_abstain"):
            top1 = ranked[0][0] if ranked else 0.0
            passed = threshold is not None and top1 < threshold
        else:
            row = ev.score_answerable(q, ranked, 10)
            passed = bool(row["all_must_in_topk"])
        outcomes[q["id"]] = [passed] * k
    return outcomes


def answers_outcomes(rows, questions, k):
    """Judge recorded answer trials with the stub judge."""
    stub = load_module("stub_judge", JC_DIR / "stub_judge.py")
    by_id = {q["id"]: q for q in questions}
    outcomes = {}
    skipped = []
    for row in rows:
        q = by_id.get(row.get("question_id"))
        if q is None:
            skipped.append(row.get("question_id"))
            continue
        expected = {
            "expected_abstain": bool(q.get("expected_abstain")),
            "key_facts": list(q.get("key_facts") or []),
            "forbidden_claims": list(q.get("forbidden_claims") or []),
            "must_cite": [
                p[len("wiki/"):-len(".md")]
                if p.startswith("wiki/") and p.endswith(".md") else p
                for p in q.get("must_cite") or []
            ],
        }
        verdicts = [
            stub.judge(trial, expected, WIKI)["verdict"] == "accept"
            for trial in row.get("trials") or []
        ]
        outcomes[row["question_id"]] = verdicts
    return outcomes, skipped


def main(argv):
    ap = argparse.ArgumentParser(
        description="pass^k runner for the Ask evaluation."
    )
    ap.add_argument("--k", type=int, default=3,
                    help="trials per question (default 3)")
    ap.add_argument("--answers", default=None,
                    help="JSONL of recorded answer trials to judge "
                         "instead of running retrieval trials")
    ap.add_argument("--label", default=None,
                    help="write evaluation/results/passk-<label>.json")
    args = ap.parse_args(argv[1:])

    questions = load_jsonl(QUESTIONS)
    if args.answers:
        rows = load_jsonl(args.answers)
        outcomes, skipped = answers_outcomes(rows, questions, args.k)
        mode = "recorded answer trials, stub-judged"
        note = ("Trials judged by the deterministic stub judge "
                "(evaluation/judge-calibration/stub_judge.py) — no "
                "LLM judge exists yet.")
    else:
        outcomes = retrieval_outcomes(questions, args.k)
        skipped = []
        mode = "deterministic retrieval trials"
        note = ("The retrieval harness is deterministic: every "
                "question's k trials are identical, so pass^k == "
                "pass^1 by construction. The counting shape is "
                "what this mode proves; stochastic answerers are "
                "measured via --answers.")

    summary = summarise(outcomes, args.k)
    report = {
        "schema": "passk-report/1",
        "generated_at": datetime.now().astimezone()
                        .isoformat(timespec="seconds"),
        "mode": mode,
        "note": note,
        "skipped_unknown_questions": skipped,
        **summary,
    }
    if args.label:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / ("passk-%s.json" % args.label)
        out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["_written_to"] = str(out.relative_to(ROOT))
    print(json.dumps(
        {key: report[key] for key in
         ("mode", "k", "questions", "scored", "passk", "pass1",
          "passk_rate", "pass1_rate", "insufficient",
          "skipped_unknown_questions", "_written_to")
         if key in report},
        indent=2,
    ))
    print("note:", note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
