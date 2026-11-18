#!/usr/bin/env python3
"""Eval trend report (Marathon R2 lane B2).

Reads every dated result file in evaluation/results/ and emits a
trend view, oldest -> newest:

  - a Markdown report: one row per usable run (date, label, corpus
    page count, coverage@10, MRR), plus a GAPS section naming every
    run that could not be plotted and exactly which field it lacks;
  - an SVG line chart (stdlib only, hand-built): coverage@10 and
    MRR plotted against corpus page count.

Deterministic: files are processed in filename order, runs are
sorted by (generated_at, label, source file), and the SVG geometry
is a pure function of the runs — the same inputs always produce
byte-identical outputs.

A run is plottable when it carries a date (generated_at, or a
YYYY-MM-DD in its filename), a corpus page count (corpus_docs, or
environment.corpus_docs in a reproducible pack), coverage@10 and
MRR. Reproducible packs contribute their FIRST engine
alphabetically per file (the pack is one dated observation; the
per-engine detail lives in wiki_memscore.py's per-engine triples).
Runs missing any field are listed as gaps — never dropped silently
and never plotted with an invented value.

Usage:
  python3 scripts/wiki_eval_trend.py [--results-dir DIR]
          [--out-md FILE] [--out-svg FILE]
Defaults: --results-dir evaluation/results,
--out-md evaluation/trend-report.md, --out-svg evaluation/trend-chart.svg.
Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evaluation" / "results"
DATE_IN_NAME = re.compile(r"(20\d\d-\d\d-\d\d)")


def _metrics(data):
    """(coverage@10, mrr) from a run dict or one engine pack."""
    agg = data.get("aggregates")
    if isinstance(agg, dict):
        cov = agg.get("citation_coverage")
        c10 = cov.get("@10") if isinstance(cov, dict) else None
        mrr = agg.get("mrr_must_cite")
        if isinstance(c10, (int, float)) and isinstance(mrr, (int, float)):
            return c10, mrr
    cov = data.get("citation_coverage")
    if isinstance(cov, dict) and isinstance(data.get("mrr_must_cite"), (int, float)):
        c10 = cov.get("@10")
        if isinstance(c10, (int, float)):
            return c10, data["mrr_must_cite"]
    return None, None


def _one_run(data, source):
    """(run, gap_reason): exactly one of the two is not None."""
    packs = data.get("results")
    if isinstance(packs, dict) and packs:
        engine = sorted(packs)[0]
        pack = packs[engine]
        env = data.get("environment") or {}
        merged = dict(pack)
        merged.setdefault("label", f"{data.get('label', source)}/{engine}")
        merged.setdefault("generated_at", data.get("generated_at"))
        merged.setdefault("corpus_docs", env.get("corpus_docs"))
        return _one_run(merged, source)
    date = None
    generated = data.get("generated_at") or data.get("recorded_at")
    if isinstance(generated, str) and len(generated) >= 10:
        date = generated[:10]
    if date is None:
        m = DATE_IN_NAME.search(source)
        if m:
            date = m.group(1)
    if date is None:
        return None, "no date (no generated_at, no date in filename)"
    docs = data.get("corpus_docs")
    if not isinstance(docs, (int, float)):
        return None, "no corpus page count (corpus_docs)"
    c10, mrr = _metrics(data)
    if c10 is None:
        return None, "no coverage@10"
    if mrr is None:
        return None, "no MRR (mrr_must_cite)"
    return {
        "date": date,
        "label": data.get("label") or Path(source).stem,
        "source": source,
        "corpus_docs": int(docs),
        "coverage10": c10,
        "mrr": mrr,
    }, None


def collect(results_dir):
    """(runs, gaps) from a results directory, deterministically
    ordered: runs oldest -> newest by (date, label, source); gaps
    in filename order."""
    runs, gaps = [], []
    for path in sorted(Path(results_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            gaps.append({"source": path.name,
                         "reason": f"unreadable JSON ({exc.__class__.__name__})"})
            continue
        run, reason = _one_run(data, path.name)
        if run is not None:
            runs.append(run)
        else:
            gaps.append({"source": path.name, "reason": reason})
    runs.sort(key=lambda r: (r["date"], r["label"], r["source"]))
    return runs, gaps


def render_markdown(runs, gaps):
    lines = [
        "# Eval trend — coverage@10 / MRR vs corpus size",
        "",
        "Oldest -> newest. Runs whose files lack a date, a corpus "
        "page count, coverage@10 or MRR are listed under Gaps, "
        "never dropped silently and never plotted with an "
        "invented value.",
        "",
        "| date | run | corpus pages | coverage@10 | MRR | source |",
        "|---|---|---|---|---|---|",
    ]
    for r in runs:
        lines.append(
            f"| {r['date']} | {r['label']} | {r['corpus_docs']} | "
            f"{r['coverage10']:.4f} | {r['mrr']:.4f} | {r['source']} |")
    lines += ["", "## Gaps", ""]
    if gaps:
        for g in gaps:
            lines.append(f"- {g['source']} — {g['reason']}")
    else:
        lines.append("None — every result file was plottable.")
    return "\n".join(lines) + "\n"


# --- SVG (stdlib only; fixed geometry so output is deterministic) ---
_W, _H = 640, 360
_LEFT, _RIGHT, _TOP, _BOTTOM = 56, 16, 24, 44


def _points(runs, key, xmin, xmax):
    iw = _W - _LEFT - _RIGHT
    ih = _H - _TOP - _BOTTOM
    span = (xmax - xmin) or 1
    pts = []
    for r in runs:
        x = _LEFT + (r["corpus_docs"] - xmin) / span * iw
        y = _TOP + (1.0 - r[key]) * ih
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def render_svg(runs):
    """SVG line chart: coverage@10 (steel) and MRR (rust) vs corpus
    page count. Pure function of runs: same input, same bytes."""
    if runs:
        xmin = min(r["corpus_docs"] for r in runs)
        xmax = max(r["corpus_docs"] for r in runs)
    else:
        xmin, xmax = 0, 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" '
        f'height="{_H}" viewBox="0 0 {_W} {_H}">',
        "<title>Eval trend: coverage@10 / MRR vs corpus pages</title>",
        f'<rect x="0" y="0" width="{_W}" height="{_H}" fill="white"/>',
    ]
    # y gridlines at 0.0 / 0.5 / 1.0
    ih = _H - _TOP - _BOTTOM
    for frac in (0.0, 0.5, 1.0):
        y = _TOP + (1.0 - frac) * ih
        parts.append(
            f'<line x1="{_LEFT}" y1="{y:.1f}" x2="{_W - _RIGHT}" '
            f'y2="{y:.1f}" stroke="#cccccc" stroke-width="1"/>')
        parts.append(
            f'<text x="{_LEFT - 6}" y="{y + 4:.1f}" font-size="10" '
            f'text-anchor="end">{frac:.1f}</text>')
    parts.append(
        f'<text x="{_LEFT}" y="{_H - 8}" font-size="11">'
        f"corpus pages ({xmin}–{xmax})</text>")
    parts.append(
        '<text x="60" y="14" font-size="11" fill="#3366aa">'
        "— coverage@10</text>")
    parts.append(
        '<text x="180" y="14" font-size="11" fill="#bb4422">'
        "— MRR</text>")
    if runs:
        for key, colour in (("coverage10", "#3366aa"), ("mrr", "#bb4422")):
            pts = _points(runs, key, xmin, xmax)
            if len(runs) > 1:
                parts.append(
                    f'<polyline points="{pts}" fill="none" '
                    f'stroke="{colour}" stroke-width="2"/>')
            for p in pts.split():
                x, y = p.split(",")
                parts.append(
                    f'<circle cx="{x}" cy="{y}" r="3" fill="{colour}"/>')
    else:
        parts.append(
            f'<text x="{_LEFT}" y="{_TOP + 40}" font-size="12">'
            "No plottable runs.</text>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--out-md", default=str(ROOT / "evaluation" / "trend-report.md"))
    ap.add_argument("--out-svg", default=str(ROOT / "evaluation" / "trend-chart.svg"))
    args = ap.parse_args(argv)
    runs, gaps = collect(args.results_dir)
    Path(args.out_md).write_text(render_markdown(runs, gaps), encoding="utf-8")
    Path(args.out_svg).write_text(render_svg(runs), encoding="utf-8")
    print(f"plottable runs: {len(runs)}  gaps: {len(gaps)}")
    for g in gaps:
        print(f"  gap: {g['source']} — {g['reason']}")
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_svg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
