#!/usr/bin/env python3
"""The Lens Ask abstention contract — deterministic checks.

the build (owner-approved). Pattern adapted from
orderye/memory-hub's ``no_reliable_match`` abstention contract
(dual MIT / Apache-2.0) and AnythingLLM's query-only
refuse-ungrounded mode (MIT): an answer is produced only when it can
cite wiki pages covering its claims; otherwise the outcome is an
explicit abstention, never a forced weak answer.

The contract, as enforced here and stated for the answering agent in
``pickup.md`` / ``pickup-instructions.md`` / ``answer-templates.md``:

1. Every stored answer carries **citations** (wiki page ids the
   answerer actually read) **or** an **abstention**: ``abstained``
   true plus an ``abstention_reason`` naming what is missing (and,
   where useful, what source would settle it). An answer record with
   neither FAILS validation — ``pickup.py record-answer`` refuses it.
2. An abstention still carries answer text: the explicit statement
   the owner reads. The reason is the machine-readable companion.
3. A compound question is decomposed: each sub-answer is validated
   on its own (citations or its own abstention), and the composed
   answer's citations must include every sub-answer's citations.
4. ``question_type``, when present, is one of the four template
   types in ``answer-templates.md``.
5. When a wiki root is supplied, every citation must resolve to a
   real page under ``wiki/`` — either the exact path
   (``wiki/<id>.md``) or a unique page whose file stem equals the id
   (the legacy bare-stem style, e.g. ``decision-register``).

The judgement call — *is* the evidence sufficient? — stays with the
answering agent. What is deterministic, and enforced here, is the
shape of the outcome: cited answer, or flagged abstention.

The remainder of batch 2.1 (same approval) adds, in this module:

6. **Ask modes.** A record may carry ``mode`` — ``search``,
   ``answer`` or ``deep-research`` (chosen by the asker at the API
   door; absent means ``answer``, which is also how every legacy
   record reads). Mode rules: a ``search`` answer is passages only,
   so a non-abstained search record must carry at least one citation
   with a passage; a ``deep-research`` record must be decomposed
   (>= 2 sub-answers) unless it abstains.
7. **Scored citations with highlighted passages.** A citation is
   either a plain page id (the legacy form, always valid) or a rich
   entry ``{"page": <id>, "score": <0..1>, "passage": "<verbatim
   excerpt>"}`` — inline in ``citations``, or in the parallel
   ``citation_details`` list keyed by page. A rich entry must have
   BOTH a score in range AND a passage, and — when a wiki root is
   supplied — the passage must actually appear in the cited page's
   text (whitespace/smart-quote normalisation only, the quote-lane
   rule from ``scripts/wiki_cite_lock.py``). A detail naming a page
   that is not among the citations is an error.
8. **Trust verdict.** :func:`compute_trust_verdict` derives
   ``ok`` / ``hold`` / ``review`` deterministically (see its
   docstring for the stated rule). A stored ``trust_verdict``, when
   present, must be one of the three and must agree with the
   structural verdict (computed without page text); a stored
   ``review`` over a structural ``ok`` is also accepted, because the
   page-text overlay (an open contradiction callout on a cited page)
   can legitimately raise ``ok`` to ``review``. Records with no
   ``trust_verdict`` at all are legacy and grandfathered — they
   validate exactly as before.
9. **Datamarking (wave-3 build, 2026-10-20).** Retrieved passages
   are DATA, never instructions. Before composition, every packed
   passage is wrapped in the datamark scheme below
   (:func:`datamark_passage` / :func:`datamark_evidence`): the
   marks carry the passage's provenance (page, score) and delimit
   it, so instruction-shaped text inside a passage is visibly
   quoted evidence, not a directive to the answering agent
   (Spotlighting's datamarking layer). The contract-side check:
   :func:`instruction_leak_findings` flags an answer that quotes
   instruction-shaped content from one of its own cited passages
   verbatim, as if the passage were giving orders — the flag
   raises the trust verdict to ``review`` (never a hard refusal:
   a page that legitimately states a rule can trip the heuristic,
   and ``review`` is exactly the "a human looks" outcome). The
   full CaMeLS design — a quarantined extractor that reads
   untrusted content but holds no capabilities, feeding a planner
   that never sees raw text — is the recorded next step
   (``tools/ask/pickup.md``, "Injection defence"); it is NOT
   implemented here, and nothing in this module pretends to be it.

10. **Chain-hedge hold (item 34, 2026-10-20; AbstentionBench,
    wave 8).** AbstentionBench's sharpest finding: models give
    definitive answers *even when their own reasoning chains
    express uncertainty* — "the chain hedges, the answer doesn't".
    A record may carry the answering chain's text (``chain`` or
    ``reasoning``, top-level or per sub-answer). When a unit's
    chain expresses uncertainty (the documented hedge patterns in
    :func:`chain_hedge_findings`) while the unit itself is NOT
    abstained, the trust verdict is forced to ``hold`` — the
    harness-side escalation the wave-10 ISE find assigns to the
    harness, not the model. Records carrying no chain text are
    unaffected. The abstention regression battery
    (``evaluation/abstention-battery.jsonl``, run by
    ``scripts/wiki_abstention_check.py``) pins this behaviour.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

from pathlib import Path

QUESTION_TYPES = ("factual", "comparison", "synthesis", "decision-history")

ASK_MODES = ("search", "answer", "deep-research")
DEFAULT_ASK_MODE = "answer"

TRUST_VERDICTS = ("ok", "hold", "review")

# Trust-verdict thresholds (the stated rule; see compute_trust_verdict).
# A single relied-upon passage scoring below the floor means the
# answer leans on barely-relevant evidence.
WEAK_SCORE_FLOOR = 0.25
# Mean relevance of the scored citations below this is weak evidence.
MEAN_SCORE_FLOOR = 0.50
# Within one answer unit, a score spread at least this wide whose low
# end is also below CONFLICT_MIN_CEILING means strong and weak
# evidence are cited side by side for the same claim: review.
CONFLICT_SPREAD = 0.60
CONFLICT_MIN_CEILING = 0.40

# The wiki's contradiction callout (AGENTS.md: contradictions are
# flagged in place with a ``> [!warning] Contradiction`` callout).
CONTRADICTION_MARKER = "[!warning] Contradiction"


# ---------------------------------------------------------------------------
# Citation resolution
# ---------------------------------------------------------------------------

def citation_path(citation, wiki_dir):
    """The Path of the page *citation* names under *wiki_dir*, or None.

    Accepts the full page id (``syntheses/decision-register`` ->
    ``wiki/syntheses/decision-register.md``) or a bare file stem
    (``decision-register``) that matches exactly one page.
    """
    wiki_dir = Path(wiki_dir)
    cid = str(citation).strip()
    if not cid:
        return None
    direct = wiki_dir / (cid + ".md")
    if direct.is_file():
        return direct
    stem_matches = [
        p for p in wiki_dir.rglob("*.md") if p.stem == cid
    ]
    return stem_matches[0] if len(stem_matches) == 1 else None


def citation_resolves(citation, wiki_dir) -> bool:
    """True when *citation* names a real page under *wiki_dir*."""
    return citation_path(citation, wiki_dir) is not None


_NORMALIZE_TEXT = None


def _normalize_text(text: str) -> str:
    """Whitespace/smart-quote normalisation for passage checks.

    Reuses the citation lockfile's quote-lane normalisation
    (``scripts/wiki_cite_lock.py``: smart quotes to straight, all
    whitespace runs to single spaces) — the same rule the wiki's
    quote-verification lane applies, loaded lazily by path so this
    module stays importable on its own.
    """
    global _NORMALIZE_TEXT
    if _NORMALIZE_TEXT is None:
        import importlib.util

        lock_path = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "wiki_cite_lock.py"
        )
        spec = importlib.util.spec_from_file_location(
            "wiki_cite_lock", lock_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _NORMALIZE_TEXT = module.normalize_text
    return _NORMALIZE_TEXT(text)


def _passage_in_page(passage: str, page_text: str) -> bool:
    """True when *passage* appears verbatim (normalised) in the page."""
    needle = _normalize_text(passage)
    if not needle:
        return False
    return needle in _normalize_text(page_text)


# ---------------------------------------------------------------------------
# Normalisation: payload form and stored-record form -> one shape
# ---------------------------------------------------------------------------

def _citation_entry(raw) -> dict:
    """Normalise one citation into an entry dict.

    Plain form (legacy, always valid): a page-id string.
    Rich form: a dict with ``page`` (or the legacy alias keys ``id``
    / ``page_id``) plus ``score`` and/or ``passage``. An entry is
    *rich* when it carries a score or a passage key at all; rich
    entries must then carry both, valid (checked in _check_unit).
    """
    if isinstance(raw, dict):
        page = raw.get("page") or raw.get("id") or raw.get("page_id")
        return {
            "page": str(page).strip() if page is not None else "",
            "score": raw.get("score"),
            "passage": raw.get("passage"),
            "rich": ("score" in raw) or ("passage" in raw),
        }
    return {
        "page": str(raw).strip(),
        "score": None,
        "passage": None,
        "rich": False,
    }


def _normalise_citations(source: dict) -> list:
    """Merge ``citations`` and the parallel ``citation_details`` list.

    Details are keyed by page and overlay the matching citation;
    details naming a page that is not cited are kept as entries with
    ``orphan_detail`` set, so validation can name the error.
    """
    entries = []
    by_page = {}
    for raw in source.get("citations") or []:
        entry = _citation_entry(raw)
        entries.append(entry)
        if entry["page"]:
            by_page.setdefault(entry["page"], entry)
    for raw in source.get("citation_details") or []:
        detail = _citation_entry(raw)
        target = by_page.get(detail["page"])
        if target is None:
            detail["orphan_detail"] = True
            entries.append(detail)
        else:
            if "score" in (raw if isinstance(raw, dict) else {}):
                target["score"] = detail["score"]
                target["rich"] = True
            if "passage" in (raw if isinstance(raw, dict) else {}):
                target["passage"] = detail["passage"]
                target["rich"] = True
    return entries


def _normalise(source: dict) -> dict:
    """Normalise an answer payload or a stored Q&A record.

    Payload form signals abstention by the presence of
    ``abstention_reason``; stored records carry ``abstained`` plus
    ``abstention_reason``. Both normalise to the same shape.
    """
    reason = source.get("abstention_reason")
    abstained = bool(source.get("abstained")) or bool(
        isinstance(reason, str) and reason.strip()
    )
    entries = _normalise_citations(source)
    sub_answers = []
    for sub in source.get("sub_answers") or []:
        if isinstance(sub, dict):
            sub_answers.append(_normalise(sub))
    return {
        "answer": source.get("answer"),
        "citations": [e["page"] for e in entries if e["page"]],
        "citation_entries": entries,
        "abstained": abstained,
        "abstention_reason": reason,
        "question_type": source.get("question_type"),
        "mode": source.get("mode"),
        "trust_verdict": source.get("trust_verdict"),
        "sub_answers": sub_answers,
    }


# ---------------------------------------------------------------------------
# Trust verdict
# ---------------------------------------------------------------------------

def _verdict_units(unit: dict) -> list:
    """All answer units a verdict judges: the answer + its sub-answers."""
    if unit["sub_answers"]:
        return [unit] + list(unit["sub_answers"])
    return [unit]


def _structural_verdict(unit: dict) -> str:
    """The trust verdict from record shape alone (no page text).

    The stated rule, in order — ``hold`` outranks ``review``:

    1. An abstention is ``hold`` (the answer itself says the
       evidence was not there).
    2. Any answer unit with neither citations nor an abstention is
       ``hold`` (an uncited claim).
    3. Weak evidence is ``hold``: any scored citation below
       WEAK_SCORE_FLOOR, or a mean scored-citation relevance below
       MEAN_SCORE_FLOOR.
    4. Conflicting evidence is ``review``: within one unit, scored
       citations whose spread is at least CONFLICT_SPREAD with the
       low end below CONFLICT_MIN_CEILING — strong and weak evidence
       cited side by side for the same claim.
    5. Otherwise ``ok``. Unscored (legacy plain) citations are
       neutral: they neither weaken nor strengthen the verdict.
    """
    if unit["abstained"]:
        return "hold"
    units = _verdict_units(unit)
    for sub in units:
        if sub["abstained"]:
            continue
        if not [c for c in sub["citations"] if str(c).strip()]:
            return "hold"
    scores = [
        float(entry["score"])
        for sub in units
        for entry in sub["citation_entries"]
        if isinstance(entry["score"], (int, float))
        and not isinstance(entry["score"], bool)
    ]
    if scores:
        if min(scores) < WEAK_SCORE_FLOOR:
            return "hold"
        if sum(scores) / len(scores) < MEAN_SCORE_FLOOR:
            return "hold"
    for sub in units:
        sub_scores = [
            float(entry["score"])
            for entry in sub["citation_entries"]
            if isinstance(entry["score"], (int, float))
            and not isinstance(entry["score"], bool)
        ]
        if len(sub_scores) >= 2:
            spread = max(sub_scores) - min(sub_scores)
            if spread >= CONFLICT_SPREAD and min(sub_scores) < CONFLICT_MIN_CEILING:
                return "review"
    return "ok"


# ---------------------------------------------------------------------------
# Chain-hedge detection (item 34; AbstentionBench, wave 8)
# ---------------------------------------------------------------------------

# Uncertainty as expressed by an answering chain about its own
# evidence: the phrases a chain uses when it is NOT sure, whatever
# the final answer goes on to claim. Deliberately narrow and
# documented — first-person / evidence-directed uncertainty, not
# mere conditionals in the subject matter.
_HEDGE_PATTERNS = None


def _hedge_patterns():
    global _HEDGE_PATTERNS
    if _HEDGE_PATTERNS is None:
        import re

        _HEDGE_PATTERNS = [
            re.compile(p, re.I)
            for p in (
                r"\bnot sure\b",
                r"\buncertain\b",
                r"\bunclear (whether|if|from)\b",
                r"\binsufficient evidence\b",
                r"\bno (direct |clear )?evidence\b",
                r"\bcannot (determine|verify|confirm|tell)\b",
                r"\bunable to (determine|verify|confirm)\b",
                r"\bdon'?t know\b",
                r"\bmight not be\b",
                r"\bmay not be\b",
                r"\bthe wiki (does not|doesn't|doesn’t) "
                r"(say|record|state|mention|settle)\b",
                r"\bnot recorded (anywhere|in the wiki)\b",
            )
        ]
    return _HEDGE_PATTERNS


def _chain_texts(source: dict) -> list:
    """(label, chain text, abstained) per answer unit, raw form.

    Chain text lives in the optional ``chain`` / ``reasoning``
    fields — top-level for the composed unit, per dict in
    ``sub_answers``. Abstention status comes from the normalised
    unit at the same position, so payload and stored forms agree.
    """
    unit = _normalise(source)
    units = [(("answer"), source, unit)]
    raw_subs = source.get("sub_answers") or []
    for index, sub in enumerate(unit["sub_answers"]):
        raw = raw_subs[index] if index < len(raw_subs) else {}
        units.append(("sub_answers[%d]" % index, raw, sub))
    found = []
    for label, raw, norm in units:
        if not isinstance(raw, dict):
            continue
        text = raw.get("chain") or raw.get("reasoning")
        if isinstance(text, str) and text.strip():
            found.append((label, text, norm["abstained"]))
    return found


def chain_hedge_findings(source: dict) -> list:
    """Chain-hedge findings for an answer payload or record.

    One finding per answer unit whose carried chain text matches
    a hedge pattern while the unit is not abstained: the chain
    expressed uncertainty the answer does not carry. Findings
    are ``{"unit", "excerpt"}`` dicts. A unit that abstains is
    the contract working, not a hedge — it never appears here.
    """
    if not isinstance(source, dict):
        return []
    findings = []
    for label, text, abstained in _chain_texts(source):
        if abstained:
            continue
        for pattern in _hedge_patterns():
            match = pattern.search(text)
            if match:
                start = max(0, match.start() - 40)
                findings.append({
                    "unit": label,
                    "excerpt": text[start:match.end() + 40].strip(),
                })
                break
    return findings


def compute_trust_verdict(source: dict, wiki_dir=None) -> str:
    """Compute the trust verdict for an answer payload or record.

    The structural rule (see :func:`_structural_verdict`), plus
    overlays:

    - **Chain hedge** (no wiki root needed): a non-abstained
      unit's chain expresses uncertainty its answer does not
      carry — the verdict is forced to ``hold``, outranking the
      ``review`` overlays (``hold`` outranks ``review``, as in
      the structural rule). See :func:`chain_hedge_findings`.
    - **Instruction leak** (no wiki root needed): the answer quotes
      instruction-shaped content from one of its own cited passages
      verbatim — raises ``ok`` to ``review``.
    - **Open contradiction** (needs *wiki_dir*): a citation to a
      page carrying an open ``> [!warning] Contradiction`` callout
      — raises ``ok`` to ``review``.
    """
    if not isinstance(source, dict):
        return "hold"
    unit = _normalise(source)
    verdict = _structural_verdict(unit)
    if verdict != "hold" and chain_hedge_findings(source):
        return "hold"
    if verdict == "ok" and _leak_findings(unit):
        verdict = "review"
    if verdict == "ok" and wiki_dir is not None:
        pages = {
            entry["page"]
            for sub in _verdict_units(unit)
            for entry in sub["citation_entries"]
            if entry["page"]
        }
        for page in pages:
            path = citation_path(page, wiki_dir)
            if path is None:
                continue
            text = path.read_text(encoding="utf-8")
            if any(
                line.lstrip().startswith("> " + CONTRADICTION_MARKER)
                or line.lstrip().startswith(">" + CONTRADICTION_MARKER)
                for line in text.splitlines()
            ):
                return "review"
    return verdict


# ---------------------------------------------------------------------------
# Datamarking (wave-3 build, 2026-10-20)
#
# Retrieved passages are DATA, never instructions. Before the
# answering agent composes, each packed passage is wrapped in the
# marks below: the opening mark carries the passage's provenance
# (page, and its relevance score when scored) and the closing mark
# ends the data region. Instruction-shaped text inside the marks is
# quoted evidence about what a page says — it is never a directive
# to the agent, and the pickup procedure states this as a rule.
# (Pattern: Spotlighting's datamarking, the light layer of the
# CaMeLS design; the quarantined-extractor half is documented as
# the next step in tools/ask/pickup.md, not implemented here.)
# ---------------------------------------------------------------------------

DATA_MARK_OPEN = "<<<DATA"
DATA_MARK_CLOSE = "<<</DATA>>>"

# How the opening mark of a passage begins, for the extractor.
_DATA_BLOCK_RE = None


def _data_block_re():
    global _DATA_BLOCK_RE
    if _DATA_BLOCK_RE is None:
        import re

        _DATA_BLOCK_RE = re.compile(
            r"<<<DATA\s+page=\"(?P<page>[^\"]*)\""
            r"(?:\s+score=\"(?P<score>[^\"]*)\")?"
            r"\s*>>>\n(?P<passage>.*?)\n<<</DATA>>>",
            re.S,
        )
    return _DATA_BLOCK_RE


def _neutralise_marks(text: str) -> str:
    """Break any literal datamark tokens inside *text*.

    A passage that itself contains the closing mark would corrupt
    the block structure; the tokens are spaced out so the text
    survives as data without ending the data region early.
    """
    return text.replace(DATA_MARK_CLOSE, "<<< /DATA >>>").replace(
        DATA_MARK_OPEN, "<<< DATA"
    )


def datamark_passage(page, passage, score=None) -> str:
    """Wrap one retrieved passage in the datamark scheme.

    The result is::

        <<<DATA page="<page>" score="<score>">>>
        <passage, verbatim>
        <<</DATA>>>

    The ``score`` attribute is omitted when *score* is not a number.
    The passage text is verbatim except that literal datamark
    tokens inside it are neutralised (see :func:`_neutralise_marks`).
    """
    attrs = 'page="%s"' % str(page).strip()
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        attrs += ' score="%.2f"' % float(score)
    return "%s %s>>>\n%s\n%s" % (
        DATA_MARK_OPEN,
        attrs,
        _neutralise_marks(str(passage)),
        DATA_MARK_CLOSE,
    )


def datamark_evidence(passages) -> str:
    """Datamark a set of retrieved passages for composition.

    *passages* is an iterable of dicts with ``page`` and ``passage``
    keys and normally a ``score`` — the shape
    ``evidence_packing.pack_evidence`` returns in its ``packed``
    list, so the pickup flow is: pack, then datamark the packed
    output, then compose from the marked block only. Blocks are
    joined by a blank line; an empty input gives an empty string.
    """
    blocks = []
    for passage in passages or []:
        blocks.append(
            datamark_passage(
                passage.get("page", ""),
                passage.get("passage", ""),
                passage.get("score"),
            )
        )
    return "\n\n".join(blocks)


def extract_datamarked(text) -> list:
    """Parse datamarked blocks out of *text*.

    Returns a list of ``{"page", "score", "passage"}`` dicts
    (``score`` a float, or None when the mark carried none) — the
    inverse of :func:`datamark_passage`, so tooling (and tests) can
    verify that what was composed from is exactly what was marked.
    """
    found = []
    for match in _data_block_re().finditer(str(text)):
        score = match.group("score")
        found.append(
            {
                "page": match.group("page"),
                "score": float(score) if score is not None else None,
                "passage": match.group("passage"),
            }
        )
    return found


# Instruction-shaped content: imperative or meta-instruction phrasing
# that, inside retrieved text, is the signature of an injection
# attempt (or of a page stating rules — the flag's consequence is
# ``review``, never refusal, for exactly that reason). The list is a
# documented heuristic, deliberately narrow: classic override
# phrasing, direct imperatives to the agent, and secrecy/output
# directives.
_INSTRUCTION_PATTERNS = None


def _instruction_patterns():
    global _INSTRUCTION_PATTERNS
    if _INSTRUCTION_PATTERNS is None:
        import re

        _INSTRUCTION_PATTERNS = [
            re.compile(p, re.I)
            for p in (
                r"ignore\s+(all\s+)?(previous|prior|above|preceding)\s+"
                r"(instructions?|directions?|prompts?|rules?)",
                r"disregard\s+(the\s+)?(above|previous|prior|earlier)\b",
                r"forget\s+(everything|all\s+previous|your\s+instructions)",
                r"new\s+instructions?\s*[:\-]",
                r"note\s+to\s+(the\s+)?(agent|assistant|ai|model|reader)\s*[:\-]",
                r"\byou\s+(must|shall|should|need\s+to)\b",
                r"\bdo\s+not\s+(mention|reveal|share|disclose|tell|say|"
                r"cite|answer)\b",
                r"\bnever\s+(reveal|disclose|share|mention|tell|say)\b",
                r"\balways\s+(respond|answer|reply|say|output|include)\b",
                r"\b(reveal|disclose|print|output|leak)\s+(the\s+)?"
                r"(token|password|secret|key|credentials?)\b",
            )
        ]
    return _INSTRUCTION_PATTERNS


def _is_instruction_shaped(sentence: str) -> bool:
    """True when *sentence* matches an instruction pattern."""
    return any(p.search(sentence) for p in _instruction_patterns())


def _match_text(text: str) -> str:
    """Normalise text for containment matching (lowercased)."""
    return _normalize_text(str(text)).lower()


# A verbatim run of this many consecutive words from an
# instruction-shaped passage sentence, reproduced in the answer,
# is the leak signature: the answer is repeating the passage's
# orders, not reporting its facts.
LEAK_WINDOW_WORDS = 6


def _leak_findings(unit: dict) -> list:
    """Instruction-leak findings for a normalised answer unit.

    For every cited passage (top-level and sub-answers), each
    instruction-shaped sentence is windowed into runs of
    LEAK_WINDOW_WORDS words; if any run appears verbatim
    (normalised) in any answer text of the record, the passage is
    leaking into the answer as a directive. Returns a list of
    ``{"page", "excerpt"}`` findings, de-duplicated.
    """
    import re

    units = _verdict_units(unit)
    answer_texts = [
        _match_text(u["answer"]) for u in units
        if isinstance(u["answer"], str)
    ]
    if not answer_texts:
        return []
    findings = []
    seen = set()
    for sub in units:
        for entry in sub["citation_entries"]:
            passage = entry["passage"]
            if not isinstance(passage, str) or not passage.strip():
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", passage):
                sentence = sentence.strip()
                if not sentence or not _is_instruction_shaped(sentence):
                    continue
                words = _match_text(sentence).split()
                if len(words) < LEAK_WINDOW_WORDS:
                    continue
                leaked = any(
                    " ".join(words[i:i + LEAK_WINDOW_WORDS]) in text
                    for text in answer_texts
                    for i in range(len(words) - LEAK_WINDOW_WORDS + 1)
                )
                if leaked:
                    key = (entry["page"], sentence[:120])
                    if key not in seen:
                        seen.add(key)
                        findings.append(
                            {"page": entry["page"],
                             "excerpt": sentence[:120]}
                        )
    return findings


def instruction_leak_findings(source: dict) -> list:
    """Instruction-leak findings for an answer payload or record.

    The datamarking contract check: an answer that quotes
    instruction-shaped content from one of its own cited passages
    verbatim is treating retrieved data as directives. Findings are
    ``{"page", "excerpt"}`` dicts; an empty list means no leak was
    detected. Detection is a heuristic over the passages carried in
    the record itself (``citation_details``); answers composed from
    unscored plain citations carry no passages and cannot leak in
    this checkable sense.
    """
    if not isinstance(source, dict):
        return []
    return _leak_findings(_normalise(source))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_entries(unit: dict, wiki_dir, label: str, errors: list) -> None:
    """Validate one unit's citation entries (plain and rich)."""
    for entry in unit["citation_entries"]:
        page = entry["page"]
        if entry.get("orphan_detail"):
            errors.append(
                "%s: citation detail names page %r, which is not "
                "among the citations" % (label, page)
            )
            continue
        if not page:
            errors.append("%s: citation with no page id" % label)
            continue
        path = None
        if wiki_dir is not None:
            path = citation_path(page, wiki_dir)
            if path is None:
                errors.append(
                    "%s: citation %r does not resolve to a wiki page"
                    % (label, page)
                )
        if not entry["rich"]:
            continue
        score = entry["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            errors.append(
                "%s: scored citation for %r needs a numeric score"
                % (label, page)
            )
        elif not 0.0 <= float(score) <= 1.0:
            errors.append(
                "%s: citation score %r for %r is outside 0..1"
                % (label, score, page)
            )
        passage = entry["passage"]
        if not isinstance(passage, str) or not passage.strip():
            errors.append(
                "%s: scored citation for %r needs the exact "
                "supporting passage" % (label, page)
            )
        elif path is not None:
            page_text = path.read_text(encoding="utf-8")
            if not _passage_in_page(passage, page_text):
                errors.append(
                    "%s: passage for %r is not contained in the "
                    "cited page's text" % (label, page)
                )


def _check_unit(unit: dict, wiki_dir, label: str, errors: list) -> None:
    """Validate one answer unit (a whole answer or one sub-answer)."""
    answer = unit["answer"]
    if not isinstance(answer, str) or not answer.strip():
        errors.append("%s: answer text is required" % label)
    citations = [c for c in unit["citations"] if str(c).strip()]
    if unit["abstained"]:
        reason = unit["abstention_reason"]
        if not isinstance(reason, str) or not reason.strip():
            errors.append(
                "%s: abstention requires an abstention_reason naming "
                "what is missing" % label
            )
    elif not citations:
        errors.append(
            "%s: no citations and no abstention — an answer must cite "
            "wiki pages or abstain (abstention contract)" % label
        )
    _check_entries(unit, wiki_dir, label, errors)


def validate_answer(source: dict, wiki_dir=None) -> list:
    """Validate an answer payload or stored Q&A record.

    Returns a list of error strings; an empty list means the answer
    satisfies the abstention contract. ``wiki_dir`` (the ``wiki/``
    directory) enables the citation-resolution check; without it,
    only the structural checks run.
    """
    if not isinstance(source, dict):
        return ["answer must be a JSON object"]
    unit = _normalise(source)
    errors: list = []

    qtype = unit["question_type"]
    if qtype is not None and qtype not in QUESTION_TYPES:
        errors.append(
            "question_type %r is not one of %s"
            % (qtype, ", ".join(QUESTION_TYPES))
        )

    mode = unit["mode"]
    if mode is not None and mode not in ASK_MODES:
        errors.append(
            "mode %r is not one of %s" % (mode, ", ".join(ASK_MODES))
        )
    elif mode == "search" and not unit["abstained"]:
        # Search mode is passages only: at least one citation must
        # carry the passage it was chosen for.
        if not any(
            entry["passage"] for entry in unit["citation_entries"]
        ):
            errors.append(
                "answer: search mode returns passages only — at "
                "least one citation must carry its supporting passage"
            )
    elif mode == "deep-research" and not unit["abstained"]:
        if len(unit["sub_answers"]) < 2:
            errors.append(
                "answer: deep-research mode must decompose the "
                "question into at least two sub-answers (or abstain)"
            )

    verdict = unit["trust_verdict"]
    if verdict is not None:
        if verdict not in TRUST_VERDICTS:
            errors.append(
                "trust_verdict %r is not one of %s"
                % (verdict, ", ".join(TRUST_VERDICTS))
            )
        else:
            structural = _structural_verdict(unit)
            # A stored "review" over a structural "ok" is legitimate:
            # the page-text overlay (open contradiction callout on a
            # cited page) raises ok -> review and is not visible to
            # the structural computation.
            if verdict != structural and not (
                verdict == "review" and structural == "ok"
            ):
                errors.append(
                    "trust_verdict %r disagrees with the computed "
                    "verdict %r" % (verdict, structural)
                )

    subs = unit["sub_answers"]
    if subs:
        for index, sub in enumerate(subs):
            _check_unit(sub, wiki_dir, "sub_answers[%d]" % index, errors)
        sub_citations = set()
        for sub in subs:
            sub_citations.update(
                str(c) for c in sub["citations"] if str(c).strip()
            )
        top_citations = {
            str(c) for c in unit["citations"] if str(c).strip()
        }
        missing = sorted(sub_citations - top_citations)
        if missing:
            errors.append(
                "composed answer's citations omit sub-answer "
                "citation(s): %s" % ", ".join(missing)
            )
        # The composed answer itself still needs its statement text,
        # and its own citation entries are held to the same checks.
        if not isinstance(unit["answer"], str) or not unit["answer"].strip():
            errors.append("answer: composed answer text is required")
        _check_entries(unit, wiki_dir, "answer", errors)
    else:
        _check_unit(unit, wiki_dir, "answer", errors)

    return errors
