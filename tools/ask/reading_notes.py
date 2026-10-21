#!/usr/bin/env python3
"""Chain-of-Note reading-notes step for the Ask door
(Marathon R4 lane D, item 3).

Pattern: Chain-of-Note (Yu et al., CC BY 4.0) — before composing
an answer, write one short relevance note for each retrieved
page, and keep those notes with the answer's working record, so
the reasoning from retrieval to answer is inspectable afterwards
instead of living only in the answering agent's head.

Standing-contract discipline (same posture as two_phase.py):

- BEHIND A FLAG, default OFF. ``reading_notes_enabled`` is true
  only when a payload/record explicitly carries
  ``reading_notes: true`` (or the caller passes ``enabled=True``).
  With the flag off, :func:`attach_reading_notes` returns the
  record UNCHANGED — no ``notes`` field is added, and the record
  shape is exactly the pre-existing one.
- DETERMINISTIC AND EXTRACTIVE — NO MODEL CALLS. A note is built
  only from what retrieval already produced: the query terms the
  page's passage actually matches (``matched_terms``) and the
  page's own summary line (``summary``: the passage's first
  sentence, or the entry's ``summary`` field when the retriever
  supplied one), truncated to a stated length. Nothing is
  paraphrased, inferred, or generated.
- ADDITIVE / BACK-COMPATIBLE. With the flag on, the record gains
  one new top-level field, ``notes``: a list of
  ``{"page", "matched_terms", "summary", "note"}`` dicts, one per
  retrieved passage, in pack order. No existing field is renamed,
  removed, or re-typed, and ``answer_contract.validate_answer``
  accepts records with and without the field.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import re

SUMMARY_MAX_CHARS = 200

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an the what is are was were does do did of in on for from "
    "to and or it its this that".split())


def reading_notes_enabled(payload=None, enabled=None) -> bool:
    """The flag: explicit caller choice, else the payload's
    ``reading_notes`` field, else OFF (the standing default)."""
    if enabled is not None:
        return bool(enabled)
    if isinstance(payload, dict):
        return payload.get("reading_notes") is True
    return False


def _terms(text) -> list:
    return [t for t in _TOKEN_RE.findall(str(text or "").lower())
            if len(t) > 2 and t not in _STOP]


def _summary_line(entry: dict) -> str:
    """The page's own summary line, extractively: the entry's
    ``summary`` when the retriever supplied one, else the first
    sentence of its passage, truncated to SUMMARY_MAX_CHARS."""
    summary = entry.get("summary")
    if isinstance(summary, str) and summary.strip():
        line = summary.strip()
    else:
        passage = str(entry.get("passage") or "").strip()
        line = re.split(r"(?<=[.!?])\s+", passage, maxsplit=1)[0] \
            if passage else ""
    if len(line) > SUMMARY_MAX_CHARS:
        line = line[:SUMMARY_MAX_CHARS].rstrip() + "…"
    return line


def build_reading_notes(passages, question=None) -> list:
    """One relevance note per retrieved passage, in pack order.

    *passages* are the packed entries (``page`` / ``passage`` /
    optional ``score`` / optional ``summary``) — the shape
    ``evidence_packing.pack_evidence`` returns. *question* is the
    question text (or an iterable of query terms); the note's
    ``matched_terms`` are the question terms that occur in the
    passage, in question order, de-duplicated.
    """
    if question is None:
        q_terms = []
    elif isinstance(question, str):
        q_terms = _terms(question)
    else:
        q_terms = [str(t).lower() for t in question]
    q_terms = list(dict.fromkeys(q_terms))
    notes = []
    for entry in passages or []:
        if not isinstance(entry, dict):
            continue
        passage_terms = set(_terms(entry.get("passage")))
        matched = [t for t in q_terms if t in passage_terms]
        summary = _summary_line(entry)
        page = str(entry.get("page", ""))
        if matched:
            note = "Relevant to: %s — %s" % (", ".join(matched), summary)
        elif summary:
            note = "No query term matched — %s" % summary
        else:
            note = "No query term matched and no passage text carried."
        notes.append({
            "page": page,
            "matched_terms": matched,
            "summary": summary,
            "note": note,
        })
    return notes


def attach_reading_notes(record: dict, passages, question=None,
                         enabled=None) -> dict:
    """Return *record* with a ``notes`` field, when the flag is on.

    Flag OFF (the default): the record is returned unchanged —
    the identical object, no ``notes`` field added. Flag ON: a
    shallow copy of the record carrying ``notes`` (built by
    :func:`build_reading_notes`); the input record is never
    mutated. *question* defaults to the record's ``question``
    field when not supplied.
    """
    if not reading_notes_enabled(record, enabled):
        return record
    if question is None and isinstance(record, dict):
        question = record.get("question")
    out = dict(record)
    out["notes"] = build_reading_notes(passages, question)
    return out


def validate_reading_notes(record: dict) -> list:
    """Shape checks for the ``notes`` field, when present.

    Absent field = legacy record, no errors. Present: it must be
    a list of dicts each carrying a non-empty ``page``, a
    ``matched_terms`` list, and a non-empty ``note`` string.
    """
    if not isinstance(record, dict) or "notes" not in record:
        return []
    notes = record["notes"]
    if not isinstance(notes, list):
        return ["notes must be a list of per-page note dicts"]
    errors = []
    for i, note in enumerate(notes):
        if not isinstance(note, dict):
            errors.append("notes[%d] must be a dict" % i)
            continue
        if not str(note.get("page", "")).strip():
            errors.append("notes[%d] carries no page" % i)
        if not isinstance(note.get("matched_terms"), list):
            errors.append("notes[%d] matched_terms must be a list" % i)
        if not str(note.get("note", "")).strip():
            errors.append("notes[%d] carries no note text" % i)
    return errors
