#!/usr/bin/env python3
"""Repeat/loop detector over eval outputs (Marathon Round 3,
lane TA2; round-2 research addition — OpenCompass's 2026
repeat-analysis tools, Apache-2.0, technique re-implemented).

Accuracy scores do not see a model stuck in a loop: an answer
that repeats one sentence forty times can still contain the
key facts. This checker scans eval OUTPUTS for the two loop
signatures and reports them as a standard quality signal
alongside the accuracy scores:

  intra-answer repetition   within one answer, the fraction of
    word n-grams (default n=4) that are repeats of an earlier
    n-gram, plus repeated whole sentences. A high ratio on a
    non-trivial answer is the classic degeneration loop.
  identical-answer clusters the same normalised answer text
    returned for DIFFERENT questions — the model (or the
    pipeline) emitting one canned answer regardless of input.
    Empty answers and declared abstentions are excluded: an
    honest "not recorded" repeated across no-answer questions
    is correct behaviour, not a loop.

Inputs (either):
  --answers FILE    JSONL of {"id": ..., "answer": "...",
                    "abstained": bool} records; or
  RESULTS.json      an eval results file whose per_question /
                    rows carry "answer" fields (rows without an
                    answer are skipped and counted).

REPORT-ONLY: findings never fail a run. Exit 0 = scan
completed (flags or not); 2 = usage error. JSON report with
--out; the plain summary names every flagged id.

Usage:
  python3 scripts/wiki_repeat_check.py --answers answers.jsonl
  python3 scripts/wiki_repeat_check.py evaluation/results/x.json
          [--ngram N] [--repeat-threshold T] [--out FILE]

Stdlib only.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NGRAM = 4
DEFAULT_REPEAT_THRESHOLD = 0.30
MIN_TOKENS = 12


def tokens(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def ngram_repeat_ratio(toks, n):
    """Fraction of n-gram occurrences that repeat an earlier
    n-gram. 0.0 for answers shorter than the n-gram window."""
    if len(toks) < n + 1:
        return 0.0
    grams = [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    seen, repeats = set(), 0
    for g in grams:
        if g in seen:
            repeats += 1
        else:
            seen.add(g)
    return repeats / len(grams)


def repeated_sentences(text):
    """Sentences occurring more than once, with counts."""
    parts = [s.strip() for s in re.split(r"[.!?]+", text or "")
             if len(s.strip()) >= 20]
    counts = Counter(" ".join(p.lower().split()) for p in parts)
    return {s: c for s, c in counts.items() if c > 1}


def normalise_answer(text):
    return " ".join(tokens(text))


def analyse(records, n=DEFAULT_NGRAM,
            threshold=DEFAULT_REPEAT_THRESHOLD):
    """records: [{id, answer, abstained}]. Returns the report."""
    rows, usable = [], 0
    clusters = defaultdict(list)
    for rec in records:
        answer = rec.get("answer") or ""
        abstained = bool(rec.get("abstained"))
        toks = tokens(answer)
        if not answer.strip():
            rows.append({"id": rec.get("id"), "skipped":
                         "empty answer"})
            continue
        usable += 1
        ratio = ngram_repeat_ratio(toks, n)
        reps = repeated_sentences(answer)
        flags = []
        if len(toks) >= MIN_TOKENS and ratio >= threshold:
            flags.append(f"n-gram repeat ratio {ratio:.2f} "
                         f">= {threshold}")
        if reps:
            flags.append(f"{sum(reps.values())} repeated "
                         f"sentence occurrences")
        rows.append({"id": rec.get("id"),
                     "tokens": len(toks),
                     "ngram_repeat_ratio": round(ratio, 4),
                     "repeated_sentences": reps,
                     "flags": flags})
        if not abstained:
            norm = normalise_answer(answer)
            if norm:
                clusters[norm].append(rec.get("id"))
    identical = [{"answer_preview": text[:80], "ids": ids}
                 for text, ids in clusters.items() if len(ids) > 1]
    flagged_ids = [r["id"] for r in rows if r.get("flags")]
    loop_ids = sorted({i for c in identical for i in c["ids"]})
    return {
        "records": len(records),
        "answers_scanned": usable,
        "ngram": n,
        "repeat_threshold": threshold,
        "flagged_repetition": flagged_ids,
        "identical_clusters": identical,
        "identical_answer_ids": loop_ids,
        "rows": rows,
    }


def load_records(path):
    """JSONL answers, or an eval results JSON with answer rows."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        records = []
        for line in text.splitlines():
            if line.strip():
                obj = json.loads(line)
                if obj.get("kind") != "header":
                    records.append(obj)
        return records
    data = json.loads(text)
    rows = data.get("per_question") or data.get("rows") or []
    return [{"id": r.get("id"), "answer": r.get("answer"),
             "abstained": r.get("abstained", False)}
            for r in rows]


def main(argv):
    ap = argparse.ArgumentParser(
        description="Repeat/loop detector over eval outputs "
                    "(report-only).")
    ap.add_argument("source", help="answers JSONL or results JSON")
    ap.add_argument("--ngram", type=int, default=DEFAULT_NGRAM)
    ap.add_argument("--repeat-threshold", type=float,
                    default=DEFAULT_REPEAT_THRESHOLD)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])

    if not Path(args.source).is_file():
        print(f"source missing: {args.source}", file=sys.stderr)
        return 2
    records = load_records(args.source)
    if not records:
        print("no records to scan", file=sys.stderr)
        return 2
    report = analyse(records, n=args.ngram,
                     threshold=args.repeat_threshold)
    report["source"] = args.source
    print(f"repeat/loop scan over {args.source}: "
          f"{report['answers_scanned']} answers scanned, "
          f"{len(report['flagged_repetition'])} flagged for "
          f"repetition, {len(report['identical_clusters'])} "
          f"identical-answer clusters "
          f"({len(report['identical_answer_ids'])} answers)")
    for r in report["rows"]:
        for f in r.get("flags") or []:
            print(f"  [LOOP?] {r['id']}: {f}")
    for c in report["identical_clusters"]:
        print(f"  [SAME-ANSWER] {', '.join(map(str, c['ids']))}: "
              f"{c['answer_preview']!r}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
