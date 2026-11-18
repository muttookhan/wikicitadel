#!/usr/bin/env python3
"""Coverage-gap line for Lens Ask answers (Marathon R2 lane B1;
gbrain pattern).

An answer that only says what the wiki holds hides what it does
NOT hold. This module computes, deterministically from the
search result set, a one-line coverage statement:

- **gaps**: the communities / facets that were searched for
  this topic and returned ZERO hits — the parts of the corpus
  that hold nothing on it; and
- **newest evidence date**: the newest evidence date among the
  packed passages, so the reader can see how fresh the best
  evidence is.

Placement (the lane's recorded decision): the line is NOT
appended to the user-facing answer text — the answer text is
the answering agent's own cited statement, and a machine line
bolted onto it would blur that. Instead the computed coverage
rides the answer RECORD as a structured ``coverage`` field
(``pickup.build_qa_record(..., coverage=...)``, stamped only
when supplied, like ``clarification`` before it) and is
rendered in the pickup report — the staged proposal markdown
(``pickup.stage_proposal_markdown``) gains a ``## Coverage``
section when the record carries the field. Validation in
``answer_contract.py`` is untouched: ``coverage`` is an extra
record field, exactly like ``clarification``, and changes no
abstention, trust-verdict or clarification-gate semantics.

Inputs
------
``packed`` is the packed evidence: dicts in the
``evidence_packing.pack_evidence`` ``packed`` shape (``page``,
``passage``, ``score`` …), or an answer record's
``citation_details`` entries. The newest evidence date is read
from the first present of the date fields ``date``,
``evidence_date``, ``updated``, ``created``, ``as_of``,
``page_date`` (an ISO ``YYYY-MM-DD`` prefix; datetimes are
truncated to their date).

``searched`` describes what was searched, in any of these
shapes:

- a mapping of facet/community name -> hit count (int) or
  list of results;
- an iterable of dicts, each with a name under ``name`` /
  ``facet`` / ``community`` / ``label`` and hits under
  ``hits`` / ``count`` / ``results``;
- an iterable of plain names: a name's hits are then derived
  from the packed passages — the number of packed passages
  whose ``facet`` / ``community`` / ``community_label`` equals
  the name (zero when none do: a searched facet that packed
  nothing is a gap).

With no ``searched`` information, no gaps can be named and the
line says so, rather than claiming full coverage.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import re

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_DATE_FIELDS = (
    "date", "evidence_date", "updated", "created", "as_of",
    "page_date",
)
_NAME_FIELDS = ("name", "facet", "community", "label")
_HIT_FIELDS = ("hits", "count")


def _passage_date(passage: dict):
    """The ISO date string a packed passage carries, or None."""
    if not isinstance(passage, dict):
        return None
    for field in _DATE_FIELDS:
        value = passage.get(field)
        if isinstance(value, str):
            match = _DATE_RE.match(value.strip())
            if match:
                return match.group(1)
    return None


def newest_evidence_date(packed) -> str | None:
    """The newest evidence date among *packed*, or None.

    ISO dates sort lexicographically, so the max is the newest.
    Passages carrying no date field are ignored; when none do,
    the result is None and the coverage line says no dated
    evidence was packed (it never invents a date).
    """
    dates = [
        d for d in (_passage_date(p) for p in packed or [])
        if d is not None
    ]
    return max(dates) if dates else None


def _searched_facets(searched, packed) -> list:
    """Normalise *searched* to ``[(name, hits), ...]``,
    preserving the caller's order."""
    if searched is None:
        return []
    if isinstance(searched, dict):
        items = list(searched.items())
        return [
            (str(name), _hit_count(value, name, packed))
            for name, value in items
        ]
    facets = []
    for entry in searched:
        if isinstance(entry, str):
            facets.append(
                (entry, _hit_count(None, entry, packed))
            )
        elif isinstance(entry, dict):
            name = None
            for field in _NAME_FIELDS:
                if entry.get(field):
                    name = str(entry[field])
                    break
            if name is None:
                continue
            value = None
            for field in _HIT_FIELDS:
                if field in entry:
                    value = entry[field]
                    break
            if value is None and "results" in entry:
                value = entry["results"]
            facets.append((name, _hit_count(value, name, packed)))
    return facets


def _hit_count(value, name, packed) -> int:
    """Hit count for one searched facet: an explicit count when
    given, else derived from the packed passages' facet /
    community fields."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (list, tuple)):
        return len(value)
    return sum(
        1
        for p in packed or []
        if isinstance(p, dict)
        and name in (
            p.get("facet"), p.get("community"),
            p.get("community_label"),
        )
    )


def compute_coverage(packed, searched=None) -> dict:
    """Compute the coverage record for one answer.

    Returns a dict:

    - ``gaps``: the searched facet/community names with zero
      hits, in searched order;
    - ``searched``: every searched name, in searched order;
    - ``newest_evidence_date``: the newest date among the
      packed passages, or None;
    - ``line``: the one-line coverage statement, e.g.
      ``Coverage: no hits in sources/leases — the searched
      corpus holds nothing on that facet for this topic;
      newest evidence 2026-10-20.`` or, with no gaps,
      ``Coverage: no gaps — every searched facet returned
      hits; newest evidence 2026-10-20.``
    """
    packed = list(packed or [])
    facets = _searched_facets(searched, packed)
    gaps = [name for name, hits in facets if hits == 0]
    newest = newest_evidence_date(packed)
    if newest is not None:
        freshness = "newest evidence %s" % newest
    elif packed:
        freshness = "no dated evidence among the packed passages"
    else:
        freshness = "no evidence was packed"
    if gaps:
        line = (
            "Coverage: no hits in %s — the searched corpus "
            "holds nothing on %s for this topic; %s."
            % (
                ", ".join(gaps),
                "that facet" if len(gaps) == 1 else "those facets",
                freshness,
            )
        )
    elif facets:
        line = (
            "Coverage: no gaps — every searched facet returned "
            "hits; %s." % freshness
        )
    else:
        line = (
            "Coverage: no searched-facet information was "
            "recorded, so no coverage gaps can be named; %s."
            % freshness
        )
    return {
        "gaps": gaps,
        "searched": [name for name, _hits in facets],
        "newest_evidence_date": newest,
        "line": line,
    }


def coverage_line(packed, searched=None) -> str:
    """Just the one-line coverage statement (see
    :func:`compute_coverage`)."""
    return compute_coverage(packed, searched)["line"]


def packed_from_record(record: dict) -> list:
    """The packed evidence an answer record carries.

    A record that embeds a pack result (``packed`` / ``evidence``
    / ``chunks``) yields that list; otherwise its
    ``citation_details`` — top-level first, then each
    sub-answer's, in record order — are the packed passages.
    """
    if not isinstance(record, dict):
        return []
    for key in ("packed", "evidence", "chunks"):
        value = record.get(key)
        if isinstance(value, list) and value:
            return [p for p in value if isinstance(p, dict)]
    packed = []
    details = record.get("citation_details") or []
    packed.extend(d for d in details if isinstance(d, dict))
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            details = sub.get("citation_details") or []
            packed.extend(
                d for d in details if isinstance(d, dict)
            )
    return packed


def coverage_for_record(record: dict, searched=None) -> dict:
    """The coverage record for a stored answer record: its
    packed evidence is read from the record itself (see
    :func:`packed_from_record`); *searched* is as in
    :func:`compute_coverage`."""
    return compute_coverage(packed_from_record(record), searched)
