#!/usr/bin/env python3
"""Search-health filing (WikiCitadel v1).

The interface the search-UX lane specified (lane D find on
search analytics): periodically — sweep-shaped, filing-shaped —
the zero-result queries, the thin-result queries, and the ranking
misses, each NAMED so the owner or the refinement loop can act in
one step: a zero-result query is a work queue, not a statistic
("either your users are searching for something you don't offer,
or they can't find it"). This tool assembles that filing from the
records that exist — it runs no searches of its own:

  - the latest golden-set run artefact and the latest extended
    run (evaluation/results/), with per-class coverage/MRR and
    the named must-cite misses;
  - the conflict slice's latest run (same directory);
  - the retrieval baseline (evaluation/retrieval-baseline.json):
    zero-result probes and thin-result probes, named with their
    questions;
  - the abstention battery (evaluation/abstention-battery.jsonl):
    its search-side cases, by kind and expected verdict (the
    battery's OUTCOMES are produced on demand by
    scripts/wiki_abstention_check.py and are not persisted, so
    this filing reports composition and says so — it does not
    claim a pass it cannot point to);
  - the Ask-door log (wiki/access/qa-*.jsonl): questions asked,
    statuses, abstention and hold rates.

Each filing embeds its headline metrics as a machine-readable
comment; the next filing diffs against the previous one and
prints a DELTA section. The first filing states "no previous
filing — baseline".

The ethics, stated on the filing itself (the survey): the log is the
owner's own queries, stored locally in his own wiki, visible to
him in full, and never leaves — analytics as a mirror, not
surveillance.

Usage:
  python3 scripts/wiki_search_health.py [--root DIR]
          [--date YYYY-MM-DD] [--out FILE] [--no-write]

Exit 0 = filing computed (missing artefacts are reported as gaps,
not errors); 2 = usage error (no evaluation/ tree). Stdlib only.
"""
import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METRICS_RE = re.compile(r"<!-- search-health-metrics: (\{.*?\}) -->", re.S)


# ------------------------------------------------------------ artefacts

def _generated_key(rec):
    raw = rec.get("generated_at") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


def result_artefacts(root: Path):
    """All parseable evaluation/results/*.json with aggregates."""
    out = []
    results = root / "evaluation" / "results"
    if not results.exists():
        return out
    for p in sorted(results.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("aggregates"),
                                                dict):
            out.append((p, rec))
    return out


def pick_latest(artefacts, pred):
    cands = [(p, r) for p, r in artefacts if pred(p, r)]
    if not cands:
        return None, None
    return max(cands, key=lambda pr: _generated_key(pr[1]))


def agg_metrics(rec):
    agg = rec.get("aggregates") or {}
    cov = agg.get("citation_coverage") or {}
    return {
        "questions": agg.get("questions"),
        "coverage@10": cov.get("@10"),
        "coverage@1": cov.get("@1"),
        "hit_rate_topk": agg.get("hit_rate_topk"),
        "mrr": agg.get("mrr_must_cite"),
    }


def named_misses(rec):
    return [q.get("id") for q in rec.get("per_question") or []
            if q.get("must_in_topk") is False]


def weakest_classes(rec, limit=3):
    rows = []
    for cls, sub in (rec.get("by_class") or {}).items():
        cov = (sub.get("citation_coverage") or {}).get("@10")
        rows.append({"class": cls, "questions": sub.get("questions"),
                     "coverage@10": cov,
                     "mrr": sub.get("mrr_must_cite"),
                     "hit_rate_topk": sub.get("hit_rate_topk")})
    rows.sort(key=lambda r: (r["coverage@10"] is None,
                             r["coverage@10"] or 0, r["mrr"] or 0))
    return rows[:limit], rows


# ------------------------------------------------------------ the report

def compute_health(root: Path):
    if not (root / "evaluation").exists():
        raise SystemExit(f"usage error: {root} has no evaluation/ tree")
    artefacts = result_artefacts(root)
    golden_p, golden = pick_latest(
        artefacts, lambda _p, r: (r["aggregates"].get("questions") == 15))
    ext_path = root / "evaluation" / "results" / "extended-latest.json"
    if ext_path.exists():
        try:
            extended = json.loads(ext_path.read_text(encoding="utf-8"))
            extended_p = ext_path
        except (ValueError, OSError):
            extended_p, extended = pick_latest(
                artefacts,
                lambda _p, r: r.get("set") == "extended"
                and not str(r.get("label") or "").startswith("conflict"))
    else:
        extended_p, extended = pick_latest(
            artefacts,
            lambda _p, r: r.get("set") == "extended"
            and not str(r.get("label") or "").startswith("conflict"))
    conflict_p, conflict = pick_latest(
        artefacts,
        lambda _p, r: str(r.get("label") or "").startswith("conflict"))

    # ---- retrieval baseline: zero / thin probes
    zero_probes, thin_probes, probe_total, median_rc = [], [], 0, None
    baseline_path = root / "evaluation" / "retrieval-baseline.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        per_query = baseline.get("per_query") or {}
        probe_total = len(per_query)
        counts = [rec.get("result_count") or 0
                  for rec in per_query.values()]
        if counts:
            median_rc = statistics.median(counts)
        thin_limit = max(10, 0.1 * (median_rc or 0))
        for qid, rec in sorted(per_query.items()):
            entry = {"id": qid, "question": rec.get("question"),
                     "result_count": rec.get("result_count")}
            if (rec.get("result_count") or 0) == 0:
                zero_probes.append(entry)
            elif (rec.get("result_count") or 0) < thin_limit:
                thin_probes.append(entry)

    # ---- abstention battery, search side
    battery = {"search_cases": 0, "by_kind": {}, "expected": {}}
    battery_path = root / "evaluation" / "abstention-battery.jsonl"
    if battery_path.exists():
        for line in battery_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") != "case":
                continue
            if rec.get("mode") in ("search", "candidates"):
                battery["search_cases"] += 1
                kind = rec.get("case_kind") or "(unkind)"
                battery["by_kind"][kind] = \
                    battery["by_kind"].get(kind, 0) + 1
                verdict = rec.get("expected_verdict") or "(unset)"
                battery["expected"][verdict] = \
                    battery["expected"].get(verdict, 0) + 1

    # ---- the Ask door
    qa = {"questions": 0, "statuses": {}, "abstentions": 0, "holds": 0,
          "distinct_citations": 0}
    citations = set()
    access = root / "wiki" / "access"
    if access.exists():
        for qa_file in sorted(access.glob("qa-*.jsonl")):
            for line in qa_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                qa["questions"] += 1
                status = str(rec.get("status") or "(unset)")
                qa["statuses"][status] = qa["statuses"].get(status, 0) + 1
                if "abstain" in status:
                    qa["abstentions"] += 1
                if "hold" in status:
                    qa["holds"] += 1
                citations.update(rec.get("citations") or [])
    qa["distinct_citations"] = len(citations)
    qa["abstention_rate"] = (qa["abstentions"] / qa["questions"]
                              if qa["questions"] else None)
    qa["hold_rate"] = (qa["holds"] / qa["questions"]
                       if qa["questions"] else None)

    weak, all_classes = (weakest_classes(extended)
                         if extended else ([], []))
    metrics = {}
    def put(key, value):
        metrics[key] = (round(value, 4) if isinstance(value, float)
                        else value)
    if golden:
        gm = agg_metrics(golden)
        put("golden_coverage@10", gm["coverage@10"])
        put("golden_mrr", gm["mrr"])
        put("golden_hit_rate", gm["hit_rate_topk"])
    if extended:
        em = agg_metrics(extended)
        put("extended_coverage@10", em["coverage@10"])
        put("extended_mrr", em["mrr"])
        put("extended_hit_rate", em["hit_rate_topk"])
        put("extended_questions", em["questions"])
    if conflict:
        cm = agg_metrics(conflict)
        put("conflict_coverage@10", cm["coverage@10"])
        put("conflict_mrr", cm["mrr"])
    put("zero_result_probes", len(zero_probes))
    put("thin_result_probes", len(thin_probes))
    put("probes_total", probe_total)
    put("qa_questions", qa["questions"])
    put("qa_abstention_rate", qa["abstention_rate"])
    put("qa_hold_rate", qa["hold_rate"])
    put("battery_search_cases", battery["search_cases"])

    return {
        "golden": {"path": golden_p, "rec": golden,
                   "metrics": agg_metrics(golden) if golden else None,
                   "misses": named_misses(golden) if golden else []},
        "extended": {"path": extended_p, "rec": extended,
                     "metrics": agg_metrics(extended) if extended else None,
                     "misses": named_misses(extended) if extended else [],
                     "weakest": weak, "classes": all_classes},
        "conflict": {"path": conflict_p, "rec": conflict,
                     "metrics": agg_metrics(conflict) if conflict else None,
                     "misses": named_misses(conflict) if conflict else []},
        "zero_probes": zero_probes, "thin_probes": thin_probes,
        "probe_total": probe_total, "median_result_count": median_rc,
        "battery": battery, "qa": qa, "metrics": metrics,
    }


def previous_metrics(root: Path, as_of: date):
    """Metrics embedded in the newest earlier search-health filing,
    or None when there is no previous filing."""
    filings = root / "wiki" / "filings"
    if not filings.exists():
        return None
    best = None
    for p in filings.glob("search-health-*.md"):
        m = re.search(r"search-health-(\d{4}-\d{2}-\d{2})\.md$", p.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < as_of and (best is None or d > best[0]):
            best = (d, p)
    if best is None:
        return None
    text = best[1].read_text(encoding="utf-8", errors="ignore")
    m = METRICS_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


# ------------------------------------------------------------ rendering

def fmt(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render(h, prev, as_of: date):
    m = h["metrics"]
    lines = [
        "---",
        f'title: "Search health — {as_of.isoformat()}"',
        "type: query",
        f"created: {as_of.isoformat()}",
        f"updated: {as_of.isoformat()}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [search, health, evaluation, filings]",
        "status: draft",
        "confidence: observed",
        "stage: seedling",
        f"planted: {as_of.isoformat()}",
        f"tended: {as_of.isoformat()}",
        "work_type: record",
        "---",
        "",
        f"# Search health — {as_of.isoformat()}",
        "",
        "> [!note] MEASUREMENT ONLY — assembled from records",
        "> Generated by `scripts/wiki_search_health.py` from the"
        " evaluation artefacts, the retrieval baseline, the"
        " abstention battery and the Ask-door log — it runs no"
        " searches of its own and changes nothing. Zero-result and"
        " thin-result queries are named because they are work"
        " queues, not statistics (lane D). The log is the"
        " owner's own queries, stored locally in his own wiki,"
        " visible to him in full, and never leaves — analytics as"
        " a mirror, not surveillance.",
        "",
        "<!-- search-health-metrics: "
        + json.dumps(m, sort_keys=True) + " -->",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key in sorted(m):
        lines.append(f"| {key} | {fmt(m[key])} |")
    lines += ["", "## Zero-result and thin-result probes", ""]
    if h["zero_probes"]:
        lines.append(f"**{len(h['zero_probes'])} zero-result"
                     " probe(s)** (the search returned nothing — a"
                     " genuine gap or a findability failure):")
        lines.append("")
        for e in h["zero_probes"]:
            q = e["question"] or "(no question text recorded)"
            lines.append(f"- `{e['id']}` — {q}")
    else:
        lines.append(f"No zero-result probes among"
                     f" {h['probe_total']} baseline probes.")
    lines.append("")
    if h["thin_probes"]:
        lines.append(f"**{len(h['thin_probes'])} thin-result"
                     f" probe(s)** (fewer than"
                     f" {max(10, 0.1 * (h['median_result_count'] or 0)):.0f}"
                     " results against a median of"
                     f" {fmt(h['median_result_count'])}):")
        lines.append("")
        for e in h["thin_probes"]:
            lines.append(f"- `{e['id']}` — {e['result_count']}"
                         f" results — {e['question'] or ''}")
    else:
        lines.append("No thin-result probes (thin = under a tenth"
                     " of the median result count, floor 10).")
    for name in ("extended", "golden", "conflict"):
        sec = h[name]
        label = {"extended": "Extended set", "golden": "Golden set",
                 "conflict": "Conflict slice"}[name]
        lines += ["", f"## {label}", ""]
        if not sec["rec"]:
            lines.append("No run artefact found — a gap in the"
                         " record, reported as such.")
            continue
        rel = sec["path"].name if sec["path"] else "?"
        mm = sec["metrics"]
        lines.append(f"Latest run: `{rel}`"
                     f" (generated {sec['rec'].get('generated_at')},"
                     f" {mm['questions']} questions). Coverage @10"
                     f" {fmt(mm['coverage@10'])}, MRR"
                     f" {fmt(mm['mrr'])}, hit rate"
                     f" {fmt(mm['hit_rate_topk'])}.")
        if name == "extended" and sec["classes"]:
            lines += ["", "Weakest classes (by coverage @10, then"
                      " MRR):", "",
                      "| Class | Questions | Coverage @10 | MRR |",
                      "|---|---|---|---|"]
            for row in sec["weakest"]:
                lines.append(f"| {row['class']} | {row['questions']}"
                             f" | {fmt(row['coverage@10'])}"
                             f" | {fmt(row['mrr'])} |")
        if sec["misses"]:
            lines.append("")
            lines.append("Named must-cite misses (the expected page"
                         " was not in the top-10): "
                         + ", ".join(f"`{i}`" for i in sec["misses"])
                         + ".")
        else:
            lines.append("")
            lines.append("No must-cite misses in this run.")
    b = h["battery"]
    lines += ["", "## Abstention battery — search side", "",
              f"{b['search_cases']} search-side cases"
              " (modes `search` + `candidates`): "
              + (", ".join(f"{k} {n}" for k, n in
                           sorted(b["by_kind"].items())) or "none")
              + ". Expected verdicts: "
              + (", ".join(f"{k} {n}" for k, n in
                           sorted(b["expected"].items())) or "none")
              + ".",
              "",
              "The battery's outcomes are produced on demand by"
              " `scripts/wiki_abstention_check.py` and are not"
              " persisted as an artefact, so this filing reports"
              " the battery's composition only — it does not claim"
              " a pass it cannot point to."]
    qa = h["qa"]
    lines += ["", "## The Ask door", "",
              f"{qa['questions']} question(s) on the log"
              f" (wiki/access/qa-*.jsonl); statuses: "
              + (", ".join(f"{k} {n}" for k, n in
                           sorted(qa["statuses"].items())) or "none")
              + f". Abstentions {qa['abstentions']}"
              f" (rate {fmt(qa['abstention_rate'])}), holds"
              f" {qa['holds']} (rate {fmt(qa['hold_rate'])}),"
              f" {qa['distinct_citations']} distinct page"
              " citation(s) across all answers.",
              "",
              "A gap, stated plainly: our records carry the"
              " question → cited-pages pair, but not click"
              " positions — the query → clicked-page → position"
              " triples the find asks the events contract"
              " to carry from day one do not exist yet, so mean"
              " click position is not computable and is not"
              " estimated here.",
              "", "## Delta vs the previous filing", ""]
    if prev is None:
        lines.append("No previous filing — baseline. The metrics"
                     " embedded in this filing are the baseline"
                     " the next filing diffs against.")
    elif not prev:
        lines.append("A previous filing exists but predates"
                     " machine-readable metrics; no delta can be"
                     " computed against it.")
    else:
        lines += ["| Metric | Previous | Now | Δ |", "|---|---|---|---|"]
        for key in sorted(set(prev) | set(m)):
            old, new = prev.get(key), m.get(key)
            if isinstance(old, (int, float)) and isinstance(new,
                                                            (int, float)):
                delta = f"{new - old:+.4g}"
            else:
                delta = "—"
            lines.append(f"| {key} | {fmt(old)} | {fmt(new)} |"
                         f" {delta} |")
    lines += ["", "## Records used", "",
              "- `evaluation/results/` (latest golden + extended +"
              " conflict-slice run artefacts)",
              "- `evaluation/retrieval-baseline.json` (probe"
              " result counts)",
              "- `evaluation/abstention-battery.jsonl` (case"
              " definitions)",
              "- `wiki/access/qa-*.jsonl` (the Ask-door log)", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--date", default=None,
                    help="filing date (default: today)")
    ap.add_argument("--out", type=Path, default=None,
                    help="filing path (default:"
                         " wiki/filings/search-health-<date>.md)")
    ap.add_argument("--no-write", action="store_true",
                    help="print the filing instead of writing it")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    as_of = date.fromisoformat(args.date) if args.date else date.today()
    h = compute_health(root)
    prev = previous_metrics(root, as_of)
    text = render(h, prev, as_of)
    m = h["metrics"]
    print(f"Search health {as_of.isoformat()}: golden cov@10"
          f" {fmt(m.get('golden_coverage@10'))} · extended cov@10"
          f" {fmt(m.get('extended_coverage@10'))} · zero-result"
          f" probes {m.get('zero_result_probes')} · QA questions"
          f" {m.get('qa_questions')}")
    if args.no_write:
        print(text)
        return 0
    out = args.out or (root / "wiki" / "filings" /
                       f"search-health-{as_of.isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Filed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
