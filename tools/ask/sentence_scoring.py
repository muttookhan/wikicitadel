#!/usr/bin/env python3
"""Sentence-level evidence scoring for Ask answers (W1.4).

The RAGBench-style row schema (``evaluation/ragbench-row-schema
.json``, validator ``scripts/wiki_ragbench_schema.py``) declares
the row shape — a response decomposed into sentences, each with a
support verdict and supporting keys, scorer outputs in separate
per-scorer columns — but until now nothing PRODUCED rows. This
module is the scorer behind the schema. It reads an Ask answer
record (the ``pickup`` record shape: ``answer`` + ``citations`` /
``citation_details``) and emits one schema row per record.

What it computes, all deterministic, stdlib only, no network:

1. **Per-sentence support verdicts.** The answer is split into
   sentences; each sentence's content tokens are checked against
   the evidence passages by GREEDY UNION coverage (passages in
   coverage order, ties broken by key, so the result does not
   depend on input order): ``supported`` when the union of the
   selected passages covers >= SUPPORTED_COVERAGE of the
   sentence's content tokens AND every numeric/date token in the
   sentence appears in the selected passages; ``partially-
   supported`` at >= PARTIAL_COVERAGE (or full coverage with a
   numeric token missing — a claim whose figures no passage
   states is never ``supported``); otherwise ``unsupported``,
   which by schema carries no supporting keys.

2. **Usefulness-scored context filter.** ``filter_context``
   re-ranks evidence passages by usefulness TO THE QUESTION —
   question-term coverage, answer-bearing density (question
   terms, numeric tokens, proper-noun-shaped tokens as a share
   of the passage's content), and marginal novelty over the
   passages already selected — not by retrieval similarity
   alone. It is a STAGE a caller may insert before packing; it
   is not wired into the standing pipeline.

3. **Citation precision / recall, semantic half.** ALCE-style:
   recall = the share of citation-needing sentences whose cited
   passages (as a union premise) entail the sentence; precision
   = the share of individual citations whose passage alone
   entails the sentence. Entailment comes through the
   ``EntailmentScorer`` interface. **There is no NLI model on
   this machine** (no torch / transformers), so the shipped
   scorer is ``LexicalEntailmentStandIn`` — a deterministic
   lexical estimator (content containment, numeric consistency,
   negation-parity penalty) that is LABELLED a stand-in in its
   name, in every output column, and here. Its numbers are the
   stand-in's numbers, never an NLI model's; a real NLI scorer
   drops in behind the same interface without touching the
   metrics code.

4. **Character-exact spans, deterministic half.** Following
   LegalBench-RAG's character-level accounting: every evidence
   passage is located verbatim in its source page (under the
   wiki's own quote-lane normalisation — ``scripts/wiki_cite
   _lock.py``: smart quotes to straight, whitespace runs to
   single spaces), and the sentence's supporting region inside
   the passage is the span from its first to its last matched
   content token. Composed, that gives a predicted span in
   NORMALISED-PAGE coordinates for every supported sentence.
   Against caller-supplied gold spans, precision / recall are
   exact character counts. Spans exist only where a passage
   locates; unlocated passages are counted, never silently
   dropped.

This module scores answers; it changes nothing. It is not
imported by the answer contract, the pickup, or the router,
and it moves no verdict, threshold, or gate. The abstention
battery and conflict slice pin the standing behaviour; this
scorer only measures composed answers after the fact.

Licence posture: clean re-implementation. The ideas — sentence
support rows (RAGBench), citation precision/recall (ALCE),
character-exact span accounting (LegalBench-RAG), usefulness
as a context-filter signal (gpt-researcher) — are restated in
this wiki's own code and vocabulary; no dataset, code, or text
from those projects is held here.

Usage:
  python3 tools/ask/sentence_scoring.py RECORDS.json
          [--wiki-dir DIR] [--gold-spans FILE] [--out ROWS.jsonl]
  RECORDS.json is one answer record (JSON object) or a JSONL
  file of records. Exit 0 = every emitted row validates
  against the row schema; 1 = schema findings; 2 = usage error.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (v1 — stated, not tuned against any fixture)
# ---------------------------------------------------------------------------

SUPPORTED_COVERAGE = 0.70   # union coverage for a supported verdict
PARTIAL_COVERAGE = 0.35     # union coverage floor for partial support
UNION_STOP = 0.95           # greedy union stops accumulating here
ENTAILMENT_THRESHOLD = 0.5  # premise entails hypothesis at >= this

USEFULNESS_WEIGHTS = {"question_coverage": 0.5, "density": 0.3,
                      "novelty": 0.2}

ANNOTATOR = {"kind": "deterministic-harness",
             "name": "tools/ask/sentence_scoring.py v1"}
DEFAULT_GENERATOR = {"kind": "model", "name": "ask-pickup"}

STOPWORDS = frozenset(
    "the a an is are was were be been being of to in on for and or "
    "it its this that these those with as at by from has have had "
    "was not no but if then than so such into about over under "
    "between who what when where which while".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
_NUMERIC_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|\$?\d[\d,]*(?:\.\d+)?%?")
_NEGATIONS = frozenset(
    "not no never none cannot isn't aren't wasn't weren't "
    "doesn't don't won't didn't".split())


# ---------------------------------------------------------------------------
# Text primitives
# ---------------------------------------------------------------------------

def split_sentences(text) -> list:
    """Split *text* into sentences, deterministically.

    Whitespace is collapsed first (the row stores the sentence
    as scored). A boundary is sentence-final punctuation
    followed by whitespace and an opening capital/digit/quote —
    the simple rule the house already lives with; abbreviations
    and decimals ending a sentence can split early, which the
    scorer tolerates (a fragment scores on its own tokens).
    Fragments with no alphanumeric character are dropped.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", flat)
    return [p.strip() for p in parts
            if p.strip() and re.search(r"[A-Za-z0-9]", p)]


def tokens(text) -> list:
    """All word tokens of *text*, lowercased, in order."""
    return _TOKEN_RE.findall(str(text or "").lower())


def content_tokens(text) -> set:
    """The checkable content of *text*: non-stopword tokens of
    length >= 2, as a set."""
    return {t for t in tokens(text)
            if t not in STOPWORDS and len(t) >= 2}


def numeric_tokens(text) -> list:
    """Numeric/date tokens of *text*, normalised (``$`` and
    thousands separators stripped), in order of appearance."""
    out = []
    for m in _NUMERIC_RE.finditer(str(text or "")):
        out.append(m.group(0).replace(",", "").replace("$", "")
                   .rstrip("%"))
    return out


def _normalize(text) -> str:
    """The quote lane's normalisation, loaded from
    ``scripts/wiki_cite_lock.py`` exactly as answer_contract.py
    loads it; a local mirror is the fallback so this module
    stays importable on its own."""
    global _NORMALIZE_FN
    if _NORMALIZE_FN is None:
        try:
            lock_path = (Path(__file__).resolve().parents[2]
                         / "scripts" / "wiki_cite_lock.py")
            spec = importlib.util.spec_from_file_location(
                "wiki_cite_lock", lock_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _NORMALIZE_FN = module.normalize_text
        except Exception:
            def _mirror(t):
                t = (t.replace("‘", "'").replace("’", "'")
                     .replace("“", '"').replace("”", '"'))
                return re.sub(r"\s+", " ", t).strip()
            _NORMALIZE_FN = _mirror
    return _NORMALIZE_FN(str(text or ""))


_NORMALIZE_FN = None


# ---------------------------------------------------------------------------
# Part 1: per-sentence support verdicts
# ---------------------------------------------------------------------------

def _passage_content(passage_text) -> set:
    return content_tokens(passage_text)


def score_sentence(sentence, passages) -> dict:
    """Score one sentence against evidence *passages*.

    *passages* is a list of entry dicts with ``key`` and
    ``passage`` (text or None). Returns the verdict record:
    ``verdict``, ``supporting_keys`` (empty unless the verdict
    is supported / partially-supported, per the row schema),
    ``coverage``, ``numeric_missing``, ``selected`` (the
    contributing entry dicts, in selection order) and
    ``no_content`` (True when the sentence has no checkable
    content tokens).
    """
    ctoks = content_tokens(sentence)
    nums = numeric_tokens(sentence)
    if not ctoks:
        return {"verdict": "unsupported", "supporting_keys": [],
                "coverage": 0.0, "numeric_missing": nums,
                "selected": [], "no_content": True}
    scored = []
    for entry in passages:
        if entry.get("passage") is None:
            continue
        ptoks = _passage_content(entry["passage"])
        cov = len(ctoks & ptoks) / len(ctoks)
        scored.append((entry, cov, ptoks))
    # Greedy union: coverage order, key order breaks ties, so
    # the selection never depends on the caller's input order.
    scored.sort(key=lambda ep: (-ep[1], ep[0]["key"]))
    selected, union = [], set()
    for entry, cov, ptoks in scored:
        if cov <= 0.0:
            continue
        grown = union | (ctoks & ptoks)
        if len(grown) > len(union):
            selected.append(entry)
            union = grown
        if len(union) / len(ctoks) >= UNION_STOP:
            break
    coverage = len(union) / len(ctoks)
    sel_nums = set()
    for entry in selected:
        sel_nums |= set(numeric_tokens(entry["passage"]))
    missing = [n for n in nums if n not in sel_nums]
    if coverage >= SUPPORTED_COVERAGE and not missing:
        verdict = "supported"
    elif coverage >= PARTIAL_COVERAGE:
        verdict = "partially-supported"
    else:
        verdict = "unsupported"
    return {"verdict": verdict,
            "supporting_keys": ([e["key"] for e in selected]
                                if verdict != "unsupported"
                                else []),
            "coverage": round(coverage, 6),
            "numeric_missing": missing,
            "selected": (selected if verdict != "unsupported"
                         else []),
            "no_content": False}


# ---------------------------------------------------------------------------
# Part 4: character-exact spans (deterministic half)
# ---------------------------------------------------------------------------

def locate_in_page(page_text, passage):
    """(start, end) of *passage* in *page_text*, in NORMALISED
    coordinates (see module docstring), or None when the
    passage does not appear verbatim (normalised)."""
    norm_pass = _normalize(passage)
    if not norm_pass:
        return None
    norm_page = _normalize(page_text)
    idx = norm_page.find(norm_pass)
    if idx < 0:
        return None
    return (idx, idx + len(norm_pass))


def support_span(sentence, passage_text):
    """(start, end) of the sentence's supporting region inside
    *passage_text*: from its first to its last matched content
    token, computed over the NORMALISED passage so the offsets
    compose with ``locate_in_page``. None when no content token
    of the sentence occurs in the passage."""
    ctoks = content_tokens(sentence)
    if not ctoks:
        return None
    norm = _normalize(passage_text)
    occ = [(m.start(), m.end())
           for m in _TOKEN_RE.finditer(norm.lower())
           if m.group(0) in ctoks]
    if not occ:
        return None
    return (occ[0][0], occ[-1][1])


def _merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlap_len(a_intervals, b_intervals):
    total = 0
    for a_start, a_end in a_intervals:
        for b_start, b_end in b_intervals:
            lo, hi = max(a_start, b_start), min(a_end, b_end)
            if hi > lo:
                total += hi - lo
    return total


def span_precision_recall(predicted, gold) -> dict:
    """Character-level precision / recall of *predicted* spans
    against *gold* spans. Spans are (page, start, end) triples;
    overlap is counted per page over merged intervals
    (micro-averaged). An empty side scores 1.0 exactly when the
    other side is also empty, else 0.0."""
    def by_page(spans):
        grouped = {}
        for page, start, end in spans:
            if end > start:
                grouped.setdefault(page, []).append((start, end))
        return {p: _merge(iv) for p, iv in grouped.items()}

    pred, gold_by = by_page(predicted), by_page(gold)
    pred_chars = sum(e - s for iv in pred.values() for s, e in iv)
    gold_chars = sum(e - s for iv in gold_by.values()
                     for s, e in iv)
    inter = sum(_overlap_len(pred.get(p, []), gold_by.get(p, []))
                for p in set(pred) & set(gold_by))
    return {
        "precision": (round(inter / pred_chars, 6) if pred_chars
                      else (1.0 if not gold_chars else 0.0)),
        "recall": (round(inter / gold_chars, 6) if gold_chars
                   else (1.0 if not pred_chars else 0.0)),
        "intersection_chars": inter,
        "predicted_chars": pred_chars,
        "gold_chars": gold_chars,
    }


# ---------------------------------------------------------------------------
# Part 2: usefulness-scored context filter
# ---------------------------------------------------------------------------

def _bearing_tokens(passage_text) -> set:
    """Answer-bearing tokens of a passage: tokens carrying a
    digit, plus proper-noun-shaped tokens (capitalised, not
    sentence-initial) — the tokens a question is usually ASKING
    about, as opposed to connective prose."""
    out = set()
    prev_end = 0
    text = str(passage_text or "")
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        low = word.lower()
        if any(ch.isdigit() for ch in word):
            out.add(low)
        elif word[0].isupper() and prev_end > 0 \
                and text[max(0, prev_end - 2):prev_end] \
                not in (". ", "! ", "? ", "\n"):
            out.add(low)
        prev_end = m.end()
    return out


def passage_usefulness(question, passage_text, covered=None) -> dict:
    """Usefulness of one passage TO THE QUESTION.

    Components (weights in USEFULNESS_WEIGHTS):
    ``question_coverage`` — share of the question's content
    tokens the passage covers; ``density`` — share of the
    passage's content tokens that are question terms or
    answer-bearing (see ``_bearing_tokens``); ``novelty`` —
    share of the passage's content tokens that are USEFUL
    (question terms or answer-bearing) and not already in
    *covered* (the union of previously selected passages).
    Novelty counts useful tokens only: a passage novel purely
    in irrelevant ways is not useful, and an exact duplicate
    of a selected passage has novelty 0 by construction.
    """
    qtoks = content_tokens(question)
    ptoks = content_tokens(passage_text)
    covered = covered or set()
    if not ptoks:
        return {"score": 0.0, "question_coverage": 0.0,
                "density": 0.0, "novelty": 0.0}
    q_cov = (len(qtoks & ptoks) / len(qtoks)) if qtoks else 0.0
    bearing = (qtoks & ptoks) | (_bearing_tokens(passage_text)
                                 & ptoks)
    density = len(bearing) / len(ptoks)
    novelty = len(bearing - covered) / len(ptoks)
    score = (USEFULNESS_WEIGHTS["question_coverage"] * q_cov
             + USEFULNESS_WEIGHTS["density"] * density
             + USEFULNESS_WEIGHTS["novelty"] * novelty)
    return {"score": round(score, 6),
            "question_coverage": round(q_cov, 6),
            "density": round(density, 6),
            "novelty": round(novelty, 6)}


def filter_context(question, passages, max_passages=None,
                   min_usefulness=0.0) -> list:
    """Re-rank *passages* (entry dicts with ``passage`` text) by
    usefulness to *question*, greedily: at each step the most
    useful remaining passage is selected and novelty is
    recomputed against what is already selected, so a duplicate
    of a selected passage sinks. Ties keep the caller's
    original order (stable). Passages scoring below
    *min_usefulness* are dropped; selection stops at
    *max_passages* when given. Returns NEW dicts (inputs are
    not mutated) annotated with a ``usefulness`` record. A
    passage without passage text scores 0.0.
    """
    remaining = list(enumerate(passages))
    selected, covered = [], set()
    while remaining:
        best = None
        for idx, entry in remaining:
            u = passage_usefulness(question,
                                   entry.get("passage") or "",
                                   covered)
            cand = (u["score"], -idx)
            if best is None or cand > best[0]:
                best = (cand, idx, entry, u)
        _, idx, entry, u = best
        if u["score"] < min_usefulness:
            break
        annotated = dict(entry)
        annotated["usefulness"] = u
        selected.append(annotated)
        covered |= content_tokens(entry.get("passage") or "")
        remaining = [(i, e) for i, e in remaining if i != idx]
        if max_passages is not None \
                and len(selected) >= max_passages:
            break
    return selected


# ---------------------------------------------------------------------------
# Part 3: citation precision / recall (semantic half, via a scorer)
# ---------------------------------------------------------------------------

class EntailmentScorer:
    """Interface for entailment scorers: ``entailment(premise,
    hypothesis)`` returns a float in [0, 1] — the degree to
    which the premise entails the hypothesis. ``name`` labels
    the scorer in every output it feeds; ``is_stand_in`` marks
    scorers that are NOT real NLI models."""

    name = "abstract-entailment-scorer"
    is_stand_in = False

    def entailment(self, premise, hypothesis) -> float:
        raise NotImplementedError


class LexicalEntailmentStandIn(EntailmentScorer):
    """Deterministic lexical STAND-IN for an NLI model — NOT
    an NLI model. No torch/transformers exists on this machine,
    so the semantic half runs on this estimator until a real
    NLI scorer is dropped in behind ``EntailmentScorer``:

    base = content-token containment of the hypothesis in the
    premise; a numeric/date token in the hypothesis that the
    premise does not state caps the score at 0.25 (a figure
    cannot be entailed by a text that never gives it); a
    negation-parity mismatch (exactly one side negated) scales
    the score by 0.3. Crude by design, and labelled everywhere
    its numbers appear.
    """

    name = "lexical-entailment-stand-in/v1"
    is_stand_in = True

    def entailment(self, premise, hypothesis) -> float:
        htoks = content_tokens(hypothesis)
        if not htoks:
            return 0.0
        ptoks = content_tokens(premise)
        base = len(htoks & ptoks) / len(htoks)
        pnums = set(numeric_tokens(premise))
        if any(n not in pnums for n in numeric_tokens(hypothesis)):
            base = min(base, 0.25)
        hneg = bool(set(tokens(hypothesis)) & _NEGATIONS)
        pneg = bool(set(tokens(premise)) & _NEGATIONS)
        if hneg != pneg and base > 0.0:
            base *= 0.3
        return round(base, 6)


def citation_precision_recall(sentence_results, scorer,
                              threshold=ENTAILMENT_THRESHOLD) -> dict:
    """ALCE-style citation precision / recall over scored
    sentences (the internal results of ``score_sentence``).

    A sentence NEEDS citation when its verdict is supported or
    partially-supported. Recall: the share of those sentences
    whose cited passages, joined as one premise, entail the
    sentence at >= *threshold*. Precision: the share of
    individual (sentence, passage) citations whose passage
    alone entails the sentence. Rates are None when their
    denominator is empty — an absent denominator is reported,
    never silently scored as success or failure.
    """
    need = [r for r in sentence_results
            if r["verdict"] in ("supported", "partially-supported")]
    recalled, per_sentence = 0, []
    for r in need:
        premise = " ".join(e["passage"] for e in r["selected"])
        ent = scorer.entailment(premise, r["sentence"])
        per_sentence.append(round(ent, 6))
        if ent >= threshold:
            recalled += 1
    total_cites, precise = 0, 0
    for r in need:
        for entry in r["selected"]:
            total_cites += 1
            if scorer.entailment(entry["passage"],
                                 r["sentence"]) >= threshold:
                precise += 1
    return {
        "scorer": scorer.name,
        "stand_in": bool(getattr(scorer, "is_stand_in", False)),
        "threshold": threshold,
        "sentences_needing_citation": len(need),
        "citation_recall": (round(recalled / len(need), 6)
                            if need else None),
        "citations": total_cites,
        "citation_precision": (round(precise / total_cites, 6)
                               if total_cites else None),
        "union_entailment": per_sentence,
    }


# ---------------------------------------------------------------------------
# Record handling and row building
# ---------------------------------------------------------------------------

def passage_key(page, anchor=None) -> str:
    """The supporting key for an evidence entry: the page id,
    with ``#anchor`` appended when the entry carries one —
    the same keys a compiled claim cites."""
    return f"{page}#{anchor}" if anchor else str(page)


def evidence_entries(record) -> list:
    """Normalise a record's citations + citation_details into
    evidence entries [{key, page, passage, score, anchor}].
    Details overlay plain citations by page (the contract's
    own rule). When the record carries only ``sub_answers``
    with their own details, those merge in sub-answer order.
    Entry order is first-seen order — deterministic."""
    entries, by_key = [], {}

    def add(raw):
        if isinstance(raw, dict):
            page = raw.get("page") or raw.get("id") \
                or raw.get("page_id")
            passage, score = raw.get("passage"), raw.get("score")
            anchor = raw.get("anchor")
        else:
            page, passage, score, anchor = raw, None, None, None
        if page is None or not str(page).strip():
            return
        key = passage_key(str(page).strip(), anchor)
        entry = by_key.get(key)
        if entry is None:
            entry = {"key": key, "page": str(page).strip(),
                     "passage": None, "score": None,
                     "anchor": anchor}
            by_key[key] = entry
            entries.append(entry)
        if passage is not None:
            entry["passage"] = passage
        if score is not None:
            entry["score"] = score

    for raw in record.get("citations") or []:
        add(raw)
    for raw in record.get("citation_details") or []:
        add(raw)
    if not entries:
        for sub in record.get("sub_answers") or []:
            for raw in sub.get("citations") or []:
                add(raw)
            for raw in sub.get("citation_details") or []:
                add(raw)
    return entries


def _question_of(record) -> str:
    if record.get("question"):
        return str(record["question"])
    entry = record.get("question_entry") or {}
    return str(entry.get("question") or "")


def _row_id_of(record) -> str:
    if record.get("id"):
        return str(record["id"])
    entry = record.get("question_entry") or {}
    return str(entry.get("id") or "row")


def _page_text(page, wiki_dir, cache):
    if wiki_dir is None:
        return None
    if page not in cache:
        try:
            contract = _load_answer_contract()
            path = contract.citation_path(page, wiki_dir)
            cache[page] = (path.read_text(encoding="utf-8")
                           if path is not None else None)
        except Exception:
            cache[page] = None
    return cache[page]


_CONTRACT = None


def _load_answer_contract():
    global _CONTRACT
    if _CONTRACT is None:
        path = Path(__file__).resolve().parent \
            / "answer_contract.py"
        spec = importlib.util.spec_from_file_location(
            "ask_answer_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CONTRACT = module
    return _CONTRACT


def score_answer_record(record, wiki_dir=None, scorer=None,
                        gold_spans=None, generator=None,
                        row_id=None) -> dict:
    """Score one Ask answer record into a RAGBench-schema row.

    *wiki_dir* (the ``wiki/`` directory) enables the span half:
    without it, spans are reported as not attempted.
    *gold_spans* is a list of (page, start, end) triples in
    normalised-page coordinates; when given, the span column
    carries exact precision / recall. *scorer* defaults to
    ``LexicalEntailmentStandIn`` — labelled as a stand-in in
    the row it feeds.
    """
    scorer = scorer or LexicalEntailmentStandIn()
    question = _question_of(record)
    answer = str(record.get("answer") or "")
    entries = evidence_entries(record)
    sentences = split_sentences(answer)

    results = []
    for sentence in sentences:
        r = score_sentence(sentence, entries)
        r["sentence"] = sentence
        results.append(r)

    # --- span half -------------------------------------------------
    page_cache, predicted = {}, []
    located, unlocated = 0, 0
    per_sentence_spans = []
    for r in results:
        spans_here = []
        for entry in r["selected"]:
            text = _page_text(entry["page"], wiki_dir, page_cache)
            if text is None or entry.get("passage") is None:
                unlocated += 1
                continue
            loc = locate_in_page(text, entry["passage"])
            if loc is None:
                unlocated += 1
                continue
            located += 1
            sup = support_span(r["sentence"], entry["passage"])
            if sup is not None:
                span = (entry["page"], loc[0] + sup[0],
                        loc[0] + sup[1])
                predicted.append(span)
                spans_here.append(
                    {"key": entry["key"], "page": entry["page"],
                     "start": span[1], "end": span[2]})
        per_sentence_spans.append(spans_here)
    span_column = {
        "coordinate_system": "normalised page text "
                             "(wiki_cite_lock normalisation)",
        "attempted": wiki_dir is not None,
        "passages_located": located,
        "passages_unlocated": unlocated,
        "predicted_spans": per_sentence_spans,
    }
    if gold_spans is not None:
        span_column["against_gold"] = span_precision_recall(
            predicted, gold_spans)

    # --- semantic half ----------------------------------------------
    cite_pr = citation_precision_recall(results, scorer)

    # --- verdict column ----------------------------------------------
    verdicts = [r["verdict"] for r in results]
    n = len(verdicts) or 1
    det_column = {
        "verdicts": verdicts,
        "coverage": [r["coverage"] for r in results],
        "numeric_missing": [r["numeric_missing"] for r in results],
        "no_content_sentences": sum(1 for r in results
                                    if r["no_content"]),
        "support_rate": round(
            verdicts.count("supported") / n, 6),
        "partial_rate": round(
            verdicts.count("partially-supported") / n, 6),
        "unsupported_rate": round(
            verdicts.count("unsupported") / n, 6),
        "thresholds": {"supported_coverage": SUPPORTED_COVERAGE,
                       "partial_coverage": PARTIAL_COVERAGE},
    }

    # --- usefulness column -------------------------------------------
    ranked = filter_context(question, entries)
    usefulness_column = {
        "order": [e["key"] for e in ranked],
        "scores": {e["key"]: e["usefulness"]["score"]
                   for e in ranked},
        "weights": dict(USEFULNESS_WEIGHTS),
    }

    row = {
        "id": row_id or _row_id_of(record),
        "question": question,
        "response_sentences": [
            {"sentence": r["sentence"],
             "support_verdict": r["verdict"],
             "supporting_keys": r["supporting_keys"]}
            for r in results],
        "scorer_columns": {
            "deterministic-sentence-support/v1": det_column,
            "span-exact/v1": span_column,
            scorer.name: cite_pr,
            "usefulness/v1": usefulness_column,
        },
        "provenance": {
            "generator": generator or dict(DEFAULT_GENERATOR),
            "annotator": dict(ANNOTATOR),
        },
    }
    return row


# ---------------------------------------------------------------------------
# Schema validation (the schema's own validator, loaded by path)
# ---------------------------------------------------------------------------

def validate_row(row) -> list:
    """Findings of ``scripts/wiki_ragbench_schema.py`` for one
    row ([] = conforms). Raises RuntimeError when the schema
    or validator cannot be loaded — an unchecked row is never
    reported as a checked one."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "wiki_ragbench_schema",
        root / "scripts" / "wiki_ragbench_schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = module.load_schema(
        root / "evaluation" / "ragbench-row-schema.json")
    return module.validate_row(row, schema)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_records(path):
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        obj = json.loads(stripped)
        return [obj] if isinstance(obj, dict) else obj
    except json.JSONDecodeError:
        return [json.loads(line) for line in stripped.splitlines()
                if line.strip()]


def main(argv):
    ap = argparse.ArgumentParser(
        description="Score Ask answer records into "
                    "RAGBench-schema sentence-support rows.")
    ap.add_argument("records")
    ap.add_argument("--wiki-dir", default=None,
                    help="the wiki/ directory (enables spans)")
    ap.add_argument("--gold-spans", default=None,
                    help="JSON: {row_id: [[page, start, end], "
                         "...]} or a bare list for one record")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv[1:])
    if not Path(args.records).is_file():
        print(f"sentence-scoring: records file missing: "
              f"{args.records}", file=sys.stderr)
        return 2
    gold = {}
    if args.gold_spans:
        gold = json.loads(Path(args.gold_spans).read_text(
            encoding="utf-8"))
    rows, findings = [], []
    for record in _load_records(args.records):
        rid = _row_id_of(record)
        gold_spans = gold.get(rid) if isinstance(gold, dict) \
            else gold
        if isinstance(gold, list):
            gold_spans = gold
        row = score_answer_record(
            record, wiki_dir=args.wiki_dir,
            gold_spans=[tuple(s) for s in gold_spans]
            if gold_spans else None)
        rows.append(row)
        for f in validate_row(row):
            findings.append(f"{rid}: {f}")
    text = "".join(json.dumps(r, ensure_ascii=False,
                              sort_keys=True) + "\n"
                   for r in rows)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    for f in findings:
        print(f"  [FINDING] {f}", file=sys.stderr)
    print(f"sentence-scoring: {len(rows)} rows, "
          f"{len(findings)} findings", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
