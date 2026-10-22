#!/usr/bin/env python3
"""Depth-ladder measurement runner (W6, 2026-10-22).

Executes the real question sets at EVERY level of the query
depth ladder (tools/ask/depth_ladder.py — quick / standard /
deep) through the Ask pipeline's deterministic core — the
same machinery the abstention battery pins:

  search     wiki_search.hybrid_rank with the severance
             list applied (the production ranking
             configuration; governance rides inside it);
  packing    evidence_packing.pack_evidence with severance
             AND standings, at the LEVEL's candidate pool
             and token budget — the only two things a level
             is allowed to change;
  decision   the battery's own rule (wiki_abstention_
             check._decide) against the frozen tau of
             evaluation/extended-baseline.json — imported,
             never restated, so the bar measured here is the
             bar the battery enforces.

What a level may NOT change, by the ladder's founding rule
(depth changes breadth, never the bar): the ranking itself
(the ranked list is computed ONCE per question and shared
by all levels — so ranked coverage@10 / MRR are level-
invariant by construction, and this runner VERIFIES that
rather than assuming it), the top-1 score the abstention
rule reads, severance, governance, and tau.

Per question and level the runner records: the packed
evidence (the passages an answer at that depth could
actually cite), whether a must-cite page is in it and at
what packed position, and the decision rule's verdict.
Aggregates: packed coverage and packed MRR per set per
level, verdict agreement where a set states expectations,
and — the point of the exercise — every NAMED change
against the standard level: questions whose must-cite
enters or leaves the packed evidence, and questions whose
verdict flips, in either direction. A deeper level that
hurts a question is reported on the same face as one it
helps.

The battery's search cases are executed at all three
levels with their expectations: the standard level must
pass all of them (the standing 12/12 gate includes them),
and every must-abstain case must abstain at every level
with the same decision basis. The battery's candidates /
record cases take caller-supplied evidence or composed
records — the ladder's pool and budget never reach them —
and are reported as depth-invariant by construction, not
re-run.

Artefacts: evaluation/depth-ladder-report.json + .md,
byte-deterministic for a fixed corpus state (the corpus
git HEAD is recorded as an input fact; no wall clock is
written). Exit 1 when the standard level fails a battery
expectation or a must-abstain verdict differs across
levels — a finding, reported, never tuned away here.

Usage:
  python3 scripts/wiki_depth_measure.py [--out-dir DIR]

Stdlib only; no network; no model calls.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "evaluation" / "extended-baseline.json"
SETS = {
    "golden": ROOT / "evaluation" / "golden-questions.jsonl",
    "extended": ROOT / "evaluation" / "extended-questions.jsonl",
    "conflict": ROOT / "evaluation" / "conflict-questions.jsonl",
}
BATTERY = ROOT / "evaluation" / "abstention-battery.jsonl"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


battery = _load("wiki_abstention_check",
                ROOT / "scripts" / "wiki_abstention_check.py")
ladder = _load("ask_depth_ladder",
               ROOT / "tools" / "ask" / "depth_ladder.py")
ws = battery.ws
packing = battery.packing


def _git_head():
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _page_of(path):
    """Battery normalisation: a ranked path to its page id
    (under wiki/, no .md)."""
    page = str(path.relative_to(ROOT / "wiki")) \
        if path.is_relative_to(ROOT / "wiki") else str(path)
    if page.endswith(".md"):
        page = page[:-3]
    return page


def _must_pages(question):
    out = []
    for cite in question.get("must_cite") or []:
        page = str(cite)
        if page.startswith("wiki/"):
            page = page[len("wiki/"):]
        if page.endswith(".md"):
            page = page[:-3]
        out.append(page)
    return out


def _load_questions(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            continue
        rows.append(obj)
    return rows


def _run_question(question, docs, adj, sev_list, standings, tau):
    """One question through the pipeline once, then packed
    at every level. Returns the per-level rows + the shared
    ranked facts."""
    terms = ws.tokenize(question["question"])
    ranked = ws.hybrid_rank(terms, docs, adj, severance=sev_list)
    ranked_pages = [_page_of(path) for _s, path, _t, _d in ranked]
    top_score = ranked[0][0] if ranked else None
    must = _must_pages(question)
    ranked_rank = None
    for pos, page in enumerate(ranked_pages, start=1):
        if page in must:
            ranked_rank = pos
            break
    # Candidate passages are extracted ONCE, for the widest
    # pool any level uses; a level's candidates are a prefix
    # slice of that one list (a passage's text cannot depend
    # on the depth it is later packed at).
    widest = max(ladder.get_level(n)["candidate_pool"]
                 for n in ladder.LEVEL_ORDER)
    all_candidates = [{
        "page": _page_of(path),
        "passage": battery._passage_from_text(text, terms),
        "score": score,
    } for score, path, text, _d in ranked[:widest]]
    levels = {}
    for name in ladder.LEVEL_ORDER:
        spec = ladder.get_level(name)
        candidates = all_candidates[:spec["candidate_pool"]]
        pack = packing.pack_evidence(
            candidates, budget=spec["pack_budget_tokens"],
            severance=sev_list, standings=standings)
        packed_pages = [p["page"] for p in pack["packed"]]
        packed_pos = None
        for pos, page in enumerate(packed_pages, start=1):
            if page in must:
                packed_pos = pos
                break
        verdict, reason = battery._decide(pack, top_score, tau)
        levels[name] = {
            "packed": len(packed_pages),
            "tokens_used": pack["tokens_used"],
            "must_cite_packed": packed_pos is not None,
            "must_cite_packed_position": packed_pos,
            "verdict": verdict,
            "verdict_reason": reason,
        }
    return {
        "id": question.get("id"),
        "question": question.get("question"),
        "must_cite": must,
        "expected_abstain": bool(question.get("expected_abstain")),
        "top_score": (round(top_score, 4)
                      if top_score is not None else None),
        "ranked_must_cite_rank": ranked_rank,
        "levels": levels,
    }


def _aggregate(rows):
    answerable = [r for r in rows if r["must_cite"]]
    abstain_expected = [r for r in rows if r["expected_abstain"]]
    out = {"questions": len(rows)}
    ranked_hits = sum(1 for r in answerable
                      if r["ranked_must_cite_rank"] is not None
                      and r["ranked_must_cite_rank"] <= 10)
    out["ranked_coverage@10"] = (
        round(ranked_hits / len(answerable), 4) if answerable else None)
    out["ranked_mrr_must_cite"] = (
        round(sum(1.0 / r["ranked_must_cite_rank"] for r in answerable
                  if r["ranked_must_cite_rank"] is not None)
              / len(answerable), 4) if answerable else None)
    per_level = {}
    for name in ladder.LEVEL_ORDER:
        packed_hits = sum(1 for r in answerable
                          if r["levels"][name]["must_cite_packed"])
        per_level[name] = {
            "packed_coverage": (
                round(packed_hits / len(answerable), 4)
                if answerable else None),
            "packed_mrr": (
                round(sum(
                    1.0 / r["levels"][name]["must_cite_packed_position"]
                    for r in answerable
                    if r["levels"][name]["must_cite_packed_position"]
                ) / len(answerable), 4) if answerable else None),
            "mean_packed_passages": (
                round(sum(r["levels"][name]["packed"] for r in rows)
                      / len(rows), 2) if rows else None),
            "mean_tokens_used": (
                round(sum(r["levels"][name]["tokens_used"]
                          for r in rows) / len(rows), 1)
                if rows else None),
        }
        if abstain_expected:
            ok = sum(1 for r in abstain_expected
                     if r["levels"][name]["verdict"] == "abstain")
            per_level[name]["abstain_expected_agreement"] = (
                f"{ok}/{len(abstain_expected)}")
    out["levels"] = per_level
    return out


def _changes(rows):
    """Named changes against the standard level, per other
    level: packed-coverage gains/losses and verdict flips."""
    out = {}
    for name in ladder.LEVEL_ORDER:
        if name == ladder.DEFAULT_DEPTH:
            continue
        gained, lost, flips = [], [], []
        for r in rows:
            std = r["levels"][ladder.DEFAULT_DEPTH]
            lvl = r["levels"][name]
            if lvl["must_cite_packed"] and not std["must_cite_packed"]:
                gained.append(r["id"])
            if std["must_cite_packed"] and not lvl["must_cite_packed"]:
                lost.append(r["id"])
            if lvl["verdict"] != std["verdict"]:
                flips.append({
                    "id": r["id"],
                    "standard": std["verdict"],
                    name: lvl["verdict"],
                    "reason": lvl["verdict_reason"],
                })
        out[name] = {"must_cite_gained": gained,
                     "must_cite_lost": lost,
                     "verdict_flips": flips}
    return out


def _render_md(report):
    lines = []
    lines.append("# Depth-ladder measurement (W6)")
    lines.append("")
    lines.append("Generated by `scripts/wiki_depth_measure.py` over the "
                 "live corpus — deterministic pipeline only (hybrid "
                 "ranking + severance/standings packing + the battery's "
                 "decision rule), no model calls. Corpus git HEAD: "
                 f"`{report['corpus']['git_head']}` · tau "
                 f"{report['tau']} (frozen, "
                 f"{report['tau_source']}) · docs "
                 f"{report['corpus']['docs']}.")
    lines.append("")
    lines.append(report["invariant"])
    lines.append("")
    lines.append("## The ladder")
    lines.append("")
    lines.append("| level | candidate pool | pack budget | sentence "
                 "scoring | provenance | cost |")
    lines.append("|---|---|---|---|---|---|")
    for name in ladder.LEVEL_ORDER:
        spec = ladder.get_level(name)
        lines.append(
            f"| {name} | {spec['candidate_pool']} | "
            f"{spec['pack_budget_tokens']} tokens | "
            f"{spec['sentence_scoring']} | {spec['provenance']} | "
            f"{spec['cost']} |")
    lines.append("")
    for set_name, sdata in report["sets"].items():
        agg = sdata["aggregate"]
        lines.append(f"## {set_name} ({agg['questions']} questions)")
        lines.append("")
        lines.append(f"Ranked (level-invariant, verified identical "
                     f"across levels): coverage@10 "
                     f"{agg['ranked_coverage@10']}, MRR "
                     f"{agg['ranked_mrr_must_cite']}.")
        lines.append("")
        lines.append("| level | packed coverage | packed MRR | mean "
                     "packed passages | mean tokens |")
        lines.append("|---|---|---|---|---|")
        for name in ladder.LEVEL_ORDER:
            la = agg["levels"][name]
            lines.append(
                f"| {name} | {la['packed_coverage']} | "
                f"{la['packed_mrr']} | {la['mean_packed_passages']} | "
                f"{la['mean_tokens_used']} |")
        lines.append("")
        for name, change in sdata["changes"].items():
            lines.append(
                f"Against standard, at **{name}**: must-cite gained "
                f"{change['must_cite_gained'] or '[]'} · lost "
                f"{change['must_cite_lost'] or '[]'} · verdict flips "
                f"{[f['id'] for f in change['verdict_flips']] or '[]'}.")
        lines.append("")
    b = report["battery"]
    lines.append(f"## Abstention battery — search cases ({b['cases']})")
    lines.append("")
    for name in ladder.LEVEL_ORDER:
        lines.append(f"- {name}: {b['levels'][name]['passed']}/"
                     f"{b['cases']} expectations met")
    lines.append(f"- Must-abstain identical at every depth: "
                 f"{b['must_abstain_identical']}")
    for row in b["rows"]:
        marks = " · ".join(
            f"{name}={row['levels'][name]['observed']}"
            for name in ladder.LEVEL_ORDER)
        lines.append(f"- {row['id']} ({row['case_kind']}, expected "
                     f"{row['expected']}): {marks}")
    lines.append("")
    lines.append("The battery's candidates / record cases take "
                 "caller-supplied evidence or composed records — the "
                 "ladder's pool and budget never reach them — and are "
                 "depth-invariant by construction; the standing "
                 "battery runner remains their gate.")
    lines.append("")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Depth-ladder measurement (W6).")
    ap.add_argument("--out-dir", default=str(ROOT / "evaluation"))
    args = ap.parse_args(argv[1:])

    if not BASELINE.is_file():
        print(f"baseline missing: {BASELINE}", file=sys.stderr)
        return 2
    tau = json.loads(BASELINE.read_text(
        encoding="utf-8")).get("abstain_threshold")

    sev_list = battery.severance.load_severance()
    standings = battery.standing.load_standings()
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)

    report = {
        "kind": "depth-ladder-measurement",
        "tool": "scripts/wiki_depth_measure.py",
        "ladder": "tools/ask/depth_ladder.py",
        "tau": tau,
        "tau_source": ladder.TAU_SOURCE,
        "invariant": ladder.ABSTENTION_INVARIANT,
        "corpus": {"docs": len(docs), "git_head": _git_head()},
        "levels": {name: ladder.get_level(name)
                   for name in ladder.LEVEL_ORDER},
        "sets": {},
        "battery": {},
    }

    failures = []
    for set_name, path in SETS.items():
        questions = _load_questions(path)
        rows = [_run_question(q, docs, adj, sev_list, standings, tau)
                for q in questions]
        report["sets"][set_name] = {
            "aggregate": _aggregate(rows),
            "changes": _changes(rows),
            "rows": rows,
        }
        agg = report["sets"][set_name]["aggregate"]
        print(f"{set_name}: {agg['questions']} questions · ranked "
              f"cov@10 {agg['ranked_coverage@10']} · packed coverage "
              + " / ".join(
                  f"{n}={agg['levels'][n]['packed_coverage']}"
                  for n in ladder.LEVEL_ORDER))

    _header, cases = battery.load_battery(BATTERY)
    search_cases = [c for c in cases if c["mode"] == "search"]
    brows = []
    for case in search_cases:
        row = _run_question(case, docs, adj, sev_list, standings, tau)
        brows.append({
            "id": case["id"], "case_kind": case["case_kind"],
            "expected": case["expected_verdict"],
            "levels": {name: {"observed": row["levels"][name]["verdict"],
                              "reason": row["levels"][name]
                              ["verdict_reason"]}
                       for name in ladder.LEVEL_ORDER},
        })
    blevels = {}
    for name in ladder.LEVEL_ORDER:
        passed = sum(1 for r in brows
                     if r["levels"][name]["observed"] == r["expected"])
        blevels[name] = {"passed": passed}
        if name == ladder.DEFAULT_DEPTH and passed != len(brows):
            failures.append(
                f"battery search cases at standard: {passed}/"
                f"{len(brows)}")
    must_abstain = [r for r in brows if r["expected"] == "abstain"]
    identical = all(
        len({r["levels"][n]["observed"] for n in ladder.LEVEL_ORDER}) == 1
        and r["levels"][ladder.DEFAULT_DEPTH]["observed"] == "abstain"
        for r in must_abstain)
    if not identical:
        failures.append("a must-abstain battery case does not abstain "
                        "identically at every depth")
    report["battery"] = {
        "cases": len(brows),
        "levels": blevels,
        "must_abstain_identical": identical,
        "rows": brows,
        "note": "search-mode cases only; candidates / record cases "
                "are depth-invariant by construction (see module "
                "docstring)",
    }
    print(f"battery search cases: "
          + " / ".join(f"{n}={blevels[n]['passed']}/{len(brows)}"
                       for n in ladder.LEVEL_ORDER)
          + f" · must-abstain identical: {identical}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "depth-ladder-report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "depth-ladder-report.md").write_text(
        _render_md(report), encoding="utf-8")
    print(f"wrote {out_dir / 'depth-ladder-report.json'}")
    print(f"wrote {out_dir / 'depth-ladder-report.md'}")
    if failures:
        for failure in failures:
            print(f"FINDING: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
