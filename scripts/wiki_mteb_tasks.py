#!/usr/bin/env python3
"""wiki_mteb_tasks.py — MTEB-style task definitions for the
benchmark pack (Marathon Round 6, lane BA, item 3).

Pattern: MTEB / MMTEB (embeddings-benchmark/mteb,
Apache-2.0) — the field's standard task vocabulary for
embedding/retrieval benchmarks. Used here as DATA ONLY: no
MTEB code or dependency is imported, no dataset is
downloaded or redistributed. The register
(evaluation/mteb-tasks.json) follows the pack shape set by
evaluation/beir-tasks.json (Round 5): a kind, a pattern
line, and one entry per task carrying its definition, its
reference (where the dataset lives — a pointer, never a
copy), and its licence AS RECORDED — null with a
licence_note where this register has not verified one. A
licence is never inferred or defaulted.

THE TWO TASKS. (1) A RERANKING task (SciDocsRR shape):
type "Reranking", category s2p, main_score "map" — the
second-stage half of retrieval the BEIR slice does not
exercise, because a ranker can retrieve well and still
order its top candidates badly. (2) A MULTILINGUAL
RETRIEVAL task (MrTIDIRetrieval shape) restricted to its
Japanese (jpn-Jpan) and Korean (kor-Hang) slices: type
"Retrieval", main_score "ndcg_at_10", eval_langs recorded
per language so a CJK/Hangul tokenisation or script
change is measured per language, never averaged away.
Language codes use the MTEB convention: ISO 639-3 code +
"-" + ISO 15924 script.

This tool validates and prints the register; it scores
nothing (scoring needs a dataset, and fetching one is a
separate act under its own terms). The golden set is NOT
touched in any mode.

Commands:
  list                     the registered tasks
  show <id>                one task definition as JSON
  check [--register F]     validate the register (shape,
                           unique ids, MTEB vocabulary,
                           licence discipline)

Exit codes: 0 ok, 1 check found problems, 2 usage error.
Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = ROOT / "evaluation" / "mteb-tasks.json"

REQUIRED_TASK_FIELDS = ("id", "name", "type", "category",
                        "eval_splits", "eval_langs",
                        "main_score", "metrics", "domain",
                        "reference", "definition")
TASK_TYPES = ("Retrieval", "Reranking", "Classification",
              "Clustering", "PairClassification", "STS",
              "Summarization", "BitextMining")
LANG_RE = re.compile(r"^[a-z]{3}-[A-Z][a-z]{3}$")


def load_register(path=DEFAULT_REGISTER):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_register(data):
    """Validate a register dict; returns problem strings."""
    problems = []
    if data.get("kind") != "mteb-task-register":
        problems.append(f"kind is {data.get('kind')!r}, expected "
                        f"'mteb-task-register'")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        problems.append("tasks is missing or empty")
        return problems
    seen = set()
    types = set()
    for task in tasks:
        tid = task.get("id")
        label = tid or "<no id>"
        if tid in seen:
            problems.append(f"duplicate task id: {tid}")
        seen.add(tid)
        types.add(task.get("type"))
        for field in REQUIRED_TASK_FIELDS:
            if not task.get(field):
                problems.append(f"task {label}: required field "
                                f"missing or empty: {field}")
        if task.get("type") not in TASK_TYPES:
            problems.append(f"task {label}: type "
                            f"{task.get('type')!r} is not an MTEB "
                            f"task type")
        for field in ("eval_splits", "eval_langs", "metrics"):
            if not isinstance(task.get(field), list) \
                    or not task.get(field):
                problems.append(f"task {label}: {field} must be "
                                f"a non-empty list")
        for lang in task.get("eval_langs") or []:
            if not LANG_RE.match(str(lang)):
                problems.append(f"task {label}: eval_langs entry "
                                f"{lang!r} is not in the MTEB "
                                f"form <iso639-3>-<Script> "
                                f"(e.g. jpn-Jpan)")
        # Licence discipline: recorded, or null WITH the note
        # that says why — never silently absent.
        if "licence" not in task:
            problems.append(f"task {label}: licence key absent "
                            f"(record the licence, or null with "
                            f"a licence_note)")
        elif task["licence"] is None and not task.get("licence_note"):
            problems.append(f"task {label}: licence is null and "
                            f"no licence_note says why")
        # Definitions only: no entry may point at dataset
        # files inside this tree.
        for key in ("reference", "definition"):
            val = str(task.get(key) or "")
            if val.startswith(("evaluation/", "raw/", "wiki/")):
                problems.append(f"task {label}: {key} points "
                                f"into this tree — the register "
                                f"holds definitions, not data")
    # The pack's stated coverage: one reranking task and one
    # multilingual (JA/KO) retrieval task.
    if "Reranking" not in types:
        problems.append("register carries no Reranking task")
    multi = [t for t in tasks if t.get("type") == "Retrieval"
             and {"jpn-Jpan", "kor-Hang"}
             <= set(t.get("eval_langs") or [])]
    if not multi:
        problems.append("register carries no Retrieval task "
                        "covering both jpn-Jpan and kor-Hang")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", default=str(DEFAULT_REGISTER))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sh = sub.add_parser("show")
    sh.add_argument("id")
    sub.add_parser("check")
    ns = ap.parse_args(argv)

    if ns.cmd == "check":
        problems = check_register(load_register(ns.register))
        for prob in problems:
            print(prob)
        print(f"{len(problems)} problem(s)")
        return 1 if problems else 0

    data = load_register(ns.register)
    tasks = data.get("tasks") or []
    if ns.cmd == "list":
        for task in tasks:
            print(f"{task['id']}\t{task['type']}\t"
                  f"{','.join(task['eval_langs'])}\t"
                  f"{task['name']}")
        return 0
    # show
    for task in tasks:
        if task["id"] == ns.id:
            print(json.dumps(task, indent=2, ensure_ascii=False))
            return 0
    print(f"wiki_mteb_tasks: unknown task id {ns.id!r} "
          f"(registered: {', '.join(t['id'] for t in tasks)})",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
