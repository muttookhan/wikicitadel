#!/usr/bin/env python3
"""Lesson injection for the Ask door (W5, 2026-10-22).

The corrections ledger (``wiki/rules/corrections-ledger.md``)
is this wiki's memory of its own mistakes: every entry
leaves a standing rule. A rule nobody is reminded of at the
moment it matters is just history. This module is the
reminder, at the two moments the build-list item names:

- **At answer time** — when the Ask door composes an answer
  whose question or cited pages touch a recorded lesson's
  ground, the lesson is surfaced INTO the answer record as
  a labelled, cited block (``record["lessons"]``, rendered
  as a ``## Lessons on record`` section in the staged
  proposal, and named in the provenance envelope). The
  block rides BESIDE the answer: it is never woven into
  the answer's claims, and it is computed from the finished
  record — after retrieval, packing, governance and the
  abstention gate have all run — so it cannot change what
  the answer says, whether it abstains, or any score.
- **Before a decision** — the companion CLI
  (``scripts/wiki_pre_decision_challenge.py``) matches a
  proposed decision's text against the same lessons.

THE MATCHING RULE (deterministic, conservative, stated in
every block it produces):

  lesson tokens = the content tokens (the decision
  register's tokeniser: tokens of length >= 3 minus its
  stopword list) of the entry's title plus its standing-
  rule text;
  lesson pages  = the wiki page stems the entry's own
  record names — the wikilinks in its Recorded line and
  its body;
  a lesson MATCHES a question when the question's content
  tokens share AT LEAST TWO distinct terms with the lesson
  tokens, OR at least one page the answer cites is a page
  the lesson's record names;
  matches are ordered page-overlap first, then by shared-
  term count descending, then by ledger order, and capped
  at MAX_LESSONS (3).

One shared term is not enough: single common words ("cache",
"record", "the owner") would fire lessons on unrelated
questions, and a lesson block that cries wolf teaches
readers to skip it. Below the rule, there is no block at
all — a question with no matching lesson carries no
``lessons`` field, so records without one render and read
exactly as before this seam existed.

The lesson data itself is DERIVED, never restated: entries,
classifications, lifecycle states, gate postures and
evidence grades come from
``scripts/wiki_corrections_lifecycle.py``'s own report over
the ledger and the correction-outcomes register (the Round
9 heed-rate register), and the standing-rule text is the
ledger's own bullet text. Nothing about a lesson is
paraphrased or summarised here — the block quotes the
ledger and cites it (``wiki/rules/corrections-ledger.md``).

Clean re-implementation: the guardrail-hook and lesson-
surface patterns of the item's idea sources (memini,
klypix-mcp, callimachus) were taken as ideas only; no code
or text was copied from any of them, and the lifecycle /
decision machinery reused is this wiki's own.

Stdlib only, no network. Dates are inputs: the lifecycle
report is computed as of a caller-supplied ``today``
(default: the ledger's own latest entry date, so the
derivation is a pure function of the record); the fields
this module copies — state, grade, gate posture — do not
vary with that date, and a test pins it.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path

KIND = "ask-lessons"
VERSION = 1
LEDGER_REL = "wiki/rules/corrections-ledger.md"
REGISTER_REL = "evaluation/correction-outcomes.jsonl"
MAX_LESSONS = 3
MIN_SHARED_TERMS = 2

MATCH_RULE_TEXT = (
    "a lesson matches when the question shares at least "
    f"{MIN_SHARED_TERMS} distinct content terms with the "
    "lesson's title + standing-rule text, or cites at least "
    "one page the lesson's record names; ordered "
    "page-overlap first, then shared-term count, then "
    "ledger order"
)

_HEADING_DATE_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) — ", re.M)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lifecycle_module(root):
    return _load("wiki_corrections_lifecycle",
                 Path(root) / "scripts" / "wiki_corrections_lifecycle.py")


def _tokens_module(root):
    return _load("wiki_decision_records",
                 Path(root) / "scripts" / "wiki_decision_records.py")


def _page_stem(name):
    """Normalise a page reference to its bare stem form, the
    way Ask citations carry page ids (``concepts/llm-wiki``
    keeps its path; a wikilink target is already bare)."""
    s = str(name).strip()
    if s.endswith(".md"):
        s = s[:-3]
    return s.lower()


def _default_today(ledger_text):
    """The ledger's own latest entry date — the derivation
    stays a pure function of the record (no wall clock)."""
    dates = _HEADING_DATE_RE.findall(ledger_text)
    if dates:
        return date.fromisoformat(max(dates))
    return date(1970, 1, 1)


def load_lessons(root, today=None):
    """Every ledger lesson, derived from the lifecycle
    report. Raises FileNotFoundError when the tree carries
    no ledger — callers decide whether that is a door (the
    challenge CLI) or a silent no-block (the Ask seam,
    which must never cost an answer its record)."""
    root = Path(root)
    ledger_path = root / LEDGER_REL
    if not ledger_path.is_file():
        raise FileNotFoundError(f"no corrections ledger at {ledger_path}")
    ledger_text = ledger_path.read_text(encoding="utf-8")
    lifecycle = _lifecycle_module(root)
    tokens_of = _tokens_module(root).tokens
    if today is None:
        today = _default_today(ledger_text)
    elif isinstance(today, str):
        today = date.fromisoformat(today)
    outcomes = lifecycle.load_outcomes(root / REGISTER_REL)
    report = lifecycle.build_report(ledger_text, outcomes, today, root)
    bodies = lifecycle.parse_bodies(ledger_text)

    lessons = []
    for row in report["entries"]:
        key = row["entry"]
        body = bodies.get(key, {"bullets": {}, "lines": []})
        rule_text = body["bullets"].get("Standing rule", "")
        pages = set()
        for ref in row.get("recorded_refs") or []:
            if ref.get("kind") == "wikilink":
                pages.add(_page_stem(ref["ref"]))
        for line in body["lines"]:
            for w in _WIKILINK_RE.findall(line):
                pages.add(_page_stem(w))
        lessons.append({
            "entry": key,
            "date": row["date"],
            "title": row["title"],
            "class": row["class"],
            "kind": row["kind"],
            "rule": row["rule"],
            "rule_text": rule_text,
            "state": row["state"],
            "gate": (row.get("gate") or {}).get("posture"),
            "grade": row["grade"],
            "citation": LEDGER_REL,
            "tokens": sorted(tokens_of(
                (row["title"] or "") + " " + rule_text)),
            "pages": sorted(pages),
        })
    return lessons


def match_by_tokens(lessons, q_tokens, pages=(), cap=MAX_LESSONS):
    """The matching rule of the module docstring, applied.
    ``lessons`` are load_lessons dicts (their ``tokens`` and
    ``pages`` fields drive the match); ``q_tokens`` is the
    question's content-token set, tokenised by the caller
    with the decision register's own tokeniser (see
    question_tokens) so the match runs in one stated
    vocabulary. Returns match dicts — the lesson's public
    fields plus its ``basis`` — ordered and capped as the
    rule states."""
    return _match(lessons, set(q_tokens or ()),
                  {_page_stem(p) for p in pages or ()}, cap)


def _match(lessons, q_tokens, q_pages, cap):
    scored = []
    for idx, lesson in enumerate(lessons):
        shared = sorted(set(lesson.get("tokens") or ()) & (q_tokens or set()))
        page_hits = sorted(set(lesson.get("pages") or ()) & q_pages)
        if len(shared) < MIN_SHARED_TERMS and not page_hits:
            continue
        basis = []
        if page_hits:
            basis.append({"signal": "page-overlap", "pages": page_hits})
        if shared:
            basis.append({"signal": "shared-terms",
                          "terms": shared, "count": len(shared)})
        scored.append((0 if page_hits else 1, -len(shared), idx,
                       lesson, basis))
    scored.sort(key=lambda s: (s[0], s[1], s[2]))
    out = []
    for _rank, _neg, _idx, lesson, basis in scored[:cap]:
        out.append({
            "entry": lesson["entry"],
            "date": lesson["date"],
            "title": lesson["title"],
            "rule": lesson["rule"],
            "kind": lesson["kind"],
            "class": lesson["class"],
            "state": lesson["state"],
            "gate": lesson["gate"],
            "grade": lesson["grade"],
            "rule_text": lesson["rule_text"],
            "citation": lesson["citation"],
            "basis": basis,
        })
    return out


def question_tokens(root, text):
    """Content tokens of a text, by the decision register's
    own tokeniser (the vocabulary the match is stated in)."""
    return _tokens_module(root).tokens(text or "")


def cited_pages_of(record):
    """Every page a finished record rests on, in record
    order: plain citations, citation details, sub-answers,
    and the provenance envelope's per-citation pages."""
    pages = []

    def add(p):
        if p and str(p) not in pages:
            pages.append(str(p))

    for c in record.get("citations") or []:
        add(c)
    for d in record.get("citation_details") or []:
        if isinstance(d, dict):
            add(d.get("page") or d.get("id"))
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            for c in sub.get("citations") or []:
                add(c)
    prov = record.get("provenance")
    if isinstance(prov, dict):
        for c in prov.get("citations") or []:
            if isinstance(c, dict):
                add(c.get("page"))
    return pages


def build_lessons_block(record, root, today=None):
    """The lessons block for one finished answer record, or
    None when no lesson matches. Computed from the record
    alone (its question + the pages it cites) against the
    ledger at ``root`` — after the answer exists, so by
    construction it cannot have influenced it."""
    record = record if isinstance(record, dict) else {}
    lessons = load_lessons(root, today=today)
    matched = match_by_tokens(
        lessons,
        question_tokens(root, record.get("question")),
        pages=cited_pages_of(record),
    )
    if not matched:
        return None
    return {
        "kind": KIND,
        "version": VERSION,
        "ledger": LEDGER_REL,
        "lessons_considered": len(lessons),
        "cap": MAX_LESSONS,
        "rule": MATCH_RULE_TEXT,
        "matched": matched,
    }


def _basis_summary(basis):
    bits = []
    for b in basis or []:
        if b.get("signal") == "page-overlap":
            bits.append("cites page(s) named in the lesson's "
                        "record: " + ", ".join(b["pages"]))
        elif b.get("signal") == "shared-terms":
            bits.append("shares terms: " + ", ".join(b["terms"]))
    return "; ".join(bits)


def render_lessons(record):
    """The staged proposal's ``## Lessons on record``
    section lines for a record carrying a lessons block, or
    None. The section names each lesson, quotes its
    standing rule verbatim from the ledger, and states why
    it was shown — it adds no claim to the answer."""
    block = record.get("lessons") if isinstance(record, dict) else None
    if not isinstance(block, dict):
        return None
    matched = [m for m in block.get("matched") or []
               if isinstance(m, dict)]
    if not matched:
        return None
    lines = ["## Lessons on record", ""]
    lines.append(
        "Recorded corrections whose ground this answer "
        "touches, surfaced from the corrections ledger — "
        "they ride beside the answer, not inside it "
        "(tools/ask/lessons.py)."
    )
    lines.append("")
    for m in matched:
        head = "**" + str(m.get("title")) + "**"
        if m.get("date"):
            head += " (" + str(m["date"]) + ")"
        facts = []
        if m.get("rule"):
            facts.append("rule `" + str(m["rule"]) + "`")
        if m.get("kind"):
            facts.append("error kind " + str(m["kind"]))
        if m.get("state"):
            facts.append("lifecycle state " + str(m["state"]))
        if m.get("gate"):
            facts.append("gate " + str(m["gate"]))
        lines.append("- " + head
                     + (" — " + ", ".join(facts) if facts else ""))
        if m.get("rule_text"):
            lines.append("  Standing rule: " + str(m["rule_text"]))
        why = _basis_summary(m.get("basis"))
        tail = "Ledger: " + str(m.get("citation") or LEDGER_REL) + "."
        lines.append("  " + (("Why shown: " + why + ". ") if why else "")
                     + tail)
    lines.append("")
    return lines
