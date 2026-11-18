#!/usr/bin/env python3
"""The query depth ladder for the Ask door (W6, 2026-10-22).

A question put to this wiki can be answered at more than one
depth, and until now the depth was invisible: the pickup
procedure ran one fixed configuration (the battery's
candidate pool, the packing default budget, sentence scoring
on, the full provenance envelope) whatever the question
needed. This module NAMES the ladder — three declared
levels, **quick / standard / deep** — as one explicit bundle
of settings per level, so a caller chooses depth
deliberately, the choice is recorded on the answer record
and named in the provenance envelope, and a deep run is
visibly costed as what it is: more of the corpus read, more
evidence packed, the same bar for believing any of it.

THE LEVELS (the settings are the whole definition — a level
is nothing but its bundle):

  quick     candidate pool 5, evidence budget 2,000 tokens,
            sentence scoring NOT run, provenance
            citations-and-snapshot. For a lookup whose answer
            is one passage on one page.
  standard  candidate pool 10, evidence budget 6,000
            tokens, sentence scoring run, provenance full.
            THE DEFAULT, and tonight's standing production
            configuration exactly: pool = the abstention
            battery's TOP_K, budget =
            evidence_packing.DEFAULT_TOKEN_BUDGET. A record
            with no depth declaration is a standard record
            and is byte-identical to a pre-ladder record.
  deep      candidate pool 25, evidence budget 12,000
            tokens, sentence scoring run, provenance full.
            For multi-source research questions. The opt-in
            search stages a deep run would want (one-hop
            vote, HyDE expansion, iterative passes, listwise)
            are DECLARED at this level but NOT WIRED into
            the Ask door — see stage postures below.

THE ABSTENTION INVARIANT (the ladder's founding rule):
**depth changes breadth, never the bar.** The abstention
threshold is the frozen tau of
``evaluation/extended-baseline.json`` at EVERY level, and
the governance composition (severance, then governance —
stages 5 and 6 of ``scripts/wiki_search.py``) runs
identically at every level: neither is a level setting, and
no level's bundle may carry one. A deep answer reads more
passages than a quick one; it abstains on exactly the same
evidence standard. ``scripts/wiki_depth_measure.py``
executes the abstention battery's search cases at all three
levels and reports the verdicts level by level — the proof
is an artefact (``evaluation/depth-ladder-report.json``),
not an assertion in this docstring.

STAGE POSTURES: each level states, per opt-in stage,
whether the stage runs. The standing pipeline stages
(coverage rerank inside hybrid_rank, severance, governance)
run at every level — they ARE the pipeline, and the
invariant above pins two of them. The opt-in stages
(one-hop vote, HyDE expansion, iterative passes, listwise)
exist in ``scripts/wiki_search.py`` behind explicit
arguments and are NOT part of the Ask door's standing
procedure (``tools/ask/pickup.md``): wiring one into the
door is an owner-visible act (the HyDE precedent,
2026-10-22: a measured stage ships opt-in at the search
CLI, and the Ask path adopts it, if ever, by a separate
calibrated act). So even at deep their posture is
``declared-not-wired`` — the level names them, the record
of a deep answer names them as not run, and nothing is
silently switched on. At quick and standard their posture
is ``off``.

PLACEMENT (the recorded seam decision, mirroring
coverage.py, lessons.py, provenance.py): the ladder is
DECLARED state, known before the answer is composed, so
unlike lessons/provenance it is stamped by
``build_qa_record`` itself — from the explicit argument or
the question entry's own ``depth`` field — as a ``depth``
block, and ``pickup.py`` refuses a record-answer payload
whose declared depth is not a level (a named refusal,
never a silent default). The block carries the level's
full bundle so a reader of the record need not open this
module to know what the answer cost. The staged proposal
renders the depth line; the provenance envelope names the
record's block. Records with no declaration carry no
``depth`` field at all — absence means standard, and the
pre-ladder record shape is unchanged byte for byte.

THE TRAVERSE DOOR: the build-list item names this ladder
as the traverse door's declared ladder, and the same
bundles bind there — ``scripts/wiki_traverse.py`` loads
this module by path and its ``search`` command takes
``--depth`` (the level's traverse bundle sets the result
count when the caller does not pass ``--top``; the output
is stamped with the depth and its cost). One ladder, two
doors, no second definition.

Licence posture: adapt-with-credit — the named
three-level depth ladder (Quick / Standard / Deep
multi-agent research) is the ``llm-knowledge-bases``
project's pattern (build list, wave 6; per the build
list's licence route, MIT/Apache source); the bundles,
the abstention invariant and all code here are this tree's
own, written against this pipeline's own constants — no
code or text from that project is held here.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_packing  # noqa: E402  (same directory)

# The battery's candidate pool at the standing configuration
# (scripts/wiki_abstention_check.py's TOP_K). Standard IS
# that configuration; the constant is restated here, not
# imported, because the battery runner is a script, not a
# library — the ladder's tests pin the two equal.
STANDARD_CANDIDATE_POOL = 10

TAU_SOURCE = ("evaluation/extended-baseline.json, "
              "abstain_threshold")

ABSTENTION_INVARIANT = (
    "Depth changes breadth, never the bar: the frozen "
    "abstention threshold (" + TAU_SOURCE + ") and the "
    "governance composition (severance, then governance) "
    "apply identically at every depth."
)

# The opt-in stages of scripts/wiki_search.py's hybrid_rank
# that no Ask level switches on (module docstring). Their
# posture is a level fact, recorded on every depth block.
_OPT_IN_STAGES = ("onehop-vote", "hyde-expansion",
                  "iterative-passes", "listwise")

_STANDING_STAGES = (
    {"stage": "coverage-rerank", "posture": "standing",
     "note": "hybrid_rank stage 4, part of the pipeline at "
             "every depth"},
    {"stage": "severance", "posture": "standing",
     "note": "hybrid_rank stage 5; pinned by the abstention "
             "invariant"},
    {"stage": "governance", "posture": "standing",
     "note": "hybrid_rank stage 6; pinned by the abstention "
             "invariant"},
)


def _stages(opt_in_posture, opt_in_note):
    return [dict(s) for s in _STANDING_STAGES] + [
        {"stage": name, "posture": opt_in_posture,
         "note": opt_in_note}
        for name in _OPT_IN_STAGES
    ]


LEVELS = {
    "quick": {
        "level": "quick",
        "label": "Quick",
        "summary": "a lookup: the answer is one passage on "
                   "one page",
        "candidate_pool": 5,
        "pack_budget_tokens": 2000,
        "sentence_scoring": "not-run",
        "provenance": "citations-and-snapshot",
        "stages": _stages(
            "off",
            "opt-in stage; off at this depth"),
        "traverse": {"search_top": 5, "neighbour_hops": 1,
                     "path_max_depth": 3},
        "cost": "reads at most 5 candidate passages and "
                "packs at most 2,000 tokens of evidence; "
                "sentence scoring is not run",
    },
    "standard": {
        "level": "standard",
        "label": "Standard",
        "summary": "the standing configuration: one "
                   "question, the corpus's ordinary evidence",
        "candidate_pool": STANDARD_CANDIDATE_POOL,
        "pack_budget_tokens":
            evidence_packing.DEFAULT_TOKEN_BUDGET,
        "sentence_scoring": "run",
        "provenance": "full",
        "stages": _stages(
            "off",
            "opt-in stage; not part of the Ask door's "
            "standing procedure"),
        "traverse": {"search_top": 10, "neighbour_hops": 1,
                     "path_max_depth": 6},
        "cost": "the standing configuration — at most 10 "
                "candidate passages, 6,000 tokens of "
                "evidence packed",
    },
    "deep": {
        "level": "deep",
        "label": "Deep",
        "summary": "multi-source research: the widest "
                   "breadth the door offers",
        "candidate_pool": 25,
        "pack_budget_tokens": 12000,
        "sentence_scoring": "run",
        "provenance": "full",
        "stages": _stages(
            "declared-not-wired",
            "implemented as an opt-in stage of "
            "scripts/wiki_search.py but NOT wired into the "
            "Ask door; wiring is an owner-visible act, so "
            "a deep answer records the stage as not run"),
        "traverse": {"search_top": 25, "neighbour_hops": 2,
                     "path_max_depth": 6},
        "cost": "the widest breadth: at most 25 candidate "
                "passages (2.5x standard) and 12,000 tokens "
                "of evidence packed (2x standard) — costed "
                "as such wherever it is declared",
    },
}

DEFAULT_DEPTH = "standard"

# The level order, shallow to deep (the ladder).
LEVEL_ORDER = ("quick", "standard", "deep")


def level_names() -> tuple:
    return LEVEL_ORDER


def is_valid_level(value) -> bool:
    return isinstance(value, str) and value in LEVELS


def get_level(name: str) -> dict:
    """The level's bundle (a fresh copy). Raises KeyError
    for an unknown level — callers validate first."""
    spec = LEVELS[name]
    out = dict(spec)
    out["stages"] = [dict(s) for s in spec["stages"]]
    out["traverse"] = dict(spec["traverse"])
    return out


def resolve_depth(explicit=None, entry_value=None):
    """Resolve a depth declaration to (level, basis).

    The explicit argument wins over the question entry's own
    ``depth`` field; either makes the basis ``declared``.
    Neither present gives the default level with basis
    ``default (undeclared)``. An invalid value resolves to
    (None, basis) so the caller can refuse it by name —
    resolution never silently substitutes another level.
    """
    if explicit is not None:
        value, basis = explicit, "declared"
    elif entry_value is not None:
        value, basis = entry_value, "declared"
    else:
        return DEFAULT_DEPTH, "default (undeclared)"
    if is_valid_level(value):
        return value, basis
    return None, basis


def declaration_error(value, where: str = "depth"):
    """None when *value* is a usable declaration (a level
    name, a full block dict, or None); otherwise the named
    error a door refuses with."""
    if value is None or isinstance(value, dict):
        return None
    if is_valid_level(value):
        return None
    return ("%s %r is not a depth level; the ladder is: %s"
            % (where, value, ", ".join(LEVEL_ORDER)))


def depth_block(level: str, basis: str) -> dict:
    """The record's ``depth`` block for a declared level:
    the full bundle, stamped on the answer record so the
    depth the answer was composed at — and what it cost —
    is readable from the record alone. Deterministic: the
    same level and basis always build the same block."""
    spec = get_level(level)
    return {
        "kind": "ask-depth",
        "level": spec["level"],
        "label": spec["label"],
        "basis": basis,
        "summary": spec["summary"],
        "candidate_pool": spec["candidate_pool"],
        "pack_budget_tokens": spec["pack_budget_tokens"],
        "sentence_scoring": spec["sentence_scoring"],
        "provenance": spec["provenance"],
        "stages": spec["stages"],
        "cost": spec["cost"],
        "abstention_invariant": ABSTENTION_INVARIANT,
    }


def envelope_summary(block: dict) -> dict:
    """The provenance envelope's naming of a record's depth
    block (mirrors the lessons summary): the envelope names
    the depth; the block itself, with the full bundle,
    rides the record."""
    return {
        "level": block.get("level"),
        "label": block.get("label"),
        "basis": block.get("basis"),
        "candidate_pool": block.get("candidate_pool"),
        "pack_budget_tokens": block.get("pack_budget_tokens"),
        "sentence_scoring": block.get("sentence_scoring"),
        "provenance": block.get("provenance"),
        "source": "the record's own depth block "
                  "(tools/ask/depth_ladder.py) — the "
                  "envelope names the depth the answer was "
                  "composed at; it does not re-derive it",
    }


def ladder_table() -> list:
    """The ladder as rows (level bundles in ladder order) —
    the traverse door's ``depth`` verb renders this."""
    return [get_level(name) for name in LEVEL_ORDER]
