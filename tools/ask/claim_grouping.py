#!/usr/bin/env python3
"""Claim-grouped citation presentation for the Ask door (W3, 2026-10-22).

Ask answers have always ended in a FLAT citation list: every
page the answer cites, dumped per answer under "Sources used".
This module derives the grouped presentation the staged
proposal renders above that list — citations attached PER
CLAIM, so a reader sees claim -> evidence as the structure:

- each claim (an answer sentence, or a decomposed sub-answer)
  is shown with the citations that support it grouped beneath
  it;
- a citation supporting more than one claim appears under
  each of them and is marked **shared**;
- a citation recorded for a part of the answer but supporting
  no single claim in it is still listed for that part, as
  unattached — grouped presentation never drops a citation
  the flat list would have shown.

GROUPING IS READ FROM THE RECORD, NEVER RE-DERIVED FROM
PROSE. Two recorded structures carry claim-level shape, in
this order:

1. **the provenance envelope** (``record["provenance"]``,
   built by ``tools/ask/provenance.py`` at answer time): its
   per-citation sentence links ARE the pipeline's own
   sentence-scoring result — which sentences each citation
   was selected to support, with the verdict and coverage.
   Links are attributed back to a unit (the top-level answer,
   or one sub-answer) by the same keys and sentence text the
   envelope recorded; sentences of a scored unit that no
   citation was selected for carry the scorer's verdict by
   construction (``score_sentence`` selects nothing exactly
   when the verdict is unsupported). The envelope is trusted
   only when it names this record (``question_id`` matches);
   a mismatched envelope is treated as absent.
2. **the sub-answer decomposition** (``record["sub_answers"]``):
   each sub-answer is one claim unit with its own citations,
   recorded when the compound question was decomposed. No
   sentence-level verdicts exist on this path, and the
   grouping says so — verdicts are absent, never synthesised.

Where NEITHER structure exists — a plain single-part answer
with a flat citation list — there is no claim structure to
present: ``group_claims`` returns None and the proposal keeps
its existing flat form byte-for-byte. Grouping never invents
a claim boundary the pipeline did not record.

Presentation only: no retrieval, scoring, packing or contract
code is touched, and nothing here writes a record — the
functions below are pure readings of the record they are
given, deterministic for the same record.

Licence posture: clean re-implementation. The idea — attach
citations per claim so each claim's support is inspectable
in place (the build list's row: Cited) — is restated against
this pipeline's own recorded structures; no code or text from
that project is held here.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sentence_scoring  # noqa: E402


# ---------------------------------------------------------------------------
# Recorded structure
# ---------------------------------------------------------------------------

def _trusted_envelope(record):
    """The record's provenance envelope, or None.

    Trusted only when it is an ask-provenance envelope naming
    THIS record: an envelope stamped for another question id
    is not this answer's structure and is treated as absent.
    """
    envelope = record.get("provenance")
    if not isinstance(envelope, dict):
        return None
    if envelope.get("kind") != "ask-provenance":
        return None
    record_id = record.get("id")
    if record_id is not None \
            and envelope.get("question_id") != record_id:
        return None
    return envelope


def _units(record):
    """The answer's units, in envelope order: the top-level
    answer first, then each sub-answer dict."""
    units = [("answer", record, None)]
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            units.append(
                ("sub-answer", sub, sub.get("question")))
    return units


def _cite_block(entry, shared=False):
    """One citation as the grouping carries it: the evidence
    entry's own key/page/score/passage."""
    return {
        "key": entry["key"],
        "page": entry["page"],
        "score": entry.get("score"),
        "passage": entry.get("passage"),
        "shared": bool(shared),
    }


def _group_from_envelope(unit_name, unit, entries, envelope):
    """Claims for one unit from the envelope's sentence links.

    The envelope's citations are keyed by the record-level
    evidence entries; a link is attributed to this unit when
    its key is one of this unit's entry keys, its unit label
    matches, and the sentence it names is this unit's sentence
    at the recorded index — exactly the fields provenance.py
    stamped at answer time. Sentences with no attributed link
    were scored and selected nothing: verdict "unsupported",
    coverage unrecorded (None).
    """
    by_key = {e["key"]: e for e in entries}
    env_citations = {}
    for citation in envelope.get("citations") or []:
        if isinstance(citation, dict) and citation.get("key"):
            env_citations[str(citation["key"])] = citation
    sentences = sentence_scoring.split_sentences(
        unit.get("answer") or "")
    attached = {}   # sentence index -> [cite blocks]
    verdicts = {}   # sentence index -> (verdict, coverage)
    used_keys = set()
    for index, sentence in enumerate(sentences):
        for key, citation in env_citations.items():
            if key not in by_key:
                continue
            for link in citation.get("sentences") or []:
                if not isinstance(link, dict):
                    continue
                if link.get("unit") != unit_name:
                    continue
                if link.get("index") != index:
                    continue
                if link.get("sentence") != sentence:
                    continue
                attached.setdefault(index, []).append(
                    _cite_block(by_key[key]))
                verdicts[index] = (
                    link.get("verdict"), link.get("coverage"))
                used_keys.add(key)
    claims = []
    for index, sentence in enumerate(sentences):
        verdict, coverage = verdicts.get(
            index, ("unsupported", None))
        claims.append({
            "index": index,
            "sentence": sentence,
            "verdict": verdict,
            "coverage": coverage,
            "citations": attached.get(index, []),
        })
    unattached = [
        _cite_block(e) for e in entries
        if e["key"] not in used_keys
    ]
    return {
        "unit": unit_name,
        "question": unit.get("question")
        if unit_name == "sub-answer" else None,
        "source": "provenance",
        "claims": claims,
        "unattached_citations": unattached,
    }


def _group_from_sub_answer(unit):
    """One claim for a sub-answer from the decomposition: the
    sub-answer's whole text is the claim; its citations are
    its recorded evidence. No sentence verdicts exist on this
    path — verdict and coverage stay None (not recorded)."""
    entries = sentence_scoring.evidence_entries(unit)
    return {
        "unit": "sub-answer",
        "question": unit.get("question"),
        "source": "sub-answers",
        "claims": [{
            "index": 0,
            "sentence": str(unit.get("answer") or ""),
            "verdict": None,
            "coverage": None,
            "citations": [_cite_block(e) for e in entries],
        }],
        "unattached_citations": [],
    }


def group_claims(record) -> dict | None:
    """The claim grouping for one Q&A *record*, or None.

    None means the record carries no claim structure to
    present (no trusted envelope sentence links and no
    sub-answer decomposition) — or the record is an
    abstention, which has no claims by construction. The
    caller then renders the existing flat form unchanged.
    """
    if not isinstance(record, dict) or record.get("abstained"):
        return None
    envelope = _trusted_envelope(record)
    units = _units(record)
    groups = []
    sub_groups = []
    for unit_name, unit, _question in units:
        entries = sentence_scoring.evidence_entries(unit)
        if unit_name == "answer":
            if envelope is not None and entries:
                groups.append(_group_from_envelope(
                    unit_name, unit, entries, envelope))
            # Without an envelope the top-level list is the
            # flat list itself; leftovers (citations no
            # sub-answer carries) are handled after the subs.
            continue
        if not entries:
            continue  # an uncited (e.g. abstained) sub-answer
        if envelope is not None:
            sub_groups.append(_group_from_envelope(
                unit_name, unit, entries, envelope))
        else:
            sub_groups.append(_group_from_sub_answer(unit))
    groups.extend(sub_groups)
    if envelope is None and sub_groups:
        # Citations recorded at answer level that no sub-answer
        # carries: shown as their own group, attached to no
        # single claim, rather than silently ungrouped.
        covered = set()
        for group in sub_groups:
            for claim in group["claims"]:
                for cite in claim["citations"]:
                    covered.add(cite["key"])
            for cite in group["unattached_citations"]:
                covered.add(cite["key"])
        leftover = [
            e for e in sentence_scoring.evidence_entries(record)
            if e["key"] not in covered
        ]
        if leftover:
            groups.insert(0, {
                "unit": "answer",
                "question": None,
                "source": "record",
                "claims": [],
                "unattached_citations": [
                    _cite_block(e) for e in leftover],
            })
    if not groups:
        return None
    # Shared: a citation key supporting two or more distinct
    # claims, anywhere in the answer, is marked on every
    # occurrence and named once at the top.
    claim_count = {}
    for group in groups:
        for claim in group["claims"]:
            for cite in claim["citations"]:
                claim_count[cite["key"]] = \
                    claim_count.get(cite["key"], 0) + 1
    shared_keys = []
    for group in groups:
        for claim in group["claims"]:
            for cite in claim["citations"]:
                if claim_count.get(cite["key"], 0) > 1:
                    cite["shared"] = True
                    if cite["key"] not in shared_keys:
                        shared_keys.append(cite["key"])
    sources = []
    for group in groups:
        if group["source"] not in sources:
            sources.append(group["source"])
    return {
        "kind": "ask-claim-groups",
        "version": 1,
        "sources": sources,
        "groups": groups,
        "shared_keys": shared_keys,
    }


# ---------------------------------------------------------------------------
# Rendering (the staged proposal's grouped section)
# ---------------------------------------------------------------------------

def _citation_line(cite, verdict=None, coverage=None):
    bits = []
    if verdict is not None:
        bits.append(str(verdict))
    if coverage is not None:
        bits.append("coverage " + str(coverage))
    if cite.get("score") is not None:
        bits.append("relevance " + str(cite["score"]))
    if cite.get("shared"):
        bits.append("**shared**")
    line = "- [[" + str(cite["page"]) + "]]"
    if bits:
        line += " — " + "; ".join(bits)
    return line


def render_claim_groups(record) -> list | None:
    """The "## Claims and their evidence" section lines for
    the staged proposal, or None when the record carries no
    claim structure (the proposal then renders exactly as
    before this module existed)."""
    grouping = group_claims(record)
    if grouping is None:
        return None
    lines = []
    lines.append("## Claims and their evidence")
    lines.append("")
    lines.append(
        "Citations grouped by the claim they support, read "
        "from the answer's own recorded structure "
        "(tools/ask/claim_grouping.py) — never re-derived "
        "from the prose. A citation marked **shared** "
        "supports more than one claim. The flat list remains "
        "under Sources used."
    )
    lines.append("")
    for group in grouping["groups"]:
        if group["unit"] == "sub-answer":
            heading = "### Sub-answer"
            if group.get("question"):
                heading += " — " + str(group["question"])
            lines.append(heading)
        else:
            lines.append("### Answer")
        lines.append("")
        if group["source"] == "sub-answers":
            lines.append(
                "Grouped by sub-answer: sentence-level "
                "support was not recorded for this part, so "
                "its citations stand with the sub-answer as a "
                "whole."
            )
            lines.append("")
        if group["source"] == "record":
            lines.append(
                "Cited at answer level; no single claim in "
                "the recorded structure carries them."
            )
            lines.append("")
        for number, claim in enumerate(group["claims"], 1):
            lines.append(
                "%d. %s" % (number, claim["sentence"]))
            lines.append("")
            if claim["citations"]:
                for cite in claim["citations"]:
                    lines.append("   " + _citation_line(
                        cite, verdict=claim["verdict"],
                        coverage=claim["coverage"]))
                    if cite.get("passage"):
                        lines.append("")
                        lines.append(
                            "   > " + str(cite["passage"]))
                        lines.append("")
            elif claim["verdict"] is not None:
                lines.append(
                    "   - (no supporting citation — scored "
                    "unsupported at answer time)")
                lines.append("")
            else:
                lines.append(
                    "   - (no citations recorded for this "
                    "claim)")
                lines.append("")
        if group["unattached_citations"]:
            lines.append(
                "Cited for this part, supporting no single "
                "claim:")
            lines.append("")
            for cite in group["unattached_citations"]:
                lines.append(_citation_line(cite))
                if cite.get("passage"):
                    lines.append("")
                    lines.append("> " + str(cite["passage"]))
                    lines.append("")
    return lines
