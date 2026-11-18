#!/usr/bin/env python3
"""The deterministic stub judge for Ask-answer calibration.

**There is no LLM judge yet.** This module is a rule-based stand-in
that exercises the calibration machinery end-to-end — the labelled
set, the confusion matrix, the certification refusal — so that the
day an LLM judge is wired in (kind ``llm`` in
``judge-config.json``), it is scored by exactly the same runner
against exactly the same labels, and it inherits the refusal: no
certification below the bars, whoever the judge is.

The stub implements the pinned rubric (``judge-prompt.md``) with
the deterministic machinery the wiki already has — the abstention
contract in ``tools/ask/answer_contract.py``:

1. Contract validity (``validate_answer``, with page resolution
   and verbatim-passage checks when a wiki root is supplied).
2. Abstention expectation: an expected abstention must be an
   abstention; an answerable question must not be abstained.
3. Key facts: every gold key fact must appear (normalised) in the
   answer text — the top-level answer plus any sub-answers.
4. Forbidden claims: no gold forbidden claim may appear in the
   answer text (verbatim normalised containment; the stub cannot
   see refutation framing — a known limitation, recorded in the
   calibration README).
5. Citations: every must-cite page id must be among the record's
   citations.
6. Trust verdict: for a non-abstained record, a computed verdict
   of ``hold`` or ``review`` is a rejection — the answer is weak
   or needs a human, so it is not auto-acceptable. (An abstention
   computes to ``hold`` by rule and is exempt here; rule 2 already
   judged whether abstaining was right.)

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_CONTRACT = None


def _contract():
    global _CONTRACT
    if _CONTRACT is None:
        path = (
            Path(__file__).resolve().parents[2]
            / "tools" / "ask" / "answer_contract.py"
        )
        spec = importlib.util.spec_from_file_location(
            "answer_contract", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CONTRACT = module
    return _CONTRACT


def _norm(text) -> str:
    return " ".join(str(text).lower().split())


def _answer_texts(record: dict) -> list:
    texts = []
    if isinstance(record.get("answer"), str):
        texts.append(record["answer"])
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict) and isinstance(sub.get("answer"), str):
            texts.append(sub["answer"])
    return texts


def _record_citations(record: dict) -> set:
    cited = set()
    for raw in record.get("citations") or []:
        if isinstance(raw, dict):
            page = raw.get("page") or raw.get("id") or raw.get("page_id")
            if page:
                cited.add(str(page).strip())
        elif raw:
            cited.add(str(raw).strip())
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            cited |= _record_citations(sub)
    return cited


def judge(record: dict, expected: dict = None, wiki_dir=None) -> dict:
    """Judge one candidate answer record against its gold expectation.

    *expected* keys (all optional): ``expected_abstain``
    (True / False / None for "no expectation"), ``key_facts``,
    ``forbidden_claims``, ``must_cite`` (page ids). Returns
    ``{"verdict": "accept"|"reject", "reasons": [...]}`` — the
    reasons name the rubric rules (see ``judge-prompt.md``) that
    decided a rejection.
    """
    ac = _contract()
    expected = expected or {}
    reasons = []

    if not isinstance(record, dict):
        return {"verdict": "reject", "reasons": ["1: not a record"]}

    # Rule 1 — the abstention contract itself.
    errors = ac.validate_answer(record, wiki_dir)
    if errors:
        reasons.append("1: contract: %s" % errors[0])

    abstained = bool(record.get("abstained")) or bool(
        isinstance(record.get("abstention_reason"), str)
        and record.get("abstention_reason", "").strip()
    )
    expected_abstain = expected.get("expected_abstain")

    # Rule 2 — abstention expectation.
    if expected_abstain is True and not abstained:
        reasons.append("2: answered a question whose correct "
                       "behaviour is to abstain")
    elif expected_abstain is False and abstained:
        reasons.append("2: abstained on an answerable question")

    texts = [_norm(t) for t in _answer_texts(record)]
    joined = "\n".join(texts)

    # Rule 3 — key facts present, forbidden claims absent.
    if not abstained:
        for fact in expected.get("key_facts") or []:
            if _norm(fact) not in joined:
                reasons.append("3: key fact missing: %r" % fact)
    for claim in expected.get("forbidden_claims") or []:
        if _norm(claim) in joined:
            reasons.append("3: forbidden claim stated: %r" % claim)

    # Rule 4 — must-cite pages actually cited.
    if not abstained:
        cited = _record_citations(record)
        for page in expected.get("must_cite") or []:
            if page not in cited:
                reasons.append("4: must-cite page not cited: %s" % page)

    # Rule 5 — the trust verdict must be ``ok`` for acceptance.
    if not abstained:
        verdict = ac.compute_trust_verdict(record, wiki_dir)
        if verdict != "ok":
            reasons.append("5: trust verdict is %r" % verdict)

    return {
        "verdict": "reject" if reasons else "accept",
        "reasons": reasons,
    }
