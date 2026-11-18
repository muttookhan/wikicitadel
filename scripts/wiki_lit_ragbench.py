#!/usr/bin/env python3
"""LIT-RAGBench as an external abstention benchmark (Marathon
Round 3, lane TA2, row JP4; Japan harvest item 4).

LIT-RAGBench (Itai et al., LREC 2026;
https://github.com/Koki-Itai/LIT-RAGBench) evaluates the RAG
*generator* independently of retrieval, across five categories —
Integration, Reasoning, Logic, Table, and Abstention (refraining
from answering when reliable evidence cannot be established) —
with fictional entities so parametric memory cannot fake
groundedness. Its data and code are CC BY-SA 4.0: usable as an
EXTERNAL benchmark with attribution, never vendored into this
codebase (the harvest's licence posture). The real dataset is
therefore NOT copied here. What this harness ships is:

  1. a runner that consumes any set in the LIT-RAGBench item
     format (question + positive_chunk_list +
     negative_chunk_list + category + reasoning_content), and
  2. a small ORIGINAL fixture set in that format
     (evaluation/lit-ragbench-fixture.jsonl), written for this
     wiki's own pages, carrying its own licence note in its
     header — the scoped form of the row. Point --set at a
     lawfully obtained copy of the real dataset (converted to
     the same JSONL shape) and the same harness scores it.

The system under test is the wiki's deterministic abstention
decision rule — the same contract layer the abstention battery
(scripts/wiki_abstention_check.py) pins, restated for chunk
lists instead of packed evidence:

  relevance(chunk) = fraction of the question's distinct terms
                     the chunk covers (wiki_search.tokenize);
  decide           abstain when the best chunk's relevance is
                     below tau (no usable evidence), else
                     answer from the best chunk;
  score            an answer is correct when the best chunk is
                     one of the item's positive chunks and (when
                     the item carries answer_key_facts) every
                     key fact appears in that chunk; an
                     abstention is correct exactly on items
                     whose expected verdict is abstain.

Fixture integrity: every chunk passage must be verbatim in the
page it cites (whitespace-normalised), exactly as the battery's
candidates mode guards its fixtures — a rotted fixture is a
usage error (exit 2), never a scored failure.

Output: per-category table (Abstention reported separately,
as the benchmark insists) + overall, JSON with --out.
Exit 0 = every item scored as expected; 1 = at least one item
misscored (a finding); 2 = usage error. Stdlib only.

Usage:
  python3 scripts/wiki_lit_ragbench.py [--root DIR]
          [--set FILE] [--tau T] [--out FILE]
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SET = ROOT / "evaluation" / "lit-ragbench-fixture.jsonl"
DEFAULT_TAU = 0.34
CATEGORIES = ("Integration", "Reasoning", "Logic", "Table",
              "Abstention")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalise(text):
    return " ".join(text.split()).lower()


def passage_in_page(passage, page_text):
    return normalise(passage) in normalise(page_text)


def load_set(path):
    """(header, items) from a LIT-RAGBench-format JSONL file."""
    header, items = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            items.append(obj)
    return header, items


def check_fixture(items, root):
    """Every chunk passage verbatim in its cited page.
    Returns a list of rot errors (empty = fixture sound)."""
    errors = []
    cache = {}
    for item in items:
        for field in ("positive_chunk_list", "negative_chunk_list"):
            for chunk in item.get(field) or []:
                page = chunk["page"]
                if page not in cache:
                    p = root / page
                    cache[page] = p.read_text(encoding="utf-8") \
                        if p.is_file() else None
                text = cache[page]
                if text is None:
                    errors.append(
                        f"{item['id']}: chunk page {page} missing")
                elif not passage_in_page(chunk["passage"], text):
                    errors.append(
                        f"{item['id']}: passage not verbatim in "
                        f"{page} — fixture has rotted; repair the "
                        f"item, do not weaken the check")
    return errors


def relevance(question_terms, chunk_text, tokenize):
    """Fraction of the question's distinct terms the chunk
    covers — the deterministic groundedness signal."""
    if not question_terms:
        return 0.0
    chunk_terms = set(tokenize(chunk_text))
    return len(question_terms & chunk_terms) / len(question_terms)


def decide(question, chunks, tau, tokenize):
    """The wiki's abstention decision rule over a chunk list.
    Returns (verdict, best_chunk_or_None, best_relevance)."""
    qterms = set(tokenize(question))
    best, best_rel = None, 0.0
    for chunk in chunks:
        rel = relevance(qterms, chunk["passage"], tokenize)
        if rel > best_rel:
            best, best_rel = chunk, rel
    if best is None or best_rel < tau:
        return "abstain", best, best_rel
    return "answer", best, best_rel


def score_item(item, tau, tokenize):
    chunks = list(item.get("positive_chunk_list") or []) + \
        list(item.get("negative_chunk_list") or [])
    verdict, best, rel = decide(item["question"], chunks, tau,
                                tokenize)
    expected = item["expected"]
    correct = False
    detail = f"best relevance {rel:.2f} (tau {tau})"
    if expected == "abstain":
        correct = verdict == "abstain"
        detail += "; expected abstention"
    elif verdict == "answer" and best is not None:
        positive = {(c["page"], normalise(c["passage"]))
                    for c in item.get("positive_chunk_list") or []}
        grounded = (best["page"], normalise(best["passage"])) \
            in positive
        facts = item.get("answer_key_facts") or []
        chunk_norm = normalise(best["passage"])
        facts_ok = all(normalise(f) in chunk_norm for f in facts)
        correct = grounded and facts_ok
        detail += (f"; grounded={grounded} key_facts_ok={facts_ok}")
    else:
        detail += "; answered nothing usable"
    return {"id": item["id"], "category": item["category"],
            "expected": expected, "observed": verdict,
            "correct": correct, "detail": detail}


def run(items, tau, tokenize):
    rows = [score_item(it, tau, tokenize) for it in items]
    by_cat = {}
    for cat in CATEGORIES:
        crows = [r for r in rows if r["category"] == cat]
        if crows:
            by_cat[cat] = {
                "items": len(crows),
                "correct": sum(1 for r in crows if r["correct"]),
                "accuracy": round(
                    sum(1 for r in crows if r["correct"])
                    / len(crows), 4),
            }
    abst = [r for r in rows if r["category"] == "Abstention"]
    return {
        "items": len(rows),
        "correct": sum(1 for r in rows if r["correct"]),
        "accuracy": round(sum(1 for r in rows if r["correct"])
                          / (len(rows) or 1), 4),
        "by_category": by_cat,
        "abstention_recall": (round(
            sum(1 for r in abst if r["correct"]) / len(abst), 4)
            if abst else None),
        "rows": rows,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        description="LIT-RAGBench-format external abstention "
                    "benchmark harness (JP4).")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--set", default=None,
                    help="default: evaluation/lit-ragbench-fixture.jsonl")
    ap.add_argument("--tau", type=float, default=DEFAULT_TAU,
                    help="relevance below which the rule abstains")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])

    root = Path(args.root)
    set_path = Path(args.set) if args.set else \
        root / "evaluation" / "lit-ragbench-fixture.jsonl"
    if not set_path.is_file():
        print(f"benchmark set missing: {set_path}", file=sys.stderr)
        return 2
    header, items = load_set(set_path)
    if not items:
        print("benchmark set has no items", file=sys.stderr)
        return 2
    rot = check_fixture(items, root)
    if rot:
        for e in rot:
            print(f"FIXTURE ROT: {e}", file=sys.stderr)
        return 2
    ws = _load("wiki_search", root / "scripts" / "wiki_search.py")
    report = run(items, args.tau, ws.tokenize)
    report["set"] = header.get("set") if header else None
    report["tau"] = args.tau
    for r in report["rows"]:
        print(f"  [{'PASS' if r['correct'] else 'FAIL'}] {r['id']} "
              f"({r['category']}): expected {r['expected']}, "
              f"observed {r['observed']} — {r['detail']}")
    for cat, agg in report["by_category"].items():
        print(f"  category {cat}: {agg['correct']}/{agg['items']} "
              f"= {agg['accuracy']:.2f}")
    print(f"lit-ragbench: {report['correct']}/{report['items']} "
          f"correct (accuracy {report['accuracy']:.2f}, "
          f"abstention recall {report['abstention_recall']})")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return 0 if report["correct"] == report["items"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
