#!/usr/bin/env python3
"""wiki_rerank.py — the swappable reranker seam (W1.1, 2026-10-22).

Until now the hybrid ranker's rerank stage was hard-wired inside
scripts/wiki_search.py's hybrid_rank(): a deterministic
term-coverage multiplier computed inline and fed to the rank
expression as the `rerank` feature. This module puts that stage
behind an interface so the reranker can be SWAPPED and BENCHMARKED
on the golden set instead of hard-wired:

    reranker.rerank(query_terms, candidates) -> {key: RerankSignal}

A candidate is a plain dict: {"key", "title", "text", "coverage",
"title_frac"} — the caller (hybrid_rank) computes the coverage
features it already owns; a reranker returns, per candidate key, a
RerankSignal(multiplier, relevance, signals):

  - multiplier: the value that enters the rank expression as the
    `rerank` feature. Every reranker maps its relevance through
    the SAME bounded lift (1 + max_lift * relevance), so a swapped
    reranker can never inflate scores past the scale the
    abstention gate's tau was calibrated on. The one exception is
    the default coverage reranker, whose multiplier is the legacy
    formula itself (see below).
  - relevance: a calibrated relevance in [0, 1] for the candidate.
    hybrid_rank stamps it on every result detail
    ("rerank_relevance", plus "below_cutoff" against the
    calibrated cut-off), which is how the reranker's score feeds
    the abstention threshold: `calibrate` (below) fits the
    relevance cut-off that reproduces tau's answer/abstain split
    on the battery's search cases, so a surface holding only
    relevance still lands on the gate's decisions.

Kinds shipped:

  - "coverage" (DEFAULT): the legacy term-coverage reranker,
    extracted unchanged — multiplier = 1 + RERANK_COVERAGE_W *
    coverage + RERANK_TITLE_W * title_frac, relevance = the lift
    normalised by the max lift. hybrid_rank's default output is
    arithmetically identical to the pre-seam pipeline (the Lens
    parity tests and the abstention battery pin that).
  - "cross-encoder": (query, passage) pair scoring with
    BCEmbedding-style long-passage handling — a passage is NEVER
    fed to the scorer whole: it is cut into overlapping token
    windows (default 512 tokens, stride 256) and the passage
    score is the MAX over its windows, so a long page is judged
    by its best-matching window instead of being truncated at
    the model's context limit. The pair scorer is pluggable;
    a model-backed scorer (FlagEmbedding's FlagReranker, the
    BCEmbedding runtime) is used when that optional dependency
    is importable, otherwise RerankerUnavailable is raised —
    never a silent fallback. LexicalPairScorer is the shipped
    deterministic stand-in so the machinery is benchmarkable on
    machines with no model (this one); reports label it as such.
  - "colbert": ColBERT-style late interaction — per-token
    embeddings, MaxSim scoring (each query token takes its best
    cosine over the document's token vectors; the document
    relevance is the mean). The embedder is pluggable;
    HashingEmbedder is the deterministic stdlib stand-in.
  - listwise (NOT a pool reranker): an optional GATED final
    stage. rank_llm-style sliding-window listwise reordering of
    the finished ranking. OFF by default and doubly gated: a
    ListwiseReranker must be supplied AND the stage explicitly
    enabled (hybrid_rank's enable_listwise=True or the
    WIKI_RERANK_LISTWISE env var). Scores travel with their
    documents when the stage permutes, so tau semantics are
    per-document unchanged.

SPLADE (in the item's source list) is deliberately NOT a kind
here: it is a first-stage sparse retriever, not a reranker — it
belongs behind bm25_rank, not behind this seam.

Comparison (ranx-style): `compare` runs the golden set through
hybrid_rank once per candidate reranker and reports the house
metrics (citation coverage @1/3/5/10, hit rate, mean precision,
MRR — the wiki_benchmark definitions) side by side, with deltas
against the default and per-reranker invocation errors listed,
never swallowed. Fixed commands:

    python3 scripts/wiki_rerank.py list
    python3 scripts/wiki_rerank.py compare \
        [--rerankers coverage,colbert,cross-encoder] \
        [--out evaluation/reranker-comparison.json]
    python3 scripts/wiki_rerank.py calibrate \
        [--out evaluation/reranker-calibration.json]

Attribution (adapt-with-credit; designs adapted, no code copied):
the model-type reranker registry shape follows AnswerDotAI/
rerankers (Apache-2.0); the long-passage windowing follows
netease-youdao/BCEmbedding (Apache-2.0) practice; the sliding-
window listwise stage follows castorini/rank_llm (Apache-2.0);
late-interaction MaxSim follows ColBERTv2 (MIT); the comparison
report shape follows ranx (MIT). Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The bounded lift budget. wiki_search passes its own
# RERANK_COVERAGE_W + RERANK_TITLE_W (= 0.40) when it builds the
# default reranker; this default matches it so standalone use
# (compare/calibrate/tests) sees the same scale.
DEFAULT_MAX_LIFT = 0.40

# The calibrated relevance cut-off: fitted 2026-10-22 by
# `calibrate` against the battery's tau = 1.23 (agreement 4/5
# search cases, zero false-answers; the fit and its per-case
# table live in evaluation/reranker-calibration.json — re-run
# calibrate to refit). A candidate under it is flagged
# "below_cutoff" on its detail; the flag is a signal, never a
# ranking change.
DEFAULT_RELEVANCE_CUTOFF = 0.575

LISTWISE_ENV_VAR = "WIKI_RERANK_LISTWISE"


class RerankerUnavailable(Exception):
    """A reranker's backing model/endpoint is not available on
    this machine. Raised, never silently substituted."""


class RerankSignal:
    """One candidate's rerank outcome: the multiplier that
    enters the rank expression, the calibrated relevance in
    [0, 1], and the reranker's own per-candidate signals.
    (A plain class, not a dataclass: this module is loaded by
    path via importlib all over the tree, and dataclass
    processing requires sys.modules registration the house
    loader does not do.)"""

    def __init__(self, multiplier, relevance, signals=None):
        self.multiplier = multiplier
        self.relevance = relevance
        self.signals = signals or {}

    def __repr__(self):
        return (f"RerankSignal(multiplier={self.multiplier!r}, "
                f"relevance={self.relevance!r}, "
                f"signals={self.signals!r})")

    def __eq__(self, other):
        return (isinstance(other, RerankSignal)
                and self.multiplier == other.multiplier
                and self.relevance == other.relevance
                and self.signals == other.signals)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def fallback_tokenize(text: str):
    """The standalone tokenizer for rerankers used without
    wiki_search's hooks (same [a-z0-9]+, len>=2 shape; wiki_search
    injects its own tokenize — with CJK segmentation — whenever
    it builds a reranker, so shipped ranking never uses this)."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def _sigmoid(x: float) -> float:
    x = max(-60.0, min(60.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


class Reranker:
    """The seam interface. rerank() receives the query terms and
    the pool candidates (dicts with key/title/text/coverage/
    title_frac) and returns {key: RerankSignal} for the keys it
    scored; unscored keys keep the neutral signal (multiplier
    1.0, relevance 0.0) at the caller."""
    name = "base"
    kind = "base"

    def rerank(self, query_terms, candidates):  # pragma: no cover
        raise NotImplementedError


class CoverageReranker(Reranker):
    """The legacy term-coverage reranker, extracted unchanged:
    multiplier = 1 + coverage_w * coverage + title_w * title_frac
    (the exact float operations hybrid_rank performed inline
    before the seam), relevance = the lift over the max lift."""
    name = "coverage"
    kind = "coverage"

    def __init__(self, coverage_w=0.25, title_w=0.15, max_lift=None):
        self.coverage_w = coverage_w
        self.title_w = title_w
        self.max_lift = (coverage_w + title_w) if max_lift is None \
            else max_lift

    def rerank(self, query_terms, candidates):
        out = {}
        for cand in candidates:
            cov = cand.get("coverage", 0.0)
            t_frac = cand.get("title_frac", 0.0)
            mult = 1.0 + self.coverage_w * cov + self.title_w * t_frac
            rel = _clamp01((mult - 1.0) / self.max_lift) \
                if self.max_lift > 0 else 0.0
            out[cand["key"]] = RerankSignal(
                multiplier=mult, relevance=rel,
                signals={"coverage": cov, "title_frac": t_frac})
        return out


class LexicalPairScorer:
    """Deterministic stand-in pair scorer for the cross-encoder
    machinery: a logit from query-term coverage of the passage
    window. NOT a model — it exists so the seam is benchmarkable
    end-to-end on machines with no embedding/reranker endpoint,
    and every report that uses it says so."""
    name = "lexical-reference-stand-in"

    def __init__(self, tokenize=None):
        self.tokenize = tokenize or fallback_tokenize

    def __call__(self, query_text, passage_text):
        q = set(self.tokenize(query_text))
        if not q:
            return -3.0
        p = set(self.tokenize(passage_text))
        cov = len(q & p) / len(q)
        return 6.0 * cov - 3.0


class BCEmbeddingScorer:
    """Model-backed pair scorer over FlagEmbedding's FlagReranker
    (the BCEmbedding runtime, Apache-2.0). Lazy: the import (and
    its torch dependency) is attempted on first use; absent, the
    scorer raises RerankerUnavailable with the reason."""
    name = "bcembedding-flagreranker"

    def __init__(self, model="BAAI/bge-reranker-base"):
        self.model = model
        self._impl = None

    def _load(self):
        if self._impl is None:
            try:
                from FlagEmbedding import FlagReranker
            except Exception as exc:
                raise RerankerUnavailable(
                    f"FlagEmbedding is not importable ({exc}); the "
                    "cross-encoder's model-backed scorer needs it "
                    "(or inject a pair scorer)") from exc
            self._impl = FlagReranker(self.model,
                                       use_fp16=False)
        return self._impl

    def __call__(self, query_text, passage_text):
        impl = self._load()
        return float(impl.compute_score([[query_text, passage_text]]))


class CrossEncoderReranker(Reranker):
    """Cross-encoder reranking with BCEmbedding-style
    long-passage handling: the passage is cut into overlapping
    token windows and scored window by window; the passage logit
    is the MAX window logit (the best-matching window speaks for
    the passage — a long page is never truncated to its head).
    relevance = sigmoid(logit); the multiplier maps relevance
    through the shared bounded lift."""
    name = "cross-encoder"
    kind = "cross-encoder"

    def __init__(self, scorer=None, window_tokens=512,
                 stride_tokens=256, max_lift=DEFAULT_MAX_LIFT,
                 tokenize=None):
        self.scorer = scorer
        self.window_tokens = window_tokens
        self.stride_tokens = stride_tokens
        self.max_lift = max_lift
        self.tokenize = tokenize or fallback_tokenize

    @staticmethod
    def chunk_windows(n_tokens, window, stride):
        """[(start, end)] token windows covering a passage of
        n_tokens: starts every `stride` tokens, each window up to
        `window` tokens, the last window ending at n_tokens."""
        if n_tokens <= 0:
            return []
        if n_tokens <= window:
            return [(0, n_tokens)]
        out = []
        start = 0
        while start < n_tokens:
            end = min(n_tokens, start + window)
            out.append((start, end))
            if end >= n_tokens:
                break
            start += stride
        return out

    def _scorer(self):
        if self.scorer is None:
            self.scorer = BCEmbeddingScorer()
        return self.scorer

    def rerank(self, query_terms, candidates):
        scorer = self._scorer()
        query_text = " ".join(query_terms)
        out = {}
        for cand in candidates:
            tokens = self.tokenize(cand.get("text", ""))
            if not tokens:
                out[cand["key"]] = RerankSignal(1.0, 0.0, {})
                continue
            best = None
            for start, end in self.chunk_windows(
                    len(tokens), self.window_tokens,
                    self.stride_tokens):
                logit = float(scorer(
                    query_text, " ".join(tokens[start:end])))
                best = logit if best is None else max(best, logit)
            rel = _sigmoid(best)
            out[cand["key"]] = RerankSignal(
                multiplier=1.0 + self.max_lift * rel, relevance=rel,
                signals={"pair_logit_max": best})
        return out


class HashingEmbedder:
    """Deterministic stdlib token embedder (stand-in): each token
    maps to a fixed pseudo-random unit vector derived from its
    SHA-256. Unrelated tokens are near-orthogonal; identical
    tokens coincide. For benchmarking the late-interaction
    machinery without a model — not a semantic embedding."""
    name = "hashing-stand-in"

    def __init__(self, dim=64):
        self.dim = dim

    def embed(self, tokens):
        vecs = []
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            raw = [digest[i % len(digest)] / 255.0 * 2.0 - 1.0
                   for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vecs.append([v / norm for v in raw])
        return vecs


class LateInteractionReranker(Reranker):
    """ColBERT-style late interaction: token embeddings for query
    and document, MaxSim per query token (best cosine over the
    document's token vectors), relevance = the mean MaxSim
    clamped to [0, 1]; multiplier through the shared lift."""
    name = "colbert"
    kind = "colbert"
    MAX_DOC_TOKENS = 1024
    MAX_QUERY_TOKENS = 64

    def __init__(self, embedder=None, max_lift=DEFAULT_MAX_LIFT,
                 tokenize=None):
        self.embedder = embedder or HashingEmbedder()
        self.max_lift = max_lift
        self.tokenize = tokenize or fallback_tokenize

    def rerank(self, query_terms, candidates):
        q_tokens = list(query_terms)[:self.MAX_QUERY_TOKENS]
        if not q_tokens:
            return {c["key"]: RerankSignal(1.0, 0.0, {})
                    for c in candidates}
        q_vecs = self.embedder.embed(q_tokens)
        out = {}
        for cand in candidates:
            d_tokens = self.tokenize(
                cand.get("title", "") + " " + cand.get("text", "")
            )[:self.MAX_DOC_TOKENS]
            if not d_tokens:
                out[cand["key"]] = RerankSignal(1.0, 0.0, {})
                continue
            d_vecs = self.embedder.embed(d_tokens)
            total = 0.0
            for qv in q_vecs:
                total += max(sum(a * b for a, b in zip(qv, dv))
                             for dv in d_vecs)
            raw = total / len(q_vecs)
            rel = _clamp01(raw)
            out[cand["key"]] = RerankSignal(
                multiplier=1.0 + self.max_lift * rel, relevance=rel,
                signals={"maxsim_mean": raw})
        return out


class ListwiseReranker:
    """rank_llm-style listwise reordering of a FINISHED ranking:
    a sliding window (default 5, stride 2) moves from the tail
    toward the head; each window is reordered jointly by the
    scorer, which sees the window's passages together. The
    scorer is pluggable; with none injected, use raises
    RerankerUnavailable (a real listwise stage needs an LLM
    endpoint this machine does not run)."""
    name = "listwise"
    kind = "listwise"

    def __init__(self, scorer=None, window=5, stride=2):
        self.scorer = scorer
        self.window = window
        self.stride = stride

    def rerank_order(self, query_terms, ordered_candidates):
        """ordered_candidates: candidate dicts in current rank
        order. Returns the reordered list (same dicts)."""
        if self.scorer is None:
            raise RerankerUnavailable(
                "listwise reranking needs a listwise scorer (an "
                "LLM endpoint, rank_llm-style); none is configured "
                "on this machine")
        order = list(ordered_candidates)
        n = len(order)
        if n <= 1:
            return order
        w = min(self.window, n)
        starts = list(range(n - w, -1, -self.stride))
        if starts[-1] != 0:
            starts.append(0)
        for s in starts:
            order[s:s + w] = self.scorer(query_terms, order[s:s + w])
        return order


class PointwiseListwiseScorer:
    """Stand-in listwise scorer: orders a window by an inner
    reranker's relevance (a degenerate listwise pass — the window
    is still scored jointly from the candidates, so the stage's
    mechanics are exercised and benchmarkable)."""
    name = "pointwise-stand-in"

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, query_terms, window_candidates):
        signals = self.inner.rerank(query_terms, window_candidates)
        return sorted(
            window_candidates,
            key=lambda c: -signals.get(
                c["key"], RerankSignal(1.0, 0.0)).relevance)


def listwise_enabled(explicit=False, env=None):
    """The listwise gate: open only when explicitly enabled by
    the caller OR the WIKI_RERANK_LISTWISE env var is set to a
    truthy value. Closed by default — the shipped ranking never
    listwise-reorders unless someone turns it on."""
    if explicit:
        return True
    env = os.environ if env is None else env
    return str(env.get(LISTWISE_ENV_VAR, "")).lower() in (
        "1", "true", "yes", "on")


RERANKER_KINDS = ("coverage", "cross-encoder", "colbert")


def get_reranker(name, **kwargs):
    """Build a reranker by kind name. kwargs: tokenize,
    coverage_w, title_w, max_lift, scorer, embedder,
    window_tokens, stride_tokens. Unknown name -> ValueError."""
    tokenize = kwargs.get("tokenize")
    max_lift = kwargs.get("max_lift", DEFAULT_MAX_LIFT)
    if name == "coverage":
        return CoverageReranker(
            coverage_w=kwargs.get("coverage_w", 0.25),
            title_w=kwargs.get("title_w", 0.15),
            max_lift=kwargs.get("max_lift"))
    if name == "cross-encoder":
        return CrossEncoderReranker(
            scorer=kwargs.get("scorer"),
            window_tokens=kwargs.get("window_tokens", 512),
            stride_tokens=kwargs.get("stride_tokens", 256),
            max_lift=max_lift, tokenize=tokenize)
    if name == "colbert":
        return LateInteractionReranker(
            embedder=kwargs.get("embedder"),
            max_lift=max_lift, tokenize=tokenize)
    raise ValueError(
        f"unknown reranker {name!r}; known: {list(RERANKER_KINDS)}")


# ---------------------------------------------------------------------------
# Calibrated relevance cut-off
# ---------------------------------------------------------------------------

class RelevanceCutoff:
    """The calibrated cut-off on the reranker's relevance scale.
    below(x): the candidate's relevance does not clear the
    cut-off — the relevance-scale twin of `top score < tau`.
    (Plain class, like RerankSignal — see its note.)"""

    def __init__(self, threshold=DEFAULT_RELEVANCE_CUTOFF):
        self.threshold = threshold

    def below(self, relevance: float) -> bool:
        return relevance < self.threshold

    def to_dict(self):
        return {"relevance_cutoff": self.threshold}


def calibrate_cutoff(samples, objective="f1"):
    """Fit a relevance cut-off on (relevance, is_positive)
    samples. objective "f1": maximise F1 of `relevance >= t`
    predicting is_positive. objective "agreement": maximise raw
    agreement (the calibration that reproduces a gate's split).
    Ties break toward FEWER false positives (a false 'answer' is
    the expensive error at an abstention gate), then toward the
    higher threshold. Returns a dict with the threshold, the
    objective value, and the confusion counts at the fit."""
    if not samples:
        return {"cutoff": DEFAULT_RELEVANCE_CUTOFF, "n": 0,
                "objective": objective, "value": None,
                "confusion": {"tp": 0, "fp": 0, "tn": 0, "fn": 0}}
    thresholds = sorted({0.0} | {r for r, _ in samples})
    best = None
    for t in thresholds:
        tp = sum(1 for r, p in samples if r >= t and p)
        fp = sum(1 for r, p in samples if r >= t and not p)
        tn = sum(1 for r, p in samples if r < t and not p)
        fn = sum(1 for r, p in samples if r < t and p)
        if objective == "agreement":
            value = (tp + tn) / len(samples)
        else:
            denom = 2 * tp + fp + fn
            value = (2 * tp / denom) if denom else 0.0
        key = (value, -fp, t)
        if best is None or key > best[0]:
            best = (key, t, value,
                    {"tp": tp, "fp": fp, "tn": tn, "fn": fn})
    _key, t, value, confusion = best
    return {"cutoff": t, "n": len(samples), "objective": objective,
            "value": round(value, 4), "confusion": confusion}


# ---------------------------------------------------------------------------
# ranx-style comparison + calibration over the golden set / battery
# ---------------------------------------------------------------------------

def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_questions(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def build_compare_rerankers(ws, names):
    """The candidate set for a comparison run. cross-encoder
    runs over the lexical reference stand-in scorer (labelled in
    the report) because no reranker model is installed here."""
    built = {}
    for name in names:
        if name == "coverage":
            built[name] = (get_reranker(
                "coverage", coverage_w=ws.RERANK_COVERAGE_W,
                title_w=ws.RERANK_TITLE_W,
                max_lift=ws.RERANK_COVERAGE_W + ws.RERANK_TITLE_W,
                tokenize=ws.tokenize), "the shipped reranker")
        elif name == "cross-encoder":
            built[name] = (get_reranker(
                "cross-encoder",
                scorer=LexicalPairScorer(tokenize=ws.tokenize),
                tokenize=ws.tokenize),
                "lexical-reference-stand-in scorer (no model "
                "installed); mechanics measured, not a model")
        elif name == "colbert":
            built[name] = (get_reranker(
                "colbert", tokenize=ws.tokenize),
                "hashing-stand-in embedder (no model installed); "
                "mechanics measured, not a model")
        else:
            raise ValueError(f"unknown reranker {name!r}")
    return built


def compare_rerankers(ws, bench, docs, adj, questions, built,
                      top=10):
    """Run every built reranker over the questions via
    ws.hybrid_rank and aggregate the wiki_benchmark metrics.
    A reranker that raises on a question is recorded under
    invocation_errors (ranx-style: reported, never swallowed)
    and that question is excluded for that reranker only."""
    models = {}
    for name, (reranker, scorer_note) in built.items():
        per_q = []
        errors = []
        top1_rel = []
        for q in questions:
            terms = ws.tokenize(q["question"])
            try:
                ranked = ws.hybrid_rank(terms, docs, adj,
                                        reranker=reranker)
            except Exception as exc:  # invocation error: record it
                errors.append({"question": q["id"],
                               "error": f"{type(exc).__name__}: {exc}"})
                continue
            paths = [str(p.relative_to(ws.ROOT))
                     if p.is_relative_to(ws.ROOT) else str(p)
                     for _s, p, _t, _d in ranked]
            per_q.append(bench.score_question(q, paths, top))
            if ranked:
                top1_rel.append(ranked[0][3].get("rerank_relevance"))
        n = len(per_q) or 1
        cov = {k: sum(1 for r in per_q
                      if r["must_cite_rank"] is not None
                      and r["must_cite_rank"] <= k) / n
               for k in (1, 3, 5, 10)}
        models[name] = {
            "scorer": scorer_note,
            "questions_scored": len(per_q),
            "citation_coverage": {f"@{k}": round(v, 4)
                                  for k, v in cov.items()},
            "hit_rate_topk": round(
                sum(1 for r in per_q if r["hit_in_topk"]) / n, 4),
            "mean_precision_at_k": round(
                sum(r["precision_at_k"] for r in per_q) / n, 4),
            "mrr_must_cite": round(sum(
                1.0 / r["must_cite_rank"] for r in per_q
                if r["must_cite_rank"] is not None) / n, 4),
            "mean_top1_relevance": round(
                sum(r for r in top1_rel if r is not None)
                / (len(top1_rel) or 1), 4),
            "invocation_errors": errors,
            "per_question": per_q,
        }
    deltas = {}
    if "coverage" in models:
        base = models["coverage"]
        for name, m in models.items():
            if name == "coverage":
                continue
            deltas[name] = {
                "mrr_must_cite": round(
                    m["mrr_must_cite"] - base["mrr_must_cite"], 4),
                "citation_coverage@10": round(
                    m["citation_coverage"]["@10"]
                    - base["citation_coverage"]["@10"], 4),
                "hit_rate_topk": round(
                    m["hit_rate_topk"] - base["hit_rate_topk"], 4),
            }
    return {"models": models, "deltas_vs_default": deltas}


def _print_compare_table(report):
    names = list(report["models"])
    metrics = ["mrr_must_cite", "hit_rate_topk", "mean_precision_at_k"]
    width = max(len(n) for n in names) + 2
    print("reranker".ljust(width) + "".join(
        m.rjust(20) for m in metrics) + "cov@10".rjust(10)
        + "errors".rjust(8))
    for name in names:
        m = report["models"][name]
        print(name.ljust(width) + "".join(
            f"{m[k]:.4f}".rjust(20) for k in metrics)
            + f"{m['citation_coverage']['@10']:.4f}".rjust(10)
            + str(len(m["invocation_errors"])).rjust(8))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="accepted for CLI uniformity; unused")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the reranker kinds + the gate")
    cp = sub.add_parser("compare",
                        help="ranx-style golden-set comparison")
    cp.add_argument("--rerankers", default="coverage,colbert,"
                    "cross-encoder")
    cp.add_argument("--questions", default=None)
    cp.add_argument("--out", default=None)
    cb = sub.add_parser("calibrate",
                        help="fit the relevance cut-off against tau")
    cb.add_argument("--battery", default=None)
    cb.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print(json.dumps({
            "kind": "rerankers",
            "rerankers": list(RERANKER_KINDS),
            "default": "coverage",
            "max_lift": DEFAULT_MAX_LIFT,
            "default_relevance_cutoff": DEFAULT_RELEVANCE_CUTOFF,
            "listwise": {"gate_env": LISTWISE_ENV_VAR,
                         "enabled_by_default": False},
        }, indent=2, sort_keys=True))
        return 0

    ws = _load_sibling("wiki_search_for_rerank", "wiki_search.py")

    if args.cmd == "compare":
        bench = _load_sibling("wiki_benchmark_for_rerank",
                              "wiki_benchmark.py")
        qpath = Path(args.questions) if args.questions else (
            ROOT / "evaluation" / "golden-questions.jsonl")
        questions = _load_questions(qpath)
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        names = [n.strip() for n in args.rerankers.split(",")
                 if n.strip()]
        built = build_compare_rerankers(ws, names)
        report = compare_rerankers(ws, bench, docs, adj, questions,
                                   built)
        report = {
            "kind": "reranker-comparison",
            "generated_at": datetime.now().astimezone().isoformat(
                timespec="seconds"),
            "command": "python3 scripts/wiki_rerank.py compare "
                       f"--rerankers {args.rerankers}",
            "corpus": "wiki/ (scope=wiki)",
            "corpus_docs": len(docs),
            "questions_file": str(qpath),
            "questions": len(questions),
            **report,
        }
        _print_compare_table(report)
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, ensure_ascii=False)
                + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
        return 0

    # calibrate
    battery_path = Path(args.battery) if args.battery else (
        ROOT / "evaluation" / "abstention-battery.jsonl")
    baseline = json.loads(
        (ROOT / "evaluation" / "extended-baseline.json").read_text(
            encoding="utf-8"))
    tau = baseline.get("abstain_threshold")
    cases = []
    for line in battery_path.read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    samples = []
    per_case = []
    for case in cases:
        if case.get("mode") != "search":
            continue
        terms = ws.tokenize(case["question"])
        ranked = ws.hybrid_rank(terms, docs, adj)
        if not ranked:
            continue
        top_score = ranked[0][0]
        top_rel = ranked[0][3].get("rerank_relevance", 0.0)
        tau_says_answer = top_score >= tau
        samples.append((top_rel, tau_says_answer))
        per_case.append({
            "id": case.get("id"), "top1_score": round(top_score, 4),
            "top1_relevance": top_rel, "tau": tau,
            "tau_decision": "answer" if tau_says_answer else "abstain",
            "expected_verdict": case.get("expected_verdict")})
    fit = calibrate_cutoff(samples, objective="agreement")
    cutoff = RelevanceCutoff(fit["cutoff"])
    agree = 0
    for row in per_case:
        row["cutoff_decision"] = "abstain" if cutoff.below(
            row["top1_relevance"]) else "answer"
        row["agree"] = row["cutoff_decision"] == row["tau_decision"]
        agree += row["agree"]
    report = {
        "kind": "reranker-calibration",
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "command": "python3 scripts/wiki_rerank.py calibrate",
        "tau": tau,
        "tau_source": "evaluation/extended-baseline.json "
                      "(abstain_threshold — the pinned battery's)",
        "method": "cut-off on the default reranker's top-1 "
                  "relevance maximising agreement with the tau "
                  "gate's answer/abstain split over the battery's "
                  "search cases (severance-driven abstains are "
                  "decided before the score gate and excluded "
                  "from the fit's meaning, not from its count)",
        "relevance_cutoff": fit["cutoff"],
        "fit_objective": fit["objective"],
        "fit_value": fit["value"],
        "confusion": fit["confusion"],
        "agreement": f"{agree}/{len(per_case)}",
        "per_case": per_case,
    }
    print(json.dumps({k: report[k] for k in (
        "tau", "relevance_cutoff", "agreement", "confusion")},
        indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
