#!/usr/bin/env python3
"""Completion predicates + evidence-strength ladder for
checkpoints (Marathon R3, Tier B row TB3-1; oota pattern).

Pattern: oota's state-machine design for autonomous coding
agents (Zenn article, japan-finds find 5, via the wave
survey): a completion claim is not a status string but a
PREDICATE — a stated boolean over artefacts — and every
piece of evidence sits on a strength ladder:

    agent-assertion < generated-summary < command-output
    < repeatable-test < independent-ci < independent-review
    < artifact-digest

A checkpoint's important conditions must NOT be satisfiable
by agent self-report alone: a predicate states a minimum
rung, and evidence below it does not count, however true
the underlying condition is.

This module is a NEW neighbour of scripts/wiki_checkpoint.py
(the signed register itself is untouched). Predicates live
in their own append-only register,
evaluation/checkpoint-predicates.jsonl — one line per
checkpoint id (latest line wins):

    {"checkpoint": "cp-000007",
     "min_evidence": "repeatable-test",
     "conditions": [
       {"name": "abstention battery green",
        "artefact": "evaluation/results/abstention.json",
        "kind": "json-field", "field": "verdict",
        "equals": "PASS",
        "evidence": {"rung": "repeatable-test",
                     "ref": "scripts/wiki_abstention_check.py"}},
       {"name": "corpus root bound",
        "artefact": "evaluation/merkle-manifest.jsonl",
        "kind": "sha256", "equals": "<hex>",
        "evidence": {"rung": "artifact-digest", "ref": "..."}}
     ]}

Condition kinds: exists (artefact present), sha256 (file's
sha256 equals `equals`), json-field (JSON artefact's field
equals `equals`). A condition is MET only when its check
passes AND its evidence rung >= the predicate's
min_evidence rung. `check` evaluates every open checkpoint
(checkpoints in the register with no later "closed" line —
here: every checkpoint that has a predicate and is not
marked satisfied by a previous passing check line) and
reports the unmet ones; exit 1 when any predicate is unmet.

Usage:
  python3 scripts/wiki_checkpoint_predicates.py define CP.json
  python3 scripts/wiki_checkpoint_predicates.py check [--json]

Exit codes: check 0 = all predicates met, 1 = unmet,
2 = usage error. Stdlib only; no network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRED_REL = "evaluation/checkpoint-predicates.jsonl"
REGISTER_REL = "evaluation/checkpoints.jsonl"

LADDER = ["agent-assertion", "generated-summary", "command-output",
          "repeatable-test", "independent-ci", "independent-review",
          "artifact-digest"]


def rung(name):
    return LADDER.index(name) if name in LADDER else -1


def load_jsonl(path: Path):
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def load_predicates(root: Path):
    """checkpoint id -> predicate (latest line wins)."""
    preds = {}
    for ln in load_jsonl(root / PRED_REL):
        if ln.get("kind") in (None, "predicate") and "checkpoint" in ln:
            preds[ln["checkpoint"]] = ln
    return preds


def condition_result(root: Path, cond: dict, min_rung: int):
    """(met, detail) for one condition."""
    ev_rung = rung((cond.get("evidence") or {}).get("rung", ""))
    if ev_rung < min_rung:
        return False, (f"evidence rung "
                       f"{(cond.get('evidence') or {}).get('rung')!r} "
                       f"below required minimum")
    art = root / cond.get("artefact", "")
    kind = cond.get("kind")
    if kind == "exists":
        ok = art.is_file()
        return ok, "artefact present" if ok else "artefact missing"
    if not art.is_file():
        return False, "artefact missing"
    if kind == "sha256":
        got = hashlib.sha256(art.read_bytes()).hexdigest()
        return got == cond.get("equals"), f"sha256 {got[:12]}…"
    if kind == "json-field":
        try:
            data = json.loads(art.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return False, f"artefact not JSON: {exc}"
        got = data.get(cond.get("field"))
        return got == cond.get("equals"), f"{cond.get('field')}={got!r}"
    return False, f"unknown condition kind {kind!r}"


def evaluate(root: Path):
    """Return (report list, all_met). One entry per predicate."""
    preds = load_predicates(root)
    report = []
    all_met = True
    for cp_id in sorted(preds):
        pred = preds[cp_id]
        min_rung = rung(pred.get("min_evidence", "agent-assertion"))
        results = []
        met_all = True
        for cond in pred.get("conditions", []):
            met, detail = condition_result(root, cond, min_rung)
            results.append({"name": cond.get("name"), "met": met,
                            "detail": detail})
            met_all = met_all and met
        report.append({"checkpoint": cp_id, "met": met_all,
                       "conditions": results})
        all_met = all_met and met_all
    return report, all_met


def cmd_define(root: Path, spec_path: Path):
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"cannot read predicate spec: {exc}", file=sys.stderr)
        return 2
    if "checkpoint" not in spec or "conditions" not in spec:
        print("spec needs 'checkpoint' and 'conditions'", file=sys.stderr)
        return 2
    if rung(spec.get("min_evidence", "")) < 0:
        print(f"min_evidence must be one of {LADDER}", file=sys.stderr)
        return 2
    reg = root / PRED_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    spec = dict(spec, kind="predicate")
    with reg.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(spec, sort_keys=True) + "\n")
    print(f"predicate recorded for {spec['checkpoint']} "
          f"({len(spec['conditions'])} condition(s), "
          f"min evidence {spec['min_evidence']})")
    return 0


def cmd_check(root: Path):
    report, all_met = evaluate(root)
    print(json.dumps({"predicates": report, "all_met": all_met},
                     indent=2, sort_keys=True))
    return 0 if all_met else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("define", help="append a predicate from a JSON spec")
    pd.add_argument("spec")
    sub.add_parser("check", help="evaluate predicates over open checkpoints")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "define":
        return cmd_define(root, Path(args.spec))
    return cmd_check(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
