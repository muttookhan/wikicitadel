#!/usr/bin/env python3
"""wiki_beir_eval.py — a BEIR zero-shot eval slice (Marathon
Round 5, lane BA, item 2).

Pattern: UKPLab/beir (Apache-2.0) — a retrieval system is
judged zero-shot, on task types it was not tuned for, against
fixed public task definitions with graded relevance judgements
(qrels) and the field's standard metrics. Re-implemented here
in our own code, stdlib only; no code copied, and NO dataset
is imported, downloaded, or redistributed by this tool.

Why: the golden set (evaluation/golden-questions.jsonl) is
this wiki's own questions about its own corpus — it can only
prove a retrieval change helps HERE. A ranking change can
just as easily be an overfit to those fifteen questions. The
BEIR slice is the complement: task DEFINITIONS registered in
evaluation/beir-tasks.json for public benchmark tasks of
kinds the wiki's own set does not contain (biomedical ad-hoc
retrieval, scientific claim retrieval, financial opinion
retrieval), so a retrieval change can later be run against
unseen task types when the owner rules the datasets
themselves may be fetched. Until then the slice exists as
definitions + a harness SHAPE: the loader and metric code
below are complete and are exercised in tests against tiny
fixture data written by the tests themselves — never against
downloaded benchmark data, of which none is in this tree.

THE REGISTER (evaluation/beir-tasks.json). One entry per
task, carrying: id (the BEIR dataset name), name, task_type,
domain, language, split, homepage (where the dataset lives —
a pointer, never a copy), the BEIR file layout a fetched
copy would land in (corpus.jsonl / queries.jsonl /
qrels/<split>.tsv with the standard field names), the
metrics the task is scored on, and the dataset's licence AS
RECORDED — null when this register does not record one, with
licence_note saying why. The discipline is the source
registry's: a licence is never inferred or defaulted.

THE HARNESS. `load_task_directory(dir)` reads a BEIR-layout
directory (the layout the register declares):

    corpus.jsonl    {"_id", "title", "text"} per line
    queries.jsonl   {"_id", "text"} per line
    qrels/<split>.tsv   query-id <TAB> corpus-id <TAB> score
    (a qrels.jsonl of {"query-id", "corpus-id", "score"}
    lines is also accepted — it is the shape test fixtures
    and small local slices are cheapest in.)

`evaluate_run(run, qrels, k)` scores a run in the BEIR
results shape ({query_id: {corpus_id: score}}; lists of ids
or of (id, score) pairs are also accepted and normalised)
on nDCG@k, Recall@k and MRR@k, averaged over the queries
that carry judgements. Ranking is deterministic: score
descending, corpus-id ascending as the tie-break, so two
runs of the same scores always produce the same metrics.

The golden set is NOT touched by this tool in any mode: it
is not read, not scored, not registered here.

Commands:
  list                     the registered tasks
  show <id>                one task definition as JSON
  check [--register F]     validate the register (shape,
                           unique ids, licence discipline)
  evaluate --task-dir D --run F [--k 10]
                           score a run file against the
                           qrels in a BEIR-layout directory

Exit codes: 0 ok, 1 check/evaluate found problems, 2 usage
error. Stdlib only.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = ROOT / "evaluation" / "beir-tasks.json"

REQUIRED_TASK_FIELDS = ("id", "name", "task_type", "domain",
                        "language", "split", "homepage",
                        "layout", "metrics")
REQUIRED_LAYOUT_FIELDS = ("corpus_file", "queries_file",
                          "qrels", "corpus_id_field",
                          "query_id_field", "score_field")


# ---------------------------------------------------------------- register

def load_register(path=DEFAULT_REGISTER):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_register(data):
    """Validate a register dict; returns problem strings."""
    problems = []
    if data.get("kind") != "beir-task-register":
        problems.append(f"kind is {data.get('kind')!r}, expected "
                        f"'beir-task-register'")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        problems.append("tasks is missing or empty")
        return problems
    seen = set()
    for task in tasks:
        tid = task.get("id")
        label = tid or "<no id>"
        if tid in seen:
            problems.append(f"duplicate task id: {tid}")
        seen.add(tid)
        for field in REQUIRED_TASK_FIELDS:
            if not task.get(field):
                problems.append(f"task {label}: required field "
                                f"missing or empty: {field}")
        layout = task.get("layout") or {}
        for field in REQUIRED_LAYOUT_FIELDS:
            if not layout.get(field):
                problems.append(f"task {label}: layout field "
                                f"missing or empty: {field}")
        if not isinstance(task.get("metrics"), list) \
                or not task.get("metrics"):
            problems.append(f"task {label}: metrics must be a "
                            f"non-empty list")
        # Licence discipline: a licence is recorded, or null
        # WITH the note that says why — never silently absent.
        if "licence" not in task:
            problems.append(f"task {label}: licence key absent "
                            f"(record the licence, or null with "
                            f"a licence_note)")
        elif task["licence"] is None and not task.get("licence_note"):
            problems.append(f"task {label}: licence is null and "
                            f"no licence_note says why")
        # Definitions only: a register entry must never point
        # at dataset files inside this tree.
        for key in ("corpus_file", "queries_file", "qrels"):
            val = layout.get(key) or ""
            if val.startswith(("evaluation/", "raw/", "wiki/")):
                problems.append(f"task {label}: layout.{key} "
                                f"points into this tree ({val}) "
                                f"— the register holds "
                                f"definitions, not data")
    return problems


# ---------------------------------------------------------------- loader

def _read_jsonl(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def load_task_directory(task_dir, split="test"):
    """Load a BEIR-layout directory. Returns
    {corpus: {id: {title, text}}, queries: {id: text},
     qrels: {query_id: {corpus_id: int score}}, split}."""
    task_dir = Path(task_dir)
    corpus = {}
    for row in _read_jsonl(task_dir / "corpus.jsonl"):
        corpus[row["_id"]] = {"title": row.get("title", ""),
                              "text": row.get("text", "")}
    queries = {}
    for row in _read_jsonl(task_dir / "queries.jsonl"):
        queries[row["_id"]] = row.get("text", "")
    qrels = {}
    tsv = task_dir / "qrels" / f"{split}.tsv"
    jsonl = task_dir / "qrels.jsonl"
    if tsv.is_file():
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3 or parts[0] == "query-id":
                continue
            qrels.setdefault(parts[0], {})[parts[1]] = int(parts[2])
    elif jsonl.is_file():
        for row in _read_jsonl(jsonl):
            qrels.setdefault(row["query-id"], {})[row["corpus-id"]] \
                = int(row["score"])
    else:
        raise ValueError(f"no qrels found in {task_dir} "
                         f"(looked for {tsv} and {jsonl})")
    return {"corpus": corpus, "queries": queries,
            "qrels": qrels, "split": split}


# ---------------------------------------------------------------- metrics

def _normalise_run(run):
    """{query_id: [(corpus_id, score), ...]} ranked
    deterministically (score desc, id asc). Accepts the BEIR
    dict-of-dicts shape, id lists, and (id, score) pairs."""
    out = {}
    for qid, hits in (run or {}).items():
        pairs = []
        if isinstance(hits, dict):
            pairs = [(cid, float(s)) for cid, s in hits.items()]
        else:
            for i, hit in enumerate(hits):
                if isinstance(hit, (list, tuple)):
                    pairs.append((hit[0], float(hit[1])))
                else:
                    pairs.append((hit, float(len(hits) - i)))
        pairs.sort(key=lambda p: (-p[1], str(p[0])))
        out[qid] = pairs
    return out


def _dcg(rels):
    return sum((2 ** rel - 1) / math.log2(rank + 2)
               for rank, rel in enumerate(rels))


def evaluate_run(run, qrels, k=10):
    """Mean nDCG@k / Recall@k / MRR@k over the judged
    queries. Deterministic; stdlib only."""
    ranked = _normalise_run(run)
    ndcgs, recalls, mrrs = [], [], []
    per_query = {}
    for qid, judged in qrels.items():
        relevant = {cid for cid, s in judged.items() if s > 0}
        hits = ranked.get(qid, [])[:k]
        hit_ids = [cid for cid, _s in hits]
        gain = _dcg([judged.get(cid, 0) for cid in hit_ids])
        ideal = _dcg(sorted(judged.values(), reverse=True)[:k])
        ndcg = gain / ideal if ideal else 0.0
        recall = (len([c for c in hit_ids if c in relevant])
                  / len(relevant)) if relevant else 0.0
        mrr = 0.0
        for i, cid in enumerate(hit_ids):
            if cid in relevant:
                mrr = 1.0 / (i + 1)
                break
        ndcgs.append(ndcg)
        recalls.append(recall)
        mrrs.append(mrr)
        per_query[qid] = {"ndcg": round(ndcg, 4),
                          "recall": round(recall, 4),
                          "mrr": round(mrr, 4)}
    n = len(ndcgs) or 1
    return {
        "queries": len(ndcgs),
        "k": k,
        "ndcg": round(sum(ndcgs) / n, 4),
        "recall": round(sum(recalls) / n, 4),
        "mrr": round(sum(mrrs) / n, 4),
        "per_query": per_query,
    }


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", default=str(DEFAULT_REGISTER))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sh = sub.add_parser("show")
    sh.add_argument("id")
    sub.add_parser("check")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--task-dir", required=True)
    ev.add_argument("--run", required=True)
    ev.add_argument("--split", default="test")
    ev.add_argument("--k", type=int, default=10)
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
            print(f"{task['id']}\t{task['task_type']}\t"
                  f"{task['domain']}\t{task['name']}")
        return 0
    if ns.cmd == "show":
        for task in tasks:
            if task["id"] == ns.id:
                print(json.dumps(task, indent=2, ensure_ascii=False))
                return 0
        print(f"wiki_beir_eval: unknown task id {ns.id!r} "
              f"(registered: {', '.join(t['id'] for t in tasks)})",
              file=sys.stderr)
        return 2
    # evaluate
    task = load_task_directory(ns.task_dir, split=ns.split)
    if not task["qrels"]:
        print("wiki_beir_eval: the task directory's qrels are "
              "empty — nothing to score against", file=sys.stderr)
        return 1
    run = json.loads(Path(ns.run).read_text(encoding="utf-8"))
    result = evaluate_run(run, task["qrels"], k=ns.k)
    result["split"] = task["split"]
    result["corpus_docs"] = len(task["corpus"])
    result["queries_in_corpus"] = len(task["queries"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
