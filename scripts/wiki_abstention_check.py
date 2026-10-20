#!/usr/bin/env python3
"""Abstention regression battery runner (WikiCitadel v1).

Executes evaluation/abstention-battery.jsonl against the CURRENT
Ask pipeline, deterministically — no live LLM, because what is
being pinned is the contract layer, not a model's prose:

  search     wiki_search.hybrid_rank with the severance list
             applied (the production ranking configuration);
  packing    evidence_packing.pack_evidence with severance AND
             standings (the strongest-source-first order);
  contract   answer_contract — the abstention decision rule below
             for search/candidate cases, and
             compute_trust_verdict + chain_hedge_findings for
             record cases.

Why a runner in scripts/ and not only ask-suite tests: the
battery is an EVAL instrument over the live corpus (like
wiki_eval_extended.py), so it lives beside the other eval
runners and reads the same baseline; the ask suite's unit tests
pin the components (packing order, hedge overlay) on fixtures.
Both must be green; this runner is the one whose red blocks an
integration (see the regression rule in the schema).

The decision rule for search/candidate cases mirrors the pickup
procedure (tools/ask/pickup.md) with the extended eval's
calibrated abstention threshold:

  1. candidates were offered and severance cut every one
     (all_evidence_severed)          -> abstain (severance);
  2. top-1 hybrid score below tau (evaluation/
     extended-baseline.json's abstain_threshold — the median
     answerable top-1 at baseline time) -> abstain (no usable
     evidence);
  3. nothing packed                  -> abstain (empty pack);
  4. otherwise                       -> answer: a record citing
     the packed passages (normalised scores; passages at >= 0.5
     relative relevance, or the single strongest) must validate
     under the contract and not compute to hold.

Usage:
  python3 scripts/wiki_abstention_check.py [--battery FILE]
          [--abstain-threshold T] [--out FILE]

Exit 0 = every case passed; 1 = at least one case failed (a
finding — report it, do not re-tune the case to hide it);
2 = usage error (missing battery/baseline). Stdlib only.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATTERY = ROOT / "evaluation" / "abstention-battery.jsonl"
BASELINE = ROOT / "evaluation" / "extended-baseline.json"
TOP_K = 10


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wiki_search", ROOT / "scripts" / "wiki_search.py")
severance = _load("ask_severance", ROOT / "tools" / "ask" / "severance.py")
standing = _load("ask_standing", ROOT / "tools" / "ask" / "standing.py")
packing = _load("evidence_packing",
                ROOT / "tools" / "ask" / "evidence_packing.py")
contract = _load("answer_contract",
                 ROOT / "tools" / "ask" / "answer_contract.py")


def load_battery(path):
    header, cases = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        elif obj.get("kind") == "case":
            cases.append(obj)
    return header, cases


def _passage_from_text(text, terms):
    """The candidate passage for a ranked doc: the full line
    holding the most distinct query terms (make_snippet's
    selection rule), UNtruncated — a candidate passage must be
    verbatim in its page, because the contract's citation check
    will hold the composed record to exactly that. (The display
    snippet truncates with an ellipsis; a truncated snippet is
    not evidence.)"""
    qset = set(terms)
    best_line, best_key = "", None
    for pos, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        line_terms = set(ws.tokenize(line))
        distinct = len(qset & line_terms)
        total = sum(1 for t in ws.tokenize(line) if t in qset)
        key = (distinct, total, -pos)
        if best_key is None or key > best_key:
            best_key, best_line = key, line
    return best_line


def _candidates_from_ranked(ranked, terms):
    out = []
    for score, path, text, _detail in ranked[:TOP_K]:
        page = str(path.relative_to(ROOT / "wiki")) \
            if path.is_relative_to(ROOT / "wiki") else str(path)
        if page.endswith(".md"):
            page = page[:-3]
        out.append({
            "page": page,
            "passage": _passage_from_text(text, terms),
            "score": score,
        })
    return out


def _answer_record(packed, top_score):
    """A deterministic record citing the packed evidence, the
    way the pickup procedure composes one: relative relevance
    scores (top passage = 1.0), citing passages at >= 0.5
    relative relevance, or the single strongest passage."""
    if not packed or not top_score:
        return None
    cited = []
    for entry in packed:
        rel = round(entry["score"] / top_score, 3) \
            if entry.get("score") else 0.0
        if rel >= 0.5:
            cited.append({
                "page": entry["page"],
                "score": max(rel, 0.05),
                "passage": entry["passage"],
            })
    if not cited:
        top = packed[0]
        cited = [{"page": top["page"], "score": 1.0,
                  "passage": top["passage"]}]
    return {
        "answer": "(battery) composed from the packed evidence",
        "citations": cited,
    }


def _decide(pack_result, top_score, tau):
    """(verdict, reason) for search/candidate cases."""
    if pack_result.get("all_evidence_severed"):
        return "abstain", "all evidence severed (register lookup)"
    if top_score is not None and tau is not None and top_score < tau:
        return "abstain", f"top-1 score {top_score:.3f} < tau {tau}"
    if not pack_result["packed"]:
        return "abstain", "nothing packed"
    return "answer", "evidence packed"


def run_search_case(case, docs, adj, sev_list, standings, tau):
    terms = ws.tokenize(case["question"])
    ranked = ws.hybrid_rank(terms, docs, adj, severance=sev_list)
    candidates = _candidates_from_ranked(ranked, terms)
    top_score = ranked[0][0] if ranked else None
    pack = packing.pack_evidence(
        candidates, severance=sev_list, standings=standings)
    verdict, reason = _decide(pack, top_score, tau)
    detail = (f"top1={top_score:.3f} tau={tau} "
              f"packed={len(pack['packed'])} — {reason}")
    if verdict == "answer":
        record = _answer_record(pack["packed"], top_score)
        errors = contract.validate_answer(record, ROOT / "wiki")
        computed = contract.compute_trust_verdict(record)
        if errors or computed == "hold":
            return False, verdict, (
                detail + f"; BUT the composed record fails the "
                f"contract (errors={errors}, verdict={computed})")
    return verdict == case["expected_verdict"], verdict, detail


def run_candidates_case(case, sev_list, standings):
    wiki = ROOT / "wiki"
    candidates = []
    for cand in case.get("candidate_passages") or []:
        page_path = contract.citation_path(cand["page"], wiki)
        if page_path is None:
            return False, "error", f"fixture page {cand['page']!r} unresolved"
        text = page_path.read_text(encoding="utf-8")
        if not contract._passage_in_page(cand["passage"], text):
            return False, "error", (
                f"fixture passage is NOT verbatim in {cand['page']} — "
                "the fixture has rotted; repair the case, do not "
                "weaken the check")
        candidates.append({"page": cand["page"],
                           "passage": cand["passage"], "score": 1.0})
    pack = packing.pack_evidence(
        candidates, severance=sev_list, standings=standings)
    verdict, reason = _decide(pack, None, None)
    detail = (f"candidates={len(candidates)} "
              f"severed={len(pack.get('severed') or [])} — {reason}")
    return verdict == case["expected_verdict"], verdict, detail


def run_record_case(case):
    record = case["record"]
    verdict = contract.compute_trust_verdict(record)
    findings = contract.chain_hedge_findings(record)
    ok = verdict == case["expected_verdict"]
    detail = f"trust verdict={verdict}, hedge findings={len(findings)}"
    expect = case.get("expect_findings")
    if expect is not None:
        if bool(findings) != bool(expect):
            ok = False
            detail += f"; expected findings present={expect}"
    return ok, verdict, detail


def main(argv):
    ap = argparse.ArgumentParser(
        description="Abstention regression battery.")
    ap.add_argument("--battery", default=str(BATTERY))
    ap.add_argument("--abstain-threshold", type=float, default=None,
                    help="default: evaluation/extended-baseline.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])

    tau = args.abstain_threshold
    if tau is None:
        if not BASELINE.is_file():
            print(f"baseline missing: {BASELINE} — the battery runs "
                  "calibrated or not at all", file=sys.stderr)
            return 2
        tau = json.loads(BASELINE.read_text(
            encoding="utf-8")).get("abstain_threshold")
    _header, cases = load_battery(args.battery)
    if not cases:
        print("battery has no cases", file=sys.stderr)
        return 2

    sev_list = severance.load_severance()
    standings = standing.load_standings()
    docs = adj = None
    if any(c["mode"] == "search" for c in cases):
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)

    results = []
    for case in cases:
        if case["mode"] == "search":
            ok, observed, detail = run_search_case(
                case, docs, adj, sev_list, standings, tau)
        elif case["mode"] == "candidates":
            ok, observed, detail = run_candidates_case(
                case, sev_list, standings)
        elif case["mode"] == "record":
            ok, observed, detail = run_record_case(case)
        else:
            ok, observed, detail = False, "error", f"unknown mode {case['mode']}"
        results.append({"id": case["id"], "kind": case["case_kind"],
                        "expected": case["expected_verdict"],
                        "observed": observed, "pass": ok,
                        "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']} "
              f"({case['case_kind']}): expected "
              f"{case['expected_verdict']}, observed {observed} — "
              f"{detail}")
    passed = sum(1 for r in results if r["pass"])
    print(f"battery: {passed}/{len(results)} cases pass "
          f"(tau={tau}, severance={'on' if sev_list else 'OFF'})")
    if args.out:
        Path(args.out).write_text(
            json.dumps({"tau": tau, "results": results}, indent=2,
                       ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
