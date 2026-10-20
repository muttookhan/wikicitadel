#!/usr/bin/env python3
"""Measured scale ceiling for the stdlib search door (gap 4).

Builds synthetic corpora in memory at increasing sizes and times the
BM25 ranking path of scripts/wiki_search.py over fixed probe queries.
The ceiling this supports is stated as measured fact, not marketing:
the largest corpus size whose MEDIAN probe latency stays under the
interactive threshold (250 ms) on the machine that ran the bench.
Numbers are dated and machine-specific; re-run to re-measure.

Usage: python3 scripts/wiki_scale_bench.py [--sizes 100,500,...]
Writes evaluation/results/scale-bench.json and prints a table.
Stdlib only.
"""
import argparse
import importlib.util
import json
import platform
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evaluation" / "results"
THRESHOLD_MS = 250.0
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet "
         "kilo lima mango nectar onyx prism quartz river solar tundra "
         "umbra velvet willow xenon yellow zephyr archive beacon cipher "
         "doctrine engine fabric garden harbor island jacket kernel").split()
PROBES = ("alpha archive engine", "quartz river doctrine",
          "velvet harbor kernel", "solar beacon fabric")


def load_search():
    spec = importlib.util.spec_from_file_location(
        "wiki_search", ROOT / "scripts" / "wiki_search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synthetic_docs(n, seed=20261020):
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        words = [rng.choice(WORDS) for _ in range(120)]
        # plant probe vocabulary sparsely so ranking does real work
        if i % 25 == 0:
            words[0:3] = ["alpha", "archive", "engine"]
        docs.append((Path(f"wiki/synth/page-{i:05d}.md"),
                     f"# Page {i}\n\n" + " ".join(words)))
    return docs


def bench_size(ws, n, repeats=5):
    docs = synthetic_docs(n)
    lat = []
    for _ in range(repeats):
        for probe in PROBES:
            t0 = time.perf_counter()
            ws.bm25_rank(ws.tokenize(probe), docs)
            lat.append((time.perf_counter() - t0) * 1000.0)
    return {"docs": n, "median_ms": round(statistics.median(lat), 2),
            "p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1], 2),
            "queries": len(lat)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="100,500,1000,2500,5000,10000")
    args = ap.parse_args(argv)
    ws = load_search()
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    rows = [bench_size(ws, n) for n in sizes]
    ceiling = max((r["docs"] for r in rows if r["median_ms"] < THRESHOLD_MS),
                  default=0)
    out = {"kind": "scale-bench", "engine": "bm25 (scripts/wiki_search.py)",
           "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "platform": platform.platform(), "python": platform.python_version(),
           "threshold_ms": THRESHOLD_MS, "rows": rows,
           "measured_ceiling_docs": ceiling,
           "ceiling_statement": (
               f"On this machine, median BM25 probe latency stays under "
               f"{THRESHOLD_MS:.0f} ms up to {ceiling} synthetic pages "
               f"(~120 words each). Beyond the measured sizes no claim is "
               f"made; the corpus this ships with is two orders of "
               f"magnitude smaller.")}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "scale-bench.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['docs']:>6} docs  median {r['median_ms']:>8} ms  "
              f"p95 {r['p95_ms']:>8} ms")
    print(out["ceiling_statement"])
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
