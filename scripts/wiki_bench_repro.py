#!/usr/bin/env python3
"""Reproducible benchmark pack (gap 13).

wiki_benchmark.py scores one engine per run. This wrapper makes a run
REPRODUCIBLE as a pack: it pins the recipe (engines, top-k, the golden
questions file by SHA-256, the corpus size, the git HEAD, the Python
version) into one manifest file, runs every engine under that recipe,
and can compare two packs — failing (exit 1) if citation coverage @10
or MRR regressed on any engine, so a pack doubles as a regression gate.

Usage:
  python3 scripts/wiki_bench_repro.py run --label nightly
  python3 scripts/wiki_bench_repro.py compare A.json B.json

Output: evaluation/results/repro-<label>.json. Stdlib only.

Marathon Round 2 (Lane G): `run` also accepts --root DIR to
score a corpus rooted elsewhere (e.g. the deterministic
synthetic corpus from scripts/wiki_bench_synth.py — that
root must carry its own copies of wiki_benchmark.py /
wiki_search.py under scripts/, exactly as a real repo does),
--questions FILE for that root's golden set, --out-dir DIR
for the pack, --git-head SHA to pin the recorded HEAD when
the root is a scratch copy with no .git of its own (the
caller states the source HEAD; it is recorded, never
invented), --corpus-kind KIND and --note TEXT, both recorded
verbatim on the pack. With none of these flags the behaviour
is exactly the original: this repo, its golden set, its git
HEAD, evaluation/results/.
"""
import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evaluation" / "results"
QUESTIONS = ROOT / "evaluation" / "golden-questions.jsonl"
ENGINES = ("bm25", "hybrid", "hindsight")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_pack(label, questions_path=None, engines=ENGINES, top=10,
             root=None, out_dir=None, git_head=None, note=None,
             corpus_kind=None):
    eff_root = Path(root).resolve() if root else ROOT
    bench_path = eff_root / "scripts" / "wiki_benchmark.py"
    if not bench_path.is_file():
        raise SystemExit(
            f"wiki_bench_repro: no benchmark runner at "
            f"{bench_path} — a --root corpus must carry the "
            f"bench scripts under its own scripts/ (as a real "
            f"repo does)")
    bench = load_module("wiki_benchmark", bench_path)
    ws = bench.ws
    if questions_path is None:
        questions_path = eff_root / "evaluation" / \
            "golden-questions.jsonl" if root else QUESTIONS
    questions = bench.load_questions(str(questions_path))
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    per_engine = {}
    for engine in engines:
        per_q = []
        for q in questions:
            paths = bench.rank_paths(engine, ws.tokenize(q["question"]),
                                     docs, adj if engine != "bm25" else None)
            per_q.append(bench.score_question(q, paths, top))
        n = len(per_q) or 1
        cov = {k: sum(1 for r in per_q if r["must_cite_rank"] is not None
                      and r["must_cite_rank"] <= k) / n for k in (1, 3, 5, 10)}
        per_engine[engine] = {
            "citation_coverage": {f"@{k}": round(v, 4) for k, v in cov.items()},
            "hit_rate_topk": round(sum(1 for r in per_q if r["hit_in_topk"]) / n, 4),
            "mrr_must_cite": round(sum(1.0 / r["must_cite_rank"] for r in per_q
                                       if r["must_cite_rank"] is not None) / n, 4),
            "per_question": per_q,
        }
    if git_head is not None:
        head = git_head
    else:
        head = subprocess.run(
            ["git", "-C", str(eff_root), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
    pack = {
        "kind": "reproducible-benchmark-pack",
        "label": label,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recipe": {
            "engines": list(engines), "top_k": top,
            "questions_file": str(Path(questions_path).relative_to(eff_root))
            if Path(questions_path).is_relative_to(eff_root) else str(questions_path),
            "questions_sha256": sha256_file(questions_path),
            "questions_count": len(questions),
        },
        "environment": {"git_head": head, "corpus_docs": len(docs),
                        "python": platform.python_version(),
                        "platform": platform.platform()},
        "results": per_engine,
    }
    if corpus_kind is not None:
        pack["corpus_kind"] = corpus_kind
    if note is not None:
        pack["note"] = note
    results_dir = Path(out_dir) if out_dir else (
        eff_root / "evaluation" / "results" if root else RESULTS_DIR)
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"repro-{label}.json"
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return pack, out


def compare(pack_a, pack_b):
    """Return (regressions, improvements) across shared engines."""
    regressions, improvements = [], []
    for engine, ra in pack_a["results"].items():
        rb = pack_b["results"].get(engine)
        if rb is None:
            continue
        for metric in ("citation_coverage", "mrr_must_cite", "hit_rate_topk"):
            if metric == "citation_coverage":
                va, vb = ra[metric]["@10"], rb[metric]["@10"]
                name = f"{engine} coverage@10"
            else:
                va, vb = ra[metric], rb[metric]
                name = f"{engine} {metric}"
            if vb < va:
                regressions.append(f"{name}: {va} -> {vb}")
            elif vb > va:
                improvements.append(f"{name}: {va} -> {vb}")
    return regressions, improvements


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--questions", default=None,
                   help="golden-questions file (default: the "
                        "effective root's evaluation/"
                        "golden-questions.jsonl)")
    r.add_argument("--root", default=None,
                   help="corpus root to score (default: this "
                        "tool's repo); must carry scripts/"
                        "wiki_benchmark.py + wiki_search.py")
    r.add_argument("--out-dir", default=None,
                   help="pack output dir (default: the "
                        "effective root's evaluation/results)")
    r.add_argument("--git-head", default=None,
                   help="record this HEAD on the pack instead "
                        "of asking git (for scratch copies of "
                        "a corpus whose HEAD the caller pins)")
    r.add_argument("--corpus-kind", default=None,
                   help="recorded verbatim as the pack's "
                        "corpus_kind (e.g. synthetic, seed, real)")
    r.add_argument("--note", default=None,
                   help="recorded verbatim as the pack's note")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        pack, out = run_pack(
            args.label, questions_path=args.questions,
            root=args.root, out_dir=args.out_dir,
            git_head=args.git_head, note=args.note,
            corpus_kind=args.corpus_kind)
        print(f"wrote {out}")
        for eng, res in pack["results"].items():
            print(f"  {eng}: coverage@10={res['citation_coverage']['@10']} "
                  f"mrr={res['mrr_must_cite']}")
        return 0
    a = json.loads(Path(args.a).read_text(encoding="utf-8"))
    b = json.loads(Path(args.b).read_text(encoding="utf-8"))
    regressions, improvements = compare(a, b)
    for line in improvements:
        print(f"improved: {line}")
    for line in regressions:
        print(f"REGRESSED: {line}")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
