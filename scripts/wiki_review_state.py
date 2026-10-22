#!/usr/bin/env python3
"""wiki_review_state.py — review-state frontmatter + the
Review Center (Wave 5, build list 2026-10-22).

Clean re-implementation. Idea source (idea only, no code
taken): "Smart Review" (build-list row) — review state
carried on the page itself, a human-facing review queue
with spaced-review feedback and review history. The FSRS
re-verification machinery (scripts/wiki_reverify.py) and
the periodic review layer (scripts/wiki_review_layer.py)
already exist here; this tool COMPLEMENTS them — it does
not re-derive their schedules, it consumes the review
layer's queue in-process and adds the page-declared
review state on top.

(a) REVIEW-STATE FRONTMATTER — the field set this tool
defines and validates (a fifth axis, about REVIEW, never
conflated with status lifecycle / confidence evidence /
stage maturity / work_type kind-of-work):

  review_state:  unreviewed | in-review | reviewed
                 DECLARED by a review act — a reviewer
                 edits the page's frontmatter when they
                 start / complete a review. Absence is a
                 census fact ("undeclared"), not an error.
  reviewed_on:   YYYY-MM-DD — the date the last review
                 completed. Required iff state=reviewed.
  reviewed_by:   who performed that review (a name).
                 Required iff state=reviewed. This is NOT
                 the owner attestation: verified_until /
                 verified_by: owner stay owner-only and
                 are only ever READ here, never written.
  review_due:    YYYY-MM-DD — optional; the page's own
                 stated next-review date. Where present
                 it takes precedence over the cadence
                 proposals (the review layer's precedence
                 rule: adopted per-page clocks first).

EFFECTIVE state is DERIVED, never stamped (the declared /
effective split of scripts/wiki_quality_track.py):

  retired page (status tombstoned / superseded /
    deprecated / archived)      out of the population
  no review_state field         undeclared
  declared unreviewed           unreviewed
  declared in-review            in-review
  declared reviewed:
    reviewed_on missing/bad     reviewed-unverifiable
                                (+ a finding)
    last substantive change (tended, else updated) after
      reviewed_on               reviewed-stale (changed)
    review_due present and < today
                                reviewed-stale (due-passed)
    no review_due and today past reviewed_on + the
      (PROPOSED) cadence interval for the page's type
                                reviewed-stale (cadence)
    otherwise                   reviewed-current

FINDINGS (an invalid review RECORD, named per page):
  unknown-review-state · reviewed-without-reviewed-on ·
  reviewed-without-reviewed-by · reviewed-on-unparseable ·
  reviewed-on-in-future · reviewed-on-before-created ·
  review-due-unparseable · review-fields-without-state
  (reviewed_on / reviewed_by / review_due present with
  no review_state — the fields assert a review the state
  does not declare).

TRANSITIONS — the closed legal table, shipped in every
census artefact so consumers share one definition:
  (none)     -> unreviewed | in-review | reviewed
  unreviewed -> in-review | reviewed
  in-review  -> reviewed | unreviewed   (done / abandoned)
  reviewed   -> in-review               (re-review begins)
  reviewed   -> reviewed is legal only with reviewed_on
                ADVANCING (a re-review completed); a
                reviewed_on moving backward is illegal.
  any        -> (none) is illegal (a declaration is never
                silently withdrawn), except on a page that
                leaves the population (retired).
`diff OLD.json NEW.json` compares two census artefacts
and reports every illegal jump by name.

(b) THE REVIEW CENTER — one prioritised worklist merging:
  - the periodic review layer's queue (its reasons as-is:
    attestation expiry, FSRS re-verification due, evidence
    TTL, source-changed, cadence, Pending Review sections,
    orphans), computed in-process via build_queue();
  - review-state items the layer cannot see: pages whose
    DECLARED review went stale, and pages whose review
    record is invalid (a finding above);
  - claim-lifecycle annotation: a queued page carrying a
    frontmatter `claim:` is annotated with the claim text
    and its lifecycle standing (frontmatter outcome_*
    fields where recorded; else "candidate — no outcomes
    recorded", the schema's rule for <3 outcomes).
  - anchored review threads (scripts/
    wiki_review_threads.py, loaded in-process): a page
    with open threads — orphaned anchors included —
    gains an "open-review-threads" reason carrying the
    count (band P3, with the rest). Zero threads, or no
    threads register, adds nothing: the artefacts are
    byte-identical to the pre-threads build.
Priority bands (the stated ordering rule; within a band:
most-overdue first, undated last, then page path):
  P1  attestation-expired · reverify-overdue ·
      pending-review-open · review-record-invalid
  P2  evidence-due · source-changed · review-state-stale
  P3  everything else the queue carries
Each worklist entry also carries SPACED-REVIEW FEEDBACK:
next_due_if_reviewed_today = today + the interval that
governs the page (its own review_due does not set the
interval; the type cadence PROPOSAL does, labelled a
proposal; claim pages follow their FSRS schedule, whose
state the queue reasons already carry).
REVIEW HISTORY is assembled from the registers only:
owner attestations (verified_until, read-only), the
reverify-history events, and declared page reviews
(reviewed_on). Nothing is inferred from edits — an edit
is not a review (the review layer's evidence rule).
The AI PAYLOAD export is the worklist as JSONL, one line
per item, shaped for an AI reviewer: page, reasons with
their proving dates, the cited sources to check against,
and the review task stated in words.

READ-ONLY over the corpus: this tool writes only its own
artefacts (evaluation/review-state-census.json,
evaluation/review-center.json, evaluation/review-center.md,
evaluation/review-center-payload.jsonl, or --out-dir).
It never stamps a page, never extends an attestation,
never marks anything reviewed.

DETERMINISM: same corpus + same --today -> identical
artefact bytes. No wall clock except as --today's default.

Usage:
  python3 scripts/wiki_review_state.py [all|census|center|
      payload|check|diff OLD NEW]
      [--root DIR] [--today YYYY-MM-DD] [--out-dir DIR]
      [--json]

Exit codes: 0 done · 1 `check` found invalid review
records · 2 usage error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wv = _load("wiki_validate")
_rl = _load("wiki_review_layer")
parse_date = _wv.parse_date


def parse_frontmatter(text):
    """wiki_validate's parser returns (fields, body);
    this tool only ever needs the fields."""
    fields, _body = _wv.parse_frontmatter(text)
    return fields
page_paths = _rl.page_paths
RETIRED_STATUSES = _rl.RETIRED_STATUSES
PROPOSED_CADENCE = _rl.PROPOSED_CADENCE
DEFAULT_INTERVAL = _rl.DEFAULT_INTERVAL

REVIEW_STATES = ("unreviewed", "in-review", "reviewed")
EFFECTIVE_STATES = ("undeclared", "unreviewed", "in-review",
                    "reviewed-current", "reviewed-stale",
                    "reviewed-unverifiable")
# The closed transition table. None = no declared state.
TRANSITIONS = {
    None: {"unreviewed", "in-review", "reviewed"},
    "unreviewed": {"in-review", "reviewed"},
    "in-review": {"reviewed", "unreviewed"},
    "reviewed": {"in-review", "reviewed"},
}

FIELD_SET = {
    "review_state": "unreviewed | in-review | reviewed — "
                    "declared by a review act; absence is "
                    "a census fact, not an error",
    "reviewed_on": "YYYY-MM-DD — required iff "
                   "review_state is reviewed",
    "reviewed_by": "who performed the review — required "
                   "iff reviewed; NOT the owner attestation "
                   "(verified_until stays owner-only)",
    "review_due": "YYYY-MM-DD — optional page-stated next "
                  "review date; takes precedence over the "
                  "cadence proposals",
}

# Priority bands over worklist reasons (stated rule; see
# the docstring). A reason not listed here is band 3.
REASON_BAND = {
    "attestation-expired": 1,
    "reverify-overdue": 1,
    "pending-review-open": 1,
    "review-record-invalid": 1,
    "evidence-due": 2,
    "source-changed": 2,
    "review-state-stale": 2,
}


def legal_transition(frm, to):
    """True iff the closed table allows frm -> to.
    frm/to are declared states or None (undeclared)."""
    if frm == to:
        return True
    return to in TRANSITIONS.get(frm, set())


def _interval_for(fields, intervals):
    ptype = (fields or {}).get("type")
    return intervals.get(ptype, DEFAULT_INTERVAL)


def default_intervals():
    out = dict(PROPOSED_CADENCE)
    return out


# -- per-page review-state analysis -----------------------------------------

def analyse_review_state(fields, today, intervals):
    """(declared, effective, stale_detail, findings) for one
    page's frontmatter dict (None = no frontmatter)."""
    findings = []
    if not fields:
        return None, "undeclared", None, findings
    declared = fields.get("review_state")
    if declared is not None:
        declared = str(declared).strip()
    reviewed_on_raw = fields.get("reviewed_on")
    reviewed_by = fields.get("reviewed_by")
    due_raw = fields.get("review_due")
    reviewed_on = (parse_date(str(reviewed_on_raw))
                   if reviewed_on_raw else None)
    due = parse_date(str(due_raw)) if due_raw else None

    if declared is None:
        if (reviewed_on_raw or reviewed_by or due_raw):
            findings.append("review-fields-without-state")
        return None, "undeclared", None, findings
    if declared not in REVIEW_STATES:
        findings.append("unknown-review-state")
        return declared, "undeclared", None, findings
    if due_raw and due is None:
        findings.append("review-due-unparseable")
    if declared in ("unreviewed", "in-review"):
        return declared, declared, None, findings

    # declared == reviewed. Only the review's OWN defects
    # (collected in rf) make it unverifiable — a broken
    # review_due is a finding on the record, not a doubt
    # on the review itself.
    rf = []
    if not reviewed_on_raw:
        rf.append("reviewed-without-reviewed-on")
    elif reviewed_on is None:
        rf.append("reviewed-on-unparseable")
    if not reviewed_by or not str(reviewed_by).strip():
        rf.append("reviewed-without-reviewed-by")
    if reviewed_on is not None:
        if reviewed_on > today:
            rf.append("reviewed-on-in-future")
        created = parse_date(str(fields.get("created") or ""))
        if created and reviewed_on < created:
            rf.append("reviewed-on-before-created")
    findings.extend(rf)
    if rf:
        return declared, "reviewed-unverifiable", None, findings

    changed, _field = _rl.last_change(fields)
    if changed and changed > reviewed_on:
        return declared, "reviewed-stale", {
            "via": "changed-since-review",
            "due": reviewed_on.isoformat(),
            "days_overdue": (today - reviewed_on).days
            if today > reviewed_on else 0,
            "detail": f"page changed {changed.isoformat()} "
                      f"after its review "
                      f"{reviewed_on.isoformat()}"}, findings
    if due is not None:
        if today > due:
            return declared, "reviewed-stale", {
                "via": "review-due-passed",
                "due": due.isoformat(),
                "days_overdue": (today - due).days,
                "detail": f"the page's own review_due "
                          f"{due.isoformat()} has passed"}, \
                findings
        return declared, "reviewed-current", None, findings
    interval = _interval_for(fields, intervals)
    cadence_due = reviewed_on + timedelta(days=interval)
    if today > cadence_due:
        return declared, "reviewed-stale", {
            "via": "cadence-passed",
            "due": cadence_due.isoformat(),
            "days_overdue": (today - cadence_due).days,
            "detail": f"reviewed {reviewed_on.isoformat()}; "
                      f"the PROPOSED {interval}d cadence "
                      f"for its type puts the next review at "
                      f"{cadence_due.isoformat()}"}, findings
    return declared, "reviewed-current", None, findings


# -- census ------------------------------------------------------------------

def build_census(root: Path, today: date, intervals=None):
    """The review-state census over the compiled layer
    (the review layer's scan set)."""
    intervals = intervals or default_intervals()
    pages, findings_all = [], []
    retired = 0
    by_declared, by_effective = {}, {}
    for path in page_paths(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        fields = parse_frontmatter(text)
        status = (fields or {}).get("status")
        if status in RETIRED_STATUSES:
            retired += 1
            continue
        declared, effective, stale, findings = \
            analyse_review_state(fields, today, intervals)
        changed, changed_field = _rl.last_change(fields)
        rec = {
            "page": rel,
            "title": (fields or {}).get("title"),
            "type": (fields or {}).get("type"),
            "declared_state": declared,
            "effective_state": effective,
            "reviewed_on": (str(fields.get("reviewed_on"))
                            if fields and fields.get("reviewed_on")
                            else None),
            "reviewed_by": (str(fields.get("reviewed_by"))
                            if fields and fields.get("reviewed_by")
                            else None),
            "review_due": (str(fields.get("review_due"))
                           if fields and fields.get("review_due")
                           else None),
            "stale": stale,
            "findings": findings,
            "last_change": (changed.isoformat()
                            if changed else None),
            "last_change_field": changed_field,
        }
        pages.append(rec)
        key_d = declared if declared is not None else "(absent)"
        by_declared[key_d] = by_declared.get(key_d, 0) + 1
        by_effective[effective] = \
            by_effective.get(effective, 0) + 1
        for f in findings:
            findings_all.append({"page": rel, "finding": f})
    findings_all.sort(key=lambda x: (x["finding"], x["page"]))
    doc = {
        "tool": "scripts/wiki_review_state.py",
        "kind": "review-state-census",
        "as_of": today.isoformat(),
        "field_set": FIELD_SET,
        "states": {"declared": list(REVIEW_STATES),
                   "effective": list(EFFECTIVE_STATES)},
        "transitions": {
            (k if k is not None else "(absent)"): sorted(v)
            for k, v in TRANSITIONS.items()},
        "population": {
            "scanned": len(pages) + retired,
            "retired_excluded": retired,
            "in_population": len(pages),
            "carrying_review_state":
                sum(1 for p in pages if p["declared_state"]),
            "with_findings":
                len({f["page"] for f in findings_all}),
        },
        "census": {"by_declared": by_declared,
                   "by_effective": by_effective},
        "findings": findings_all,
        "pages": pages,
    }
    return doc


def diff_censuses(old: dict, new: dict):
    """Illegal declared-state jumps between two census
    artefacts, by name. A page absent from the old census
    counts as (absent); a page that left the population
    (retired / removed) is not a transition finding."""
    old_pages = {p["page"]: p for p in old.get("pages", [])}
    new_pages = {p["page"]: p for p in new.get("pages", [])}
    out = []
    for page in sorted(new_pages):
        frm = (old_pages.get(page) or {}).get("declared_state")
        to = new_pages[page].get("declared_state")
        if frm == to:
            if frm == "reviewed":
                o = (old_pages[page].get("reviewed_on")
                     if page in old_pages else None)
                n = new_pages[page].get("reviewed_on")
                od, nd = parse_date(o or ""), parse_date(n or "")
                if od and nd and nd < od:
                    out.append({
                        "page": page, "from": frm, "to": to,
                        "finding": "reviewed-on-moved-backward",
                        "detail": f"reviewed_on {o} -> {n}"})
            continue
        if not legal_transition(frm, to):
            out.append({
                "page": page, "from": frm, "to": to,
                "finding": "illegal-transition",
                "detail": f"{frm or '(absent)'} -> "
                          f"{to or '(absent)'} is not in the "
                          f"closed transition table"})
    return out


# -- the Review Center --------------------------------------------------------

def _claim_annotation(fields):
    """The claim-lifecycle standing of a page carrying a
    frontmatter `claim:` (schema: candidate while fewer
    than 3 outcomes are recorded, rule at 3+, retired when
    the three most recent outcomes all contradict). Read
    from the page's own outcome_* fields, which
    scripts/wiki_claims.py maintains; never computed into
    the page here."""
    if not fields or not fields.get("claim"):
        return None
    status = fields.get("outcome_status")
    n = fields.get("outcome_n")
    if status:
        standing = str(status)
    elif n is None or str(n).strip() in ("", "0"):
        standing = "candidate — no outcomes recorded"
    else:
        standing = "candidate — fewer than 3 outcomes"
    return {"claim": str(fields["claim"]),
            "as_of": (str(fields["as_of"])
                      if fields.get("as_of") else None),
            "outcome_status": standing,
            "outcome_n": n}


def _history(root: Path, census_pages, today: date):
    """Review history from the registers only: owner
    attestations (read-only), reverify-history events, and
    declared page reviews. Edits are not reviews."""
    attestations, declared = [], []
    for rec in census_pages:
        path = root / rec["page"]
        fields = parse_frontmatter(
            path.read_text(encoding="utf-8", errors="ignore"))
        state, until = _rl.attestation_state(fields, today)
        if state is not None:
            attestations.append({
                "page": rec["page"], "state": state,
                "verified_until": (until.isoformat()
                                   if until else None),
                "verified_by": (str(fields.get("verified_by"))
                                if fields.get("verified_by")
                                else None)})
        if rec["reviewed_on"]:
            declared.append({
                "page": rec["page"],
                "reviewed_on": rec["reviewed_on"],
                "reviewed_by": rec["reviewed_by"]})
    attestations.sort(key=lambda a: a["page"])
    declared.sort(key=lambda d: (d["reviewed_on"], d["page"]),
                  reverse=True)
    events, _by_claim = _rl.load_reverify_history(root)
    reverify = []
    for ev in events:
        reverify.append({
            "claim": ev.get("claim"),
            "date": ev.get("date") or ev.get("checked_on"),
            "outcome": ev.get("outcome")})
    reverify.sort(key=lambda e: (str(e["date"] or ""),
                                 str(e["claim"] or "")),
                  reverse=True)
    return {"owner_attestations": attestations,
            "declared_page_reviews": declared,
            "reverify_events": reverify}


def build_review_center(root: Path, today: date):
    """The merged, prioritised worklist + census summary +
    history. Consumed by the CLI (artefacts) and by the
    Lens build (data/review.js)."""
    intervals = default_intervals()
    queue_doc, _records = _rl.build_queue(root, today,
                                          dict(intervals))
    census = build_census(root, today, intervals)
    census_by_page = {p["page"]: p for p in census["pages"]}

    items = {}
    for entry in queue_doc["queue"]:
        items[entry["page"]] = {
            "page": entry["page"],
            "page_id": Path(entry["page"]).stem,
            "title": entry["title"],
            "type": entry["type"],
            "reasons": [dict(r) for r in entry["reasons"]],
            "max_days_overdue": entry["max_days_overdue"],
            "never_reviewed": entry["never_reviewed"],
            "last_change": entry["last_change"],
        }
    for rec in census["pages"]:
        extra = []
        if rec["effective_state"] == "reviewed-stale" \
                and rec["stale"]:
            extra.append({
                "reason": "review-state-stale",
                "detail": rec["stale"]["detail"],
                "due": rec["stale"]["due"],
                "days_overdue": rec["stale"]["days_overdue"]})
        if rec["findings"]:
            extra.append({
                "reason": "review-record-invalid",
                "detail": "invalid review record: "
                          + ", ".join(rec["findings"]),
                "due": None, "days_overdue": None})
        if not extra:
            continue
        item = items.get(rec["page"])
        if item is None:
            item = {
                "page": rec["page"],
                "page_id": Path(rec["page"]).stem,
                "title": rec["title"], "type": rec["type"],
                "reasons": [], "max_days_overdue": None,
                "never_reviewed": False,
                "last_change": rec["last_change"],
            }
            items[rec["page"]] = item
        item["reasons"].extend(extra)
        dated = [r["days_overdue"] for r in item["reasons"]
                 if r.get("days_overdue") is not None]
        item["max_days_overdue"] = max(dated) if dated else None

    # Anchored review threads: open threads on a page are
    # review work owed on it. Consumed from the threads
    # register in-process; an absent register is the
    # honest zero and changes nothing above.
    _rt = _load("wiki_review_threads")
    thread_counts = _rt.open_threads_by_page(root)
    for page in sorted(thread_counts):
        counts = thread_counts[page]
        item = items.get(page)
        if item is None:
            path = root / page
            fields = (parse_frontmatter(path.read_text(
                encoding="utf-8", errors="ignore"))
                if path.is_file() else None)
            changed, _field = _rl.last_change(fields)
            item = {
                "page": page,
                "page_id": Path(page).stem,
                "title": (fields or {}).get("title"),
                "type": (fields or {}).get("type"),
                "reasons": [], "max_days_overdue": None,
                "never_reviewed": False,
                "last_change": (changed.isoformat()
                                if changed else None),
            }
            items[page] = item
        detail = (f"{counts['open']} open review "
                  f"thread(s) anchored on this page")
        if counts["orphaned"]:
            detail += (f" ({counts['orphaned']} "
                       f"orphaned — the passage moved)")
        item["reasons"].append({
            "reason": "open-review-threads",
            "detail": detail,
            "due": None, "days_overdue": None})

    worklist = []
    for item in items.values():
        fields = parse_frontmatter(
            (root / item["page"]).read_text(
                encoding="utf-8", errors="ignore"))
        band = min(REASON_BAND.get(r["reason"], 3)
                   for r in item["reasons"])
        interval = _interval_for(fields, intervals)
        crec = census_by_page.get(item["page"]) or {}
        item.update({
            "priority": band,
            "review_state": crec.get("effective_state"),
            "declared_state": crec.get("declared_state"),
            "claim": _claim_annotation(fields),
            "sources": [str(s) for s in
                        _wv.as_list((fields or {}).get(
                            "sources"))],
            "next_due_if_reviewed_today":
                (today + timedelta(days=interval)).isoformat(),
            "next_due_basis": f"PROPOSED cadence {interval}d "
                              f"for type "
                              f"{(fields or {}).get('type')}",
        })
        worklist.append(item)
    # Stated ordering: priority band, then most-overdue
    # first (undated last within the band), then page path.
    worklist.sort(key=lambda e: (
        e["priority"],
        -(e["max_days_overdue"]
          if e["max_days_overdue"] is not None else -1),
        e["page"]))

    by_reason = {}
    for item in worklist:
        for r in item["reasons"]:
            by_reason[r["reason"]] = \
                by_reason.get(r["reason"], 0) + 1
    in_review = [p["page"] for p in census["pages"]
                 if p["effective_state"] == "in-review"]
    center = {
        "tool": "scripts/wiki_review_state.py",
        "kind": "review-center",
        "as_of": today.isoformat(),
        "ordering": "priority band (P1 attestation-expired / "
                    "reverify-overdue / pending-review-open / "
                    "review-record-invalid; P2 evidence-due / "
                    "source-changed / review-state-stale; P3 "
                    "the rest), then most-overdue first "
                    "(undated last), then page path",
        "cadence": queue_doc["cadence"],
        "census": {
            "population": census["population"],
            "by_declared": census["census"]["by_declared"],
            "by_effective": census["census"]["by_effective"],
            "findings": census["findings"],
        },
        "stats": {"worklist": len(worklist),
                  "by_reason": by_reason,
                  "in_review": len(in_review)},
        "worklist": worklist,
        "in_review": in_review,
        "history": _history(root, census["pages"], today),
    }
    return center


def build_ai_payload(center: dict):
    """The worklist shaped for an AI reviewer: one object
    per item, in worklist order."""
    out = []
    for item in center["worklist"]:
        out.append({
            "page": item["page"],
            "title": item["title"],
            "type": item["type"],
            "priority": item["priority"],
            "task": "Review this page against its cited "
                    "sources: confirm each claim still "
                    "matches its source, carry the sources' "
                    "conditions and limits, and record the "
                    "review in the page's review_state / "
                    "reviewed_on / reviewed_by frontmatter.",
            "reasons": item["reasons"],
            "review_state": item["review_state"],
            "claim": item["claim"],
            "check_against_sources": item["sources"],
            "last_change": item["last_change"],
            "next_due_if_reviewed_today":
                item["next_due_if_reviewed_today"],
        })
    return out


# -- rendering -----------------------------------------------------------------

def render_center_md(center: dict) -> str:
    pop = center["census"]["population"]
    lines = [
        "# Review Center", "",
        f"As of {center['as_of']} — generated by "
        f"`scripts/wiki_review_state.py` from the review "
        f"layer's queue, the pages' declared review state, "
        f"and the review registers. Report only: nothing "
        f"here marks a page reviewed.", "",
        "## Census", "",
        f"- Population: {pop['in_population']} pages "
        f"({pop['scanned']} scanned, "
        f"{pop['retired_excluded']} retired excluded)",
        f"- Carrying a declared review_state: "
        f"{pop['carrying_review_state']}",
        f"- By effective state: "
        + ", ".join(f"{k} {v}" for k, v in
                    sorted(center['census']['by_effective']
                           .items())),
        f"- Pages with an invalid review record: "
        f"{pop['with_findings']}", "",
        "## Worklist (priority, then most overdue, "
        "then path)", "",
    ]
    if not center["worklist"]:
        lines.append("Nothing is due. The queue is empty.")
    for item in center["worklist"]:
        overdue = (f"{item['max_days_overdue']}d overdue"
                   if item["max_days_overdue"] is not None
                   else "undated")
        lines.append(f"### P{item['priority']} — "
                     f"{item['page']} ({overdue})")
        for r in item["reasons"]:
            lines.append(f"- **{r['reason']}** — "
                         f"{r['detail']}")
        if item["claim"]:
            lines.append(f"- claim: {item['claim']['claim']} "
                         f"({item['claim']['outcome_status']})")
        lines.append(f"- if reviewed today, next due "
                     f"{item['next_due_if_reviewed_today']} "
                     f"({item['next_due_basis']})")
        lines.append("")
    hist = center["history"]
    lines += ["## Review history (from the registers)", ""]
    lines.append(f"- Owner attestations: "
                 f"{len(hist['owner_attestations'])}")
    for a in hist["owner_attestations"]:
        lines.append(f"  - {a['page']} — {a['state']} "
                     f"(verified_until {a['verified_until']})")
    lines.append(f"- Declared page reviews: "
                 f"{len(hist['declared_page_reviews'])}")
    for d in hist["declared_page_reviews"]:
        lines.append(f"  - {d['page']} — reviewed "
                     f"{d['reviewed_on']} by {d['reviewed_by']}")
    lines.append(f"- Re-verification events: "
                 f"{len(hist['reverify_events'])}")
    for e in hist["reverify_events"][:20]:
        lines.append(f"  - {e['date']} — {e['claim']}: "
                     f"{e['outcome']}")
    lines.append("")
    return "\n".join(lines)


# -- CLI -----------------------------------------------------------------------

def _dump(path: Path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False,
                               sort_keys=True, indent=1) + "\n",
                    encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Review-state census + Review Center")
    ap.add_argument("command", nargs="?", default="all",
                    choices=["all", "census", "center",
                             "payload", "check", "diff"])
    ap.add_argument("old", nargs="?")
    ap.add_argument("new", nargs="?")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--today")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    today = (parse_date(args.today) if args.today
             else date.today())
    if today is None:
        print("bad --today", file=sys.stderr)
        return 2
    root = args.root

    if args.command == "diff":
        if not args.old or not args.new:
            print("diff needs OLD and NEW census JSON paths",
                  file=sys.stderr)
            return 2
        old = json.loads(Path(args.old).read_text(
            encoding="utf-8"))
        new = json.loads(Path(args.new).read_text(
            encoding="utf-8"))
        jumps = diff_censuses(old, new)
        print(json.dumps({"illegal_transitions": jumps},
                         indent=1, sort_keys=True))
        return 1 if jumps else 0

    out_dir = args.out_dir or (root / "evaluation")
    if args.command in ("all", "census", "check"):
        census = build_census(root, today)
        if args.command == "check":
            print(json.dumps(
                {"population": census["population"],
                 "by_effective": census["census"]
                 ["by_effective"],
                 "findings": census["findings"]},
                indent=1, sort_keys=True))
            return 1 if census["findings"] else 0
        if args.json and args.command == "census":
            print(json.dumps(census, indent=1, sort_keys=True))
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            _dump(out_dir / "review-state-census.json", census)
            print(f"census: {census['population']} · "
                  f"effective {census['census']['by_effective']}")
        if args.command == "census":
            return 0
    if args.command in ("all", "center", "payload"):
        center = build_review_center(root, today)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.command in ("all", "center"):
            _dump(out_dir / "review-center.json", center)
            (out_dir / "review-center.md").write_text(
                render_center_md(center), encoding="utf-8")
            print(f"center: {center['stats']}")
        if args.command in ("all", "payload"):
            payload = build_ai_payload(center)
            (out_dir / "review-center-payload.jsonl").write_text(
                "".join(json.dumps(p, ensure_ascii=False,
                                   sort_keys=True) + "\n"
                        for p in payload), encoding="utf-8")
            print(f"payload: {len(payload)} item(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
