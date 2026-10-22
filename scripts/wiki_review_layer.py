#!/usr/bin/env python3
"""wiki_review_layer.py — the periodic review layer (Wave 5).

Build-list item "Periodic review layer" (2026-10-22), clean
re-implementation. Idea sources (ideas only, no code taken):
the Plus/Minus/Next weekly review format (Anne-Laure Le
Cunff), Stephen Wolfram's periodic patterns review over a
personal log, gentlekk/personal-memory-archivist and
goodmonk06/personal-life-log-orchestrator (review rhythms
over an existing record). The Monday Morning Test already
stands as a sweep check (Phase 5); this layer adds the
review formats and the queue around it.

WHAT IT BUILDS — two generated artefacts, nothing else:

  queue   evaluation/review-queue.json + review-queue.md
          Every page due for periodic review, with WHY:
          each entry carries its reasons, and each reason
          carries the dates that prove it.
  report  evaluation/review-cadence-report.md
          The cadence report: what the record shows was
          reviewed, what is overdue and by how much, a
          daily review for --today, a Plus/Minus/Next
          weekly review derived from the log, and a
          bounded patterns review over wiki/log.md ONLY
          (no new data is collected — the auto-discovery
          rejection is the boundary).

The layer PROPOSES reviews. It never edits a page it
queues, never marks anything reviewed, and writes only
its own artefacts (under --out-dir, default evaluation/).

REVIEW vs EDIT — the evidence rule. This corpus's record
distinguishes the two, and the layer honours the
distinction:
  - a REVIEW event is: an owner attestation
    (`verified_until` / `verified_by: owner` — the
    horizon is the review's validity), or a verification
    event in evaluation/reverify-history.jsonl (the FSRS
    register; a claim re-checked against its sources).
  - an EDIT (created / updated / tended) is NOT a review.
    A page with no review event is queued by its last
    substantive change — tended, else updated, else
    created — and the queue says so on its face:
    "no review event on record".

CADENCE. AGENTS.md defines no per-type review interval:
the adopted clocks are per-page (evidence TTL), per-claim
(FSRS re-verification) and per-attestation (the owner's
horizon), and those always take precedence here. The
per-type intervals below are therefore PROPOSALS, printed
as proposals in both artefacts — not schema, and never
written into AGENTS.md by this tool. Override them per
run with --interval TYPE=DAYS.

  synthesis 30d · entity 90d · source 180d · concept 180d
  query 365d · anything else 90d

QUEUE REASONS (a page appears once, with all its reasons):
  attestation-expired   verified_until < today (dated)
  attestation-invalid   verified_until present, unparseable
  reverify-overdue      claim schedule overdue (dated)
  reverify-due          claim schedule due today
  evidence-due          evidence TTL reached (dated)
  evidence-invalid      TTL fields half-stated (wiki_evidence_ttl)
  source-changed        a cited raw source's last git change
                        is after the page's `updated` (dated:
                        days since the source moved)
  cadence-stale         never reviewed, and the last
                        substantive change is older than the
                        (proposed) interval for its type
  no-date               no created/updated/tended date —
                        cadence cannot be judged
  no-frontmatter        no frontmatter — nothing can be judged
  pending-review-open   open entries in a ## Pending Review
                        section (wiki_pending_review's grammar)
  orphaned-from-index   the page is not catalogued in
                        wiki/index.md

Scan set: wiki/**/*.md minus wiki/index.md, wiki/log.md,
wiki/access/, wiki/filings/, wiki/talk/ (the exclusions
the house scanners use). Retired pages (status:
tombstoned / superseded / deprecated / archived) are out
of the review population and counted, not queued.

REUSE, not reinvention: frontmatter parsing and dates
from scripts/wiki_validate.py; the claim schedule from
scripts/wiki_reverify.py (its pure fold — the FSRS math
is not re-derived here); evidence-TTL state from
scripts/wiki_evidence_ttl.py; Pending Review sections
from scripts/wiki_pending_review.py; the source-changed
rule mirrors scripts/wiki_stale.py (slug token-set
resolution over raw/sources + git last-change date),
re-implemented only because that tool binds the repo
root at module level and this one takes --root.

DETERMINISM: same corpus + same --today + same intervals
-> identical artefact bytes. No wall clock is read except
as the default for --today; all orderings are total
(queue: most-overdue first, ties by page path; undated-
only entries last, by path).

Usage:
  python3 scripts/wiki_review_layer.py [all|queue|report]
      [--root DIR] [--today YYYY-MM-DD]
      [--interval TYPE=DAYS ...] [--out-dir DIR]
      [--json] [--stdout]

Exit codes: 0 done · 2 usage error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}
EXCLUDED_DIRS = ("wiki/access/", "wiki/filings/", "wiki/talk/")
RETIRED_STATUSES = {"tombstoned", "superseded", "deprecated", "archived"}

# PROPOSED per-type review intervals in days — see the
# docstring. Not schema; printed as proposals everywhere.
PROPOSED_CADENCE = {
    "synthesis": 30,
    "entity": 90,
    "source": 180,
    "concept": 180,
    "query": 365,
}
DEFAULT_INTERVAL = 90

LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\]\s+([^|]+?)\s*\|\s*(.*?)\s*$", re.M)
LEDGER_ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s+—\s+(.*?)\s*$", re.M)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Log kinds counted as forward motion for the weekly Plus
# column, and as friction for Minus. Every other kind is
# counted in the patterns section but lands in neither
# column — the derivation rule is stated on the report.
PLUS_KINDS = {"ingest", "query", "setup", "build", "feature",
              "source", "decision", "ruling", "direction"}
MINUS_KINDS = {"lint", "correction", "fix"}
WEEKLY_BULLET_CAP = 15


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wv = _load("wiki_validate")
_reverify = _load("wiki_reverify")
_ttl = _load("wiki_evidence_ttl")
_pending = _load("wiki_pending_review")
parse_frontmatter = _wv.parse_frontmatter
parse_date = _wv.parse_date
as_list = _wv.as_list


# -- corpus scan -----------------------------------------------------------

def page_paths(root: Path):
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    out = []
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in EXCLUDED_FILES or rel.startswith(EXCLUDED_DIRS):
            continue
        out.append(p)
    return out


def index_targets(root: Path):
    """(stems, paths) catalogued by wiki/index.md: every
    [[target]] reduced to its stem, plus the target as
    written (path form) without the .md suffix."""
    index = root / "wiki" / "index.md"
    stems, paths = set(), set()
    if not index.is_file():
        return stems, paths
    text = index.read_text(encoding="utf-8", errors="ignore")
    for raw in WIKILINK_RE.findall(text):
        target = raw.split("|")[0].strip()
        if not target:
            continue
        paths.add(target[:-3] if target.endswith(".md") else target)
        stem = target.rsplit("/", 1)[-1]
        stems.add(stem[:-3] if stem.endswith(".md") else stem)
    return stems, paths


def slug_tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class SourceResolver:
    """Mirror of wiki_stale.py's resolution rule: entries
    containing '/' are repo-relative paths; bare slugs
    resolve against raw/sources/ by exact token-set match
    on the file stem (first in sorted order wins)."""

    def __init__(self, root: Path):
        self.root = root
        self.by_tokens = {}
        raw_sources = root / "raw" / "sources"
        if raw_sources.is_dir():
            for p in sorted(raw_sources.rglob("*")):
                if p.is_file():
                    key = frozenset(slug_tokens(p.stem))
                    self.by_tokens.setdefault(
                        key, p.relative_to(root).as_posix())
        self._git_cache = {}

    def resolve(self, entry: str):
        if "/" in entry:
            return entry
        return self.by_tokens.get(frozenset(slug_tokens(entry)))

    def git_last_change(self, rel: str):
        """Date of the last commit touching rel, or None."""
        if rel in self._git_cache:
            return self._git_cache[rel]
        out = None
        try:
            r = subprocess.run(
                ["git", "-C", str(self.root), "log", "-1",
                 "--format=%cI", "--", rel],
                capture_output=True, text=True, timeout=30)
            txt = r.stdout.strip()
            if txt:
                out = date.fromisoformat(txt[:10])
        except Exception:
            out = None
        self._git_cache[rel] = out
        return out


def attestation_state(fields, today):
    """Mirror of the lint lanes' rule: (state, until) where
    state is current / expired / invalid / None."""
    if not fields:
        return None, None
    raw = fields.get("verified_until")
    if raw is None or str(raw).strip() == "":
        return None, None
    until = parse_date(str(raw))
    if until is None:
        return "invalid", None
    return ("expired" if until < today else "current"), until


def last_change(fields):
    """(date, field) of the last substantive change:
    tended, else updated, else created. An edit, not a
    review — callers label it as such."""
    if not fields:
        return None, None
    for key in ("tended", "updated", "created"):
        value = fields.get(key)
        if value:
            when = parse_date(str(value))
            if when is not None:
                return when, key
    return None, None


def load_reverify_history(root: Path):
    path = root / "evaluation" / "reverify-history.jsonl"
    events = []
    if path.is_file():
        for line in path.read_text(
                encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    by_claim = {}
    for ev in events:
        by_claim.setdefault(ev.get("claim"), []).append(ev)
    return events, by_claim


# -- per-page analysis -------------------------------------------------------

def _reason(reason, detail, due=None, days_overdue=None):
    return {"reason": reason, "detail": detail,
            "due": due.isoformat() if isinstance(due, date) else due,
            "days_overdue": days_overdue}


def analyse_page(root, path, today, intervals, resolver,
                 index_stems, index_paths, history_by_claim):
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="ignore")
    fields, _body = parse_frontmatter(text)
    record = {"page": rel, "fields": fields, "text": text}

    if not fields:
        record.update({"type": None, "title": None, "status": None,
                       "last_change": None, "last_change_field": None,
                       "attestation": None, "never_reviewed": True,
                       "reasons": []})
        stem = path.stem
        no_ext = rel[:-3] if rel.endswith(".md") else rel
        if stem not in index_stems and no_ext not in index_paths:
            record["reasons"].append(_reason(
                "orphaned-from-index",
                "page is not catalogued in wiki/index.md"))
        record["reasons"].append(_reason(
            "no-frontmatter",
            "no frontmatter — type, dates and review state "
            "cannot be judged"))
        return record

    ptype = str(fields.get("type") or "").strip() or None
    status = str(fields.get("status") or "").strip().lower() or None
    changed, changed_field = last_change(fields)
    reasons = []

    # Owner attestation (a review event; the horizon is
    # its validity).
    a_state, a_until = attestation_state(fields, today)
    attestation = None
    if a_state is not None:
        attestation = {"state": a_state,
                       "verified_until": (a_until.isoformat()
                                          if a_until else None),
                       "verified_by": str(fields.get("verified_by")
                                          or "")}
        if a_state == "expired":
            reasons.append(_reason(
                "attestation-expired",
                f"owner attestation (verified_by: "
                f"{attestation['verified_by'] or 'unstated'}) "
                f"ran through {a_until.isoformat()}; the "
                f"horizon has passed",
                due=a_until, days_overdue=(today - a_until).days))
        elif a_state == "invalid":
            reasons.append(_reason(
                "attestation-invalid",
                f"verified_until {fields.get('verified_until')!r} "
                f"is present but is not a parseable date — a "
                f"horizon a reader may trust that does not exist"))

    # Claim re-verification schedule (FSRS, wiki_reverify).
    events = history_by_claim.get(rel, [])
    schedule = None
    if fields.get("claim"):
        sched = _reverify.claim_schedule(fields, events, today)
        schedule = {"status": sched["status"],
                    "due": (sched["due"].isoformat()
                            if sched["due"] else None),
                    "days_overdue": sched["days_overdue"],
                    "last_verified": (sched["last_verified"].isoformat()
                                      if sched["last_verified"] else None),
                    "verifications": len(events)}
        if sched["status"] == "overdue":
            reasons.append(_reason(
                "reverify-overdue",
                f"claim last verified "
                f"{schedule['last_verified'] or 'never (as_of anchor)'}; "
                f"re-check fell due {schedule['due']}",
                due=sched["due"], days_overdue=sched["days_overdue"]))
        elif sched["status"] == "due":
            reasons.append(_reason(
                "reverify-due",
                f"claim re-check falls due today "
                f"({schedule['due']}); last verified "
                f"{schedule['last_verified'] or 'never (as_of anchor)'}",
                due=sched["due"], days_overdue=0))

    # Evidence TTL (wiki_evidence_ttl's own state machine).
    ttl_state = _ttl.page_state(fields, today)
    if ttl_state and ttl_state["status"] == "due":
        reasons.append(_reason(
            "evidence-due",
            f"evidence gathered {ttl_state['evidence_as_of']} "
            f"with a {ttl_state['ttl_days']}d TTL; refresh fell "
            f"due {ttl_state['due']}",
            due=date.fromisoformat(ttl_state["due"]),
            days_overdue=ttl_state["days_overdue"]))
    elif ttl_state and ttl_state["status"] == "invalid":
        reasons.append(_reason(
            "evidence-invalid",
            f"evidence TTL half-stated: {ttl_state['reason']}"))

    # Cited source changed after the page's `updated`
    # (wiki_stale's rule).
    updated = parse_date(str(fields.get("updated") or ""))
    sources_changed = []
    if updated is not None:
        for entry in as_list(fields.get("sources")):
            resolved = resolver.resolve(str(entry))
            if resolved is None or not (root / resolved).is_file():
                continue
            changed_on = resolver.git_last_change(resolved)
            if changed_on is not None and changed_on > updated:
                sources_changed.append(
                    {"source": resolved,
                     "changed": changed_on.isoformat()})
                reasons.append(_reason(
                    "source-changed",
                    f"cited source {resolved} last changed "
                    f"{changed_on.isoformat()}, after the page's "
                    f"updated {updated.isoformat()} — the page "
                    f"may rest on a superseded reading",
                    due=changed_on,
                    days_overdue=(today - changed_on).days))

    # Pending Review sections with open entries.
    sections = _pending.scan_page(text, today)
    open_entries = sum(s["open"] for s in sections)
    if open_entries:
        reasons.append(_reason(
            "pending-review-open",
            f"{open_entries} open entr"
            f"{'y' if open_entries == 1 else 'ies'} in a "
            f"## Pending Review section — claims still to "
            f"corroborate, named on the page"))

    # Review evidence census for this page.
    has_review_evidence = attestation is not None or bool(events)
    never_reviewed = not has_review_evidence

    # Cadence (proposed intervals) — only for pages with no
    # review event on record; attested and re-verified
    # pages run on their own adopted clocks above.
    if never_reviewed:
        if changed is None:
            reasons.append(_reason(
                "no-date",
                "no parseable created/updated/tended date — "
                "cadence cannot be judged"))
        else:
            interval = intervals.get(ptype, DEFAULT_INTERVAL)
            age = (today - changed).days
            if age > interval:
                due = changed + timedelta(days=interval)
                reasons.append(_reason(
                    "cadence-stale",
                    f"no review event on record (no owner "
                    f"attestation, no re-verification); last "
                    f"substantive change {changed.isoformat()} "
                    f"(frontmatter `{changed_field}`) is {age}d "
                    f"ago, beyond the proposed {interval}d "
                    f"interval for type "
                    f"{ptype or 'untyped'} — queued by last "
                    f"substantive change, which is an edit, "
                    f"not a review",
                    due=due, days_overdue=(today - due).days))

    # Index catalogue membership.
    stem = path.stem
    no_ext = rel[:-3] if rel.endswith(".md") else rel
    indexed = stem in index_stems or no_ext in index_paths
    if not indexed:
        reasons.append(_reason(
            "orphaned-from-index",
            "page is not catalogued in wiki/index.md"))

    record.update({
        "type": ptype,
        "title": str(fields.get("title") or "") or None,
        "status": status,
        "last_change": changed.isoformat() if changed else None,
        "last_change_field": changed_field,
        "attestation": attestation,
        "claim_schedule": schedule,
        "evidence_ttl": ttl_state,
        "sources_changed": sources_changed,
        "pending_sections": len(sections),
        "pending_open": open_entries,
        "pending_clearable": sum(1 for s in sections if s["clearable"]),
        "indexed": indexed,
        "reverify_events": len(events),
        "never_reviewed": never_reviewed,
        "reasons": reasons,
    })
    return record


def build_queue(root: Path, today: date, intervals: dict):
    """The full population scan + the queue. Returns
    (queue_doc, records) — records is every scanned page's
    analysis (the cadence report reuses it)."""
    resolver = SourceResolver(root)
    index_stems, index_paths = index_targets(root)
    _events, by_claim = load_reverify_history(root)
    records, retired, queue = [], 0, []
    for path in page_paths(root):
        rec = analyse_page(root, path, today, intervals, resolver,
                           index_stems, index_paths, by_claim)
        records.append(rec)
        status = rec.get("status")
        if status in RETIRED_STATUSES:
            retired += 1
            continue
        if rec["reasons"]:
            dated = [r["days_overdue"] for r in rec["reasons"]
                     if r["days_overdue"] is not None]
            entry = {
                "page": rec["page"],
                "type": rec["type"],
                "title": rec["title"],
                "last_change": rec["last_change"],
                "last_change_field": rec["last_change_field"],
                "never_reviewed": rec["never_reviewed"],
                "max_days_overdue": max(dated) if dated else None,
                "reasons": rec["reasons"],
            }
            queue.append(entry)
    # Most overdue first; ties by page path; entries whose
    # reasons are all undated last, by path.
    queue.sort(key=lambda e: (
        -(e["max_days_overdue"] if e["max_days_overdue"] is not None
          else -1), e["page"]))
    by_reason = {}
    for entry in queue:
        for r in entry["reasons"]:
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    doc = {
        "tool": "scripts/wiki_review_layer.py",
        "kind": "review-queue",
        "as_of": today.isoformat(),
        "cadence": {
            "status": "PROPOSED — not in AGENTS.md; the adopted "
                      "clocks (evidence TTL, FSRS re-verification, "
                      "owner attestation horizons) take precedence "
                      "where a page carries them",
            "intervals_days": {k: intervals[k]
                               for k in sorted(intervals)},
            "default_days": DEFAULT_INTERVAL,
        },
        "population": {
            "scanned": len(records),
            "retired_excluded": retired,
            "no_frontmatter": sum(1 for r in records
                                   if r["fields"] is None),
            "never_reviewed": sum(1 for r in records
                                  if r["never_reviewed"]),
            "attested_current": sum(
                1 for r in records if r["attestation"]
                and r["attestation"]["state"] == "current"),
            "attested_expired": sum(
                1 for r in records if r["attestation"]
                and r["attestation"]["state"] == "expired"),
        },
        "stats": {"queued": len(queue), "by_reason": by_reason},
        "queue": queue,
    }
    return doc, records


# -- rendering: the queue ----------------------------------------------------

def render_queue_md(doc: dict) -> str:
    pop, stats = doc["population"], doc["stats"]
    lines = [
        "# Review queue",
        "",
        f"Generated by `scripts/wiki_review_layer.py` as of "
        f"{doc['as_of']} — a proposal list, not an edit: this "
        f"layer queues pages for review and changes nothing "
        f"it queues.",
        "",
        "A **review** here means the record shows one: an "
        "owner attestation (`verified_until`) or a "
        "re-verification event in "
        "`evaluation/reverify-history.jsonl`. An edit is not "
        "a review; pages with no review event are queued by "
        "their last substantive change and say so.",
        "",
        f"Cadence intervals are **PROPOSED** (not in "
        f"AGENTS.md): "
        + " · ".join(f"{k} {v}d" for k, v in
                     doc["cadence"]["intervals_days"].items())
        + f" · other {doc['cadence']['default_days']}d. "
          "Per-page clocks (evidence TTL, FSRS, attestation "
          "horizons) take precedence where present.",
        "",
        f"Population: {pop['scanned']} pages scanned · "
        f"{pop['retired_excluded']} retired excluded · "
        f"{pop['never_reviewed']} with no review event on "
        f"record · {pop['attested_current']} attested "
        f"current · {pop['attested_expired']} attested "
        f"expired.",
        "",
        f"**{stats['queued']} page(s) queued.** By reason: "
        + " · ".join(f"{k} {v}" for k, v in
                     sorted(stats["by_reason"].items())),
        "",
    ]
    for entry in doc["queue"]:
        head = f"## `{entry['page']}`"
        meta = []
        if entry["type"]:
            meta.append(f"type {entry['type']}")
        if entry["last_change"]:
            meta.append(f"last substantive change "
                        f"{entry['last_change']} "
                        f"(`{entry['last_change_field']}`)")
        if entry["max_days_overdue"] is not None:
            meta.append(f"worst clock {entry['max_days_overdue']}d "
                        f"overdue")
        lines.append(head)
        if meta:
            lines.append("")
            lines.append(" — ".join(meta) + ".")
        lines.append("")
        for r in entry["reasons"]:
            lines.append(f"- **{r['reason']}** — {r['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# -- the log (patterns + weekly review are bounded to it) --------------------

def parse_log(root: Path):
    """[(date, kind, title)] from wiki/log.md entry
    headers, in file order. The log only — the patterns
    review collects no new data."""
    log = root / "wiki" / "log.md"
    if not log.is_file():
        return []
    text = log.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in LOG_ENTRY_RE.finditer(text):
        try:
            when = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        out.append((when, m.group(2).strip().lower(),
                    m.group(3).strip()))
    return out


def parse_ledger_entries(root: Path, start: date, end: date):
    """Corrections-ledger entries (### YYYY-MM-DD — …)
    whose date falls in [start, end]."""
    ledger = root / "wiki" / "rules" / "corrections-ledger.md"
    if not ledger.is_file():
        return []
    text = ledger.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in LEDGER_ENTRY_RE.finditer(text):
        try:
            when = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if start <= when <= end:
            out.append((when, m.group(2).strip()))
    return out


def _bullets(items, cap=WEEKLY_BULLET_CAP):
    lines = [f"- {item}" for item in items[:cap]]
    if len(items) > cap:
        lines.append(f"- … and {len(items) - cap} more "
                     f"(see `wiki/log.md`)")
    if not items:
        lines.append("- (none in the record for this window)")
    return lines


# -- rendering: the cadence report -------------------------------------------

def build_report(root: Path, today: date, intervals: dict,
                 queue_doc: dict, records: list) -> str:
    history, _by_claim = load_reverify_history(root)
    entries = parse_log(root)
    pop, stats = queue_doc["population"], queue_doc["stats"]

    def window_events(days):
        start = today - timedelta(days=days - 1)
        return [e for e in history
                if (d := parse_date(str(e.get("date") or "")))
                and start <= d <= today]

    ev7, ev30 = window_events(7), window_events(30)

    def outcome_counts(evs):
        counts = {}
        for e in evs:
            counts[e.get("outcome")] = counts.get(e.get("outcome"), 0) + 1
        return " · ".join(f"{k} {counts[k]}" for k in sorted(counts))

    attested_current = sorted(
        r["page"] for r in records if r["attestation"]
        and r["attestation"]["state"] == "current")
    attested_expired = sorted(
        r["page"] for r in records if r["attestation"]
        and r["attestation"]["state"] == "expired")
    pending_open = sum(r.get("pending_open", 0) for r in records)
    pending_clearable = sum(r.get("pending_clearable", 0)
                            for r in records)

    week_start = today - timedelta(days=6)
    week = [(d, k, t) for d, k, t in entries
            if week_start <= d <= today]
    plus = [f"[{d.isoformat()}] {t} ({k})"
            for d, k, t in week if k in PLUS_KINDS]
    minus = [f"[{d.isoformat()}] {t} ({k})"
             for d, k, t in week if k in MINUS_KINDS]
    for when, title in parse_ledger_entries(root, week_start, today):
        minus.append(f"[{when.isoformat()}] correction entered: "
                     f"{title} (corrections ledger)")
    if attested_expired:
        minus.append(f"{len(attested_expired)} owner attestation(s) "
                     f"past their horizon — early warning, see the "
                     f"queue")
    if stats["queued"]:
        minus.append(f"{stats['queued']} page(s) stand in the "
                     f"review queue — early warning, see the queue")
    nxt = []
    for entry in queue_doc["queue"][:5]:
        worst = entry["reasons"][0]
        for r in entry["reasons"]:
            if r["days_overdue"] is not None and (
                    worst["days_overdue"] is None
                    or r["days_overdue"] > worst["days_overdue"]):
                worst = r
        od = (f", {worst['days_overdue']}d overdue"
              if worst["days_overdue"] is not None else "")
        nxt.append(f"`{entry['page']}` — {worst['reason']}{od}")

    today_entries = [(k, t) for d, k, t in entries if d == today]
    due_today = [e["page"] for e in queue_doc["queue"]
                 if any(r.get("due") == today.isoformat()
                        for r in e["reasons"])]

    # Patterns over the log only.
    by_kind, by_week, by_day, titles = {}, {}, {}, {}
    for d, k, t in entries:
        by_kind[k] = by_kind.get(k, 0) + 1
        iso = d.isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        by_week[wk] = by_week.get(wk, 0) + 1
        by_day[d] = by_day.get(d, 0) + 1
        norm = re.sub(r"\s+", " ", t.lower()).strip()
        if norm:
            titles[norm] = titles.get(norm, 0) + 1
    recurring = sorted(((c, t) for t, c in titles.items() if c >= 2),
                       key=lambda x: (-x[0], x[1]))[:10]
    busiest = None
    if by_day:
        best = max(by_day.values())
        busiest = (min(d for d, c in by_day.items() if c == best), best)
    span = (f"{min(d for d, _, _ in entries).isoformat()} → "
            f"{max(d for d, _, _ in entries).isoformat()}"
            if entries else "no entries")

    lines = [
        "# Periodic review — cadence report",
        "",
        f"Generated by `scripts/wiki_review_layer.py` as of "
        f"{today.isoformat()}, from the corpus and its own "
        f"record only. Companion artefact: "
        f"`evaluation/review-queue.md` / `.json`.",
        "",
        "## The cadence (proposed)",
        "",
        "AGENTS.md sets no per-type review interval; the "
        "adopted clocks are per-page (evidence TTL), "
        "per-claim (FSRS re-verification) and per-attestation "
        "(the owner's `verified_until` horizon), and they "
        "take precedence wherever a page carries them. The "
        "intervals below are **PROPOSALS** for the remaining "
        "population — stated here, not legislated into the "
        "schema:",
        "",
        "| page type | proposed interval |",
        "|---|---|",
    ]
    for ptype in sorted(intervals):
        lines.append(f"| {ptype} | {intervals[ptype]}d |")
    lines += [
        f"| (any other / untyped) | {DEFAULT_INTERVAL}d |",
        "",
        "## Evidence rule",
        "",
        "A page counts as reviewed only where the record "
        "shows a review: an owner attestation, or a "
        "re-verification event in "
        "`evaluation/reverify-history.jsonl`. An edit "
        "(`tended` / `updated`) is not a review. Pages with "
        "no review event are queued by last substantive "
        "change, labelled as such — the house record "
        "distinguishes the two, and this layer does not "
        "blur them.",
        "",
        "## Population",
        "",
        f"- {pop['scanned']} pages scanned "
        f"({pop['retired_excluded']} retired excluded, "
        f"{pop['no_frontmatter']} without frontmatter)",
        f"- {pop['never_reviewed']} pages carry no review "
        f"event on record",
        f"- {stats['queued']} pages stand in the review queue",
        "",
        "## Reviewed — what the record shows",
        "",
        f"- Re-verification events, last 7 days: "
        f"{len(ev7)} ({outcome_counts(ev7) or 'none'})",
        f"- Re-verification events, last 30 days: "
        f"{len(ev30)} ({outcome_counts(ev30) or 'none'})",
        f"- Owner attestations current: "
        f"{len(attested_current)}"
        + (": " + ", ".join(f"`{p}`" for p in attested_current)
           if attested_current else ""),
        f"- Owner attestations expired: {len(attested_expired)}",
        f"- Pending Review sections across the corpus: "
        f"{pending_open} open entr"
        f"{'y' if pending_open == 1 else 'ies'}, "
        f"{pending_clearable} clearable section(s)",
        "",
        "## Overdue — the queue in brief",
        "",
    ]
    if stats["by_reason"]:
        lines.append("By reason: " + " · ".join(
            f"{k} {v}" for k, v in
            sorted(stats["by_reason"].items())))
        lines.append("")
        lines.append("| page | worst reason | overdue |")
        lines.append("|---|---|---|")
        for entry in queue_doc["queue"][:10]:
            worst = max(entry["reasons"],
                        key=lambda r: (r["days_overdue"]
                                       if r["days_overdue"] is not None
                                       else -1))
            od = (f"{worst['days_overdue']}d"
                  if worst["days_overdue"] is not None else "—")
            lines.append(f"| `{entry['page']}` | "
                         f"{worst['reason']} | {od} |")
    else:
        lines.append("Nothing is queued. The corpus is inside "
                     "every clock it carries.")
    lines += [
        "",
        f"## Daily review — {today.isoformat()}",
        "",
    ]
    if today_entries:
        lines += [f"- [{k}] {t}" for k, t in today_entries]
    else:
        lines.append("- No log entries carry today's date.")
    if due_today:
        lines.append("- Falling due today: "
                     + ", ".join(f"`{p}`" for p in due_today))
    lines += [
        "",
        f"## Weekly review — Plus / Minus / Next "
        f"({week_start.isoformat()} → {today.isoformat()})",
        "",
        "Bullets only (the Le Cunff format). Derived from "
        "`wiki/log.md` and the corrections ledger by the "
        "rule stated in the tool: Plus ← forward-motion "
        "log entries; Minus ← lint / correction / fix "
        "entries, corrections entered, and standing queue "
        "warnings (the Minus column doubles as early "
        "warning); Next ← the head of the review queue.",
        "",
        "### Plus",
        "",
    ]
    lines += _bullets(plus)
    lines += ["", "### Minus", ""]
    lines += _bullets(minus)
    lines += ["", "### Next", ""]
    lines += _bullets(nxt)
    lines += [
        "",
        "## Patterns over the log",
        "",
        "Bounded to `wiki/log.md` — no new data collected "
        "(the auto-discovery rejection is the boundary).",
        "",
        f"- {len(entries)} entries, {span}",
        "- By kind: " + (" · ".join(
            f"{k} {v}" for k, v in sorted(
                by_kind.items(), key=lambda kv: (-kv[1], kv[0])))
            if by_kind else "none"),
        "- By ISO week: " + (" · ".join(
            f"{k} {by_week[k]}" for k in sorted(by_week))
            if by_week else "none"),
    ]
    if busiest:
        lines.append(f"- Busiest day: {busiest[0].isoformat()} "
                     f"({busiest[1]} entries)")
    if recurring:
        lines.append("- Recurring entry titles: " + " · ".join(
            f"“{t}” ×{c}" for c, t in recurring))
    lines += [
        "",
        "## Boundaries",
        "",
        "- This layer proposes; it edits nothing it queues "
        "and marks nothing reviewed.",
        "- Cadence intervals above are proposals in this "
        "report, not schema; adopting them is a separate, "
        "recorded act.",
        "- Patterns derive from the log only; nothing is "
        "inferred from outside the record.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# -- CLI -----------------------------------------------------------------------

def _parse_intervals(pairs):
    intervals = dict(PROPOSED_CADENCE)
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--interval {pair!r}: want TYPE=DAYS")
        ptype, _, days = pair.partition("=")
        try:
            intervals[ptype.strip()] = int(days)
        except ValueError:
            raise ValueError(
                f"--interval {pair!r}: DAYS is not an integer") from None
    return intervals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Periodic review layer: review queue + "
                    "cadence report (report-only over the corpus).")
    ap.add_argument("command", nargs="?", default="all",
                    choices=("all", "queue", "report"),
                    help="what to generate (default: all)")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--today", default=None,
                    help="date treated as today (default: the "
                         "real today); pass it for a "
                         "deterministic run")
    ap.add_argument("--interval", action="append", default=None,
                    metavar="TYPE=DAYS",
                    help="override a proposed cadence interval "
                         "(repeatable)")
    ap.add_argument("--out-dir", default=None,
                    help="where artefacts land (default: "
                         "<root>/evaluation)")
    ap.add_argument("--json", action="store_true",
                    help="with --stdout, print the queue as JSON")
    ap.add_argument("--stdout", action="store_true",
                    help="print instead of writing artefacts")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if args.today:
        today = parse_date(args.today)
        if today is None:
            print(f"error: --today {args.today!r} is not an ISO "
                  f"date", file=sys.stderr)
            return 2
    else:
        today = date.today()
    try:
        intervals = _parse_intervals(args.interval)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    queue_doc, records = build_queue(root, today, intervals)
    queue_json = json.dumps(queue_doc, indent=2, sort_keys=True,
                            ensure_ascii=False) + "\n"
    queue_md = render_queue_md(queue_doc)
    report_md = build_report(root, today, intervals, queue_doc,
                             records)

    written = []
    if args.stdout:
        if args.command in ("all", "queue"):
            print(queue_json if args.json else queue_md)
        if args.command == "report" or (args.command == "all"
                                        and args.json):
            print(report_md)
    else:
        out_dir = (Path(args.out_dir).resolve() if args.out_dir
                   else root / "evaluation")
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.command in ("all", "queue"):
            (out_dir / "review-queue.json").write_text(
                queue_json, encoding="utf-8")
            (out_dir / "review-queue.md").write_text(
                queue_md, encoding="utf-8")
            written += ["review-queue.json", "review-queue.md"]
        if args.command in ("all", "report"):
            (out_dir / "review-cadence-report.md").write_text(
                report_md, encoding="utf-8")
            written.append("review-cadence-report.md")

    pop, stats = queue_doc["population"], queue_doc["stats"]
    print(f"review layer as of {today.isoformat()}: "
          f"{pop['scanned']} scanned, {stats['queued']} queued "
          f"({', '.join(f'{k}={v}' for k, v in sorted(stats['by_reason'].items())) or 'no reasons'})",
          file=sys.stderr)
    if written:
        print(f"wrote: {', '.join(written)} -> "
              f"{out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
