#!/usr/bin/env python3
"""wiki_usage_weights.py — usage-weighted link strength with a
self-reinforcement guardrail (W1.12, 2026-10-22).

The wiki graph's edges are structural: a wikilink counts the
same whether the page it points at is served every day or has
never been read. This module adds the missing signal — RECORDED
usage — as a bounded, evaporating weight on pages and edges,
shipped as an OPT-IN ranker input behind the reranker seam
(scripts/wiki_rerank.py): pass the reranker built here to
hybrid_rank(reranker=...) and pool candidates gain a usage
lift; construct nothing and the shipped ranking is untouched,
byte for byte (this module edits no existing file and the
default path never imports it).

THE FORMULA (deterministic; every weight reproducible from the
recorded inputs + the as-of date):

    raw(page)  = Σ_day min(deposits(page, day), DAILY_DEPOSIT_CAP)
                   · 2^(−age_days(day) / HALF_LIFE_DAYS)
    lift(page) = MAX_USAGE_LIFT · raw / (raw + SATURATION_K)
    applied    = lift(page)  if base relevance ≥ RELEVANCE_GATE
                 0           otherwise (the relevance gate)
    multiplier_final = multiplier_base · (1 + applied)

with HALF_LIFE_DAYS = 30, DAILY_DEPOSIT_CAP = 3.0,
SATURATION_K = 10.0, MAX_USAGE_LIFT = 0.10 (a quarter of the
seam's 0.40 lift budget) and RELEVANCE_GATE =
wiki_rerank.DEFAULT_RELEVANCE_CUTOFF (0.575 — the seam's own
calibrated cut-off, fitted by W1.1 against the abstention
gate's tau; reused, not refitted). Edge strength is the same
shape over edge deposits: strength(a→b) = 1 + lift_edge(a→b).
Never-traversed pages/edges have raw = 0: their pheromone has
fully evaporated and they keep exactly their structural weight.

THE GUARDRAIL (why runaway self-reinforcement is mathematically
impossible, not merely unlikely):

  1. Bounded stock. Per-day deposits are capped, so even an
     infinite daily-max history gives raw ≤ CAP / (1 − 2^(−1/30))
     ≈ 131.4 (RAW_SUPREMUM below, computed exactly in code),
     for events dated on or before the as-of date — the standard
     build sets as-of to the latest event date, so no deposit
     is ever future-dated in it.
  2. Saturating response. lift is increasing in raw and bounded
     by MAX · RAW_SUP / (RAW_SUP + K) ≈ 0.0929 for ANY history.
     The multiplier ratio between the most-used page in the
     world and a never-used one is < 1.0929, forever.
  3. Evaporation. With no fresh deposits, raw shrinks by 2^(−n)
     over n half-lives (300 quiet days ⇒ raw / 1024). Popularity
     must be re-earned continuously; no rank is permanent.
  4. The feedback loop is a contraction: each day adds at most
     CAP of fresh deposit while the stock decays by the factor
     2^(−1/30) ≈ 0.977, so serve→deposit→lift→serve converges
     to the fixed point in (1) instead of diverging.
  5. The relevance gate. Usage never rescues a candidate the
     base reranker rates below the calibrated cut-off: the lift
     is exactly 0 there, so the signal can only reorder and
     boost among candidates already rated usable evidence —
     it cannot push a sub-gate candidate across the abstention
     threshold on popularity alone (the flip thresholds without
     the gate are measured in the build note).

USAGE SOURCES SURVEYED (2026-10-22, honest): this tree records
almost no serving telemetry. What exists:
  - evaluation/use-log.jsonl — filed-back use events (a page
    built FROM sources/supports/contradicts): the traversal
    record with dates. SEEDED EMPTY (header only) today.
  - evaluation/research-log.jsonl — claim searches: date, the
    page served, the query. 7 events today.
  - Ask traces (tools/ask/trace.py's *.traces.jsonl) — the
    machinery exists; ZERO trace files exist on disk today.
    The loader reads them if they ever land; trace records
    carry no date, and undated events are COUNTED in the
    survey but NEVER deposited (no invented dates).
  - Lens serving — the Lens is a static build; it keeps no
    serving log at all. Gateway ledger — tool-call bookkeeping,
    no page-serve records.
So today's real weights rest on the 7 research searches alone
and every page lift is at most a fraction of a percent: the
signal is built and measured, and its data is thin. That gap
is recorded here, not papered over.

Deposits: use-event sources/supports/contradicts = 1.0 each
(usage, not endorsement — a contradicted source was still
traversed) plus an edge deposit filed-page → each; research
search served page = 0.5; Ask trace packed page = 1.0,
retrieved-but-not-packed = 0.25 (both moot until traces exist
and only if a future trace shape carries a date).

CLI:
    python3 scripts/wiki_usage_weights.py survey
    python3 scripts/wiki_usage_weights.py weights [--as-of D]
        [--out evaluation/usage-weights.json]
    python3 scripts/wiki_usage_weights.py search "query"
        [--usage] [--top N]
    python3 scripts/wiki_usage_weights.py gate-check
        [--adversarial targeted|uniform]
    python3 scripts/wiki_usage_weights.py simulate

Attribution (adapt-with-credit; pattern adapted, code ours):
the deposit-and-evaporate pheromone weighting of links follows
Wrste/pheromone-network (via the Round 7 deep-dive candidates
on usage-weighted link strength). The saturating response, the
daily deposit cap, the relevance gate, the survey discipline
and all code are this tree's own. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- the shipped constants (see the docstring for the proof) ---
HALF_LIFE_DAYS = 30.0
DAILY_DEPOSIT_CAP = 3.0
SATURATION_K = 10.0
MAX_USAGE_LIFT = 0.10

USE_FIELD_DEPOSIT = 1.0
RESEARCH_DEPOSIT = 0.5
TRACE_PACKED_DEPOSIT = 1.0
TRACE_RETRIEVED_DEPOSIT = 0.25

# The exact supremum of raw under a daily-capped, half-life
# decayed deposit stream: CAP · Σ_{k≥0} 2^(−k/HL)
# = CAP / (1 − 2^(−1/HL)).
RAW_SUPREMUM = DAILY_DEPOSIT_CAP / (1.0 - 0.5 ** (1.0 / HALF_LIFE_DAYS))
LIFT_SUPREMUM = MAX_USAGE_LIFT * RAW_SUPREMUM / (RAW_SUPREMUM + SATURATION_K)


def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Page identity
# ---------------------------------------------------------------------------

def canon_page(raw):
    """Canonical page key for a recorded page reference: drop a
    trailing anchor suffix (" (§2)"), the .md suffix and any
    leading ./ or wiki/ — 'wiki/syntheses/x.md' and
    'syntheses/x' are the same key. Corpus docs canonicalise
    through the same function (see canon_doc), so a recorded
    reference matches its doc by construction.
    """
    s = str(raw).strip()
    if " (" in s:
        s = s.split(" (", 1)[0].strip()
    if s.startswith("./"):
        s = s[2:]
    if s.endswith(".md"):
        s = s[:-3]
    if s.startswith("wiki/"):
        s = s[5:]
    return s


def canon_doc(path):
    """Canonical key for a corpus doc path (a Path under ROOT,
    as collect_docs returns): repo-relative, wiki/ and .md
    stripped — the same form canon_page produces."""
    p = Path(path)
    try:
        rel = str(p.relative_to(ROOT))
    except ValueError:
        rel = str(p)
    return canon_page(rel)


# ---------------------------------------------------------------------------
# Events: (date|None, page, amount, source, edge_from|None)
# ---------------------------------------------------------------------------

class Event:
    def __init__(self, when, page, amount, source, edge_from=None):
        self.when = when            # datetime.date or None (undated)
        self.page = page            # canonical page key
        self.amount = amount
        self.source = source
        self.edge_from = edge_from  # canonical key or None

    def __repr__(self):
        return (f"Event({self.when}, {self.page!r}, {self.amount}, "
                f"{self.source!r}, edge_from={self.edge_from!r})")


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def events_from_record(obj, source):
    """One recorded JSON object -> its usage Events. Kinds:
    'use-event' (the use-log), 'search' (the research log),
    'ask-trace' (Ask trace records), 'usage-event' (a generic
    {date, page, amount, edge_from} line — the fixture/future
    shape). Headers and unknown kinds yield nothing."""
    kind = obj.get("kind")
    out = []
    if kind == "use-event":
        when = _parse_date(obj.get("date"))
        origin = canon_page(obj.get("page", "")) if obj.get("page") \
            else None
        for field in ("sources", "supports", "contradicts"):
            for pg in obj.get(field) or []:
                out.append(Event(when, canon_page(pg),
                                 USE_FIELD_DEPOSIT, source,
                                 edge_from=origin))
    elif kind == "search":
        if obj.get("page"):
            out.append(Event(_parse_date(obj.get("date")),
                             canon_page(obj["page"]),
                             RESEARCH_DEPOSIT, source))
    elif kind == "ask-trace":
        when = _parse_date(obj.get("date") or obj.get("timestamp"))
        packing = obj.get("packing") or {}
        packed = {p.get("page") for p in packing.get("packed") or []
                  if p.get("page")}
        for pg in packed:
            out.append(Event(when, canon_page(pg),
                             TRACE_PACKED_DEPOSIT, source))
        for pid in obj.get("retrieved_ids") or []:
            if pid not in packed:
                out.append(Event(when, canon_page(pid),
                                 TRACE_RETRIEVED_DEPOSIT, source))
    elif kind == "usage-event":
        out.append(Event(_parse_date(obj.get("date")),
                         canon_page(obj.get("page", "")),
                         float(obj.get("amount", 1.0)), source,
                         edge_from=(canon_page(obj["edge_from"])
                                    if obj.get("edge_from") else None)))
    return out


def load_events_from_jsonl(path, source):
    events = []
    p = Path(path)
    if not p.is_file():
        return events
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.extend(events_from_record(json.loads(line), source))
    return events


def survey_usage_sources(root=ROOT):
    """Every recorded usage source in the tree, honestly
    counted. Returns (events, survey): the depositable event
    stream plus per-source counts (records seen, events,
    dated/undated)."""
    events = []
    survey = {}

    def _add(name, path, records):
        evs = []
        for obj in records:
            evs.extend(events_from_record(obj, name))
        events.extend(evs)
        survey[name] = {
            "path": str(path),
            "records": len(records),
            "events": len(evs),
            "dated": sum(1 for e in evs if e.when is not None),
            "undated": sum(1 for e in evs if e.when is None),
        }

    for name, rel in (("use-log", "evaluation/use-log.jsonl"),
                      ("research-log", "evaluation/research-log.jsonl")):
        path = root / rel
        records = []
        if path.is_file():
            records = [json.loads(l) for l in
                       path.read_text(encoding="utf-8").splitlines()
                       if l.strip()]
        _add(name, path, records)

    trace_files = sorted(root.glob("**/*.traces.jsonl"))
    records = []
    for tf in trace_files:
        records.extend(json.loads(l) for l in
                       tf.read_text(encoding="utf-8").splitlines()
                       if l.strip())
    _add("ask-traces", f"{len(trace_files)} trace file(s)", records)
    survey["ask-traces"]["files"] = len(trace_files)
    return events, survey


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

def decay(age_days):
    """The evaporation factor for a deposit age_days old:
    2^(−age / HALF_LIFE_DAYS). Future-dated deposits clamp to
    age 0 (full strength, never more)."""
    age = max(0.0, float(age_days))
    return 0.5 ** (age / HALF_LIFE_DAYS)


def lift_from_raw(raw):
    """The saturating response: [0, ∞) → [0, MAX_USAGE_LIFT)."""
    if raw <= 0.0:
        return 0.0
    return MAX_USAGE_LIFT * raw / (raw + SATURATION_K)


class UsageWeights:
    """A reproducible snapshot: page/edge raw pheromone and the
    lifts they imply, computed from an event list as of a date.
    Build it fresh to refresh it (the projection-rebuild
    pattern); two builds from the same events + as-of are
    byte-identical (see to_dict)."""

    def __init__(self, events, as_of, corpus_keys=None):
        self.as_of = as_of
        self.survey_counts = {
            "events_total": len(events),
            "events_dated": 0, "events_undated": 0,
            "deposits_matched": 0, "deposits_unmatched": 0,
        }
        page_days = {}   # page -> {date: summed deposits}
        edge_days = {}   # (frm, to) -> {date: summed deposits}
        for e in events:
            if e.when is None:
                self.survey_counts["events_undated"] += 1
                continue
            self.survey_counts["events_dated"] += 1
            if corpus_keys is not None:
                if e.page in corpus_keys:
                    self.survey_counts["deposits_matched"] += 1
                else:
                    self.survey_counts["deposits_unmatched"] += 1
            pd = page_days.setdefault(e.page, {})
            pd[e.when] = pd.get(e.when, 0.0) + e.amount
            if e.edge_from and e.edge_from != e.page:
                ed = edge_days.setdefault((e.edge_from, e.page), {})
                ed[e.when] = ed.get(e.when, 0.0) + e.amount
        self.page_raw = {pg: self._raw(days)
                         for pg, days in page_days.items()}
        self.edge_raw = {et: self._raw(days)
                         for et, days in edge_days.items()}
        # zero-raw pages (possible only via zero-amount events)
        # carry no signal; drop them so `active` is honest.
        self.page_raw = {k: v for k, v in self.page_raw.items()
                         if v > 0.0}
        self.edge_raw = {k: v for k, v in self.edge_raw.items()
                         if v > 0.0}

    def _raw(self, days):
        total = 0.0
        for when, amount in days.items():
            capped = min(amount, DAILY_DEPOSIT_CAP)
            total += capped * decay((self.as_of - when).days)
        return total

    @property
    def active(self):
        """True when any page carries a nonzero lift."""
        return any(lift_from_raw(v) > 0.0 for v in self.page_raw.values())

    def page_lift(self, page):
        """The usage lift for a page key or a doc path."""
        key = page if isinstance(page, str) and page in self.page_raw \
            else canon_page(page) if isinstance(page, str) \
            else canon_doc(page)
        return lift_from_raw(self.page_raw.get(key, 0.0))

    def raw_of(self, page):
        key = page if isinstance(page, str) and page in self.page_raw \
            else canon_page(page) if isinstance(page, str) \
            else canon_doc(page)
        return self.page_raw.get(key, 0.0)

    def edge_strength(self, frm, to):
        """1.0 (structural) + the edge's evaporating usage lift."""
        key = (canon_page(frm), canon_page(to))
        return 1.0 + lift_from_raw(self.edge_raw.get(key, 0.0))

    def to_dict(self):
        pages = [{"page": pg, "raw": round(v, 6),
                  "lift": round(lift_from_raw(v), 6)}
                 for pg, v in sorted(self.page_raw.items(),
                                     key=lambda kv: (-kv[1], kv[0]))]
        edges = [{"from": f, "to": t, "raw": round(v, 6),
                  "strength": round(1.0 + lift_from_raw(v), 6)}
                 for (f, t), v in sorted(self.edge_raw.items(),
                                         key=lambda kv: (-kv[1], kv[0]))]
        return {
            "kind": "usage-weights",
            "as_of": self.as_of.isoformat(),
            "constants": {
                "half_life_days": HALF_LIFE_DAYS,
                "daily_deposit_cap": DAILY_DEPOSIT_CAP,
                "saturation_k": SATURATION_K,
                "max_usage_lift": MAX_USAGE_LIFT,
                "raw_supremum": round(RAW_SUPREMUM, 4),
                "lift_supremum": round(LIFT_SUPREMUM, 6),
            },
            "counts": dict(self.survey_counts),
            "pages": pages,
            "edges": edges,
        }


def build_weights(events, as_of=None, corpus_keys=None):
    if as_of is None:
        dated = [e.when for e in events if e.when is not None]
        as_of = max(dated) if dated else date.today()
    return UsageWeights(events, as_of, corpus_keys=corpus_keys)


# ---------------------------------------------------------------------------
# The seam consumer: a wrapping reranker
# ---------------------------------------------------------------------------

def _load_rerank():
    return _load_sibling("wiki_rerank_for_usage", "wiki_rerank.py")


class UsageWeightedReranker:
    """A wiki_rerank.Reranker wrapping any base reranker: the
    base signal's multiplier gains the page's usage lift,
    (1 + applied), with applied = 0 below the relevance gate.
    The base RELEVANCE is passed through unchanged — the
    calibrated relevance scale (and the below_cutoff flag the
    abstention surface reads) stays the base reranker's own;
    usage acts only through the multiplier, inside the seam's
    'a swapped reranker may only scale pool candidates'
    contract. Structural (non-dataclass) like the seam's own
    classes, for the same loader reason."""

    name = "coverage+usage"
    kind = "usage-weighted"

    def __init__(self, base, weights, docs=None, relevance_gate=None):
        rr = _load_rerank()
        self.base = base
        self.weights = weights
        self.relevance_gate = rr.DEFAULT_RELEVANCE_CUTOFF \
            if relevance_gate is None else relevance_gate
        self._page_by_index = {}
        if docs:
            for i, (p, _t) in enumerate(docs):
                self._page_by_index[i] = canon_doc(p)
        self.name = f"{getattr(base, 'name', 'base')}+usage"

    def page_for_key(self, key):
        if key in self._page_by_index:
            return self._page_by_index[key]
        return None

    def applied_lift(self, key, base_relevance):
        """The lift that will be applied to a candidate: the
        page's lift if the candidate clears the relevance gate,
        else exactly 0."""
        page = self.page_for_key(key)
        if page is None:
            return 0.0, 0.0, "no-page"
        raw = self.weights.raw_of(page)
        if raw <= 0.0:
            return 0.0, 0.0, "no-usage"
        if base_relevance < self.relevance_gate:
            return raw, 0.0, "below-cutoff"
        return raw, self.weights.page_lift(page), "applied"

    def rerank(self, query_terms, candidates):
        base_signals = self.base.rerank(query_terms, candidates)
        out = {}
        for cand in candidates:
            key = cand["key"]
            sig = base_signals.get(key)
            if sig is None:
                continue
            raw, applied, gate = self.applied_lift(key, sig.relevance)
            signals = dict(sig.signals)
            signals.update({
                "usage_raw": round(raw, 6),
                "usage_lift": round(applied, 6),
                "usage_gate": gate,
            })
            out[key] = type(sig)(
                multiplier=sig.multiplier * (1.0 + applied),
                relevance=sig.relevance,
                signals=signals)
        return out


def build_usage_reranker(ws, weights, docs, base_name="coverage"):
    """The factory hybrid_rank callers use: the base reranker
    built exactly as wiki_rerank.build_compare_rerankers builds
    it (the seam's own constants from wiki_search), wrapped in
    the usage signal. `docs` is the same list passed to
    hybrid_rank — the seam's candidate keys are doc indices, so
    the wrapper resolves them through it."""
    rr = _load_rerank()
    if base_name == "coverage":
        base = rr.get_reranker(
            "coverage", coverage_w=ws.RERANK_COVERAGE_W,
            title_w=ws.RERANK_TITLE_W,
            max_lift=ws.RERANK_COVERAGE_W + ws.RERANK_TITLE_W,
            tokenize=ws.tokenize)
    else:
        base = rr.get_reranker(base_name, tokenize=ws.tokenize)
    return UsageWeightedReranker(base, weights, docs=docs)


# ---------------------------------------------------------------------------
# The gate harness: the pinned battery, run with the signal on
# ---------------------------------------------------------------------------

def _run_battery_with_weights(weights, out_path=None):
    """Run the abstention battery's OWN runner (imported, its
    hybrid_rank wrapped to inject the usage reranker) and
    return (passed, total, per-case results). The instrument
    is the pinned one; only the reranker argument changes."""
    ws_mod = _load_sibling("wiki_search_for_usage_gate",
                           "wiki_search.py")
    battery = _load_sibling("wiki_abstention_for_usage_gate",
                            "wiki_abstention_check.py")
    docs_holder = {}

    def wrapped(terms, docs, adj=None, severance=None, **kw):
        if "reranker" not in kw:
            kw["reranker"] = build_usage_reranker(
                battery.ws, weights, docs)
        return ws_mod.hybrid_rank(terms, docs, adj,
                                  severance=severance, **kw)

    orig = battery.ws.hybrid_rank
    battery.ws.hybrid_rank = wrapped
    try:
        argv = ["wiki_abstention_check.py"]
        tmp_out = out_path
        if tmp_out:
            argv += ["--out", str(tmp_out)]
        rc = battery.main(argv)
    finally:
        battery.ws.hybrid_rank = orig
    results = []
    if tmp_out and Path(tmp_out).is_file():
        results = json.loads(Path(tmp_out).read_text(
            encoding="utf-8"))["results"]
    passed = sum(1 for r in results if r["pass"])
    return passed, len(results), results, rc


def adversarial_events(mode, as_of):
    """Synthetic worst-case usage: every relevant page deposited
    at the daily cap for a full year ending at as_of.
    'targeted': only the battery search cases' current top-1
    pages (the dangerous direction for the tau gate).
    'uniform': every corpus page. Returns an event list."""
    ws = _load_sibling("wiki_search_for_usage_adv", "wiki_search.py")
    docs = ws.collect_docs("wiki")
    pages = set()
    if mode == "uniform":
        pages = {canon_doc(p) for p, _t in docs}
    elif mode == "targeted":
        battery_path = ROOT / "evaluation" / "abstention-battery.jsonl"
        adj = ws.build_link_graph(docs)
        for line in battery_path.read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            if case.get("kind") == "case" and case.get("mode") == "search":
                ranked = ws.hybrid_rank(
                    ws.tokenize(case["question"]), docs, adj)
                if ranked:
                    pages.add(canon_doc(ranked[0][1]))
    else:
        raise ValueError(f"unknown adversarial mode {mode!r}")
    events = []
    for pg in sorted(pages):
        for back in range(365):
            events.append(Event(as_of - timedelta(days=back), pg,
                                DAILY_DEPOSIT_CAP, f"adversarial-{mode}"))
    return events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_survey(survey, weights):
    for name, s in survey.items():
        print(f"{name}: records={s['records']} events={s['events']} "
              f"dated={s['dated']} undated={s['undated']}")
    c = weights.survey_counts
    print(f"deposits: dated={c['events_dated']} "
          f"undated(not deposited)={c['events_undated']} "
          f"matched={c['deposits_matched']} "
          f"unmatched={c['deposits_unmatched']}")
    print(f"pages with usage: {len(weights.page_raw)}; "
          f"max lift: "
          f"{max((lift_from_raw(v) for v in weights.page_raw.values()), default=0.0):.6f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("survey", help="survey recorded usage + weights")
    wp = sub.add_parser("weights", help="write the weights artefact")
    wp.add_argument("--as-of", default=None)
    wp.add_argument("--out", default="evaluation/usage-weights.json")
    sp = sub.add_parser("search", help="hybrid search, default vs usage")
    sp.add_argument("query")
    sp.add_argument("--usage", action="store_true",
                    help="also run with the usage reranker")
    sp.add_argument("--top", type=int, default=5)
    gp = sub.add_parser("gate-check",
                        help="the pinned battery with the signal on")
    gp.add_argument("--adversarial", choices=("targeted", "uniform"),
                    default=None)
    gp.add_argument("--out", default=None)
    sub.add_parser("simulate", help="the guardrail bound, computed")
    args = ap.parse_args(argv)

    if args.cmd == "simulate":
        print(f"RAW_SUPREMUM  = {RAW_SUPREMUM:.4f}  "
              f"(cap {DAILY_DEPOSIT_CAP}/day, half-life "
              f"{HALF_LIFE_DAYS:g} days, infinite history)")
        print(f"LIFT_SUPREMUM = {LIFT_SUPREMUM:.6f}  "
              f"(< MAX_USAGE_LIFT {MAX_USAGE_LIFT})")
        print(f"max multiplier ratio (most-used vs never-used): "
              f"{1.0 + LIFT_SUPREMUM:.6f}")
        # feedback loop: deposit at cap daily, watch raw converge
        as_of = date(2026, 10, 22)
        events = [Event(as_of - timedelta(days=back), "p",
                        DAILY_DEPOSIT_CAP, "sim")
                  for back in range(3650)]
        w = UsageWeights(events, as_of)
        print(f"10 years at the daily cap: raw={w.raw_of('p'):.4f} "
              f"lift={w.page_lift('p'):.6f}")
        w2 = UsageWeights(events, as_of + timedelta(days=300))
        print(f"then 300 quiet days: raw={w2.raw_of('p'):.4f} "
              f"(evaporated ×{w.raw_of('p') / w2.raw_of('p'):.1f}) "
              f"lift={w2.page_lift('p'):.6f}")
        return 0

    ws = _load_sibling("wiki_search_for_usage", "wiki_search.py")
    docs = ws.collect_docs("wiki")
    corpus_keys = {canon_doc(p) for p, _t in docs}

    if args.cmd in ("survey", "weights"):
        events, survey = survey_usage_sources()
        as_of = _parse_date(args.as_of) if getattr(args, "as_of", None) \
            else None
        weights = build_weights(events, as_of=as_of,
                                corpus_keys=corpus_keys)
        _print_survey(survey, weights)
        if args.cmd == "weights":
            artefact = weights.to_dict()
            artefact["sources"] = {k: {kk: vv for kk, vv in v.items()}
                                    for k, v in survey.items()}
            out = Path(args.out)
            if not out.is_absolute():
                out = ROOT / out
            out.write_text(json.dumps(artefact, indent=2,
                                      ensure_ascii=False) + "\n",
                           encoding="utf-8")
            print(f"wrote {out}")
        return 0

    if args.cmd == "search":
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize(args.query)
        ranked = ws.hybrid_rank(terms, docs, adj)
        print("default:")
        for s, p, _t, d in ranked[:args.top]:
            print(f"  {s:.4f}  {canon_doc(p)}  rerank={d.get('rerank')}")
        if args.usage:
            events, _survey = survey_usage_sources()
            weights = build_weights(events, corpus_keys=corpus_keys)
            reranker = build_usage_reranker(ws, weights, docs)
            ranked_u = ws.hybrid_rank(terms, docs, adj,
                                      reranker=reranker)
            print(f"usage (active={weights.active}):")
            for s, p, _t, d in ranked_u[:args.top]:
                print(f"  {s:.4f}  {canon_doc(p)}  "
                      f"rerank={d.get('rerank')}")
        return 0

    if args.cmd == "gate-check":
        as_of = date.today()
        if args.adversarial:
            events = adversarial_events(args.adversarial, as_of)
            weights = build_weights(events, as_of=as_of,
                                    corpus_keys=corpus_keys)
            print(f"adversarial mode={args.adversarial}: "
                  f"{len(events)} synthetic events over "
                  f"{len(weights.page_raw)} pages")
        else:
            events, _survey = survey_usage_sources()
            weights = build_weights(events, corpus_keys=corpus_keys)
            print(f"real recorded usage: {len(events)} events, "
                  f"active={weights.active}")
        passed, total, _results, rc = _run_battery_with_weights(
            weights, out_path=args.out)
        print(f"gate-check: battery {passed}/{total} with the "
              f"usage signal ON")
        return 0 if passed == total else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
