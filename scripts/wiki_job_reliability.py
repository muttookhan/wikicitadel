#!/usr/bin/env python3
"""pass^k reliability line for scheduled-job run logs.

Marathon R9 lane BA (ideas board R7 research, Tier A; pattern:
tau-bench pass^k, Yao et al. 2024): a scheduled job that
succeeded once may still be flaky; the reliability a reader
actually experiences is whether the job succeeds REPEATEDLY.
This module computes, per job, from recorded run outcomes:

  runs            total recorded runs;
  last-k          successes over the last k runs (k = 3 by
                  default), stated as successes/k considered;
  pass^k          ALL of the last k runs succeeded — the
                  tau-bench all-must-pass flag. A job with
                  fewer than k recorded runs is reported
                  "insufficient runs", never passed or failed
                  by default;
  latest          the most recent run's date and outcome;
  streak          consecutive successes ending at the latest
                  run.

The standing jobs' run records do NOT live in a single
canonical register in this wiki (sweep reports are prose in
the log; scheduler history lives outside the wiki), so this
build defines the minimal register shape as data —
evaluation/job-runs.jsonl: a header line stating the shape,
then one {"kind": "run", "job", "run_id", "started",
"outcome"} record per run, outcome in {success, failure}.
The register is seeded EMPTY-BUT-VALID (header only):
populating it from the scheduler's records is operational
use, not part of this build, and this module never writes it.

REPORTING ONLY: no job is run, gated, or altered; malformed
register lines are reported as register findings, never
silently dropped. Exit follows the wiki_corrections report
convention: 0 for a report (failures in the data are data),
2 when the register cannot be read at all.

Usage:
  python3 scripts/wiki_job_reliability.py [--register FILE]
          [--k 3] [--json]
Stdlib only. No model calls, no network, writes nothing.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = ROOT / "evaluation" / "job-runs.jsonl"
OUTCOMES = ("success", "failure")
DEFAULT_K = 3


def load_register(path):
    """(runs, findings) from a job-runs register.

    runs: [{job, run_id, started, outcome}] in file order.
    findings: one string per malformed line (bad JSON, missing
    field, unknown outcome) — reported, never dropped quietly.
    """
    runs = []
    findings = []
    text = Path(path).read_text(encoding="utf-8")
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            findings.append(f"line {n}: not JSON")
            continue
        if row.get("kind") == "header":
            continue
        if row.get("kind") != "run":
            findings.append(f"line {n}: kind "
                            f"{row.get('kind')!r} is not 'run'")
            continue
        missing = [f for f in ("job", "run_id", "started",
                               "outcome") if not row.get(f)]
        if missing:
            findings.append(f"line {n}: run missing "
                            f"{', '.join(missing)}")
            continue
        if row["outcome"] not in OUTCOMES:
            findings.append(f"line {n}: outcome "
                            f"{row['outcome']!r} not in "
                            f"{OUTCOMES}")
            continue
        runs.append({f: row[f] for f in
                     ("job", "run_id", "started", "outcome")})
    return runs, findings


def reliability(runs, k=DEFAULT_K):
    """Per-job pass^k reliability over recorded runs.

    Runs are ordered by (started, run_id) within a job — the
    register's own recorded order of events.
    """
    by_job = {}
    for run in runs:
        by_job.setdefault(run["job"], []).append(run)
    report = {}
    for job in sorted(by_job):
        ordered = sorted(by_job[job],
                         key=lambda r: (r["started"],
                                        r["run_id"]))
        window = ordered[-k:] if k > 0 else ordered
        successes = sum(1 for r in window
                        if r["outcome"] == "success")
        if len(ordered) < k:
            passk = None  # insufficient runs — stated, not scored
        else:
            passk = successes == len(window)
        streak = 0
        for r in reversed(ordered):
            if r["outcome"] == "success":
                streak += 1
            else:
                break
        report[job] = {
            "runs": len(ordered),
            "outcomes": dict(Counter(r["outcome"]
                                     for r in ordered)),
            "k": k,
            "window": len(window),
            "window_successes": successes,
            "passk": passk,
            "latest": {"started": ordered[-1]["started"],
                       "outcome": ordered[-1]["outcome"]},
            "success_streak": streak,
        }
    return report


def render_text(report, findings, k):
    lines = [f"Scheduled-job reliability — pass^{k} over the "
             f"last {k} recorded runs (all must pass)"]
    if not report:
        lines.append("No runs recorded in the register yet — "
                     "the register is seeded empty-but-valid; "
                     "populating it is operational use.")
    for job, r in sorted(report.items()):
        if r["passk"] is None:
            flag = (f"INSUFFICIENT RUNS ({r['runs']} < k={k}) "
                    f"— not scored")
        elif r["passk"]:
            flag = f"pass^{k}: PASS (all {k} passed)"
        else:
            flag = f"pass^{k}: FAIL (not all of the last {k} " \
                   f"passed)"
        lines.append(
            f"  {job}: runs={r['runs']} · last-{r['window']} "
            f"successes={r['window_successes']}/{r['window']} "
            f"· {flag} · latest {r['latest']['started']} "
            f"{r['latest']['outcome']} · streak "
            f"{r['success_streak']}")
    if findings:
        lines.append("Register findings (malformed lines, "
                     "reported not dropped):")
        for f in findings:
            lines.append(f"  - {f}")
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(
        description="pass^k reliability over scheduled-job "
                    "run records (reporting only).")
    ap.add_argument("--register", default=None)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    path = Path(args.register) if args.register \
        else DEFAULT_REGISTER
    if not path.is_file():
        print(f"job-reliability: register missing: {path}",
              file=sys.stderr)
        return 2
    if args.k < 1:
        print("job-reliability: --k must be >= 1",
              file=sys.stderr)
        return 2
    runs, findings = load_register(path)
    report = reliability(runs, k=args.k)
    if args.json:
        print(json.dumps({"k": args.k, "jobs": report,
                          "register_findings": findings},
                         indent=2, ensure_ascii=False))
    else:
        print(render_text(report, findings, args.k), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
