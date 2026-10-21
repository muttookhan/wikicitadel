#!/usr/bin/env python3
"""Token-budget evidence packing for Lens Ask pickup (batch 2.1).

Before composing an answer, the pickup agent gathers candidate
passages (each with the page it came from and a relevance score).
This helper packs them into a stated token budget: passages are
taken in relevance order until the budget is full, and everything
that did not fit is reported as dropped — never silently discarded.

Token counting is an approximation, stated plainly: **one token is
taken to be four characters** (``CHARS_PER_TOKEN``), the standard
rough rule for English prose. The count is deterministic and
conservative enough for budgeting; it is not a tokenizer.

Packing is greedy with skip-and-continue: a passage that does not
fit is dropped, but a later, shorter passage may still fit in the
remaining budget. Ties in score keep the caller's original order
(the sort is stable), so the same input always packs identically.

Severance (consolidated-queue item 20, 2026-10-20): when a
severance list is supplied (``severance`` — the parsed
``evaluation/retrieval-severance.json``, loaded by
``tools/ask/severance.py``), candidate passages are checked
against it BEFORE packing: a passage carrying a severed claim,
or lifted from a severed page, never becomes answer evidence.
Severed passages are reported in the result's ``severed`` list
with the entry and register line that cut them — recorded, never
silent — and ``all_evidence_severed`` flags the case where
severance removed every candidate, whose honest outcome is the
abstention contract's abstention path.

Strongest source first (consolidated-queue item 33, 2026-10-20;
wave 8's knowledge-conflict find — evidence order is a real
variable, Xie et al.): when a standings map is supplied
(``standings`` — folded from the treatment and source-grades
registers by ``tools/ask/standing.py``), packing considers
passages in STANDING order before relevance: tier 0 (strongest
standing) first, then neutral, weakened, and negative last;
within a tier, relevance order and the stable tie rule apply
unchanged. Every packed and dropped entry then carries a
``standing`` record (tier, label, ``negative`` flag, signals) —
a negatively-treated passage may still pack when it IS the
evidence, but it is labelled, never silently presented as
ordinary support. Without ``standings``, packing is exactly the
pre-item-33 relevance order.

Patterns: Kotaemon's budgeted context assembly and mlx-memo's
fixed-window passage selection (survey, wave 1) — re-implemented.

Lost-in-the-Middle packing order (Marathon R2 lane B1): models
use evidence at the head and tail of a long context better than
evidence buried in the middle (Liu et al., "Lost in the Middle").
Once selection (which passages fit the budget) is settled in
consideration order, the PACKED list of a pack of four or more
is rearranged for composition: the strongest passages (by the
pack's existing consideration order — relevance score, or
standing tier then score when standings are supplied; ties in
that ranking were already broken by the caller's original order)
sit at the head and the tail, and the weakest sit in the middle.
Selection, the dropped list and every other field are untouched:
only the composition order of ``packed`` changes, and the result
then carries ``lost_in_middle_applied``: true. Packs of three or
fewer keep the consideration order exactly — every position in
such a pack is already edge-adjacent, and rearranging them would
only disturb the standing/tie order for no positional gain.

Prompt Capsules (same lane): a passage dict carrying
``"pinned": True`` (built by ``tools/ask/capsules.py`` from a
named capsule's pinned pages) is considered BEFORE every
unpinned passage, in its given (capsule) order, so a capsule's
pages are packed first under the budget. Severance still runs
before ordering, so a pinned passage from a severed page — or
carrying a severed claim — is cut exactly like any other.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

from pathlib import Path

CHARS_PER_TOKEN = 4

# The default evidence budget for one Ask answer, in approximate
# tokens. Configurable per call; the pickup procedure states the
# value it uses.
DEFAULT_TOKEN_BUDGET = 6000


def estimate_tokens(text) -> int:
    """Approximate token count of *text*: ceil(chars / 4); "" is 0."""
    if not text:
        return 0
    return -(-len(str(text)) // CHARS_PER_TOKEN)


# Packs at least this large get the Lost-in-the-Middle
# composition rearrangement (see the module docstring).
LOST_IN_MIDDLE_MIN_PACK = 4


def arrange_lost_in_middle(packed: list) -> list:
    """Rearrange *packed* (already in consideration order,
    strongest first) so the strongest passages sit at the head
    and the tail and the weakest in the middle.

    The arrangement is deterministic: take the even-ranked
    passages (ranks 0, 2, 4, …) in order, then the odd-ranked
    passages in REVERSE order (…, 5, 3, 1). Rank 0 heads the
    pack, rank 1 closes it, and the weakest passages meet in
    the centre. Packs smaller than LOST_IN_MIDDLE_MIN_PACK are
    returned unchanged (the same list object). The input list
    is never mutated.
    """
    if len(packed) < LOST_IN_MIDDLE_MIN_PACK:
        return packed
    return list(packed[::2]) + list(packed[1::2][::-1])


def _score(passage: dict) -> float:
    score = passage.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score)
    return 0.0


_SEVERANCE_MODULE = None
_STANDING_MODULE = None


def _fresh_key(page):
    """Normalise a passage's page to the freshness map's keys:
    the path under wiki/ without the .md suffix (mirrors
    tools/ask/standing.py page_key, so a page id and a repo
    path resolve to the same record)."""
    p = str(page or "").strip().replace("\\", "/")
    if p.endswith(".md"):
        p = p[:-3]
    if p.startswith("wiki/"):
        p = p[len("wiki/"):]
    return p




def _severance_module():
    """Load tools/ask/severance.py by path (the same lazy-load
    pattern answer_contract uses for the citation lockfile), so
    this module stays importable on its own."""
    global _SEVERANCE_MODULE
    if _SEVERANCE_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "severance.py"
        spec = importlib.util.spec_from_file_location(
            "ask_severance", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SEVERANCE_MODULE = module
    return _SEVERANCE_MODULE


def _standing_module():
    """Load tools/ask/standing.py by path (same lazy pattern)."""
    global _STANDING_MODULE
    if _STANDING_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "standing.py"
        spec = importlib.util.spec_from_file_location(
            "ask_standing", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _STANDING_MODULE = module
    return _STANDING_MODULE


def pack_evidence(passages, budget: int = DEFAULT_TOKEN_BUDGET,
                  severance=None, standings=None,
                  freshness=None) -> dict:
    """Pack *passages* into *budget* approximate tokens.

    Each passage is a dict with at least ``page`` and ``passage``
    keys and normally a ``score`` (missing/invalid scores count as
    0.0). Returns a dict:

    - ``budget``: the budget that was applied;
    - ``tokens_used``: approximate tokens of the packed passages;
    - ``packed``: the selected passages, each with its ``tokens``
      count added — in consideration (relevance) order for packs
      of three or fewer, and in Lost-in-the-Middle composition
      order (strongest at head and tail, weakest in the middle;
      ``lost_in_middle_applied`` set) for packs of four or more.
      Passages carrying ``"pinned": True`` (Prompt Capsules, see
      ``tools/ask/capsules.py``) are considered before all
      unpinned passages, in their given order;
    - ``dropped``: the passages that did not fit, in the order they
      were considered, each with ``tokens`` and
      ``reason: "over-budget"`` added.

Freshness at the moment of use (consolidated-queue item 46,
2026-10-20): when ``freshness`` is given — a mapping of page
to the freshness record computed by
``scripts/wiki_search.py`` (``freshness_record``), or a
callable taking a passage's page and returning such a
record — every packed and dropped entry whose page carries
a freshness signal gains a ``freshness`` key with that
record (its one-line rendering included). Signal-less pages
gain nothing: the pack stays quiet where the record is
quiet, and the result then carries ``freshness_applied``:
true.

    When *severance* is a parsed severance list (see
    ``tools/ask/severance.py``), passages are filtered against it
    first and the result additionally carries:

    - ``severed``: the passages the list cut, each with ``tokens``,
      ``reason: "severed"``, ``severed_by`` (the entry id) and
      ``source`` (the register + line the entry derives from);
    - ``all_evidence_severed``: true when candidates were offered
      and severance removed every one — the abstention signal.

    When *standings* is a standings map (see
    ``tools/ask/standing.py``), consideration order is standing
    tier first, then relevance (stable on ties), and every
    packed/dropped entry carries a ``standing`` record —
    ``{"tier", "label", "negative", "signals"}`` — naming the
    standing its page packs under. The result then also carries
    ``standing_applied``: true. Severed entries are cut before
    ordering and carry no standing record: they never pack.

    ``freshness`` is a ``{page: record}`` mapping or a
    ``page -> record | None`` callable (the records come from
    ``scripts/wiki_search.py``'s ``freshness_record``). An
    entry gains ``freshness`` only when its page's record
    carries a line — a signal-less page packs silently.
    """
    if budget < 0:
        raise ValueError("budget must be >= 0")
    severed = None
    if severance is not None:
        outcome = _severance_module().filter_passages(
            passages, severance
        )
        passages = outcome["kept"]
        severed = []
        for record in outcome["severed"]:
            entry = dict(record)
            entry["tokens"] = estimate_tokens(
                entry.get("passage", "")
            )
            entry["reason"] = "severed"
            severed.append(entry)
    standing_of = None
    if standings is not None:
        standing_mod = _standing_module()

        def standing_of(passage):
            return standing_mod.standing_for(
                standings, passage.get("page")
            )

    freshness_of = None
    if freshness is not None:
        if callable(freshness):
            def freshness_of(passage):
                return freshness(passage.get("page"))
        else:
            table = {_fresh_key(k): v for k, v in
                     freshness.items()}

            def freshness_of(passage):
                return table.get(_fresh_key(passage.get("page")))

    def _consideration_key(item):
        index, passage = item
        pinned = 0 if passage.get("pinned") else 1
        tier = standing_of(passage)["tier"] if standing_of else 0
        # Pinned (capsule) passages come first, in their given
        # order — the index decides among them, so their tier /
        # score never reorders a capsule. Unpinned passages keep
        # the pre-capsule order exactly: standing tier, then
        # relevance, stable on ties.
        return (
            pinned,
            index if pinned == 0 else 0,
            tier,
            -_score(passage),
            index,
        )

    ordered = sorted(enumerate(passages), key=_consideration_key)
    packed = []
    dropped = []
    used = 0
    for _index, passage in ordered:
        cost = estimate_tokens(passage.get("passage", ""))
        entry = dict(passage)
        entry["tokens"] = cost
        if standing_of is not None:
            entry["standing"] = standing_of(passage)
        if freshness_of is not None:
            record = freshness_of(passage)
            if record and record.get("line"):
                entry["freshness"] = record
        if used + cost <= budget:
            packed.append(entry)
            used += cost
        else:
            entry["reason"] = "over-budget"
            dropped.append(entry)
    # Lost-in-the-Middle: selection above is final; only the
    # composition order of the packed list changes (module
    # docstring). Dropped passages keep consideration order.
    rearranged = arrange_lost_in_middle(packed)
    result = {
        "budget": budget,
        "tokens_used": used,
        "packed": rearranged,
        "dropped": dropped,
    }
    if rearranged is not packed:
        result["lost_in_middle_applied"] = True
    if standing_of is not None:
        result["standing_applied"] = True
    if freshness_of is not None:
        result["freshness_applied"] = True
    if severed is not None:
        result["severed"] = severed
        result["all_evidence_severed"] = bool(severed) and not passages
    return result
