"""Phase-8 state-shaped views + Briefing honesty computations.

Consolidated build queue items 63 and 65 (wave-10 synthesis §3,
the surfaces build), computed at Lens build time from the wiki's real
registers — never from fixtures:

  63a  evidence_matrix()  — topics (frontmatter tags) × verification
       state over the compiled pages. An empty cell is a gap in the
       evidence, and the gap list IS the work list (EPPI Reviewer
       evidence-and-gap map; wave-7 surfaces find 5: mosaic squares,
       not bubbles — position/length/count encodings only).
  63b  lifecycle_paths()  — every lifecycle-bearing page's path so
       far, assembled from the registers that record lifecycle
       events (claim frontmatter, the citation lockfile, owner
       attestation, the treatment register, the severance register,
       supersession frontmatter, the re-verification history, the
       outcomes log), aggregated by shared prefix, LifeFlow-style
       (wave-7 surfaces find 3: aggregate by shared prefix, width =
       count, dead ends visible). Computed from the record, never
       narrated.
  63c  parse_argdown() / argdown_svg() — a small own parser for the
       Argdown subset our pages would use (see the subset spec in
       parse_argdown's docstring), compiled at build time to an
       inline SVG map. Nothing is vendored; Argdown itself is MIT
       (argdown.org) and this is an independent implementation of
       the documented syntax subset.
  65   lint_lane_series() — the per-lane headline counts from the
       nightly lint-lane filings, drawn as sparklines on ONE shared
       scale (wave-7 surfaces find 17: same scale always, numbers
       beside the marks).
       bullet geometry is computed here (zero baseline, target
       tick, declared qualitative bands — find 16) so the geometry
       is testable without a browser.
       due_forecast() — the re-verification schedule drawn with the
       overdue/due-now claims as a visible leading block, never
       excluded from the window (find 15, correcting Anki's Future
       Due flaw).
       ADMISSION_VERDICTS — the vanity-metrics admission rule
       (find 19: a metric joins the Briefing only if its movement
       would change a decision) applied to the metrics the Briefing
       currently shows, verdicts on the record.

Everything here is pure and deterministic: same registers in, same
artefact out. The WCAG numeric gate lives in wcag_gate.py; the
reading-profile calibration scoring lives in app.js (scoreCalibration)
and is exercised by the Phase-8 smoke lane.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

# ------------------------------------------------------------------
# 63a — evidence-and-gap matrix
# ------------------------------------------------------------------

# Display order for the columns. A page carries exactly ONE state:
# the strongest current signal about whether it can be trusted
# as-is. Precedence (first match wins):
#   superseded          — the record says it was replaced; citations
#                         do not rescue it.
#   owner-verified      — an owner attestation still in force.
#   re-verification-due — it sits on the FSRS due list today; its
#                         citations no longer guarantee standing.
#   cited               — it cites raw sources and nothing above
#                         applies.
#   unverified          — nothing vouches for it yet.
VERIFICATION_STATES = [
    "owner-verified",
    "cited",
    "re-verification-due",
    "superseded",
    "unverified",
]

STATE_NOTES = {
    "owner-verified": "An owner attestation (frontmatter verified_until, verified_by: owner) is still in force.",
    "cited": "The page cites at least one raw source and no stronger signal applies.",
    "re-verification-due": "The page is on the re-verification due list today (FSRS schedule, scripts/wiki_reverify.py).",
    "superseded": "Frontmatter marks the page superseded or deprecated, or names a superseded_by page.",
    "unverified": "No citation, attestation, or schedule vouches for this page yet.",
}

# What an empty cell means, per column — the gap is the work item.
GAP_MEANING = {
    "owner-verified": "no page on this topic carries an in-force owner attestation",
    "cited": "no page on this topic cites any raw source — the topic has no evidence base yet",
    "re-verification-due": "nothing on this topic is due for re-verification (no gap — a full cell here is the work)",
    "superseded": "nothing on this topic has been superseded (no gap — a full cell here is history)",
    "unverified": "every page on this topic is vouched for at some level (no gap)",
}
# Only these columns make an empty cell a work item; for the other
# two an empty cell is the healthy state and an entry would be the
# finding. The matrix shows all cells; the work list names only the
# real gaps.
GAP_COLUMNS = ("owner-verified", "cited")


def verification_state(page, due_paths, today_iso):
    """One page's verification state. `page` is a mapping with keys:
    status (frontmatter), superseded_by, attested_until (already
    build-validated: non-empty only while in force), sources_count,
    path (repo-relative). `due_paths` is the set of repo-relative
    paths on today's re-verification due list."""
    status = str(page.get("status") or "").lower()
    if status in ("superseded", "deprecated") or page.get("superseded_by"):
        return "superseded"
    if page.get("attested_until"):
        return "owner-verified"
    if page.get("path") in due_paths:
        return "re-verification-due"
    if (page.get("sources_count") or 0) > 0:
        return "cited"
    return "unverified"


def evidence_matrix(pages, due_paths, min_topic_pages=2):
    """Topics (tags) × verification state over `pages`.

    A page counts once in every topic row it is tagged with (the
    EPPI convention: a coded record sits in every row it is coded
    under), and once in the totals. Topics are tags carried by at
    least `min_topic_pages` pages; rarer tags are folded into the
    totals only, and the artefact says so."""
    totals = {s: [] for s in VERIFICATION_STATES}
    by_topic = {}
    untagged = []
    tag_counts = {}
    for pg in pages:
        state = verification_state(pg, due_paths, None)
        totals[state].append(pg["id"])
        tags = [str(t) for t in (pg.get("tags") or [])]
        if not tags:
            untagged.append(pg["id"])
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
            by_topic.setdefault(t, {s: [] for s in VERIFICATION_STATES})
            by_topic[t][state].append(pg["id"])
    topics = []
    folded = []
    for tag in sorted(by_topic, key=lambda t: (-tag_counts[t], t)):
        if tag_counts[tag] < min_topic_pages:
            folded.append(tag)
            continue
        cells = {s: sorted(ids) for s, ids in by_topic[tag].items()}
        topics.append({"topic": tag,
                       "total": sum(len(v) for v in cells.values()),
                       "cells": cells})
    gaps = []
    for row in topics:
        for state in GAP_COLUMNS:
            if not row["cells"][state]:
                gaps.append({"topic": row["topic"], "state": state,
                             "meaning": GAP_MEANING[state]})
    return {
        "states": VERIFICATION_STATES,
        "state_notes": STATE_NOTES,
        "topics": topics,
        "totals": {s: sorted(ids) for s, ids in totals.items()},
        "total_pages": len(pages),
        "untagged_pages": sorted(untagged),
        "folded_topics": sorted(folded),
        "gaps": gaps,
        "unverified_pages": sorted(totals["unverified"]),
        "due_pages": sorted(totals["re-verification-due"]),
    }


# ------------------------------------------------------------------
# 63b — claim histories aggregated by shared lifecycle prefix
# ------------------------------------------------------------------

# The lifecycle's canonical order. A page's path is its recorded
# events sorted by this order (registers give most events a date;
# the path is a sequence of STATES, and the order is the lifecycle's
# own definition — stated here, on the record, not smuggled in).
LIFECYCLE_ORDER = [
    "asserted",
    "cited",
    "attested",
    "treated-followed",
    "treated-questioned",
    "treated-caution",
    "treated-negative",
    "re-verification-due",
    "verification-failed",
    "verified",
    "outcome-recorded",
    "severed",
    "superseded",
]
_ORDER_IDX = {s: i for i, s in enumerate(LIFECYCLE_ORDER)}

# States in which a claim owes nothing further. A path ENDING in any
# other state is an open loop, and the view names it as one.
RESTING_STATES = {"attested", "verified", "superseded", "cited"}


def _read_jsonl(path):
    out = []
    p = Path(path)
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def lifecycle_events(repo, pages_by_path, due_map=None):
    """{repo-relative page path: [event, ...]} from the registers.

    Event = {"state", "date" (iso or None), "source" (the register
    or frontmatter the event was read from), "detail"}. Only events
    the record actually states are emitted — nothing is inferred
    from prose. `due_map` = lenslib.freshness_due_map's output
    ({path: {"due", "status"}}): a page on today's due list carries
    the re-verification-due state, dated with its due date."""
    repo = Path(repo)
    events = {}

    def add(path, state, when, source, detail=""):
        if not path:
            return
        events.setdefault(path, []).append(
            {"state": state, "date": when, "source": source,
             "detail": detail})

    # Claim pages: asserted (claim frontmatter) + owner attestation.
    for path, info in pages_by_path.items():
        fm = info.get("fm") or {}
        if fm.get("claim"):
            add(path, "asserted",
                str(fm.get("as_of") or fm.get("created") or "") or None,
                "frontmatter claim:",
                str(fm.get("claim"))[:120])
        if info.get("attested_until"):
            add(path, "attested", None,
                "frontmatter verified_until (verified_by: owner)",
                f"in force until {info['attested_until']}")

    # Locked citations (claim-level citation lockfile).
    lock_path = repo / "evaluation" / "citation-lockfile.json"
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            lock = {}
        cited_pages = sorted({c.get("page") for c in lock.get("citations", [])
                              if c.get("page")})
        for path in cited_pages:
            add(path, "cited", None,
                "evaluation/citation-lockfile.json",
                "carries at least one locked claim-level citation")

    # Treatment register (Shepard's-style signals on pages/claims).
    for e in _read_jsonl(repo / "evaluation" / "treatment-register.jsonl"):
        if e.get("kind") != "treatment":
            continue
        subj = e.get("subject") or {}
        grade = str(e.get("grade") or "").lower()
        if grade in ("followed", "questioned", "caution", "negative"):
            add(subj.get("page"), f"treated-{grade}", e.get("date"),
                f"evaluation/treatment-register.jsonl {e.get('id', '')}".strip(),
                str(subj.get("claim") or "")[:120])

    # Severance register (retrieval cues cut).
    sev_path = repo / "evaluation" / "retrieval-severance.json"
    if sev_path.exists():
        try:
            sev = json.loads(sev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sev = {}
        for e in sev.get("entries", []):
            src = e.get("source") or {}
            add(e.get("page"), "severed", None,
                "evaluation/retrieval-severance.json "
                f"{e.get('id', '')} (from {src.get('register', '?')} "
                f"line {src.get('line', '?')})",
                str(e.get("claim") or "")[:120])

    # Supersession frontmatter.
    for path, info in pages_by_path.items():
        fm = info.get("fm") or {}
        status = str(fm.get("status") or "").lower()
        if status in ("superseded", "deprecated") or fm.get("superseded_by"):
            add(path, "superseded", None, "frontmatter status/superseded_by",
                str(fm.get("superseded_by") or status))

    # Re-verification history (FSRS events on claims).
    for e in _read_jsonl(repo / "evaluation" / "reverify-history.jsonl"):
        outcome = str(e.get("outcome") or "").lower()
        if outcome == "pass":
            add(e.get("claim"), "verified", e.get("date"),
                "evaluation/reverify-history.jsonl", "re-verification passed")
        elif outcome in ("fail", "changed"):
            add(e.get("claim"), "verification-failed", e.get("date"),
                "evaluation/reverify-history.jsonl",
                f"re-verification outcome: {outcome}")

    # Outcomes log (real-world results recorded against claims).
    for e in _read_jsonl(repo / "evaluation" / "outcomes.jsonl"):
        page = e.get("page") or e.get("claim_page")
        if page:
            add(page, "outcome-recorded", e.get("date") or e.get("recorded"),
                "evaluation/outcomes.jsonl",
                str(e.get("outcome") or e.get("result") or "")[:120])

    # Re-verification due state (today's schedule).
    for path, due in (due_map or {}).items():
        add(path, "re-verification-due", due.get("due"),
            "re-verification schedule (scripts/wiki_reverify.py; "
            "lenslib.freshness_due_map mirror)",
            f"status {due.get('status')} — due {due.get('due')}")

    # Enrichment, not creation: a page already carrying a lifecycle
    # record that also cites raw sources in its frontmatter gains
    # the cited state from that frontmatter. (Sources alone do not
    # open a lifecycle record — the record opens with a claim, a
    # treatment, a severance, an attestation, or the schedule.)
    for path in list(events):
        info = pages_by_path.get(path) or {}
        fm = info.get("fm") or {}
        srcs = fm.get("sources") or []
        if srcs and not any(e["state"] == "cited" for e in events[path]):
            add(path, "cited", None, "frontmatter sources:",
                f"{len(srcs) if isinstance(srcs, list) else 1} raw "
                "source(s) cited at page level")
    return events


def lifecycle_paths(repo, pages_by_path, id_by_path, due_map=None):
    """Aggregate the lifecycle events into per-page paths and a
    shared-prefix table. Returns {"records": [...], "prefixes":
    [...], "open_loops": [...]} — records carry the full event list
    so every step of every path can be audited back to its register
    line."""
    raw = lifecycle_events(repo, pages_by_path, due_map)
    records = []
    for path in sorted(raw):
        evs = sorted(raw[path],
                     key=lambda e: (_ORDER_IDX.get(e["state"], 99),
                                    e["date"] or ""))
        path_states = []
        for e in evs:
            if not path_states or path_states[-1] != e["state"]:
                path_states.append(e["state"])
        records.append({
            "page": id_by_path.get(path, path),
            "path_rel": path,
            "states": path_states,
            "events": evs,
            "terminal": path_states[-1] if path_states else None,
            "open_loop": bool(path_states)
            and path_states[-1] not in RESTING_STATES,
        })
    # Shared-prefix aggregation (LifeFlow): every prefix of every
    # path, with the count of records passing through it.
    pref = {}
    for rec in records:
        states = rec["states"]
        for i in range(1, len(states) + 1):
            key = tuple(states[:i])
            node = pref.setdefault(key, {"through": [], "terminal": []})
            node["through"].append(rec["page"])
            if i == len(states):
                node["terminal"].append(rec["page"])
    prefixes = []
    for key in sorted(pref, key=lambda k: (len(k), -len(pref[k]["through"]), k)):
        node = pref[key]
        prefixes.append({
            "prefix": list(key),
            "count": len(node["through"]),
            "pages": sorted(node["through"]),
            "terminal_count": len(node["terminal"]),
            "terminal_pages": sorted(node["terminal"]),
        })
    return {
        "order": LIFECYCLE_ORDER,
        "resting_states": sorted(RESTING_STATES),
        "records": records,
        "prefixes": prefixes,
        "open_loops": [r["page"] for r in records if r["open_loop"]],
        "record_count": len(records),
    }


# ------------------------------------------------------------------
# 63c — Argdown subset parser + SVG compiler (own implementation)
# ------------------------------------------------------------------

_NODE_RE = re.compile(r"^\s*(?:[-*]\s*)?(\[[^\]]+\]|<[^>]+>)\s*(.*)$")
_REL_RE = re.compile(
    r"^\s*(\[[^\]]+\]|<[^>]+>)\s*(\+|-|\+>|->)\s*(\[[^\]]+\]|<[^>]+>)\s*(.*)$")


def _node_key(token):
    return token[1:-1].strip()


def parse_argdown(text):
    """Parse the Argdown subset our pages would use.

    Supported subset (stated, deliberately small):
      * Statement declarations:  [Title] optionally followed on the
        same line or the lines below by description text, and by
        #tags and {key: value} metadata, which are carried through.
      * Argument declarations:   <Title> likewise.
      * Relation lines:          A + B   (A supports B)
                                 A - B   (A attacks B)
        where A and B are [statement] or <argument> references.
        The long forms +> and -> are accepted as support / attack.
      * Blank lines separate blocks. Anything else non-empty is
        returned in `unparsed`, never silently dropped.

    Returns {"statements": [...], "arguments": [...],
             "relations": [{"from","to","kind"}], "unparsed": [...],
             "warnings": [...]}. Nodes referenced but never declared
    are created implicitly and named in `warnings`."""
    statements, arguments, relations = {}, {}, []
    unparsed, warnings = [], []
    current = None  # (kind, key) currently collecting description

    def declare(token, rest):
        kind = "statement" if token.startswith("[") else "argument"
        key = _node_key(token)
        table = statements if kind == "statement" else arguments
        node = table.setdefault(key, {"name": key, "kind": kind,
                                      "text": "", "tags": [],
                                      "meta": {}})
        if rest:
            node["text"] = (node["text"] + " " + rest).strip()
        return kind, key

    for raw in str(text).splitlines():
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        m = _REL_RE.match(line)
        if m:
            a, op, b, _rest = m.groups()
            kind = "support" if op in ("+", "+>") else "attack"
            relations.append({"from": _node_key(a), "to": _node_key(b),
                              "kind": kind})
            current = None
            continue
        m = _NODE_RE.match(line)
        if m:
            token, rest = m.groups()
            current = declare(token, rest)
            continue
        if current:
            kind, key = current
            table = statements if kind == "statement" else arguments
            node = table[key]
            for tag in re.findall(r"#([A-Za-z0-9_-]+)", line):
                if tag not in node["tags"]:
                    node["tags"].append(tag)
            for k, v in re.findall(r"\{(\w+):\s*([^}]+)\}", line):
                node["meta"][k] = v.strip()
            node["text"] = (node["text"] + " " + line.strip()).strip()
            continue
        unparsed.append(line.strip())

    known = set(statements) | set(arguments)
    for rel in relations:
        for end in (rel["from"], rel["to"]):
            if end not in known:
                warnings.append(f"relation references undeclared node {end!r}; "
                                "created implicitly as a statement")
                statements[end] = {"name": end, "kind": "statement",
                                   "text": "", "tags": [], "meta": {},
                                   "implicit": True}
                known.add(end)
    return {"statements": [statements[k] for k in sorted(statements)],
            "arguments": [arguments[k] for k in sorted(arguments)],
            "relations": relations,
            "unparsed": unparsed,
            "warnings": warnings}


def _wrap(text, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def argdown_svg(model, width=720):
    """Compile a parsed Argdown model to a deterministic inline SVG.

    Layout: supporters sit BELOW the node they support (premises
    under conclusions, the standard argument-map reading). Rank =
    longest path over the relation graph; cycles are broken
    deterministically by name order and reported in the returned
    warnings. Encoding is position + labelled +/- edge markers
    only — no area or angle encodes a quantity (Cairo gate)."""
    nodes = {n["name"]: n for n in model["statements"] + model["arguments"]}
    names = sorted(nodes)
    if not names:
        return "", ["empty argument map"]
    # rank: a node ranks above everything that supports/attacks it.
    rank = {n: 0 for n in names}
    warnings = []
    for _ in range(len(names) + 1):
        changed = False
        for rel in model["relations"]:
            want = rank[rel["from"]] + 1
            if rank[rel["to"]] < want:
                rank[rel["to"]] = want
                changed = True
        if not changed:
            break
    else:
        warnings.append("relation graph contains a cycle; ranks are "
                        "best-effort by name order")
    by_rank = {}
    for n in names:
        by_rank.setdefault(rank[n], []).append(n)
    max_rank = max(by_rank)
    char_w, line_h, pad = 7.2, 15, 8
    boxes = {}
    # Box widths from wrapped titles; rows laid out left to right.
    row_y = {}
    y = pad
    for r in range(max_rank, -1, -1):
        row = by_rank.get(r, [])
        x = pad
        row_h = 0
        for n in row:
            lines = _wrap(n, 26)
            w = max(len(l) for l in lines) * char_w + 2 * pad
            h = len(lines) * line_h + 2 * pad
            boxes[n] = {"x": x, "y": y, "w": w, "h": h, "lines": lines,
                        "kind": nodes[n]["kind"]}
            x += w + 28
            row_h = max(row_h, h)
        row_y[r] = y
        y += row_h + 46
    total_w = max(b["x"] + b["w"] for b in boxes.values()) + pad
    total_h = y - 46 + pad
    out = [f'<svg viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
           f'width="{min(width, total_w):.0f}" role="img" '
           f'aria-label="Argument map" xmlns="http://www.w3.org/2000/svg">']
    for rel in model["relations"]:
        a, b = boxes[rel["from"]], boxes[rel["to"]]
        x1, y1 = a["x"] + a["w"] / 2, a["y"]
        x2, y2 = b["x"] + b["w"] / 2, b["y"] + b["h"]
        colour = "#5FA88F" if rel["kind"] == "support" else "#D95D4E"
        glyph = "+" if rel["kind"] == "support" else "−"
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" '
                   f'y2="{y2:.0f}" stroke="{colour}" stroke-width="1.6"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append(f'<circle cx="{mx:.0f}" cy="{my:.0f}" r="8" '
                   f'fill="#171512" stroke="{colour}"/>'
                   f'<text x="{mx:.0f}" y="{my + 4:.0f}" fill="{colour}" '
                   f'font-size="12" text-anchor="middle">{glyph}</text>')
    for n in names:
        b = boxes[n]
        dash = ' stroke-dasharray="4 3"' if b["kind"] == "argument" else ""
        out.append(f'<rect x="{b["x"]:.0f}" y="{b["y"]:.0f}" '
                   f'width="{b["w"]:.0f}" height="{b["h"]:.0f}" rx="6" '
                   f'fill="#1F1C17" stroke="#454034"{dash}/>')
        for i, ln in enumerate(b["lines"]):
            out.append(f'<text x="{b["x"] + b["w"] / 2:.0f}" '
                       f'y="{b["y"] + pad + 12 + i * line_h:.0f}" '
                       f'fill="#F2EEE6" font-size="12.5" '
                       f'text-anchor="middle">{html.escape(ln)}</text>')
    out.append("</svg>")
    return "".join(out), warnings


# ------------------------------------------------------------------
# 65 — lint-lane series + same-scale sparklines
# ------------------------------------------------------------------

# Lane definitions: (key, filing-summary label, what the headline
# number is). The headline metric is stated per lane because the
# honesty is in knowing what the number counts.
LANES = [
    ("contradictions", "Contradictions", "observation candidates"),
    ("stale", "Stale", "pages semantically marked replaced or retired"),
    ("missing", "Missing", "broken-wikilink + orphan lines (validator)"),
    ("leaks", "Leaks", "NEW leak findings this run (baselined findings excluded)"),
    ("quotes", "Quotes", "divergent quotations"),
    ("decision_gate", "Decision gate", "live references to superseded decision forms"),
]

_SUMMARY_RES = {
    "contradictions": re.compile(r"contradictions\s+(\d+)"),
    "stale": re.compile(r"stale\s+(\d+)"),
    "missing": re.compile(r"missing\s+(\d+)"),
    # Leaks counts NEW findings only, and only in the current
    # summary format ("leaks 2 new (185 baselined ...)"). The
    # 2026-10-19 filing predates the baseline system and reports a
    # total ("leaks 187"); mixing the two would lie by shape, so a
    # filing without the "new" form contributes no leaks point.
    "leaks": re.compile(r"leaks\s+(\d+)\s+new"),
    "quotes": re.compile(r"quotes\s+\d+\s+checked,\s*(\d+)\s+divergent"),
    "decision_gate": re.compile(r"decision gate\s+(\d+)\s+live"),
}


def lint_lane_series(repo):
    """Parse the dated lint-lane filings under wiki/filings/ into
    per-lane time series. A lane's series starts when the lane (and
    its current metric) starts — filings that predate a lane's
    format contribute no point for it, and the artefact says which
    filings were used."""
    filings_dir = Path(repo) / "wiki" / "filings"
    used, skipped = [], []
    per_lane = {k: [] for k, _lbl, _m in LANES}
    if filings_dir.exists():
        for f in sorted(filings_dir.glob("lint-lanes-*.md")):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
            if not m:
                skipped.append(f.name)
                continue
            day = m.group(1)
            summary = ""
            for ln in f.read_text(encoding="utf-8",
                                  errors="ignore").splitlines():
                if ln.startswith("Summary:"):
                    summary = ln
                    break
            if not summary:
                skipped.append(f.name)
                continue
            used.append(f.name)
            for key, rx in _SUMMARY_RES.items():
                mm = rx.search(summary)
                if mm:
                    per_lane[key].append({"date": day,
                                          "value": int(mm.group(1))})
    series = []
    shared_max = 1
    for key, label, metric in LANES:
        pts = sorted(per_lane[key], key=lambda p: p["date"])
        for p in pts:
            shared_max = max(shared_max, p["value"])
        series.append({"lane": key, "label": label, "metric": metric,
                       "points": pts})
    return {"series": series, "shared_max": shared_max,
            "filings_used": used, "filings_skipped": skipped,
            "scale_note": "All six sparklines share one scale "
                          f"(0–{shared_max}); different scales per lane "
                          "would lie by shape."}


def sparkline_points(values, shared_max, width=100, height=28, pad=2):
    """Polyline points for `values` on the SHARED scale. The scale
    maximum is an input, never derived from the series itself —
    that is the whole honesty of the thing. A single point renders
    as a dot pair (a line needs two points; one filing is a dot,
    stated as such in the view)."""
    if not values:
        return ""
    top = max(1, shared_max)
    span_w = width - 2 * pad
    span_h = height - 2 * pad
    if len(values) == 1:
        xs = [width / 2]
    else:
        xs = [pad + i * span_w / (len(values) - 1)
              for i in range(len(values))]
    pts = []
    for x, v in zip(xs, values):
        y = pad + span_h * (1 - v / top)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


# ------------------------------------------------------------------
# 65 — bullet graphs (geometry computed here, drawn by the client)
# ------------------------------------------------------------------

def bullet_geometry(value, target, scale_max, bands):
    """Stephen Few bullet geometry on a zero-based scale.

    `bands` = [{"to": <value at band end>, "label": str,
    "tone": "good"|"watch"|"bad"}] covering [0, scale_max] in
    order. Returns fractions of the scale so the client draws
    without re-deriving anything. Bars start at zero — there is
    no other honest start for a length encoding (Cairo gate)."""
    top = max(scale_max, value, target, 1e-9)

    def frac(v):
        return round(min(1.0, max(0.0, v / top)), 4)

    out_bands = []
    prev = 0.0
    for b in bands:
        end = frac(b["to"])
        out_bands.append({"from": prev, "to": end, "label": b["label"],
                          "tone": b["tone"]})
        prev = end
    if out_bands:
        out_bands[-1]["to"] = 1.0
    return {"value_frac": frac(value), "target_frac": frac(target),
            "scale_max": top, "bands": out_bands}


# ------------------------------------------------------------------
# 65 — re-verification due forecast (overdue never excluded)
# ------------------------------------------------------------------

def due_forecast(schedule, today, window_days=90):
    """Draw the re-verification schedule honestly.

    `schedule` = scripts/wiki_reverify.due_claims(today) rows:
    {"page", "claim", "due" (iso), "status", "days_overdue"}.
    Claims already due (status overdue or due today) form the
    leading DUE NOW block — Anki's Future Due drops exactly these
    from its window, which is the flaw this corrects. Upcoming
    claims are bucketed by ISO week; the do-nothing scenario is
    the cumulative line: if nothing is verified, the due pile only
    grows. The forecast covers the current schedule only — a claim
    verified today re-enters later by its own stability, which
    this view does not project, and the artefact says so."""
    def _iso(value):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    due_now, upcoming = [], []
    for row in schedule:
        row = dict(row)
        row["due"] = _iso(row["due"])
        if row.get("status") in ("overdue", "due"):
            due_now.append({"page": row["page"], "claim": row["claim"],
                            "due": row["due"],
                            "days_overdue": row.get("days_overdue", 0),
                            "status": row["status"]})
        else:
            upcoming.append(row)
    due_now.sort(key=lambda r: (r["due"], r["page"]))
    end = today + timedelta(days=window_days)
    weeks = []
    cursor = today + timedelta(days=1)
    while cursor <= end:
        wk_end = min(end, cursor + timedelta(days=6))
        count = sum(1 for r in upcoming
                    if cursor.isoformat() <= r["due"] <= wk_end.isoformat())
        weeks.append({"from": cursor.isoformat(),
                      "to": wk_end.isoformat(), "due_count": count})
        cursor = wk_end + timedelta(days=1)
    cumulative, running = [], len(due_now)
    for w in weeks:
        running += w["due_count"]
        cumulative.append(running)
    return {
        "today": today.isoformat(),
        "window_days": window_days,
        "due_now": due_now,
        "due_now_count": len(due_now),
        "overdue_count": sum(1 for r in due_now
                             if r["status"] == "overdue"),
        "weeks": weeks,
        "cumulative_if_neglected": cumulative,
        "total_scheduled": len(schedule),
        "note": "The DUE NOW block is part of the window, never "
                "excluded from it. The forecast covers the current "
                "schedule only: a claim verified today re-enters "
                "later by its own stability (FSRS), which this view "
                "does not project.",
    }


# ------------------------------------------------------------------
# 65 — the vanity-metrics admission rule, applied on the record
# ------------------------------------------------------------------

# The rule (wave-7 surfaces find 19): a metric joins the Briefing
# only if it can change a decision — the test is "if this number
# moved 20%, what would I do?" Counts that can only grow are
# vanity as health signals; they may stay as CONTEXT, labelled as
# context, and the actionable numbers (rates, due counts, open
# cases, gate distances) carry the Briefing's health section.
ADMISSION_RULE = ("A metric is admitted as a Briefing health signal "
                  "only if its movement would change a decision — "
                  "the test: 'if this moved 20%, what would I do?' "
                  "A count that can only grow answers 'nothing' and "
                  "is demoted to context, labelled as context.")

ADMISSION_VERDICTS = [
    {"metric": "Pages", "briefing_key": "pages", "verdict": "context",
     "reason": "Cumulative corpus size. A 20% jump changes no "
               "decision; page count cannot go down. Orientation "
               "only."},
    {"metric": "Raw sources", "briefing_key": "raw_files",
     "verdict": "context",
     "reason": "Provenance inventory size (with its MB). Cumulative; "
               "growth is the ingest rule working, not a signal."},
    {"metric": "Decisions decided", "briefing_key": "decisions_decided",
     "verdict": "context",
     "reason": "Register size. The actionable form of this number "
               "is decisions awaiting a ruling, which the Briefing "
               "already lists under 'Waiting on you'."},
    {"metric": "Log entries", "briefing_key": "log_entries",
     "verdict": "context",
     "reason": "Activity volume. More entries is not better or "
               "worse; nothing is decided from it."},
    {"metric": "Graph edges", "briefing_key": "edges",
     "verdict": "context",
     "reason": "Link count grows with the corpus. The actionable "
               "forms — orphans, broken targets — are lint counts "
               "and appear as bullets, not as this total."},
]
