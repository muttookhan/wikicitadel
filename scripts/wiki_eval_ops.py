#!/usr/bin/env python3
"""Operation-level eval scoring — HaluMem (Marathon Round 3,
lane TA2; feature survey 2026-10-19, Evaluation section).

HaluMem's finding: in a memory system, errors are born at
EXTRACTION and UPDATE and only surface later at QA. Scoring a
memory system with one end-to-end QA number hides where the
error was born. (HaluMem itself is CC-BY-NC-ND — methodology
only, re-implemented here from the idea; no code or data
copied.)

This scorer takes an OPERATIONS RUN — a JSONL record of the
operations a system under test performed, each with what was
expected and what was observed — and scores CREATE, UPDATE,
DELETE and ANSWER separately, producing the per-operation
accuracy table the survey asked for. It also computes the
propagation view HaluMem motivates: an ANSWER operation that
depends on a failed CREATE/UPDATE is counted as a PROPAGATED
error (born upstream), distinct from an answer error born at
the answer step itself.

Ops-run record format (one JSON object per line; a leading
{"kind": "header"} line is metadata):

  {"id": "OP-001", "operation": "create"|"update"|"delete"|"answer",
   "subject": "wiki/<page>.md" or a question id,
   "depends_on": ["OP-000", ...]        (optional),
   "expected": {...}, "observed": {...}}

  create   expected {"present": true, "key_facts": [...]},
           observed {"present": bool, "text": "..."}
           correct: present as expected AND every key fact
           appears in the observed text.
  update   expected {"key_facts": [new facts],
                     "forbidden_facts": [superseded facts]},
           observed {"text": "..."}
           correct: every new fact present AND no superseded
           fact present (an update that keeps the old value
           beside the new one has not updated).
  delete   expected {"present": false},
           observed {"present": bool, "text": "..."}
           correct: the subject is absent afterwards (and its
           text does not resurface in the observed text).
  answer   expected {"key_facts": [...], "forbidden_facts": [...],
                     "abstain": bool},
           observed {"text": "...", "abstained": bool}
           correct: abstention matches, every key fact present,
           no forbidden fact present.

Fact matching is case-insensitive substring over whitespace-
normalised text — the same deterministic judge-lite the other
eval tools use; it scores records, not prose quality.

--from-results converts an extended-eval results file
(evaluation/results/*.json, wiki_eval_extended.py output) into
answer operations (correct = the must-cite page was hit in
top-k) so the ANSWER row can be produced from existing runs
with no ops log at all.

Usage:
  python3 scripts/wiki_eval_ops.py OPS.jsonl [--out FILE]
  python3 scripts/wiki_eval_ops.py --from-results \
      evaluation/results/extended-latest.json [--out FILE]

Exit 0 = report produced (scores are findings, not a gate);
1 = a scored operation file was empty of operations;
2 = usage error. Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPERATIONS = ("create", "update", "delete", "answer")


def normalise(text):
    return " ".join((text or "").split()).lower()


def facts_present(text, facts):
    norm = normalise(text)
    return all(normalise(f) in norm for f in facts or [])


def facts_absent(text, facts):
    norm = normalise(text)
    return all(normalise(f) not in norm for f in facts or [])


def score_create(rec):
    exp, obs = rec.get("expected") or {}, rec.get("observed") or {}
    if bool(obs.get("present")) != bool(exp.get("present", True)):
        return False, "presence mismatch"
    if exp.get("present", True) and not facts_present(
            obs.get("text"), exp.get("key_facts")):
        return False, "created content misses key facts"
    return True, "created with key facts"


def score_update(rec):
    exp, obs = rec.get("expected") or {}, rec.get("observed") or {}
    text = obs.get("text")
    if not facts_present(text, exp.get("key_facts")):
        return False, "new value missing after update"
    if not facts_absent(text, exp.get("forbidden_facts")):
        return False, "superseded value still present after update"
    return True, "new value present, superseded value gone"


def score_delete(rec):
    exp, obs = rec.get("expected") or {}, rec.get("observed") or {}
    if bool(obs.get("present")) != bool(exp.get("present", False)):
        return False, "subject still present after delete"
    if obs.get("present") and obs.get("text"):
        return False, "deleted content resurfaces"
    return True, "subject absent after delete"


def score_answer(rec):
    exp, obs = rec.get("expected") or {}, rec.get("observed") or {}
    if bool(obs.get("abstained")) != bool(exp.get("abstain", False)):
        return False, "abstention mismatch"
    if exp.get("abstain"):
        return True, "abstained as expected"
    if not facts_present(obs.get("text"), exp.get("key_facts")):
        return False, "answer misses key facts"
    if not facts_absent(obs.get("text"), exp.get("forbidden_facts")):
        return False, "answer states a forbidden (superseded) fact"
    return True, "answer carries key facts, no forbidden facts"


SCORERS = {"create": score_create, "update": score_update,
           "delete": score_delete, "answer": score_answer}


def load_ops(path):
    header, ops = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            ops.append(obj)
    return header, ops


def ops_from_results(path):
    """Extended-eval per_question rows -> answer operations."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = []
    for row in data.get("per_question") or []:
        if "must_in_topk" in row:
            ops.append({
                "id": row["id"], "operation": "answer",
                "subject": row["id"],
                "expected": {"key_facts": [], "abstain": False},
                "observed": {"text": "", "abstained": False},
                "_precomputed": bool(row["must_in_topk"]),
                "_detail": "must-cite hit in top-k"
                if row["must_in_topk"] else "must-cite missed top-k",
            })
        elif "top1_score" in row:  # no_answer rows: abstention headroom
            ops.append({
                "id": row["id"], "operation": "answer",
                "subject": row["id"],
                "expected": {"key_facts": [], "abstain": True},
                "observed": {"text": "", "abstained": True},
                "_precomputed": True,
                "_detail": "no_answer row (abstention axis scored "
                           "by the extended harness itself)",
            })
    return ops


def score_ops(ops):
    rows = []
    for rec in ops:
        op = rec.get("operation")
        if op not in SCORERS:
            rows.append({"id": rec.get("id"), "operation": op,
                         "correct": False,
                         "detail": f"unknown operation {op!r}"})
            continue
        if "_precomputed" in rec:
            ok, detail = rec["_precomputed"], rec["_detail"]
        else:
            ok, detail = SCORERS[op](rec)
        rows.append({"id": rec.get("id"), "operation": op,
                     "subject": rec.get("subject"),
                     "depends_on": rec.get("depends_on") or [],
                     "correct": bool(ok), "detail": detail})
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["operation"] == "answer" and not r["correct"]:
            upstream = [d for d in r["depends_on"]
                        if d in by_id and not by_id[d]["correct"]
                        and by_id[d]["operation"]
                        in ("create", "update")]
            r["propagated_from"] = upstream or None
        else:
            r["propagated_from"] = None
    table = {}
    for op in OPERATIONS:
        orows = [r for r in rows if r["operation"] == op]
        if orows:
            table[op] = {
                "operations": len(orows),
                "correct": sum(1 for r in orows if r["correct"]),
                "accuracy": round(
                    sum(1 for r in orows if r["correct"])
                    / len(orows), 4),
            }
    answers = [r for r in rows if r["operation"] == "answer"]
    return {
        "operations_total": len(rows),
        "correct_total": sum(1 for r in rows if r["correct"]),
        "accuracy": round(sum(1 for r in rows if r["correct"])
                          / (len(rows) or 1), 4),
        "by_operation": table,
        "answer_errors": {
            "total": sum(1 for r in answers if not r["correct"]),
            "propagated_from_create_update": sum(
                1 for r in answers
                if not r["correct"] and r["propagated_from"]),
            "born_at_answer": sum(
                1 for r in answers
                if not r["correct"] and not r["propagated_from"]),
        },
        "rows": rows,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="Operation-level eval scoring (HaluMem).")
    ap.add_argument("ops", nargs="?", default=None,
                    help="ops-run JSONL file")
    ap.add_argument("--from-results", default=None,
                    help="extended-eval results JSON to convert "
                         "into answer operations")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])

    if bool(args.ops) == bool(args.from_results):
        print("give exactly one of OPS.jsonl / --from-results",
              file=sys.stderr)
        return 2
    if args.from_results:
        ops = ops_from_results(args.from_results)
        source = args.from_results
    else:
        _header, ops = load_ops(args.ops)
        source = args.ops
    if not ops:
        print("no operations to score", file=sys.stderr)
        return 1
    report = score_ops(ops)
    report["source"] = source
    print(f"operation-level scores over {source}:")
    for op in OPERATIONS:
        t = report["by_operation"].get(op)
        if t:
            print(f"  {op:<7} {t['correct']}/{t['operations']} "
                  f"= {t['accuracy']:.2f}")
    print(f"  overall {report['correct_total']}/"
          f"{report['operations_total']} = {report['accuracy']:.2f}")
    ae = report["answer_errors"]
    print(f"  answer errors: {ae['total']} "
          f"(propagated from create/update: "
          f"{ae['propagated_from_create_update']}, "
          f"born at answer: {ae['born_at_answer']})")
    for r in report["rows"]:
        if not r["correct"]:
            extra = (f" [propagated from "
                     f"{', '.join(r['propagated_from'])}]"
                     if r.get("propagated_from") else "")
            print(f"  [FAIL] {r['id']} ({r['operation']}): "
                  f"{r['detail']}{extra}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
