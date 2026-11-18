#!/usr/bin/env python3
"""Judge calibration runner (WikiCitadel v1).

Scores a candidate Ask-answer judge against the labelled set in
``evaluation/judge-calibration/`` and decides whether it may be
certified for use. The rule (ideas board): **any LLM
judge is calibrated on 100+ owner-labelled examples, TPR and TNR
both >= 0.8, before use; the judge prompt and model are pinned in
git** (``judge-config.json`` + the prompt file's SHA-256).

What the runner does:

- Verifies the pin: the prompt file on disk must hash to the
  config's ``prompt_sha256`` — drift is a refusal, not a warning.
- Loads the judge named by the config. ``stub-rules`` is the
  deterministic stand-in (no LLM judge exists yet); ``llm`` is
  refused outright until one is wired — the runner never pretends.
- Runs the judge over every labelled example and computes the
  confusion matrix against the labels. The positive class is
  ``accept`` (a sound answer): TPR = accepted-sound / all sound;
  TNR = rejected-unsound / all unsound.
- **Certifies only when every bar is met**: >= min_examples
  examples, >= min_owner_labeled owner-labelled examples, TPR >=
  bar, TNR >= bar. Otherwise REFUSES, naming each unmet bar. A
  refusal still writes its report — the measured rates are the
  record, certified or not.

Usage:
  python3 scripts/wiki_judge_calibrate.py [--config FILE]
          [--examples FILE] [--label NAME] [--no-write]

Exit code 0 = certified; 1 = refused. Stdlib only.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JC_DIR = ROOT / "evaluation" / "judge-calibration"
DEFAULT_CONFIG = JC_DIR / "judge-config.json"
DEFAULT_EXAMPLES = JC_DIR / "labeled-examples.jsonl"
RESULTS_DIR = JC_DIR / "results"
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


def confusion(judgements):
    """Confusion counts + TPR/TNR from (label, verdict) pairs.

    Positive class = ``accept``. judgements: list of dicts with
    ``label`` and ``verdict`` keys. Rates are None when their
    denominator is zero (no examples of that class) — a missing
    class is reported, never smoothed into a number.
    """
    tp = sum(1 for j in judgements
             if j["label"] == "accept" and j["verdict"] == "accept")
    fn = sum(1 for j in judgements
             if j["label"] == "accept" and j["verdict"] != "accept")
    tn = sum(1 for j in judgements
             if j["label"] == "reject" and j["verdict"] == "reject")
    fp = sum(1 for j in judgements
             if j["label"] == "reject" and j["verdict"] != "reject")
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "tpr": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "tnr": round(tn / (tn + fp), 4) if (tn + fp) else None,
    }


def run_calibration(config: dict, examples: list, wiki_dir=WIKI) -> dict:
    """Score the configured judge over *examples*; return the report.

    Pure with respect to its inputs (no file writes): certification
    logic lives here so tests can drive it with synthetic configs
    and example sets.
    """
    bars = config.get("certification") or {}
    judge_cfg = config.get("judge") or {}
    refusal_reasons = []

    # --- the pin ------------------------------------------------------
    prompt_rel = judge_cfg.get("prompt_file")
    prompt_path = ROOT / prompt_rel if prompt_rel else None
    pin_ok = False
    if prompt_path is not None and prompt_path.is_file():
        digest = hashlib.sha256(
            prompt_path.read_bytes()
        ).hexdigest()
        pin_ok = digest == judge_cfg.get("prompt_sha256")
    if not pin_ok:
        refusal_reasons.append(
            "prompt pin mismatch: %s does not hash to the config's "
            "prompt_sha256 (config drift — re-pin deliberately or "
            "restore the file)" % prompt_rel
        )

    # --- the judge -----------------------------------------------------
    kind = judge_cfg.get("kind")
    judge_fn = None
    if kind == "stub-rules":
        module = load_module(
            "stub_judge", ROOT / judge_cfg["module"]
        )
        judge_fn = module.judge
    elif kind == "llm":
        refusal_reasons.append(
            "judge kind 'llm': no LLM judge is wired in this repo "
            "yet — refusing rather than pretending to score one"
        )
    else:
        refusal_reasons.append("unknown judge kind: %r" % (kind,))

    # --- score ---------------------------------------------------------
    judgements = []
    by_source = {}
    owner_labeled = 0
    if judge_fn is not None:
        for ex in examples:
            outcome = judge_fn(
                ex["candidate"], ex.get("expected") or {}, wiki_dir
            )
            judgements.append(
                {
                    "id": ex["id"],
                    "label": ex["label"],
                    "verdict": outcome["verdict"],
                    "agree": outcome["verdict"] == ex["label"],
                    "reasons": outcome["reasons"],
                }
            )
            src = ex.get("label_source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
            if src == "owner":
                owner_labeled += 1
    scores = confusion(judgements)

    # --- the bars ------------------------------------------------------
    n = len(examples)
    if n < bars.get("min_examples", 100):
        refusal_reasons.append(
            "only %d labelled examples; the bar is %d"
            % (n, bars.get("min_examples", 100))
        )
    if owner_labeled < bars.get("min_owner_labeled", 100):
        refusal_reasons.append(
            "only %d owner-labelled examples; the bar is %d "
            "(the starter set is derived — owner labelling is the "
            "outstanding step)" % (owner_labeled,
                                   bars.get("min_owner_labeled", 100))
        )
    tpr_min = bars.get("tpr_min", 0.8)
    tnr_min = bars.get("tnr_min", 0.8)
    if scores["tpr"] is None or scores["tpr"] < tpr_min:
        refusal_reasons.append(
            "TPR %s is below the %s bar" % (scores["tpr"], tpr_min)
        )
    if scores["tnr"] is None or scores["tnr"] < tnr_min:
        refusal_reasons.append(
            "TNR %s is below the %s bar" % (scores["tnr"], tnr_min)
        )

    return {
        "schema": "judge-calibration-report/1",
        "generated_at": datetime.now().astimezone()
                        .isoformat(timespec="seconds"),
        "judge": {
            "kind": kind,
            "model": judge_cfg.get("model"),
            "prompt_file": prompt_rel,
            "pin_ok": pin_ok,
        },
        "examples": n,
        "owner_labeled": owner_labeled,
        "by_label_source": by_source,
        "confusion": scores,
        "bars": bars,
        "certified": not refusal_reasons,
        "refusal_reasons": refusal_reasons,
        "disagreements": [j for j in judgements if not j["agree"]],
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="Judge calibration runner."
    )
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    ap.add_argument("--label", default=None,
                    help="report file stem (default: calibration-<date>)")
    ap.add_argument("--no-write", action="store_true",
                    help="print the report but do not write it")
    args = ap.parse_args(argv[1:])

    config = json.loads(
        Path(args.config).read_text(encoding="utf-8")
    )
    examples = load_jsonl(args.examples)
    report = run_calibration(config, examples)

    if not args.no_write:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        label = args.label or (
            "calibration-" + datetime.now().strftime("%Y-%m-%d")
        )
        out = RESULTS_DIR / (label + ".json")
        out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["_written_to"] = str(out.relative_to(ROOT))

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
