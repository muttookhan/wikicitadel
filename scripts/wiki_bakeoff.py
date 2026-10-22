#!/usr/bin/env python3
"""Uniform benchmark harness + bakeoff ledger (W3, 2026-10-22).

One harness pattern for every retrieval/answering CONFIGURATION
of this wiki, one uniform row-set per run, one MemScore triple
per configuration, and an append-only bakeoff ledger whose every
published figure a verifier can recompute from stored
per-question detail.

Patterns adapted with credit (per the build list's licence
route, adapt-with-credit, MIT/Apache sources):

  - the uniform ingest -> search -> evaluate harness shape and
    the MemScore triple (accuracy% / latencyMs / contextTokens,
    reported side by side, NEVER collapsed into one number) —
    mem0ai/memory-benchmarks and MemoryBench (supermemoryai);
    the triple reporter itself is the house tool
    scripts/wiki_memscore.py (Marathon R2), which this harness
    feeds and cross-checks against, not replaces;
  - the bakeoff method — a small gold-document set, a doc-gate
    read over mean scores, a per-run cost record, and a verifier
    recomputing every published figure — okf-model-bakeoff.

What this harness does NOT do: it replaces no scorer. Golden and
conflict questions are scored by wiki_benchmark.score_question;
extended and supersession (directional-slice) questions by
wiki_eval_extended.score_answerable + wiki_eval_extended
.aggregates; rerankers are built by wiki_rerank
.build_compare_rerankers; the abstention battery runs through
wiki_abstention_check's own case runners, packing and coverage
report, with the configuration injected into its pipeline; the
dense legs are wiki_dense_trial's own runs. A divergence
between a figure here and the owning instrument's own CLI on
the same configuration is a defect, never a rounding note.

Configurations are named compositions of the pipeline's real
switches (wiki_search.hybrid_rank's reranker / governance /
expansion arguments, the bm25 engine, the W1.12 usage wrapper,
the W1.2 dense fusion runs):

  house          hybrid + coverage reranker + governance on
                 (the serving defaults, exactly)
  hybrid-nogov   hybrid + coverage reranker + governance OFF
  bm25-plain     the bm25 engine alone (wiki_benchmark's path)
  cross-encoder  hybrid + cross-encoder reranker (lexical
                 stand-in scorer — no model installed; the
                 seam's own label, carried into the record)
  colbert        hybrid + ColBERT reranker (hashing stand-in,
                 same labelling)
  hyde-on        house + W3 lexical HyDE expansion stage
  usage-on       hybrid + W1.12 usage-weighted reranker over
                 the coverage base, governance on
  dense-rrf      W1.2 trial run rrf_bm25+dense_svd (RRF fusion
                 of production BM25 with the projection's SVD
                 dense leg), scored like every other config

The abstention battery pins the hybrid pipeline, so it runs
for hybrid-family configurations (with that configuration
injected) and is recorded as not-applicable — with the reason —
for bm25-plain and dense-rrf. The battery's tau is read from
evaluation/extended-baseline.json and never moved here.

Usage:
  python3 scripts/wiki_bakeoff.py run --config house \
      [--config NAME ...] [--append] [--out-dir DIR] \
      [--ledger FILE]
  python3 scripts/wiki_bakeoff.py verify [--ledger FILE]
  python3 scripts/wiki_bakeoff.py list

Run files land in evaluation/results/bakeoff-<config>.json in
the shape scripts/wiki_memscore.py already reads (top-level
aggregates / latencyMs / contextTokens). The ledger is
evaluation/bakeoff-ledger.jsonl: one JSON line per measured
configuration, hash-chained (prev_entry_sha256), append-only —
`run` never rewrites an earlier line, and `verify` recomputes
every aggregate and every MemScore component from the run
files' per-question rows and checks the chain.

Row identity: sha256 over the canonical JSON of {config spec,
corpus git HEAD + doc count, per-instrument aggregates,
per-question rank rows, battery summary, MemScore accuracy +
contextTokens}. Timestamps and the measured latency are run
metadata, excluded from identity: the same configuration on
the same corpus reproduces the same identity.

Exit codes: 0 ok · 1 verify failure · 2 usage error.
Stdlib only, no network.
"""
import argparse
import hashlib
import importlib.util
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "evaluation"
RESULTS_DIR = EVAL / "results"
LEDGER = EVAL / "bakeoff-ledger.jsonl"
TOP = 10

INSTRUMENT_FILES = {
    "golden": EVAL / "golden-questions.jsonl",
    "extended": EVAL / "extended-questions.jsonl",
    "conflict": EVAL / "conflict-questions.jsonl",
    "battery": EVAL / "abstention-battery.jsonl",
}


def _load(name, filename, base=None):
    spec = importlib.util.spec_from_file_location(
        name, (base or (ROOT / "scripts")) / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("wiki_search", "wiki_search.py")
bench = _load("wiki_benchmark", "wiki_benchmark.py")
ext = _load("wiki_eval_extended", "wiki_eval_extended.py")
rerank = _load("wiki_rerank", "wiki_rerank.py")
hyde = _load("wiki_hyde_expand", "wiki_hyde_expand.py")
usage = _load("wiki_usage_weights", "wiki_usage_weights.py")
dense = _load("wiki_dense_trial", "wiki_dense_trial.py")
memscore_mod = _load("wiki_memscore", "wiki_memscore.py")
abst = _load("wiki_abstention_check", "wiki_abstention_check.py")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path):
    return sha256_text(Path(path).read_text(encoding="utf-8"))


def git_head():
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def git_dirty():
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True).stdout
        return bool(out.strip())
    except Exception:
        return None


def load_questions(path):
    return bench.load_questions(str(path))


def relpath(p):
    p = Path(p)
    return str(p.relative_to(ROOT)) if p.is_absolute() else str(p)


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------

CONFIGS = {
    "house": {
        "engine": "hybrid", "reranker": "coverage",
        "governance": "on", "expansion": None, "usage": False,
        "dense_run": None,
        "note": "the serving defaults: hybrid_rank with the "
                "default coverage reranker and the governance "
                "artefact loaded (governance=None)",
    },
    "hybrid-nogov": {
        "engine": "hybrid", "reranker": "coverage",
        "governance": "off", "expansion": None, "usage": False,
        "dense_run": None,
        "note": "governance=False — the pre-W1.5 pipeline exactly",
    },
    "bm25-plain": {
        "engine": "bm25", "reranker": None,
        "governance": None, "expansion": None, "usage": False,
        "dense_run": None,
        "note": "the bm25 engine alone (wiki_benchmark's path)",
    },
    "cross-encoder": {
        "engine": "hybrid", "reranker": "cross-encoder",
        "governance": "on", "expansion": None, "usage": False,
        "dense_run": None,
        "note": "cross-encoder reranker over the seam's lexical "
                "stand-in scorer (no model installed)",
    },
    "colbert": {
        "engine": "hybrid", "reranker": "colbert",
        "governance": "on", "expansion": None, "usage": False,
        "dense_run": None,
        "note": "ColBERT reranker over the seam's hashing "
                "stand-in embedder (no model installed)",
    },
    "hyde-on": {
        "engine": "hybrid", "reranker": "coverage",
        "governance": "on", "expansion": "hyde-lexical",
        "usage": False, "dense_run": None,
        "note": "house + the W3 lexical HyDE expansion stage "
                "(expansion records built per question by "
                "wiki_hyde_expand.build_expansion)",
    },
    "usage-on": {
        "engine": "hybrid", "reranker": "coverage+usage",
        "governance": "on", "expansion": None, "usage": True,
        "dense_run": None,
        "note": "W1.12 usage-weighted reranker over the "
                "coverage base, built from the recorded usage "
                "registers by wiki_usage_weights itself",
    },
    "dense-rrf": {
        "engine": "dense", "reranker": None,
        "governance": None, "expansion": None, "usage": False,
        "dense_run": "rrf_bm25+dense_svd",
        "note": "W1.2 trial run: RRF fusion of production BM25 "
                "with the projection's SVD dense leg",
    },
}


class ConfigRunner:
    """Builds one configuration's rank function over a fixed
    corpus snapshot (docs + adjacency). rank(terms) ->
    [(score, relpath)] plus, for hybrid/bm25, the raw ranked
    tuples the battery's candidate construction expects."""

    def __init__(self, name, docs, adj):
        if name not in CONFIGS:
            raise ValueError(f"unknown configuration {name!r}")
        self.name = name
        self.spec = dict(CONFIGS[name])
        self.docs = docs
        self.adj = adj
        self.reranker = None
        self.reranker_note = None
        self._dense_rank = None
        if self.spec["engine"] == "hybrid":
            if self.spec["usage"]:
                events, _survey = usage.survey_usage_sources()
                corpus_keys = {usage.canon_doc(p) for p, _t in docs}
                weights = usage.build_weights(
                    events, corpus_keys=corpus_keys)
                self.reranker = usage.build_usage_reranker(
                    ws, weights, docs)
                self.reranker_note = (
                    "usage-weighted coverage reranker (W1.12), "
                    f"active pages={weights.active}")
            elif self.spec["reranker"]:
                built = rerank.build_compare_rerankers(
                    ws, [self.spec["reranker"]])
                self.reranker, self.reranker_note = built[
                    self.spec["reranker"]]
        elif self.spec["engine"] == "dense":
            import sqlite3
            conn = sqlite3.connect(":memory:")
            embedder = dense.make_embedder("svd")
            dense.build_projection_conn(conn, embedder, docs, ws)
            store = dense.ProjectionStore(conn)
            token_lists = [ws.tokenize(t) for _p, t in docs]
            runs = dense.build_runs(store, docs, adj, token_lists, ws)
            self._dense_rank = runs[self.spec["dense_run"]]

    @property
    def governance_arg(self):
        return False if self.spec["governance"] == "off" else None

    def expansion_for(self, terms):
        if not self.spec["expansion"]:
            return None
        return hyde.build_expansion(ws, list(terms), self.docs)

    def rank_raw(self, terms):
        """The pipeline's own ranked tuples, unmodified."""
        engine = self.spec["engine"]
        if engine == "bm25":
            return [(s, p, t, {}) for s, p, t in ws.bm25_rank(
                terms, self.docs)]
        if engine == "hybrid":
            return ws.hybrid_rank(
                terms, self.docs, self.adj,
                reranker=self.reranker,
                governance=self.governance_arg,
                expansion=self.expansion_for(terms))
        raise ValueError(f"rank_raw has no tuples for {engine!r}")

    def rank(self, terms):
        """[(score, relpath)] — the uniform shape every scorer
        below consumes."""
        if self.spec["engine"] == "dense":
            return self._dense_rank(list(terms))
        return [(s, relpath(p))
                for s, p, _t, _d in self.rank_raw(terms)]


# ---------------------------------------------------------------------------
# Aggregation — one formula, shared by run and verify.
# Mirrors wiki_rerank.compare_rerankers / wiki_benchmark.main
# exactly (coverage@k over must_cite_rank); the test suite
# proves this harness's house aggregates equal compare_rerankers'
# own output on the golden set.
# ---------------------------------------------------------------------------

def aggregate_bench_rows(rows):
    n = len(rows) or 1
    cov = {k: sum(1 for r in rows
                  if r["must_cite_rank"] is not None
                  and r["must_cite_rank"] <= k) / n
           for k in (1, 3, 5, 10)}
    return {
        "questions": len(rows),
        "citation_coverage": {f"@{k}": round(v, 4)
                              for k, v in cov.items()},
        "hit_rate_topk": round(
            sum(1 for r in rows if r["hit_in_topk"]) / n, 4),
        "mean_precision_at_k": round(
            sum(r["precision_at_k"] for r in rows) / n, 4),
        "mrr_must_cite": round(sum(
            1.0 / r["must_cite_rank"] for r in rows
            if r["must_cite_rank"] is not None) / n, 4),
    }


def uniform_row(scorer_row):
    """The uniform per-question row: the three keys every
    aggregate recomputes from, plus the scorer's own row
    verbatim for inspection."""
    return {
        "id": scorer_row["id"],
        "must_cite_rank": scorer_row["must_cite_rank"],
        "hit_in_topk": scorer_row["hit_in_topk"],
        "must_in_topk": scorer_row["must_in_topk"],
        "precision_at_k": scorer_row["precision_at_k"],
        "top3": scorer_row.get("top3"),
        "scorer_row": scorer_row,
    }


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

def run_bench_instrument(runner, questions):
    """Golden / conflict: wiki_benchmark.score_question over
    the configuration's ranked paths. Returns (aggregates,
    uniform rows, per-question rank latency ms)."""
    rows, lat = [], []
    for q in questions:
        terms = ws.tokenize(q["question"])
        t0 = time.perf_counter()
        ranked = runner.rank(terms)
        lat.append((time.perf_counter() - t0) * 1000.0)
        paths = [p for _s, p in ranked]
        rows.append(uniform_row(bench.score_question(q, paths, TOP)))
    return aggregate_bench_rows(rows), rows, lat


def run_ext_instrument(runner, questions):
    """Extended / supersession slice:
    wiki_eval_extended.score_answerable + its own aggregates."""
    rows = []
    for q in questions:
        ranked = runner.rank(ws.tokenize(q["question"]))
        rows.append(uniform_row(ext.score_answerable(q, ranked, TOP)))
    return ext.aggregates([r["scorer_row"] for r in rows]), rows


def run_battery(runner):
    """The abstention battery under this configuration.

    Hybrid-family only: the battery pins the hybrid pipeline,
    so the configuration is injected into the battery module's
    own wiki_search copy and its own case runners, packing,
    contract and coverage report do all the scoring. tau comes
    from the battery's own baseline file and is never moved.
    """
    if runner.spec["engine"] != "hybrid":
        return {"applicable": False,
                "note": "the battery pins the hybrid pipeline "
                        "(wiki_abstention_check header); this "
                        "configuration is not hybrid-family"}
    tau = json.loads((EVAL / "extended-baseline.json").read_text(
        encoding="utf-8")).get("abstain_threshold")
    _header, cases = abst.load_battery(str(INSTRUMENT_FILES["battery"]))
    sev_list = abst.severance.load_severance()
    standings = abst.standing.load_standings()
    docs = abst.ws.collect_docs("wiki")
    adj = abst.ws.build_link_graph(docs)

    real_rank = abst.ws.hybrid_rank
    built = {}
    if runner.spec["usage"]:
        events, _s = usage.survey_usage_sources()
        keys = {usage.canon_doc(p) for p, _t in docs}
        weights = usage.build_weights(events, corpus_keys=keys)
        built["reranker"] = usage.build_usage_reranker(
            abst.ws, weights, docs)
    elif runner.spec["reranker"]:
        built["reranker"] = rerank.build_compare_rerankers(
            abst.ws, [runner.spec["reranker"]])[
                runner.spec["reranker"]][0]
    gov = False if runner.spec["governance"] == "off" else None

    def configured_rank(terms, docs_, adj_=None, severance=None,
                        **_kw):
        expansion = None
        if runner.spec["expansion"]:
            expansion = hyde.build_expansion(
                abst.ws, list(terms), docs_)
        return real_rank(terms, docs_, adj_, severance=severance,
                         reranker=built.get("reranker"),
                         governance=gov, expansion=expansion)

    abst.ws.hybrid_rank = configured_rank
    try:
        results = []
        for case in cases:
            if case["mode"] == "search":
                ok, observed, detail = abst.run_search_case(
                    case, docs, adj, sev_list, standings, tau)
            elif case["mode"] == "candidates":
                ok, observed, detail = abst.run_candidates_case(
                    case, sev_list, standings)
            elif case["mode"] == "record":
                ok, observed, detail = abst.run_record_case(case)
            else:
                ok, observed, detail = (
                    False, "error", f"unknown mode {case['mode']}")
            results.append({"id": case["id"],
                            "kind": case["case_kind"],
                            "expected": case["expected_verdict"],
                            "observed": observed, "pass": ok,
                            "detail": detail})
    finally:
        abst.ws.hybrid_rank = real_rank
    passed = sum(1 for r in results if r["pass"])
    return {
        "applicable": True,
        "tau": tau,
        "cases": len(results),
        "passed": passed,
        "all_pass": passed == len(results),
        "coverage": abst.coverage_report(results),
        "per_case": results,
    }


def packed_context_tokens(runner, questions):
    """Per-question context size: the battery's own candidate
    construction (wiki_abstention_check._candidates_from_ranked)
    over the configuration's top-10, packed by the Ask
    pipeline's own evidence packer with severance + standings;
    the token count (wiki_search.tokenize) of the packed
    passages. This is the context an answer under this
    configuration would be composed from."""
    sev_list = abst.severance.load_severance()
    standings = abst.standing.load_standings()
    by_rel = {relpath(p): (p, t) for p, t in runner.docs}
    out = []
    for q in questions:
        terms = ws.tokenize(q["question"])
        if runner.spec["engine"] == "dense":
            raw = []
            for s, rp in runner.rank(terms)[:TOP]:
                p, t = by_rel[rp]
                raw.append((s, p, t, {}))
        else:
            raw = runner.rank_raw(terms)
        candidates = abst._candidates_from_ranked(raw, terms)
        pack = abst.packing.pack_evidence(
            candidates, severance=sev_list, standings=standings)
        out.append(sum(len(ws.tokenize(e["passage"]))
                       for e in pack["packed"]))
    return out


# ---------------------------------------------------------------------------
# Run assembly
# ---------------------------------------------------------------------------

def run_configuration(name, docs=None, adj=None):
    """Measure one configuration over every instrument and
    assemble the run record (the shape wiki_memscore.py reads:
    top-level aggregates / latencyMs / contextTokens)."""
    if docs is None:
        docs = ws.collect_docs("wiki")
    if adj is None:
        adj = ws.build_link_graph(docs)
    runner = ConfigRunner(name, docs, adj)
    golden_q = load_questions(INSTRUMENT_FILES["golden"])
    extended_all = load_questions(INSTRUMENT_FILES["extended"])
    supersession_q = [q for q in extended_all
                      if q.get("slice") == "directional"]
    conflict_q = [q for q in load_questions(INSTRUMENT_FILES["conflict"])
                  if q.get("kind") != "header"]

    instruments = {}
    g_agg, g_rows, g_lat = run_bench_instrument(runner, golden_q)
    instruments["golden"] = {"aggregates": g_agg, "per_question": g_rows}
    e_agg, e_rows = run_ext_instrument(runner, extended_all)
    instruments["extended"] = {"aggregates": e_agg,
                               "per_question": e_rows}
    s_agg, s_rows = run_ext_instrument(runner, supersession_q)
    instruments["supersession"] = {"aggregates": s_agg,
                                   "per_question": s_rows}
    c_agg, c_rows, _lat = run_bench_instrument(runner, conflict_q)
    cq001 = next((r for r in c_rows if r["id"] == "CQ-001"), None)
    instruments["conflict"] = {
        "aggregates": c_agg, "per_question": c_rows,
        "cq001_must_cite_rank": cq001["must_cite_rank"] if cq001
        else None}
    battery = run_battery(runner)
    ctx_tokens = packed_context_tokens(runner, golden_q)

    latency_ms = round(statistics.median(g_lat), 3)
    context_tokens = int(statistics.median(ctx_tokens))
    run = {
        "kind": "bakeoff-run",
        "version": 1,
        "label": f"bakeoff-{name}",
        "config": {"name": name, "spec": runner.spec,
                   "reranker_note": runner.reranker_note},
        "corpus": {"git_head": git_head(), "dirty": git_dirty(),
                   "docs": len(docs), "scope": "wiki/"},
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "instruments": instruments,
        "battery": battery,
        "aggregates": g_agg,
        "latencyMs": latency_ms,
        "contextTokens": context_tokens,
        "measurements": {
            "latency": {
                "definition": "median per-question rank-call "
                              "wall time over the golden set, "
                              "ms, this machine, this run — a "
                              "measurement, excluded from row "
                              "identity",
                "per_question_ms": [round(v, 3) for v in g_lat],
                "median_ms": latency_ms},
            "context_tokens": {
                "definition": "median over the golden set of "
                              "the token count (wiki_search "
                              ".tokenize) of the passages the "
                              "Ask evidence packer packs from "
                              "this configuration's top-10 "
                              "(severance + standings applied)",
                "per_question": ctx_tokens,
                "median": context_tokens},
        },
    }
    triple = memscore_mod.memscore(run, source=run["label"])
    run["memscore"] = {
        "accuracy": {
            "metric": "golden citation coverage@10",
            "value": triple["accuracy"],
            "percent": round(triple["accuracy"] * 100, 2)
            if isinstance(triple["accuracy"], (int, float))
            else None},
        "latencyMs": {"metric": "median per-question "
                                 "retrieval latency (ms)",
                      "value": triple["latencyMs"]},
        "contextTokens": {"metric": "median packed-evidence "
                                     "context (tokens)",
                          "value": triple["contextTokens"]},
        "note": "the MemScore triple — three numbers, reported "
                "side by side, never collapsed into one",
        "via": "scripts/wiki_memscore.py extract_runs over "
               "this run record",
    }
    run["row_identity"] = row_identity(run)
    return run


def row_identity(run):
    """sha256 over everything that makes this measurement the
    measurement it is — config, corpus, figures, per-question
    rank rows, battery outcome, MemScore accuracy + context.
    Excluded: timestamps and measured latency."""
    core = {
        "config": run["config"],
        "corpus": {"git_head": run["corpus"]["git_head"],
                   "docs": run["corpus"]["docs"]},
        "instruments": {
            name: {"aggregates": inst["aggregates"],
                   "per_question": [
                       {"id": r["id"],
                        "must_cite_rank": r["must_cite_rank"],
                        "hit_in_topk": r["hit_in_topk"],
                        "precision_at_k": r["precision_at_k"]}
                       for r in inst["per_question"]]}
            for name, inst in run["instruments"].items()},
        "battery": ({"applicable": run["battery"]["applicable"],
                     "passed": run["battery"].get("passed"),
                     "cases": run["battery"].get("cases")}
                    if run["battery"].get("applicable") else
                    {"applicable": False}),
        "memscore_accuracy": run["memscore"]["accuracy"]["value"],
        "memscore_context_tokens":
            run["memscore"]["contextTokens"]["value"],
    }
    return sha256_text(canonical(core))


# ---------------------------------------------------------------------------
# Ledger — append-only, hash-chained; verify recomputes everything
# ---------------------------------------------------------------------------

def instrument_meta():
    # An instrument file a tree does not carry (e.g. the public
    # tree has no abstention-battery instrument) is recorded as
    # missing with a null hash — named on the ledger entry, never
    # a crash and never a fabricated hash. (Coordinator glue,
    # 2026-10-22, applied identically in both trees.)
    out = {}
    for name, path in INSTRUMENT_FILES.items():
        if path.is_file():
            out[name] = {"file": f"evaluation/{path.name}",
                         "sha256": file_sha256(path)}
        else:
            out[name] = {"file": f"evaluation/{path.name}",
                         "sha256": None, "missing": True}
    return out


def ledger_summaries(run):
    out = {}
    for name, inst in run["instruments"].items():
        entry = {"aggregates": inst["aggregates"]}
        if "cq001_must_cite_rank" in inst:
            entry["cq001_must_cite_rank"] = inst[
                "cq001_must_cite_rank"]
        out[name] = entry
    bat = run["battery"]
    out["battery"] = ({"applicable": True, "tau": bat["tau"],
                       "cases": bat["cases"],
                       "passed": bat["passed"],
                       "all_pass": bat["all_pass"],
                       "coverage": bat["coverage"]}
                      if bat.get("applicable") else
                      {"applicable": False, "note": bat["note"]})
    return out


def append_to_ledger(run, run_file_rel, ledger_path=LEDGER):
    ledger_path = Path(ledger_path)
    prev = None
    if ledger_path.is_file():
        lines = [l for l in ledger_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        if lines:
            prev = json.loads(lines[-1]).get("entry_sha256")
    entry = {
        "kind": "bakeoff-entry",
        "version": 1,
        "recorded_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "config": run["config"],
        "corpus": run["corpus"],
        "instruments_meta": instrument_meta(),
        "summaries": ledger_summaries(run),
        "memscore": run["memscore"],
        "run_file": run_file_rel,
        "row_identity": run["row_identity"],
        "prev_entry_sha256": prev,
    }
    entry["entry_sha256"] = sha256_text(canonical(
        {k: v for k, v in entry.items() if k != "entry_sha256"}))
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _recompute_summaries(run):
    """Every published figure, recomputed from the run file's
    stored per-question rows with the instruments' own
    aggregation (extended/supersession via
    wiki_eval_extended.aggregates over the scorer rows)."""
    out = {}
    for name, inst in run["instruments"].items():
        rows = inst["per_question"]
        if name in ("extended", "supersession"):
            agg = ext.aggregates([r["scorer_row"] for r in rows])
        else:
            agg = aggregate_bench_rows(rows)
        entry = {"aggregates": agg}
        if "cq001_must_cite_rank" in inst:
            entry["cq001_must_cite_rank"] = inst[
                "cq001_must_cite_rank"]
        out[name] = entry
    bat = run["battery"]
    out["battery"] = ({"applicable": True, "tau": bat["tau"],
                       "cases": bat["cases"],
                       "passed": bat["passed"],
                       "all_pass": bat["all_pass"],
                       "coverage": bat["coverage"]}
                      if bat.get("applicable") else
                      {"applicable": False, "note": bat["note"]})
    return out


def verify_ledger(ledger_path=LEDGER):
    """Returns (ok, findings). Checks the hash chain and, for
    every entry, recomputes the aggregates, the battery
    summary, the MemScore accuracy + context tokens and the
    medians from the run file's per-question detail."""
    ledger_path = Path(ledger_path)
    if not ledger_path.is_file():
        return False, [f"ledger missing: {ledger_path}"]
    findings = []
    prev = None
    entries = []
    for i, line in enumerate(ledger_path.read_text(
            encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"line {i + 1}: unparseable ({exc})")
            continue
        entries.append(entry)
        expect = sha256_text(canonical(
            {k: v for k, v in entry.items()
             if k != "entry_sha256"}))
        if entry.get("entry_sha256") != expect:
            findings.append(
                f"line {i + 1} ({entry.get('config', {}).get('name')}): "
                "entry_sha256 mismatch — the line was altered")
        if entry.get("prev_entry_sha256") != prev:
            findings.append(
                f"line {i + 1}: prev_entry_sha256 does not chain "
                "to the previous entry")
        prev = entry.get("entry_sha256")
    for entry in entries:
        name = entry.get("config", {}).get("name")
        run_path = ROOT / entry["run_file"]
        if not run_path.is_file():
            findings.append(f"{name}: run file missing: "
                            f"{entry['run_file']}")
            continue
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("row_identity") != entry.get("row_identity"):
            findings.append(f"{name}: row_identity differs from "
                            "the run file")
        if row_identity(run) != entry.get("row_identity"):
            findings.append(f"{name}: row_identity does not "
                            "recompute from the run file's rows")
        recomputed = _recompute_summaries(run)
        if recomputed != entry.get("summaries"):
            findings.append(f"{name}: published summaries do not "
                            "recompute from per-question rows")
            for key in recomputed:
                if recomputed[key] != entry["summaries"].get(key):
                    findings.append(f"  {name}/{key}: published "
                                    f"{entry['summaries'].get(key)} "
                                    f"!= recomputed {recomputed[key]}")
        ms = entry.get("memscore", {})
        gold = run["instruments"]["golden"]["aggregates"]
        if ms.get("accuracy", {}).get("value") != gold[
                "citation_coverage"]["@10"]:
            findings.append(f"{name}: MemScore accuracy does not "
                            "match the golden coverage@10")
        meas = run.get("measurements", {})
        lat = meas.get("latency", {}).get("per_question_ms") or []
        if lat and round(statistics.median(lat), 3) != ms.get(
                "latencyMs", {}).get("value"):
            findings.append(f"{name}: MemScore latencyMs does "
                            "not recompute as the median of the "
                            "stored per-question latencies")
        ctx = meas.get("context_tokens", {}).get("per_question") or []
        if ctx and int(statistics.median(ctx)) != ms.get(
                "contextTokens", {}).get("value"):
            findings.append(f"{name}: MemScore contextTokens "
                            "does not recompute as the median of "
                            "the stored per-question token counts")
    return not findings, findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_run(run):
    ms = run["memscore"]
    bat = run["battery"]
    bat_txt = (f"{bat['passed']}/{bat['cases']} (tau={bat['tau']})"
               if bat.get("applicable") else "n/a (not hybrid)")
    print(f"[{run['config']['name']}] "
          f"golden cov@10={run['aggregates']['citation_coverage']['@10']:.4f} "
          f"MRR={run['aggregates']['mrr_must_cite']:.4f}  "
          f"extended cov@10={run['instruments']['extended']['aggregates']['citation_coverage']['@10']:.4f}  "
          f"supersession cov@10={run['instruments']['supersession']['aggregates']['citation_coverage']['@10']:.4f}  "
          f"conflict cov@10={run['instruments']['conflict']['aggregates']['citation_coverage']['@10']:.4f} "
          f"(CQ-001 rank {run['instruments']['conflict']['cq001_must_cite_rank']})  "
          f"battery {bat_txt}")
    print(f"    MemScore: accuracy {ms['accuracy']['percent']}% "
          f"({ms['accuracy']['metric']}) / latencyMs "
          f"{ms['latencyMs']['value']} / contextTokens "
          f"{ms['contextTokens']['value']}  "
          f"identity {run['row_identity'][:12]}…")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Uniform benchmark harness + bakeoff ledger.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run", help="measure configurations")
    rp.add_argument("--config", action="append", required=True,
                    choices=sorted(CONFIGS))
    rp.add_argument("--append", action="store_true",
                    help="append each run to the ledger")
    rp.add_argument("--out-dir", default=str(RESULTS_DIR))
    rp.add_argument("--ledger", default=str(LEDGER))
    vp = sub.add_parser("verify", help="recompute the ledger")
    vp.add_argument("--ledger", default=str(LEDGER))
    sub.add_parser("list", help="configurations + ledger state")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print("configurations:")
        for name, spec in CONFIGS.items():
            print(f"  {name:14s} {spec['note']}")
        ledger_path = Path(args.ledger) if hasattr(
            args, "ledger") else LEDGER
        if Path(ledger_path).is_file():
            lines = [l for l in Path(ledger_path).read_text(
                encoding="utf-8").splitlines() if l.strip()]
            print(f"ledger: {ledger_path} — {len(lines)} entries")
            for line in lines:
                e = json.loads(line)
                print(f"  {e['recorded_at']}  "
                      f"{e['config']['name']:14s} "
                      f"identity {e['row_identity'][:12]}…")
        else:
            print(f"ledger: {ledger_path} — not created yet")
        return 0

    if args.cmd == "verify":
        ok, findings = verify_ledger(args.ledger)
        if ok:
            n = sum(1 for l in Path(args.ledger).read_text(
                encoding="utf-8").splitlines() if l.strip())
            print(f"verify: OK — {n} ledger entries, every "
                  "published figure recomputes from stored "
                  "per-question detail; chain intact")
            return 0
        print("verify: FAILED")
        for f in findings:
            print(f"  - {f}")
        return 1

    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in args.config:
        run = run_configuration(name, docs, adj)
        out_path = out_dir / f"bakeoff-{name}.json"
        out_path.write_text(json.dumps(
            run, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        _print_run(run)
        print(f"    wrote {out_path}")
        if args.append:
            entry = append_to_ledger(
                run, str(out_path.relative_to(ROOT))
                if out_path.is_relative_to(ROOT) else str(out_path),
                args.ledger)
            print(f"    ledger += {name} "
                  f"(entry {entry['entry_sha256'][:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
