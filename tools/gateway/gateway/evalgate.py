"""Eval-gated promotion (the build, owner-approved).

Promotion precondition: the wiki's extended eval must not have
regressed. The extended harness (scripts/wiki_eval_extended.py)
scores retrieval, abstention headroom and citation presence against
evaluation/extended-questions.jsonl and writes
evaluation/results/extended-latest.json; the recorded baseline is
evaluation/extended-baseline.json.

REGRESSION, concretely: any gated metric in the latest report more
than `epsilon` (baseline file, 0.02 at recording) below its
baseline value:

  citation_coverage@10   must-cite pages findable in top-10
  hit_rate_topk          a must/acceptable page in top-10
  mrr_must_cite          rank quality of the first must-cite hit
  abstention_rate        no-answer questions whose top-1 retrieval
                         score stays under the baseline threshold

ARMING RULE (the profile convention: absent machinery is inert):
  - no baseline file          -> gate not armed, promotion proceeds
                                 (the eval regime has not been set up
                                 for this wiki root);
  - baseline, but no report   -> BLOCK (the gate was armed and the
                                 evidence it needs is missing);
  - malformed baseline/report -> BLOCK (fail closed);
  - gated metric missing/null -> BLOCK for that metric.

The gate is a code-level precondition in store.promote(). It does
not replace any existing precondition (publish scope, review
separation, owner authorisation, plan-hash binding) and it cannot
be satisfied by the proposer: an owner override is a separate,
explicit, recorded act (store.write_eval_override) - the override
record and every gate block land in the eval-gate ledger.

COACHING (item 41): a block names not only the metric and the
delta but what evidence would change the verdict. check()
returns a `guidance` list parallel to `reasons`: for each
blocking reason, the concrete route back to a pass — the fresh
eval run that would clear it and the number it must reach, the
file to repair, or the owner override. A gate that only
rejects teaches contributors to route around it (the Halfaker
warning, via the wave-8 survey). Guidance is text only: the
arming rule and every verdict are exactly what they were
before it existed.
"""
from __future__ import annotations

import json
from pathlib import Path

GATED_METRICS = ("citation_coverage@10", "hit_rate_topk",
                 "mrr_must_cite", "abstention_rate")
DEFAULT_EPSILON = 0.02


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable: {exc}"


def _latest_metrics(report: dict) -> dict:
    agg = report.get("aggregates") or {}
    cov = agg.get("citation_coverage") or {}
    abst = report.get("abstention") or {}
    return {
        "citation_coverage@10": cov.get("@10"),
        "hit_rate_topk": agg.get("hit_rate_topk"),
        "mrr_must_cite": agg.get("mrr_must_cite"),
        "abstention_rate": abst.get("abstention_rate"),
    }


def check(wiki_root: Path, report_path: Path | None = None,
          baseline_path: Path | None = None) -> dict:
    """Return {armed, status, reasons, guidance, metrics, baseline,
    epsilon, report}. status: 'pass' | 'block' | 'not_armed'.
    `guidance` is parallel to `reasons`: for each block, the
    concrete evidence that would change the verdict."""
    wiki_root = Path(wiki_root)
    baseline_path = baseline_path or (wiki_root / "evaluation" / "extended-baseline.json")
    report_path = report_path or (wiki_root / "evaluation" / "results" / "extended-latest.json")

    if not baseline_path.exists():
        return {"armed": False, "status": "not_armed", "reasons": [],
                "guidance": ["to arm this gate, record a baseline at "
                             "evaluation/extended-baseline.json (a "
                             "gated_metrics object + epsilon) from a "
                             "known-good extended eval run; until then "
                             "the gate is inert by design"],
                "metrics": {}, "baseline": {}, "epsilon": DEFAULT_EPSILON,
                "report": str(report_path)}
    baseline, err = _load_json(baseline_path)
    if err or not isinstance(baseline, dict) or not isinstance(baseline.get("gated_metrics"), dict):
        return {"armed": True, "status": "block",
                "reasons": [f"eval baseline unreadable ({err or 'malformed'}); failing closed"],
                "guidance": ["to clear: repair "
                             "evaluation/extended-baseline.json so it "
                             "parses as JSON carrying a gated_metrics "
                             "object — or re-record it from a known-good "
                             "extended eval run. The gate stays blocked "
                             "while the baseline it reads cannot be "
                             "trusted; an owner eval override with a "
                             "recorded reason is the only way past a "
                             "single promotion meanwhile"],
                "metrics": {}, "baseline": {}, "epsilon": DEFAULT_EPSILON,
                "report": str(report_path)}
    base_metrics = baseline["gated_metrics"]
    epsilon = baseline.get("epsilon", DEFAULT_EPSILON)
    try:
        epsilon = float(epsilon)
    except (TypeError, ValueError):
        epsilon = DEFAULT_EPSILON

    report, err = _load_json(report_path)
    if err or not isinstance(report, dict):
        return {"armed": True, "status": "block",
                "reasons": [f"no usable extended eval report at "
                            f"{report_path.relative_to(wiki_root) if report_path.is_relative_to(wiki_root) else report_path} "
                            f"({err or 'malformed'}); run scripts/wiki_eval_extended.py"],
                "guidance": ["to clear: run "
                             "scripts/wiki_eval_extended.py so a fresh "
                             "report exists at that path — the gate "
                             "judges current evidence, and an absent or "
                             "unreadable report blocks by design. An "
                             "owner eval override with a recorded reason "
                             "is the only way past a single promotion "
                             "meanwhile"],
                "metrics": {}, "baseline": base_metrics, "epsilon": epsilon,
                "report": str(report_path)}

    latest = _latest_metrics(report)
    reasons = []
    guidance = []
    for name in GATED_METRICS:
        base = base_metrics.get(name)
        cur = latest.get(name)
        if base is None:
            continue  # metric not gated in this baseline
        if cur is None:
            reasons.append(f"{name}: missing from the latest eval report "
                           f"(baseline {base}); failing closed")
            guidance.append(
                f"{name}: to clear, produce a fresh extended eval "
                f"report whose aggregates include {name} (run "
                f"scripts/wiki_eval_extended.py) — a report that omits "
                f"a gated metric cannot pass. If {name} should no "
                f"longer be gated, that change belongs in the baseline "
                f"file, made deliberately and recorded — not in a "
                f"report that quietly drops the metric")
        elif cur < base - epsilon:
            reasons.append(f"{name}: {cur} is more than epsilon ({epsilon}) "
                           f"below baseline {base}")
            guidance.append(
                f"{name}: to clear, fix the change that moved the "
                f"metric and re-run scripts/wiki_eval_extended.py — "
                f"the gate passes when a fresh report shows {name} "
                f"at or above {round(base - epsilon, 6)} (baseline "
                f"{base} - epsilon {epsilon}). An owner eval override "
                f"with a recorded reason remains the only way past a "
                f"single promotion before that evidence exists")
    return {"armed": True,
            "status": "block" if reasons else "pass",
            "reasons": reasons, "guidance": guidance, "metrics": latest,
            "baseline": base_metrics, "epsilon": epsilon,
            "report": str(report_path),
            "report_generated_at": report.get("generated_at"),
            "report_git_head": report.get("git_head")}
