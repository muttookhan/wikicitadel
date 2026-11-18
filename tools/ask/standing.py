#!/usr/bin/env python3
"""Source standing for Ask evidence packing (consolidated-queue
item 33, 2026-10-20).

Wave 8's knowledge-conflict find (Xie et al., ICLR 2024) names
evidence ORDER as a real variable: when supportive and
contradictory evidence are both present, models show confirmation
bias toward their prior, and are measurably sensitive to the
order evidence is presented in. The buildable practice: **the
strongest source goes first in the pack**. This module computes,
for every wiki page, a deterministic standing from the two
registers that already grade the corpus —

- the treatment register (``evaluation/treatment-register.jsonl``,
  item 10): how later records treated a page's claims. Its own
  fold governs here too: a page's standing grade is the strongest
  signal across its subjects (``scripts/wiki_treatment.py``:
  GRADES weakest→strongest ``followed, questioned, caution,
  negative``);
- the source-grades register
  (``evaluation/source-grades.jsonl``, items 11–12): two-axis
  grades (integrity / precision), folded latest-per-axis, the
  register's own rule. The axes are never merged into a score
  there; for ORDERING only, this module takes the weaker axis's
  severity as the page's — the conservative direction, and the
  label always names the axis that governed.

Severity scale (shared, documented here so the packing order is
auditable): a page's severity is the maximum over its signals —

- treatment: followed −1 · questioned 1 · caution 2 · negative 3
- integrity: established −1 · unremarkable 0 · questioned 2 ·
  compromised 3
- precision: exact −1 · careful 0 · loose 2 · error-prone 3

Tiers (lower packs earlier):

- tier 0 — strongest: severity < 0 (positively graded, nothing
  weaker on record);
- tier 1 — neutral: severity 0 (ungraded, or middling grades
  only) — the default state of the corpus;
- tier 2 — weakened: severity 1–2 (questioned / caution / loose);
- tier 3 — negative: severity 3 (negative treatment, compromised
  integrity, or error-prone precision). Passages at tier 3 are
  labelled ``negative`` in the pack — they may still pack when
  they ARE the evidence; they are labelled, never hidden.

An absent register changes nothing: pages simply have no signals
and stand neutral, exactly as before this module existed.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import json
from pathlib import Path

TREATMENT_RELATIVE_PATH = "evaluation/treatment-register.jsonl"
GRADES_RELATIVE_PATH = "evaluation/source-grades.jsonl"

# Severity per grade, per signal family (see module docstring).
TREATMENT_SEVERITY = {
    "followed": -1,
    "questioned": 1,
    "caution": 2,
    "negative": 3,
}
INTEGRITY_SEVERITY = {
    "established": -1,
    "unremarkable": 0,
    "questioned": 2,
    "compromised": 3,
}
PRECISION_SEVERITY = {
    "exact": -1,
    "careful": 0,
    "loose": 2,
    "error-prone": 3,
}

TIER_NAMES = {
    0: "strongest",
    1: "neutral",
    2: "weakened",
    3: "negative",
}


def repo_root() -> Path:
    """Repository root, derived from this file's location
    (tools/ask/standing.py -> parents[2])."""
    return Path(__file__).resolve().parents[2]


def page_key(page) -> str:
    """Normalise a page reference to the key standings are stored
    under: the path under ``wiki/`` without the ``.md`` suffix.
    Accepts repo paths (``wiki/sources/hindsight.md``), page ids
    (``sources/hindsight``) and bare stems (``hindsight`` -> kept
    as-is; a bare stem only matches a page registered under that
    exact stem, which register subjects never are — register
    subjects are full paths, so bare stems stand neutral)."""
    p = str(page or "").strip().replace("\\", "/")
    if p.endswith(".md"):
        p = p[:-3]
    if p.startswith("wiki/"):
        p = p[len("wiki/"):]
    return p


def _read_jsonl(path):
    """Parse a JSONL register file; [] when absent/unreadable."""
    p = Path(path)
    if not p.is_file():
        return []
    rows = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _tier_for(severity: int) -> int:
    if severity < 0:
        return 0
    if severity == 0:
        return 1
    if severity <= 2:
        return 2
    return 3


def fold_standings(treatment_rows, grade_rows) -> dict:
    """Fold register rows into per-page standings.

    *treatment_rows* / *grade_rows* are parsed JSONL dicts (header
    lines are skipped). Returns ``{page_key: standing}`` where a
    standing is::

        {"tier": int, "severity": int, "negative": bool,
         "label": str, "signals": [str, ...]}

    ``label`` names the governing (highest-severity, ties broken
    by signal order: treatment, integrity, precision) signal, so
    a reader can see WHY a page packs where it does. Pages with
    no signals are absent from the dict — absence IS neutral.
    """
    signals = {}  # page_key -> [(severity, order, text)]

    def add(key, severity, order, text):
        if key:
            signals.setdefault(key, []).append((severity, order, text))

    for row in treatment_rows or []:
        if row.get("kind") != "treatment":
            continue
        subject = row.get("subject") or {}
        grade = row.get("grade")
        if grade not in TREATMENT_SEVERITY:
            continue
        scope = "claim-scoped" if subject.get("claim") else "page"
        add(
            page_key(subject.get("page")),
            TREATMENT_SEVERITY[grade],
            0,
            "treatment %s (%s, %s)" % (grade, row.get("id"), scope),
        )
    # Source grades fold latest-per-axis (the register's own
    # rule): an older grade on the same axis is replaced, never
    # averaged in.
    latest_grades = {}
    for row in grade_rows or []:
        if row.get("kind") != "grade":
            continue
        latest_grades[(row.get("source"), row.get("axis"))] = row
    for row in latest_grades.values():
        axis = row.get("axis")
        grade = row.get("grade")
        table = (
            INTEGRITY_SEVERITY if axis == "integrity"
            else PRECISION_SEVERITY if axis == "precision"
            else None
        )
        if table is None or grade not in table:
            continue
        add(
            page_key(row.get("source")),
            table[grade],
            1 if axis == "integrity" else 2,
            "%s %s" % (axis, grade),
        )

    standings = {}
    for key, entries in signals.items():
        severity = max(e[0] for e in entries)
        governing = min(
            (e for e in entries if e[0] == severity),
            key=lambda e: e[1],
        )
        tier = _tier_for(severity)
        standings[key] = {
            "tier": tier,
            "severity": severity,
            "negative": tier == 3,
            "label": "%s — %s" % (TIER_NAMES[tier], governing[2]),
            "signals": [e[2] for e in sorted(entries,
                                             key=lambda e: (-e[0], e[1]))],
        }
    return standings


def load_standings(root=None) -> dict:
    """Standings folded from the repo's two registers.

    Missing/unreadable registers contribute no signals (standing
    is off for their pages), mirroring severance's absent-list
    behaviour."""
    base = Path(root) if root is not None else repo_root()
    return fold_standings(
        _read_jsonl(base / TREATMENT_RELATIVE_PATH),
        _read_jsonl(base / GRADES_RELATIVE_PATH),
    )


def standing_for(standings, page) -> dict:
    """The standing of one page: its folded standing, or the
    neutral standing when the page has no signals on record."""
    if standings:
        found = standings.get(page_key(page))
        if found is not None:
            return found
    return {
        "tier": 1,
        "severity": 0,
        "negative": False,
        "label": "neutral — no standing on record",
        "signals": [],
    }
