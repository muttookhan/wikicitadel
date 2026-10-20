#!/usr/bin/env python3
"""Retrieval-anomaly watch for the LLM Wiki — retrieval treated
as a security signal (WikiCitadel v1).

Why this exists (survey, lane C finds 14–15): the wiki
is persistent, agent-written memory, and the published attacks
on exactly that shape of system work through retrieval.
AgentPoison (Chen et al., NeurIPS 2024) backdoors a RAG agent's
memory at a poison rate under 0.1% of the store with ≥80%
average attack success; MINJA (Dong et al., NeurIPS 2025)
injects memory through queries alone at a 98.2% average
injection success rate. Both stay invisible in normal use until
the trigger context arrives — benign performance barely moves.
The symptom that IS visible, named in find 14's verdict, is a
retrieval anomaly: a page suddenly being retrieved for
unrelated questions, or one source suddenly dominating result
lists it has no business dominating. This tool makes that
symptom a standing, measured signal instead of something
nobody is watching for.

What it does: replays a fixed probe set over the live hybrid
search (scripts/wiki_search.py, the same engine the Lens
parity-checks against, severance stage included — the watch
observes live behaviour, not an idealised one) and computes,
per probe query, the distribution features a poisoning or
gaming event moves:

  result_count    how many documents the query ranks at all
  top1_share      the top hit's share of the top-10 score mass
                  (a crafted page engineered to win its trigger
                  queries takes an outsized share)
  concentration   the largest share of the top-10 held by one
                  collection (two path components, e.g.
                  wiki/sources, raw/filings) — a poisoned or
                  gamed cluster floods lists from one origin.
                  Judged against the collection's own share of
                  the corpus: raw/sources legitimately holds
                  ~64% of this corpus, so a top-10 that is 70%
                  raw/sources is base rate, not a flood; the
                  signal fires on share ABOVE base rate (see
                  CONCENTRATION_BASE_MARGIN)
  new_in_top10    top-10 pages that entered the corpus within
                  NEW_PAGE_WINDOW_DAYS — new pages are where
                  injected content lives; an established query's
                  top-10 suddenly filling with week-old pages
                  is the AgentPoison shape

and, across the probe set, top1_wins: how many probes each
page wins outright. A page that wins many unrelated probes is
the single strongest poison signature either paper describes.

Probe set (stated, fixed): the golden set's 15 questions
(evaluation/golden-questions.jsonl) + the extended set's 78
(evaluation/extended-questions.jsonl) = 93 probes, scope
"all" (wiki + raw), hybrid engine — the corpus and ranking
the Ask door actually draws on.

Baseline: evaluation/retrieval-baseline.json, written on the
first run and thereafter ONLY by an explicit --update-baseline
act. A baseline that drifts to follow the corpus would
normalise the very anomaly it exists to catch (the survey
lane's Halfaker lesson: every safeguard drifts), so updating
it is a deliberate, recorded act, never a side effect of a
watch run.

Thresholds are constants below, each with its rationale.
Absolute signals (concentration, top-1 wins) fire with or
without a baseline; delta signals compare against the
baseline. Exit 0 = quiet, 1 = anomalies found, 2 = usage
error. Stdlib only.
"""
import argparse
import importlib.util
import json
import statistics
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
BASELINE_PATH = ROOT / "evaluation" / "retrieval-baseline.json"
GOLDEN_PATH = ROOT / "evaluation" / "golden-questions.jsonl"
EXTENDED_PATH = ROOT / "evaluation" / "extended-questions.jsonl"

# --- thresholds (stated constants; rationale in the docstring) ---

# One collection holding >= 70% of a query's top-10 AND
# beating its own share of the corpus by the margin below.
# Measured on the first real run: raw/sources is
# 64% of the corpus and held >= 70% of the top-10 for 51 of 93
# probes — base rate, not attack. A threshold that fires on
# most probes is a broken signal (alarm fatigue is its own
# failure mode), so the absolute signal guards the origins
# that have no business flooding; the giant origin is guarded
# by the delta signals (concentration_rise, new dominator,
# intrusion), which compare against the baseline.
CONCENTRATION_LIMIT = 0.7
CONCENTRATION_BASE_MARGIN = 0.45
# A page winning >= 25% of all probes outright (and at least
# TOP1_WINS_MIN probes). No honest page is the best answer to
# a quarter of a deliberately heterogeneous probe set.
TOP1_WINS_SHARE = 0.25
TOP1_WINS_MIN = 3
# A page's top-1 wins rising by at least this many against the
# baseline, from a baseline of fewer, is a new dominator.
NEW_DOMINATOR_MIN_WINS = 3
# Per-query movement vs baseline that counts as an anomaly.
RESULT_COUNT_REL_DELTA = 0.5    # result count halves or grows by half…
RESULT_COUNT_MIN_DELTA = 5      # …and moves at least 5 documents
TOP1_SHARE_DELTA = 0.25         # top-1 score share jumps 25 points
CONCENTRATION_DELTA = 0.3       # one origin gains 30 points of a top-10
# A top-10 page counts as "new" if it entered the corpus this
# many days before the run (or is not yet committed at all).
NEW_PAGE_WINDOW_DAYS = 7


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wsearch = _load("wiki_search")


# ---------------------------------------------------------------- probes

def load_probes():
    """The fixed probe set: golden 15 + extended 78.
    Returns [{qid, question, origin}]."""
    probes = []
    for path, origin in ((GOLDEN_PATH, "golden"),
                         (EXTENDED_PATH, "extended")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") == "header":
                continue
            probes.append({"qid": row["id"],
                           "question": row["question"],
                           "origin": origin})
    return probes


# ------------------------------------------------------- first-seen dates

def git_first_seen(root):
    """{repo-relative path: ISO date} of each tracked file's
    earliest add commit, from ONE git log pass. Files git has
    never added are absent (caller falls back to mtime — a file
    not yet committed entered the working corpus when written,
    which for intrusion purposes is the honest date)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--diff-filter=A",
             "--date=short", "--format=COMMIT %ad", "--name-only"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    seen = {}
    current = None
    # git log runs newest-first: the LAST add date seen for a
    # path is its earliest, so later lines overwrite earlier.
    for line in out.stdout.splitlines():
        if line.startswith("COMMIT "):
            current = line[len("COMMIT "):].strip()
        elif line.strip() and current:
            seen[line.strip()] = current
    return seen


def first_seen_map(root, paths):
    """First-seen ISO date per path: git add date when tracked,
    else the file's mtime date."""
    git_dates = git_first_seen(root)
    out = {}
    for rel in paths:
        if rel in git_dates:
            out[rel] = git_dates[rel]
        else:
            p = root / rel
            try:
                out[rel] = date.fromtimestamp(
                    p.stat().st_mtime).isoformat()
            except OSError:
                out[rel] = None
    return out


# ---------------------------------------------------------------- features

def collection_key(rel_path):
    """The origin a result floods from: the first two path
    components (wiki/sources, raw/filings, wiki/entities, …);
    a two-component path keys on its first component."""
    parts = rel_path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def query_features(ranked, seen, run_date):
    """Distribution features for one probe's ranked list.
    ranked: [(score, path, text, detail)] as wiki_search
    returns; seen: {rel_path: ISO first-seen date}."""
    top10 = ranked[:10]
    scores = [s for s, _p, _t, _d in top10]
    total = sum(scores)
    rels = []
    for _s, p, _t, _d in top10:
        rels.append(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT)
                    else str(p))
    conc = 0.0
    top_collection = None
    if rels:
        counts = Counter(collection_key(r) for r in rels)
        top_collection, top_n = counts.most_common(1)[0]
        conc = top_n / len(rels)
    new_pages = []
    for rel in rels:
        d = seen.get(rel)
        if d is None:
            continue
        try:
            age = (run_date - date.fromisoformat(d)).days
        except ValueError:
            continue
        if 0 <= age <= NEW_PAGE_WINDOW_DAYS:
            new_pages.append(rel)
    return {
        "result_count": len(ranked),
        "top1_path": rels[0] if rels else None,
        "top1_share": round(scores[0] / total, 4) if total else 0.0,
        "concentration": round(conc, 4),
        "top_collection": top_collection,
        "top10": rels,
        "new_in_top10": new_pages,
    }


def run_probes(probes, run_date, root=ROOT):
    """Replay the probe set over the live search. Returns
    (per_query {qid: features+question}, aggregate)."""
    docs = wsearch.collect_docs("all")
    adj = wsearch.build_link_graph(docs)
    seen = first_seen_map(root, [str(p.relative_to(root))
                                 if p.is_relative_to(root) else str(p)
                                 for p, _t in docs])
    per_query = {}
    for probe in probes:
        terms = wsearch.tokenize(probe["question"])
        ranked = wsearch.hybrid_rank(terms, docs, adj=adj) if terms else []
        feats = query_features(ranked, seen, run_date)
        feats["question"] = probe["question"]
        feats["origin"] = probe["origin"]
        per_query[probe["qid"]] = feats
    wins = Counter(f["top1_path"] for f in per_query.values()
                   if f["top1_path"])
    counts = [f["result_count"] for f in per_query.values()]
    doc_keys = Counter()
    for p, _t in docs:
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        doc_keys[collection_key(rel)] += 1
    n_docs = sum(doc_keys.values()) or 1
    aggregate = {
        "probes": len(per_query),
        "median_result_count": statistics.median(counts) if counts else 0,
        "top1_wins": dict(wins.most_common()),
        "collection_shares": {k: round(v / n_docs, 4)
                              for k, v in doc_keys.most_common()},
        "intrusion_pages": sorted({
            rel for f in per_query.values() for rel in f["new_in_top10"]}),
    }
    return per_query, aggregate


# ---------------------------------------------------------------- anomalies

def detect_anomalies(current_q, current_agg, baseline, shares=None):
    """Compare current features against thresholds and, when a
    baseline is given, against it. Returns a list of anomaly
    dicts: {signal, qid|None, page|None, detail, values}.
    `shares` = each collection's share of the corpus (base
    rates); the baseline's recorded shares govern when a
    baseline exists — they are the pre-existing base rates —
    else the current corpus's."""
    anomalies = []
    n = current_agg["probes"] or 1
    if shares is None:
        if baseline is not None:
            shares = baseline["aggregate"].get("collection_shares", {})
        else:
            shares = current_agg.get("collection_shares", {})

    # Absolute: a collection flooding one top-10 — share above
    # the limit AND above its own corpus base rate by the
    # margin (a giant collection at base rate is not a flood).
    for qid, f in sorted(current_q.items()):
        coll = f.get("top_collection")
        if not coll or not f["top10"]:
            continue
        base_rate = shares.get(coll, 0.0)
        if f["concentration"] >= CONCENTRATION_LIMIT \
                and f["concentration"] - base_rate \
                >= CONCENTRATION_BASE_MARGIN:
            anomalies.append({
                "signal": "concentration",
                "qid": qid,
                "detail": (f"collection {coll} holds "
                           f"{f['concentration']:.0%} of the top-10 "
                           f"against a {base_rate:.0%} share of the "
                           f"corpus"),
                "values": {"concentration": f["concentration"],
                           "collection": coll,
                           "base_rate": base_rate}})

    # Absolute: one page winning an outsized share of probes.
    for page, wins in sorted(current_agg["top1_wins"].items()):
        if wins >= TOP1_WINS_MIN and wins / n >= TOP1_WINS_SHARE:
            anomalies.append({
                "signal": "top1_dominance",
                "page": page,
                "detail": (f"page is the top hit for {wins} of {n} "
                           f"probes ({wins / n:.0%})"),
                "values": {"wins": wins, "probes": n}})

    if baseline is None:
        return anomalies
    base_q = baseline["per_query"]
    base_wins = baseline["aggregate"]["top1_wins"]

    # Delta: a new dominator — wins now, (near-)none at baseline.
    for page, wins in sorted(current_agg["top1_wins"].items()):
        before = base_wins.get(page, 0)
        if wins >= NEW_DOMINATOR_MIN_WINS and before < NEW_DOMINATOR_MIN_WINS \
                and not any(a["signal"] == "top1_dominance"
                            and a.get("page") == page for a in anomalies):
            anomalies.append({
                "signal": "new_dominator",
                "page": page,
                "detail": (f"page now wins {wins} probes outright; "
                           f"baseline wins: {before}"),
                "values": {"wins": wins, "baseline_wins": before}})

    for qid, f in sorted(current_q.items()):
        b = base_q.get(qid)
        if b is None:
            continue
        # Delta: result count moved by half and by >= 5 docs.
        bc, cc = b["result_count"], f["result_count"]
        if bc and abs(cc - bc) >= RESULT_COUNT_MIN_DELTA \
                and abs(cc - bc) / bc >= RESULT_COUNT_REL_DELTA:
            anomalies.append({
                "signal": "result_count_shift",
                "qid": qid,
                "detail": (f"ranked documents moved {bc} -> {cc}"),
                "values": {"baseline": bc, "current": cc}})
        # Delta: top-1 score share jumped.
        if f["top1_share"] - b["top1_share"] >= TOP1_SHARE_DELTA:
            anomalies.append({
                "signal": "top1_share_jump",
                "qid": qid,
                "detail": (f"top-1 score share moved "
                           f"{b['top1_share']:.2f} -> {f['top1_share']:.2f} "
                           f"(top hit now {f['top1_path']})"),
                "values": {"baseline": b["top1_share"],
                           "current": f["top1_share"]}})
        # Delta: concentration gained 30 points.
        if f["concentration"] - b["concentration"] >= CONCENTRATION_DELTA:
            anomalies.append({
                "signal": "concentration_rise",
                "qid": qid,
                "detail": (f"top-10 concentration moved "
                           f"{b['concentration']:.2f} -> "
                           f"{f['concentration']:.2f}"),
                "values": {"baseline": b["concentration"],
                           "current": f["concentration"]}})
        # Intrusion: a week-old page sits in this query's top-10
        # that was not in the baseline's top-10 at all.
        base_top10 = set(b["top10"])
        for rel in f["new_in_top10"]:
            if rel not in base_top10:
                anomalies.append({
                    "signal": "new_page_intrusion",
                    "qid": qid,
                    "page": rel,
                    "detail": (f"page entered the corpus within "
                               f"{NEW_PAGE_WINDOW_DAYS} days and is in "
                               f"this probe's top-10; it was not in the "
                               f"baseline top-10"),
                    "values": {"baseline_top10": b["top10"][:3]}})
    return anomalies


# ---------------------------------------------------------------- baseline

def baseline_document(per_query, aggregate, run_date):
    return {
        "kind": "retrieval-baseline",
        "version": 1,
        "created": run_date.isoformat(),
        "probe_set": ("evaluation/golden-questions.jsonl (15) + "
                      "evaluation/extended-questions.jsonl (78) = 93 "
                      "probes, scope 'all', hybrid engine"),
        "thresholds": {
            "concentration_limit": CONCENTRATION_LIMIT,
            "concentration_base_margin": CONCENTRATION_BASE_MARGIN,
            "top1_wins_share": TOP1_WINS_SHARE,
            "top1_wins_min": TOP1_WINS_MIN,
            "new_dominator_min_wins": NEW_DOMINATOR_MIN_WINS,
            "result_count_rel_delta": RESULT_COUNT_REL_DELTA,
            "result_count_min_delta": RESULT_COUNT_MIN_DELTA,
            "top1_share_delta": TOP1_SHARE_DELTA,
            "concentration_delta": CONCENTRATION_DELTA,
            "new_page_window_days": NEW_PAGE_WINDOW_DAYS,
        },
        "note": ("Written by scripts/wiki_retrieval_watch.py. "
                 "Regenerated ONLY by an explicit --update-baseline "
                 "act; a watch run never moves it (a drifting "
                 "baseline normalises the anomaly it exists to "
                 "catch)."),
        "per_query": per_query,
        "aggregate": aggregate,
    }


def load_baseline():
    if not BASELINE_PATH.is_file():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(
        description="Retrieval-anomaly watch : replay the "
                    "probe set over the live search and report "
                    "anomalous result distributions.")
    ap.add_argument("--update-baseline", action="store_true",
                    help="overwrite evaluation/retrieval-baseline.json "
                         "with the current features (an explicit, "
                         "recorded act — never automatic)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full report as JSON")
    args = ap.parse_args(argv[1:])

    run_date = datetime.now(timezone.utc).date()
    probes = load_probes()
    baseline = load_baseline()
    per_query, aggregate = run_probes(probes, run_date)

    created_baseline = False
    if baseline is None:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(baseline_document(per_query, aggregate, run_date),
                       indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")
        created_baseline = True
        baseline = None  # first run: no delta verdict is possible

    anomalies = detect_anomalies(per_query, aggregate, baseline)

    updated_baseline = False
    if args.update_baseline and not created_baseline:
        BASELINE_PATH.write_text(
            json.dumps(baseline_document(per_query, aggregate, run_date),
                       indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")
        updated_baseline = True

    report = {
        "date": run_date.isoformat(),
        "probes": aggregate["probes"],
        "median_result_count": aggregate["median_result_count"],
        "baseline": ("created this run" if created_baseline
                     else "updated this run" if updated_baseline
                     else baseline["created"] if baseline else None),
        "anomalies": anomalies,
    }
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Retrieval watch — {report['date']}")
        print(f"Probe set: {aggregate['probes']} queries "
              f"(golden 15 + extended 78), scope 'all', hybrid engine")
        print(f"Median ranked documents per probe: "
              f"{aggregate['median_result_count']}")
        if created_baseline:
            print("Baseline: CREATED this run "
                  "(evaluation/retrieval-baseline.json) — no delta "
                  "verdict is possible on a first run.")
        elif updated_baseline:
            print("Baseline: UPDATED this run by explicit "
                  "--update-baseline.")
        else:
            print(f"Baseline: {baseline['created']} "
                  f"(evaluation/retrieval-baseline.json)")
        if anomalies:
            print(f"\nANOMALIES: {len(anomalies)}")
            for a in anomalies:
                where = " ".join(x for x in (a.get("qid"),
                                             a.get("page")) if x)
                print(f"  [{a['signal']}] {where} — {a['detail']}")
        else:
            print("\nAnomalies: none. Retrieval distributions are "
                  "within thresholds"
                  + (" and match the baseline." if baseline else
                     " on this first (baseline) run."))
    return 1 if anomalies else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
