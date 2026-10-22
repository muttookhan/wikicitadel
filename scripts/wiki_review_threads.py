#!/usr/bin/env python3
"""wiki_review_threads.py — anchored review threads
(implementation wave 2026-10-22, wave 6; build-list item
"Anchored review threads + A2A handoff vocabulary and
agent cards").

Clean re-implementation. Idea sources (ideas only, no
code taken): GitWarren (GPL-3.0+ — review comments
anchored to the content under review, surviving edits or
flagged on drift; the build list's licence route for this
item is clean re-implementation) and this wiki's own Lens
margin notes (Build-list W2, 2026-10-22), whose W3C Web
Annotation anchoring model this tool REUSES verbatim in
discipline — the same selectors, the same resolution
rule, ported to the repo side. No service is contacted;
there is no network path anywhere in this file.

THE STORE. Threads live in the append-only register
evaluation/review-threads.jsonl (created by the first
thread filed, header line first — the standing-queries
precedent: absence is the honest empty state, never a
seeded example). Three record kinds:

  {"kind": "thread", "id": "rt-000001",
   "page": "wiki/concepts/x.md",
   "anchor": null | {"source": "wiki/concepts/x.md",
             "selector": [TextQuoteSelector,
                          TextPositionSelector,
                          FragmentSelector]},
   "opened_by": "<who>", "opened_on": "YYYY-MM-DD",
   "note": "why this thread was opened"}

  {"kind": "reply", "id": "rr-000001",
   "thread": "rt-000001", "by": "<who>",
   "on": "YYYY-MM-DD", "body": "..."}

  {"kind": "resolution", "id": "rs-000001",
   "thread": "rt-000001", "by": "<who>",
   "on": "YYYY-MM-DD", "note": "what resolved it"}

STATE IS DERIVED, NEVER ASSERTED (the handoff register's
closure rule): a thread is resolved iff a resolution
record for it stands in the register; a thread record
carrying a "state"/"status" field is a finding
(state-asserted-not-derived). A thread resolves ONLY by
that recorded act — who resolved it, when, and what the
resolution was are the record's own fields. Replies to a
resolved thread are findings (reply-after-resolution).

ANCHORING — the margin-notes model, unchanged. The
anchor text is the page BODY (frontmatter stripped),
whitespace-normalised by the Lens rule (every whitespace
run collapses to one space). Selectors are built at open
time from the quote the opener supplies: the quote must
occur EXACTLY ONCE in the normalised body (0 -> refused
quote-not-found; >1 -> refused quote-ambiguous, with the
count — widen the quote). Resolution of a stored anchor
against today's body, exactly as marginResolve:
  - at the stored offsets            -> anchored
  - found once elsewhere, or once its
    stored prefix/suffix context is
    applied to the repeats            -> moved
  - gone, or ambiguous                -> ORPHANED
An orphaned thread keeps its quoted words on its face
(the artefact and the rendered view print them) and is
attached to nothing. It is never silently re-anchored
to different words. A thread with anchor null is a
page-level thread (state "page").

SURFACING. The Review Center consumes this register
(scripts/wiki_review_state.py calls open_threads_by_page
in-process): a page with open threads — orphaned ones
included, the discussion is unresolved and its passage
has moved — is worklisted with the count. Zero threads
adds nothing to the Center's artefacts, byte for byte.
A thread whose disagreement must not be smoothed over
graduates to a talk page (AGENTS.md, "Disputes: talk
pages"); threads are the review machinery, talk pages
are the dispute record — this tool files no talk pages.

DETERMINISM: no wall clock anywhere. Dates are the
caller's recorded acts (opened_on / on), ids are the
caller's or the next free sequence number in the
register, and every artefact is a pure function of the
register + the corpus as it stands.

Usage:
  python3 scripts/wiki_review_threads.py template
  python3 scripts/wiki_review_threads.py open REC.json
  python3 scripts/wiki_review_threads.py reply REC.json
  python3 scripts/wiki_review_threads.py resolve REC.json
  python3 scripts/wiki_review_threads.py check [--json]
  python3 scripts/wiki_review_threads.py census [--json]
  python3 scripts/wiki_review_threads.py render
      [--out-dir DIR]
  (all take [--root DIR])

Exit codes: 0 done / no findings · 1 findings or a
refused act · 2 usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote as urlquote

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
REGISTER_REL = "evaluation/review-threads.jsonl"

THREAD_ID = re.compile(r"^rt-\d{6}$")
REPLY_ID = re.compile(r"^rr-\d{6}$")
RESOLUTION_ID = re.compile(r"^rs-\d{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SELECTOR_TYPES = ("TextQuoteSelector", "TextPositionSelector",
                  "FragmentSelector")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wv = _load("wiki_validate")
parse_date = _wv.parse_date


# -- the margin-notes anchoring model, ported -------------------------------

def normalize_text(s: str) -> str:
    """The Lens margin-notes normalisation, verbatim in
    effect: every whitespace run collapses to one space."""
    return re.sub(r"\s+", " ", str(s))


def selectors_for(norm: str, start: int, end: int):
    """The selector set marginSelectorsFor builds for a
    passage at [start, end) of the normalised text."""
    exact = norm[start:end]
    return [
        {"type": "TextQuoteSelector", "exact": exact,
         "prefix": norm[max(0, start - 32):start],
         "suffix": norm[end:end + 32]},
        {"type": "TextPositionSelector",
         "start": start, "end": end},
        {"type": "FragmentSelector",
         "conformsTo": "https://www.w3.org/TR/media-frags/",
         "value": ":~:text=" + urlquote(
             exact, safe="-_.!~*'()")},
    ]


def find_quote(norm: str, quote: str):
    """Every start offset of quote in norm (the JS scan
    steps one character past each hit, as here)."""
    hits, i = [], norm.find(quote)
    while i >= 0:
        hits.append(i)
        i = norm.find(quote, i + 1)
    return hits


def resolve_anchor(anchor, norm: str):
    """marginResolve, ported state for state. Returns
    {"state": page|anchored|moved|orphaned, start, end}.
    anchor None (a page-level thread) -> page."""
    if not anchor:
        return {"state": "page", "start": None, "end": None}
    sels = anchor.get("selector") or []
    if not sels:
        return {"state": "page", "start": None, "end": None}
    quote = None
    pos = None
    for s in sels:
        if s.get("type") == "TextQuoteSelector":
            quote = s.get("exact") or ""
        elif s.get("type") == "TextPositionSelector":
            pos = s
    if not quote and not pos:
        # Selectors exist but none is a text selector this
        # surface resolves: carried verbatim, page-level.
        return {"state": "page", "start": None, "end": None}
    if quote:
        if pos and norm[pos["start"]:pos["end"]] == quote:
            return {"state": "anchored",
                    "start": pos["start"], "end": pos["end"]}
        hits = find_quote(norm, quote)
        if not hits:
            return {"state": "orphaned",
                    "start": None, "end": None}
        if len(hits) == 1:
            return {"state": "moved", "start": hits[0],
                    "end": hits[0] + len(quote)}
        q = next(s for s in sels
                 if s.get("type") == "TextQuoteSelector")
        prefix, suffix = q.get("prefix") or "", \
            q.get("suffix") or ""
        ctx = [h for h in hits
               if norm[max(0, h - len(prefix)):h]
               .endswith(prefix)
               and norm[h + len(quote):
                        h + len(quote) + len(suffix)]
               == suffix]
        if len(ctx) == 1:
            return {"state": "moved", "start": ctx[0],
                    "end": ctx[0] + len(quote)}
        return {"state": "orphaned",
                "start": None, "end": None}
    if pos and 0 <= pos["start"] < pos["end"] <= len(norm):
        return {"state": "anchored",
                "start": pos["start"], "end": pos["end"]}
    return {"state": "orphaned", "start": None, "end": None}


def anchor_quote(anchor):
    """The quoted words an anchor carries, or None."""
    if not anchor:
        return None
    for s in anchor.get("selector") or []:
        if s.get("type") == "TextQuoteSelector":
            return s.get("exact")
    return None


# -- the register -------------------------------------------------------------

def register_path(root: Path) -> Path:
    return root / REGISTER_REL


def load_register(root: Path):
    """(present, records, problems). Absence is the
    honest empty state: present False, no records, no
    problems. Problems name malformed lines by number."""
    path = register_path(root)
    if not path.is_file():
        return False, [], []
    records, problems = [], []
    for n, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append({"line": n,
                             "finding": "bad-json",
                             "detail": str(e)})
            continue
        if not isinstance(rec, dict):
            problems.append({"line": n,
                             "finding": "not-an-object",
                             "detail": "register line is not "
                                       "a JSON object"})
            continue
        if rec.get("kind") == "header":
            continue
        records.append(rec)
    return True, records, problems


def _append(root: Path, rec: dict):
    path = register_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False,
                      sort_keys=True) + "\n"
    if not path.is_file():
        header = {"kind": "header",
                  "register": "review-threads", "version": 1,
                  "purpose": "Anchored review threads "
                             "(scripts/wiki_review_threads"
                             ".py): discussion anchored to "
                             "page passages; state derived "
                             "by the checker, never "
                             "asserted. Append-only."}
        path.write_text(
            json.dumps(header, ensure_ascii=False,
                       sort_keys=True) + "\n" + line,
            encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def _next_id(records, kind, prefix, pattern):
    top = 0
    for rec in records:
        if rec.get("kind") == kind and \
                pattern.match(str(rec.get("id") or "")):
            top = max(top, int(rec["id"].split("-")[1]))
    return f"{prefix}-{top + 1:06d}"


def page_body(root: Path, page: str):
    """The page's normalised BODY text (frontmatter
    stripped — the prose a reader reads), or None when
    the page does not exist."""
    path = root / page
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    _fields, body = _wv.parse_frontmatter(text)
    return normalize_text(body)


# -- derivation + validation ---------------------------------------------------

def derive_threads(records):
    """Fold the register into threads. Returns
    (threads, findings): threads keyed by id, each with
    its replies and its resolution (or None); findings
    name every malformed or out-of-order record."""
    threads, findings = {}, []
    seen_ids = set()

    def note(rec, finding, detail):
        findings.append({"id": rec.get("id"),
                         "kind": rec.get("kind"),
                         "finding": finding,
                         "detail": detail})

    for rec in records:
        kind = rec.get("kind")
        rid = rec.get("id")
        if kind not in ("thread", "reply", "resolution"):
            note(rec, "unknown-record-kind",
                 f"kind {kind!r} is not thread / reply / "
                 f"resolution")
            continue
        if rid in seen_ids:
            note(rec, "duplicate-id",
                 f"id {rid} appears more than once")
            continue
        seen_ids.add(rid)
        if kind == "thread":
            if not THREAD_ID.match(str(rid or "")):
                note(rec, "bad-id",
                     "thread id must be rt-NNNNNN")
            if "state" in rec or "status" in rec:
                note(rec, "state-asserted-not-derived",
                     "thread state is derived from the "
                     "resolution records, never asserted "
                     "on the thread record")
            page = rec.get("page")
            if not page or not str(page).startswith(
                    "wiki/") or not str(page).endswith(".md"):
                note(rec, "bad-page",
                     "page must be a repo-relative wiki/ "
                     "....md path")
            if not rec.get("opened_by"):
                note(rec, "missing-field:opened_by",
                     "a thread names who opened it")
            if not DATE_RE.match(str(
                    rec.get("opened_on") or "")):
                note(rec, "missing-field:opened_on",
                     "opened_on must be YYYY-MM-DD (the "
                     "recorded act's date, caller-supplied)")
            anchor = rec.get("anchor")
            if anchor is not None:
                if not isinstance(anchor, dict) or \
                        not isinstance(
                            anchor.get("selector"), list):
                    note(rec, "bad-anchor",
                         "anchor must be null or carry a "
                         "selector list")
                else:
                    for s in anchor["selector"]:
                        if s.get("type") not in \
                                SELECTOR_TYPES:
                            note(rec, "unknown-selector:"
                                 f"{s.get('type')}",
                                 "selector types are the "
                                 "margin-notes set")
                        elif s["type"] == \
                                "TextQuoteSelector" and \
                                not s.get("exact"):
                            note(rec, "bad-anchor",
                                 "a TextQuoteSelector "
                                 "carries its exact words")
            threads[rid] = {
                "id": rid, "page": page,
                "anchor": anchor,
                "opened_by": rec.get("opened_by"),
                "opened_on": rec.get("opened_on"),
                "note": rec.get("note"),
                "replies": [], "resolution": None}
        elif kind == "reply":
            if not REPLY_ID.match(str(rid or "")):
                note(rec, "bad-id",
                     "reply id must be rr-NNNNNN")
            target = threads.get(rec.get("thread"))
            if target is None:
                note(rec, "unknown-thread",
                     f"reply names thread "
                     f"{rec.get('thread')!r}, which does "
                     f"not stand earlier in the register")
                continue
            for field in ("by", "on", "body"):
                if not rec.get(field):
                    note(rec, f"missing-field:{field}",
                         f"a reply carries {field}")
            if rec.get("on") and not DATE_RE.match(
                    str(rec["on"])):
                note(rec, "missing-field:on",
                     "on must be YYYY-MM-DD")
            if target["resolution"] is not None:
                note(rec, "reply-after-resolution",
                     "the thread already stands resolved; "
                     "a further point opens a new thread")
            target["replies"].append(rec)
        else:  # resolution
            if not RESOLUTION_ID.match(str(rid or "")):
                note(rec, "bad-id",
                     "resolution id must be rs-NNNNNN")
            target = threads.get(rec.get("thread"))
            if target is None:
                note(rec, "unknown-thread",
                     f"resolution names thread "
                     f"{rec.get('thread')!r}, which does "
                     f"not stand earlier in the register")
                continue
            for field in ("by", "on", "note"):
                if not rec.get(field):
                    note(rec, f"missing-field:{field}",
                         f"a resolution carries {field} — "
                         f"who resolved it, when, and what "
                         f"the resolution was")
            if rec.get("on") and not DATE_RE.match(
                    str(rec["on"])):
                note(rec, "missing-field:on",
                     "on must be YYYY-MM-DD")
            if target["resolution"] is not None:
                note(rec, "duplicate-resolution",
                     "a thread resolves once; a changed "
                     "outcome is a new thread")
            else:
                target["resolution"] = rec
    findings.sort(key=lambda f: (str(f["finding"]),
                                 str(f["id"])))
    return threads, findings


def thread_states(root: Path):
    """Every thread with its derived state and its
    anchor's state against the corpus as it stands."""
    present, records, problems = load_register(root)
    threads, findings = derive_threads(records)
    out = []
    for tid in sorted(threads, key=str):
        t = threads[tid]
        body = (page_body(root, t["page"])
                if isinstance(t["page"], str) else None)
        if body is None:
            anchor_state, detail = "orphaned", "page-missing"
        else:
            res = resolve_anchor(t["anchor"], body)
            anchor_state, detail = res["state"], None
        participants = []
        for who in [t["opened_by"]] + \
                [r.get("by") for r in t["replies"]]:
            if who and who not in participants:
                participants.append(who)
        out.append({
            "id": tid, "page": t["page"],
            "state": "resolved" if t["resolution"]
                     else "open",
            "anchor_state": anchor_state,
            "anchor_detail": detail,
            "quote": anchor_quote(t["anchor"]),
            "opened_by": t["opened_by"],
            "opened_on": t["opened_on"],
            "participants": participants,
            "replies": len(t["replies"]),
            "resolution": (
                {"by": t["resolution"].get("by"),
                 "on": t["resolution"].get("on"),
                 "note": t["resolution"].get("note")}
                if t["resolution"] else None),
        })
    return present, out, findings, problems


def open_threads_by_page(root: Path):
    """{page: {"open": n, "orphaned": m}} over threads
    whose derived state is open; orphaned anchors are
    counted in both (the discussion is unresolved AND
    its passage has moved). Consumed in-process by the
    Review Center (scripts/wiki_review_state.py)."""
    _present, states, _f, _p = thread_states(root)
    out = {}
    for t in states:
        if t["state"] != "open":
            continue
        slot = out.setdefault(t["page"],
                              {"open": 0, "orphaned": 0})
        slot["open"] += 1
        if t["anchor_state"] == "orphaned":
            slot["orphaned"] += 1
    return out


def build_artefact(root: Path):
    present, states, findings, problems = \
        thread_states(root)
    counts = {"threads": len(states), "open": 0,
              "resolved": 0, "anchored": 0, "moved": 0,
              "orphaned": 0, "page_level": 0}
    for t in states:
        counts[t["state"]] += 1
        if t["anchor_state"] in ("anchored", "moved",
                                  "orphaned"):
            counts[t["anchor_state"]] += 1
        elif t["anchor_state"] == "page":
            counts["page_level"] += 1
    return {
        "tool": "scripts/wiki_review_threads.py",
        "kind": "review-threads",
        "register": REGISTER_REL,
        "register_present": present,
        "counts": counts,
        "findings": findings,
        "register_problems": problems,
        "threads": states,
    }


def render_md(artefact: dict) -> str:
    c = artefact["counts"]
    lines = [
        "# Review threads", "",
        "Generated by `scripts/wiki_review_threads.py` "
        "from `evaluation/review-threads.jsonl`. State "
        "is derived from the register; anchor states are "
        "resolved against the corpus as it stands.", "",
        f"- Threads: {c['threads']} "
        f"({c['open']} open, {c['resolved']} resolved)",
        f"- Anchors: {c['anchored']} anchored, "
        f"{c['moved']} moved, {c['orphaned']} orphaned, "
        f"{c['page_level']} page-level", "",
    ]
    if not artefact["threads"]:
        lines += ["No review threads stand on the "
                  "register.", ""]
    by_page = {}
    for t in artefact["threads"]:
        by_page.setdefault(t["page"], []).append(t)
    for page in sorted(by_page):
        lines.append(f"## {page}")
        lines.append("")
        for t in by_page[page]:
            head = f"### {t['id']} — {t['state']}"
            if t["anchor_state"] == "orphaned":
                head += " · ORPHANED (passage moved or gone)"
            elif t["anchor_state"] == "moved":
                head += " · anchor moved"
            lines.append(head)
            lines.append("")
            if t["quote"]:
                lines.append(f"> {t['quote']}")
                lines.append("")
            lines.append(
                f"- Opened by {t['opened_by']} on "
                f"{t['opened_on']}; participants: "
                f"{', '.join(t['participants'])}; "
                f"replies: {t['replies']}")
            if t["resolution"]:
                r = t["resolution"]
                lines.append(
                    f"- Resolved by {r['by']} on {r['on']}: "
                    f"{r['note']}")
            lines.append("")
    return "\n".join(lines)


# -- recorded acts (open / reply / resolve) -----------------------------------

def _refuse(name, detail):
    return {"refused": name, "detail": detail}


def open_thread(root: Path, spec: dict):
    """Validate + append a thread. spec: {id?, page,
    quote?, opened_by, opened_on, note?}. Returns the
    record, or a {"refused": ...} dict."""
    _present, records, _p = load_register(root)
    threads, _f = derive_threads(records)
    page = spec.get("page")
    if not page or not str(page).startswith("wiki/") or \
            not str(page).endswith(".md"):
        return _refuse("bad-page",
                       "page must be a repo-relative "
                       "wiki/....md path")
    body = page_body(root, str(page))
    if body is None:
        return _refuse("page-missing",
                       f"{page} does not exist")
    if not spec.get("opened_by"):
        return _refuse("missing-field:opened_by",
                       "a thread names who opened it")
    if not DATE_RE.match(str(spec.get("opened_on") or "")):
        return _refuse("missing-field:opened_on",
                       "opened_on must be YYYY-MM-DD")
    anchor = None
    if spec.get("quote"):
        quote = normalize_text(spec["quote"])
        hits = find_quote(body, quote)
        if not hits:
            return _refuse(
                "quote-not-found",
                "the quoted words do not occur in the "
                "page body as it stands")
        if len(hits) > 1:
            return _refuse(
                "quote-ambiguous",
                f"the quoted words occur {len(hits)} "
                f"times; widen the quote so it names "
                f"one passage")
        anchor = {"source": page,
                  "selector": selectors_for(
                      body, hits[0],
                      hits[0] + len(quote))}
    rid = spec.get("id") or _next_id(
        records, "thread", "rt", THREAD_ID)
    if not THREAD_ID.match(str(rid)):
        return _refuse("bad-id",
                       "thread id must be rt-NNNNNN")
    if rid in threads:
        return _refuse("duplicate-id",
                       f"thread {rid} already stands")
    rec = {"kind": "thread", "id": rid, "page": page,
           "anchor": anchor,
           "opened_by": spec["opened_by"],
           "opened_on": spec["opened_on"],
           "note": spec.get("note")}
    _append(root, rec)
    return rec


def append_reply(root: Path, spec: dict):
    """spec: {id?, thread, by, on, body}."""
    _present, records, _p = load_register(root)
    threads, _f = derive_threads(records)
    target = threads.get(spec.get("thread"))
    if target is None:
        return _refuse("unknown-thread",
                       f"no thread {spec.get('thread')!r} "
                       f"stands on the register")
    if target["resolution"] is not None:
        return _refuse("thread-resolved",
                       "the thread stands resolved; a "
                       "further point opens a new thread")
    for field in ("by", "on", "body"):
        if not spec.get(field):
            return _refuse(f"missing-field:{field}",
                           f"a reply carries {field}")
    if not DATE_RE.match(str(spec["on"])):
        return _refuse("missing-field:on",
                       "on must be YYYY-MM-DD")
    rid = spec.get("id") or _next_id(
        records, "reply", "rr", REPLY_ID)
    if not REPLY_ID.match(str(rid)):
        return _refuse("bad-id", "reply id must be "
                                  "rr-NNNNNN")
    if any(r.get("id") == rid for r in records):
        return _refuse("duplicate-id",
                       f"record {rid} already stands")
    rec = {"kind": "reply", "id": rid,
           "thread": spec["thread"], "by": spec["by"],
           "on": spec["on"], "body": spec["body"]}
    _append(root, rec)
    return rec


def append_resolution(root: Path, spec: dict):
    """spec: {id?, thread, by, on, note} — the recorded
    act that resolves a thread."""
    _present, records, _p = load_register(root)
    threads, _f = derive_threads(records)
    target = threads.get(spec.get("thread"))
    if target is None:
        return _refuse("unknown-thread",
                       f"no thread {spec.get('thread')!r} "
                       f"stands on the register")
    if target["resolution"] is not None:
        return _refuse("duplicate-resolution",
                       "the thread already stands "
                       "resolved")
    for field in ("by", "on", "note"):
        if not spec.get(field):
            return _refuse(f"missing-field:{field}",
                           f"a resolution carries {field}")
    if not DATE_RE.match(str(spec["on"])):
        return _refuse("missing-field:on",
                       "on must be YYYY-MM-DD")
    rid = spec.get("id") or _next_id(
        records, "resolution", "rs", RESOLUTION_ID)
    if not RESOLUTION_ID.match(str(rid)):
        return _refuse("bad-id", "resolution id must be "
                                  "rs-NNNNNN")
    if any(r.get("id") == rid for r in records):
        return _refuse("duplicate-id",
                       f"record {rid} already stands")
    rec = {"kind": "resolution", "id": rid,
           "thread": spec["thread"], "by": spec["by"],
           "on": spec["on"], "note": spec["note"]}
    _append(root, rec)
    return rec


# -- CLI -----------------------------------------------------------------------

TEMPLATE = {
    "open": {"page": "wiki/concepts/example.md",
             "quote": "the exact words under review",
             "opened_by": "agent",
             "opened_on": "YYYY-MM-DD",
             "note": "why this thread was opened"},
    "reply": {"thread": "rt-000001", "by": "grok",
              "on": "YYYY-MM-DD", "body": "..."},
    "resolve": {"thread": "rt-000001", "by": "agent",
                "on": "YYYY-MM-DD",
                "note": "what resolved it"},
}


def _dump(path: Path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False,
                               sort_keys=True, indent=1)
                    + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Anchored review threads")
    ap.add_argument("command",
                    choices=["template", "open", "reply",
                             "resolve", "check", "census",
                             "render"])
    ap.add_argument("record", nargs="?",
                    help="record JSON for open/reply/"
                         "resolve")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = args.root

    if args.command == "template":
        print(json.dumps(TEMPLATE, indent=1,
                         sort_keys=True))
        return 0
    if args.command in ("open", "reply", "resolve"):
        if not args.record:
            print(f"{args.command} needs a record JSON "
                  f"path", file=sys.stderr)
            return 2
        spec = json.loads(Path(args.record).read_text(
            encoding="utf-8"))
        fn = {"open": open_thread, "reply": append_reply,
              "resolve": append_resolution}[args.command]
        rec = fn(root, spec)
        print(json.dumps(rec, indent=1, sort_keys=True))
        return 1 if "refused" in rec else 0
    if args.command == "check":
        artefact = build_artefact(root)
        drift = [t for t in artefact["threads"]
                 if t["state"] == "open"
                 and t["anchor_state"] == "orphaned"]
        out = {"counts": artefact["counts"],
               "findings": artefact["findings"],
               "register_problems":
                   artefact["register_problems"],
               "drift": [{"id": t["id"], "page": t["page"],
                          "finding": "anchor-orphaned",
                          "quote": t["quote"]}
                         for t in drift]}
        print(json.dumps(out, indent=1, sort_keys=True))
        return 1 if (out["findings"] or out["drift"]
                     or out["register_problems"]) else 0
    if args.command == "census":
        artefact = build_artefact(root)
        if args.json:
            print(json.dumps(artefact, indent=1,
                             sort_keys=True))
        else:
            print(f"register present: "
                  f"{artefact['register_present']} · "
                  f"counts: {artefact['counts']}")
        return 0
    if args.command == "render":
        artefact = build_artefact(root)
        out_dir = args.out_dir or (root / "evaluation")
        out_dir.mkdir(parents=True, exist_ok=True)
        _dump(out_dir / "review-threads.json", artefact)
        (out_dir / "review-threads.md").write_text(
            render_md(artefact), encoding="utf-8")
        print(f"rendered: {artefact['counts']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
