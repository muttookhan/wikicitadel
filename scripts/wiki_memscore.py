#!/usr/bin/env python3
"""MemScore triple reporter (Marathon R2 lane B2).

Reads bench / eval result JSON files (the shapes that already land
in evaluation/results/) and reports, PER RUN, the MemScore triple:

  accuracy       coverage@10 when the run carries it, else the
                 file's own headline metric (hit_rate_topk,
                 pass^k rate) — the metric NAME is always reported
                 alongside the value, never just a bare number;
  latencyMs      the run's latency in milliseconds, ONLY when the
                 result file itself carries a timing field;
  contextTokens  the run's context size in tokens, ONLY when the
                 result file itself carries a token field.

The three components are reported side by side and are NEVER
collapsed into a composite score: a run that is accurate but slow
(or cheap but wrong) must stay visible as exactly that. A component
the file does not carry is reported as the literal string
"not recorded" — this tool never invents, estimates, or back-fills
a latency or a token count.

Recognised shapes:
  - benchmark / extended-eval results: top-level "aggregates" with
    citation_coverage {"@10": ...} and/or "mrr_must_cite";
  - reproducible-benchmark packs ("results": {engine: pack, ...}):
    one triple per engine;
  - pass^k results: "passk_rate" is the headline accuracy;
  - scale-bench files: per-size timing rows are NOT a single run's
    latency, so latencyMs stays "not recorded" with a note saying
    why (honesty over a plausible-looking number).

Usage:
  python3 scripts/wiki_memscore.py [RESULT.json ...]
  python3 scripts/wiki_memscore.py --results-dir evaluation/results
  python3 scripts/wiki_memscore.py --json FILE...

With no file arguments, every *.json in evaluation/results/ is
read. Output is a Markdown table (or JSON with --json). Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evaluation" / "results"
NOT_RECORDED = "not recorded"

# Field names a result file may carry its latency under, in
# preference order. Values are milliseconds by convention in this
# corpus; a value found under any of these keys is reported as-is.
LATENCY_KEYS = ("latencyMs", "latency_ms", "median_ms", "p50_ms",
                "elapsed_ms", "duration_ms", "mean_ms")
TOKEN_KEYS = ("contextTokens", "context_tokens", "total_tokens",
              "tokens", "context_length")


def _first(mapping, keys):
    """First present, numeric value among keys in mapping (or None)."""
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        val = mapping.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return val
    return None


def _latency(data):
    """(latencyMs-or-None, note) from a run dict, top level + timing."""
    val = _first(data, LATENCY_KEYS)
    if val is not None:
        return val, ""
    timing = data.get("timing")
    if isinstance(timing, dict):
        val = _first(timing, LATENCY_KEYS)
        if val is not None:
            return val, ""
    if data.get("kind") == "scale-bench" and data.get("rows"):
        return None, ("scale-bench rows carry per-size median_ms, "
                      "not a single run latency")
    return None, ""


def _tokens(data):
    val = _first(data, TOKEN_KEYS)
    if val is not None:
        return val
    for holder in ("usage", "context"):
        sub = data.get(holder)
        if isinstance(sub, dict):
            val = _first(sub, TOKEN_KEYS)
            if val is not None:
                return val
    return None


def _accuracy(data):
    """(value-or-None, metric-name) — coverage@10 first, then the
    file's own headline metric, named either way."""
    agg = data.get("aggregates")
    if isinstance(agg, dict):
        cov = agg.get("citation_coverage")
        if isinstance(cov, dict) and isinstance(cov.get("@10"), (int, float)):
            return cov["@10"], "coverage@10"
        if isinstance(agg.get("citation_coverage@10"), (int, float)):
            return agg["citation_coverage@10"], "coverage@10"
        if isinstance(agg.get("hit_rate_topk"), (int, float)):
            return agg["hit_rate_topk"], "hit_rate_topk (headline)"
    cov = data.get("citation_coverage")
    if isinstance(cov, dict) and isinstance(cov.get("@10"), (int, float)):
        return cov["@10"], "coverage@10"
    if isinstance(data.get("passk_rate"), (int, float)):
        return data["passk_rate"], "passk_rate (headline)"
    if isinstance(data.get("hit_rate_topk"), (int, float)):
        return data["hit_rate_topk"], "hit_rate_topk (headline)"
    return None, ""


def extract_runs(data, source=""):
    """MemScore triples for one parsed result file: a list of dicts
    {label, source, accuracy, accuracy_metric, latencyMs,
    contextTokens, notes}. A reproducible pack yields one triple per
    engine; every other shape yields exactly one. The triple is
    never collapsed — no composite key is ever produced."""
    label = data.get("label") or data.get("kind") or Path(source).stem
    packs = data.get("results")
    if isinstance(packs, dict) and packs and all(
            isinstance(v, dict) for v in packs.values()):
        return [extract_runs({**v, "label": f"{label}/{engine}"},
                             source)[0]
                for engine, v in sorted(packs.items())]
    accuracy, metric = _accuracy(data)
    latency, note = _latency(data)
    run = {
        "label": label,
        "source": source,
        "accuracy": accuracy,
        "accuracy_metric": metric,
        "latencyMs": latency,
        "contextTokens": _tokens(data),
    }
    if note:
        run["notes"] = note
    return [run]


def memscore(data, source=""):
    """The single-run convenience form of extract_runs."""
    return extract_runs(data, source)[0]


def _fmt(value):
    return NOT_RECORDED if value is None else f"{value:g}"


def render_markdown(runs):
    lines = [
        "# MemScore triples",
        "",
        "One row per run. Accuracy, latency and context are reported "
        "side by side and never collapsed into a composite; a "
        "component the result file does not carry is shown as "
        f"\"{NOT_RECORDED}\", never invented.",
        "",
        "| run | accuracy | latencyMs | contextTokens | source |",
        "|---|---|---|---|---|",
    ]
    for r in runs:
        acc = NOT_RECORDED if r["accuracy"] is None else (
            f"{r['accuracy']:g} ({r['accuracy_metric']})")
        lines.append(
            f"| {r['label']} | {acc} | {_fmt(r['latencyMs'])} | "
            f"{_fmt(r['contextTokens'])} | {r['source']} |")
        if r.get("notes"):
            lines.append(f"|  | note: {r['notes']} |  |  |  |")
    return "\n".join(lines) + "\n"


def load_runs(paths):
    runs = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        runs.extend(extract_runs(data, Path(path).name))
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="result JSON files")
    ap.add_argument("--results-dir", default=None,
                    help="read every *.json in this directory instead")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of the Markdown table")
    args = ap.parse_args(argv)
    if args.results_dir:
        paths = sorted(Path(args.results_dir).glob("*.json"))
    elif args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = sorted(RESULTS_DIR.glob("*.json"))
    runs = load_runs(paths)
    if args.json:
        print(json.dumps(runs, indent=2))
    else:
        print(render_markdown(runs), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
