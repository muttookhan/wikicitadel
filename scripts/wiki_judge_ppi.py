#!/usr/bin/env python3
"""PPI-style judge-score reporting over the calibration register.

Marathon R8 lane BB (ideas board R6 deep-dive, Tier A): pattern of
ARES (Apache-2.0) / prediction-powered inference - a judge-derived
score is never reported as a bare number. Every report carries:
the estimate, a 95% confidence interval, the judge's measured
accuracy on human labels, and labelled-n (how many human labels
that accuracy and interval rest on).

Reporting ONLY: this module certifies nothing and changes no
gate; certification stays with scripts/wiki_judge_calibrate.py.

The honest-zero rule: where labelled-n is zero there are no human
labels to measure accuracy against and no rectifier to correct
the judge mean with, so the report says so plainly and emits NO
interval and NO accuracy figure - an interval manufactured from
zero labels would be a fiction.

Estimator (when labelled-n > 0): PPI rectifier form.
  estimate = mean(judge scores over all N items)
             + mean(human - judge over the n labelled items)
  var      = var(human - judge, labelled) / n
             + var(judge, all) / N
  CI       = estimate +/- 1.96 * sqrt(var)

Usage:
  python3 scripts/wiki_judge_ppi.py [--scores FILE] [--register]
--scores: JSONL rows {judge_score, human_label?} (human_label
present only on human-labelled rows). Default --register reads
the calibration register (judge-calibration/) and reports its
labelled-n honestly. Exit 0 = report produced; 2 = usage error.
Stdlib only; no network; no model calls.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JC_DIR = ROOT / "evaluation" / "judge-calibration"
HUMAN_SOURCES = {"owner", "human", "owner-labelled",
                 "owner-labeled", "human-labelled",
                 "human-labeled"}


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def ppi_report(judge_scores, labelled_pairs):
    """labelled_pairs: [(judge_score, human_label), ...]."""
    n = len(labelled_pairs)
    big_n = len(judge_scores)
    base = {"labelled_n": n, "scored_n": big_n,
            "certifies": False,
            "note": "PPI-style report only - certifies nothing, "
                    "changes no gate"}
    if big_n == 0:
        base.update(estimate=None, confidence_interval=None,
                    judge_accuracy_on_human_labels=None,
                    statement="no judge scores supplied - "
                              "nothing to estimate")
        return base
    judge_mean = _mean(judge_scores)
    if n == 0:
        base.update(
            estimate=round(judge_mean, 4),
            confidence_interval=None,
            judge_accuracy_on_human_labels=None,
            statement="labelled-n is zero: no human-labelled "
                      "examples exist, so no confidence interval "
                      "and no judge accuracy on human labels can "
                      "be reported; the estimate shown is the "
                      "uncorrected judge mean only")
        return base
    diffs = [h - j for j, h in labelled_pairs]
    estimate = judge_mean + _mean(diffs)
    var = _var(diffs) / n + _var(judge_scores) / big_n
    half = 1.96 * math.sqrt(var)
    accuracy = sum(1 for j, h in labelled_pairs
                   if (j >= 0.5) == (h >= 0.5)) / n
    base.update(
        estimate=round(estimate, 4),
        confidence_interval=[round(estimate - half, 4),
                             round(estimate + half, 4)],
        judge_accuracy_on_human_labels=round(accuracy, 4),
        statement="estimate is the judge mean corrected by the "
                  "mean rectifier over %d human-labelled items; "
                  "interval is the PPI 95%% interval" % n)
    return base


def register_report(root=None):
    """Report over the existing judge-calibration register."""
    jc = (Path(root) / "evaluation" / "judge-calibration") \
        if root else JC_DIR
    examples = []
    ex_path = jc / "labeled-examples.jsonl"
    if ex_path.is_file():
        examples = [json.loads(l) for l in
                    ex_path.read_text(
                        encoding="utf-8").splitlines() if l.strip()]
    human = [e for e in examples
             if str(e.get("label_source", "")).lower()
             in HUMAN_SOURCES or e.get("human_label") is not None]
    results = sorted((jc / "results").glob("*.json")) \
        if (jc / "results").is_dir() else []
    owner_labeled = None
    if results:
        rep = json.loads(results[-1].read_text(encoding="utf-8"))
        owner_labeled = rep.get("owner_labeled")
    labelled_n = owner_labeled if owner_labeled is not None \
        else len(human)
    return {
        "register": str(jc),
        "examples": len(examples),
        "labelled_n": labelled_n,
        "human_labelled_rows_in_set": len(human),
        "latest_results_file": results[-1].name if results
                               else None,
        "report": {
            "labelled_n": labelled_n,
            "scored_n": len(examples),
            "certifies": False,
            "estimate": None,
            "confidence_interval": None,
            "judge_accuracy_on_human_labels": None,
            "statement": "no per-item judge scores are stored "
                         "in the register and labelled-n is "
                         "zero, so no estimate, interval or "
                         "accuracy figure is emitted; run with "
                         "--scores over per-item scores for a "
                         "numeric PPI report"},

        "statement": (
            "labelled-n is zero in the calibration register: "
            "no owner/human-labelled examples exist yet, so this "
            "lane reports no interval and no accuracy figure "
            "rather than manufacturing one"
            if labelled_n == 0 else
            "human-labelled examples exist; run with --scores "
            "over per-item judge scores for the full PPI report"),
        "certifies": False,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="PPI-style judge-score report (ARES pattern).")
    ap.add_argument("--scores", default=None)
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.scores:
        rows = [json.loads(l) for l in
                Path(args.scores).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        if not rows:
            print("judge-ppi: scores file has no rows",
                  file=sys.stderr)
            return 2
        pairs = [(float(r["judge_score"]), float(r["human_label"]))
                 for r in rows if r.get("human_label") is not None]
        print(json.dumps(ppi_report(
            [float(r["judge_score"]) for r in rows], pairs),
            indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(register_report(), indent=2,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
