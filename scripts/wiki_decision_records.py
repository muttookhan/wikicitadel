#!/usr/bin/env python3
"""Decision records, upgraded (build-list wave 5, 2026-10-22):
the v2 decision register for the LLM Wiki.

Patterns, credited — ideas only, no code or text copied
(clean re-implementation, the lane's licence route):

  - ADR (Architecture Decision Records, M. Nygard's public
    pattern family): a decision is a durable record with
    context, the decision itself, and consequences — here
    extended with the fields this wiki's record-keeping
    demands (rejected options with the reason each lost,
    hash-bound basis, outcome, supersession).
  - The build list's idea sources for this item
    (LiLara-AI/shadowgraph, glovrex-cli, robbrain,
    uniskela/adhd-hub): machine-checkable reopen conditions
    re-evaluated against stored facts; decision-to-commit-
    to-outcome edges with outcome gaps left visible; a
    first-class rejected[] field with VetoBench-style
    measurement of re-proposed rejections; an overlap check
    that ranks proposed work against open threads and never
    merges anything itself.

WHAT THIS IS. evaluation/decisions-register.jsonl (v1)
remains the register of record for the gate and the
decision-basis tool; this tool builds a NEW artefact,
evaluation/decision-records.json (v2), alongside it. The
v2 entry for a decision carries the full upgraded field
set:

  identity from v1 (id, title, status, decided, redecided,
  decided_by, source, current_form — copied verbatim, and
  the checker flags any drift from v1);
  tier — the delegation tier the decision was taken under;
  chosen + rejected[] — every rejected entry carries
  why_lost, a recorded_rationale (a verbatim quote from the
  human record, or null), a disposition, and match_phrases
  used by the reproposal measurement;
  reversibility — a class plus its grounding on the record;
  reopen_when — conditions in a small closed vocabulary
  (owner-ruling / date / basis-changed) the checker
  re-evaluates against stored facts;
  basis — the basis file paths from
  evaluation/decision-basis.json (the Rutter machinery);
  the checker recomputes their hashes against that
  artefact's baseline;
  commits[] — decision-to-commit edges named on the record;
  outcome — recorded text with its source, or the gap
  status "not-recorded";
  supersedes / superseded_by — the DECISION-level chain,
  checked for symmetry both ways;
  form_supersessions — the v1 form-level chain, mirrored
  and checked for equality with v1;
  watch_records — how many records the decision-watches
  sidecar carries for this decision (the sidecar stays
  the watch machinery; this register references it,
  never duplicates it).

MIGRATION HONESTY. v2 content that only the human record
carries lives in evaluation/decision-records-overlay.json,
authored from wiki/syntheses/chapter7-decisions.md and the
v1 register. A field the record does not support is
emitted as the sentinel "not-recorded-at-the-time" —
never backfilled with invented rationale. A decision
present in v1 but absent from the overlay is still built,
with chosen = null; the checker flags it FIELD GAP rather
than letting it pass half-built. NO decision is retaken,
reworded or re-ruled here: this tool describes records.

AWAITING ITEMS ARE NOT DECISIONS. The register covers
decisions TAKEN. Items still waiting on the owner
(wiki/ideas.md, "## Waiting for your call") are referenced
in the header as open (a count, computed at build) and are
targets of the overlap check — never pre-registered with
an outcome.

CHECKER (check). Stable-sorted lines:
  FIELD GAP <id>: <field> — a required field is absent or
    null in the built register;
  REGISTER DRIFT <id> — a verbatim-copied field no longer
    matches v1, or the id sets differ;
  CHAIN BROKEN ... — a supersedes/superseded_by pair is
    asymmetric, or form_supersessions diverge from v1;
  BASIS CHANGED <id>: <path> / BASIS MISSING <id>: <path>
    — same semantics and wording family as
    wiki_decision_basis.py check: the decision stands;
    its basis moving is the finding;
  OUTCOME GAP <id> — no outcome is recorded (surfacing);
  REOPEN TRIGGERED <id>: <condition> / REOPEN MANUAL <id>
    — a reopen_when condition fired against stored facts,
    or is owner-only and cannot fire mechanically;
  REPROPOSAL CANDIDATE <id>: <n> ideas-board bullet(s)
    mention a rejected option's phrases (surfacing; a
    mention is a candidate for human judgement, never an
    automatic merge or re-decision);
  REPROPOSALS MEASURED: <k> of <n> rejected options carry
    at least one candidate mention on the ideas board.
Exit: check exits 1 when any FIELD GAP / REGISTER DRIFT /
CHAIN BROKEN / BASIS CHANGED / BASIS MISSING exists, 0
otherwise; --report always exits 0. OUTCOME GAP, REOPEN
and REPROPOSAL lines surface; they do not fail the check.

OVERLAP (overlap --text ... | --file ...). Ranks a piece
of proposed work against (a) the registered decisions —
settled law, where overlap means re-litigation risk —
(b) the decisions' rejected options, and (c) the open
threads on the ideas board's waiting list. Scoring is a
fixed token-containment measure (content tokens of the
shorter side found in the longer), ties broken by kind
then id then board order. ADVISORY ONLY: it prints a
reading list and merges, closes or decides nothing;
duplicate merges require human confirmation — the
owner's — per the spec.

TEMPLATE (template) prints a blank v2 entry with every
required field, for the next decision taken.

Determinism: build output depends only on its four inputs
(v1 register, overlay, decision-basis artefact, ideas
board); their sha256s are recorded in the header. No
wall-clock anywhere in the artefact. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1_REL = "evaluation/decisions-register.jsonl"
OVERLAY_REL = "evaluation/decision-records-overlay.json"
BASIS_REL = "evaluation/decision-basis.json"
WATCHES_REL = "evaluation/decision-watches.jsonl"
IDEAS_REL = "wiki/ideas.md"
OUT_REL = "evaluation/decision-records.json"
SENTINEL = "not-recorded-at-the-time"

REQUIRED_FIELDS = [
    "id", "title", "status", "decided", "redecided",
    "decided_by", "tier", "source", "current_form", "chosen",
    "rejected", "reversibility", "reopen_when", "basis",
    "commits", "outcome", "supersedes", "superseded_by",
    "form_supersessions", "watch_records",
]
# Fields whose VALUE may be null by design (null = "none"):
# a decision never redecided, a decision that supersedes
# nothing and is superseded by nothing. Presence is still
# required — an absent key is a gap, a null value is not.
NULLABLE_FIELDS = {"redecided", "supersedes", "superseded_by"}
REJECTED_REQUIRED = ["option", "why_lost", "recorded_rationale",
                     "disposition", "match_phrases"]
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on",
    "for", "with", "by", "as", "at", "is", "it", "its",
    "this", "that", "from", "into", "under", "over", "per",
    "via", "not", "no", "yes", "be", "are", "was", "were",
    "has", "have", "had", "when", "what", "which", "who",
    "will", "would", "can", "could", "should", "one", "two",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def normalise(text: str) -> str:
    """The decision gate's normalisation, restated: fold
    case, markdown emphasis/backticks, curly apostrophes;
    collapse whitespace."""
    t = text.replace("’", "'").replace("‘", "'")
    t = re.sub(r"[*_`#>]+", " ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-]*",
                                 normalise(text))
            if len(w) >= 3 and w not in STOPWORDS}


def load_v1(root: Path):
    path = root / V1_REL
    decisions = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            obj = json.loads(ln)
            if obj.get("kind") == "decision":
                decisions.append(obj)
    return decisions


def load_json(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def waiting_bullets(root: Path):
    """The ideas board's 'Waiting for your call' bullets,
    in board order (first lines only)."""
    text = (root / IDEAS_REL).read_text(encoding="utf-8")
    m = re.search(r"^## Waiting for your call\s*$(.*?)^## ",
                  text, re.M | re.S)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines()
            if ln.startswith("- ")]


def watch_counts(root: Path):
    counts = {}
    path = root / WATCHES_REL
    if not path.is_file():
        return counts
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        obj = json.loads(ln)
        did = obj.get("decision_id") or obj.get("decision")
        wid = obj.get("id") or ""
        if not did and "-" in wid:
            did = "-".join(wid.split("-")[:2])
        if did:
            counts[did] = counts.get(did, 0) + 1
    return counts


def build(root: Path):
    v1 = load_v1(root)
    overlay = load_json(root, OVERLAY_REL)
    basis_doc = load_json(root, BASIS_REL)
    basis_by_id = {d["id"]: d for d in basis_doc["decisions"]}
    watches = watch_counts(root)
    waiting = waiting_bullets(root)
    ov = overlay.get("decisions", {})

    entries = []
    for d in sorted(v1, key=lambda x: x["id"]):
        o = ov.get(d["id"], {})
        b = basis_by_id.get(d["id"], {})
        basis_files = [e["path"] for e in b.get("basis", [])]
        entry = {
            "id": d["id"],
            "title": d.get("title"),
            "status": d.get("status"),
            "decided": d.get("decided"),
            "redecided": d.get("redecided"),
            "decided_by": d.get("decided_by"),
            "tier": o.get("tier", SENTINEL),
            "source": d.get("source"),
            "current_form": d.get("current_form"),
            "chosen": o.get("chosen"),
            "rejected": o.get("rejected", []),
            "reversibility": o.get(
                "reversibility",
                {"class": SENTINEL, "grounding": None}),
            "reopen_when": o.get("reopen_when", [{
                "type": "owner-ruling",
                "text": "The owner reopens it — "
                        "chapter7-decisions.md: the six are "
                        "'DECIDED and final unless he "
                        "reopens them'.",
            }]),
            "basis": {"artefact": BASIS_REL, "files": basis_files,
                      "basis_status": b.get("basis_status")},
            "commits": o.get("commits", []),
            "outcome": o.get(
                "outcome", {"status": "not-recorded",
                            "text": None, "source": None}),
            "supersedes": o.get("supersedes"),
            "superseded_by": o.get("superseded_by"),
            "form_supersessions": [
                {"form_id": f["form_id"],
                 "superseded_on": f.get("superseded_on")}
                for f in d.get("superseded_forms", [])],
            "watch_records": watches.get(d["id"], 0),
        }
        entries.append(entry)

    inputs = {}
    for rel in (V1_REL, OVERLAY_REL, BASIS_REL, IDEAS_REL):
        p = root / rel
        inputs[rel] = sha256_file(p) if p.is_file() else None
    out = {
        "kind": "decision-records",
        "version": 2,
        "register_of_record": V1_REL,
        "derivation": (
            "Built by scripts/wiki_decision_records.py build "
            "from the v1 register (identity + forms, copied "
            "verbatim), the migration overlay "
            f"({OVERLAY_REL}: the fields only the human "
            "record carries, authored from "
            "wiki/syntheses/chapter7-decisions.md), the "
            "decision-basis artefact (basis file paths), "
            "the decision-watches sidecar (counts only) and "
            "the ideas board (the open-items count). A field "
            "the record does not support carries the "
            f"sentinel '{SENTINEL}'. No decision is retaken, "
            "reworded or re-ruled."),
        "tier_note": (
            "The delegation tiers (A/B/C) were established "
            "2026-10-20 (AGENTS.md, 'Delegation tiers'); the "
            "six Chapter 7 decisions were taken by the owner "
            "himself, one by one, on 2026-10-13, before "
            "that vocabulary existed, and no tier is "
            "retro-fitted: tier carries the sentinel and "
            "decided_by carries who took each decision."),
        "open_references": {
            "source": IDEAS_REL,
            "section": "Waiting for your call",
            "count_at_build": len(waiting),
            "note": "Items still awaiting the owner are NOT "
                    "decision records and are never "
                    "pre-registered here with an outcome; "
                    "they are referenced as open only, and "
                    "serve as overlap-check targets.",
        },
        "inputs_sha256": inputs,
        "decisions": entries,
    }
    target = root / OUT_REL
    target.write_text(json.dumps(out, indent=2,
                                 ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return out


def cmd_build(root: Path):
    out = build(root)
    print(f"wrote {OUT_REL} ({len(out['decisions'])} decisions)")
    for d in out["decisions"]:
        gaps = []
        if d["chosen"] is None:
            gaps.append("chosen NOT MIGRATED")
        if d["tier"] == SENTINEL:
            gaps.append("tier not-recorded-at-the-time")
        if d["reversibility"]["class"] == SENTINEL:
            gaps.append("reversibility not-recorded-at-the-time")
        if d["outcome"]["status"] != "recorded":
            gaps.append("outcome not recorded")
        print(f"  {d['id']}: rejected {len(d['rejected'])}, "
              f"commits {len(d['commits'])}, "
              f"watches {d['watch_records']}"
              + (f" — {'; '.join(gaps)}" if gaps else ""))
    return 0


HARD_KINDS = ("FIELD GAP", "REGISTER DRIFT", "CHAIN BROKEN",
              "BASIS CHANGED", "BASIS MISSING")


def check_lines(root: Path, today: str):
    """All checker lines, as (kind, text) pairs, unsorted."""
    lines = []
    reg_path = root / OUT_REL
    if not reg_path.is_file():
        return [("FIELD GAP", f"no {OUT_REL} — run build first")]
    reg = load_json(root, OUT_REL)
    v1 = {d["id"]: d for d in load_v1(root)}
    basis_doc = load_json(root, BASIS_REL)
    basis_by_id = {d["id"]: d for d in basis_doc["decisions"]}
    entries = {d["id"]: d for d in reg["decisions"]}

    if set(entries) != set(v1):
        lines.append(("REGISTER DRIFT",
                      f"decision id sets differ — v2 only: "
                      f"{sorted(set(entries) - set(v1))}, "
                      f"v1 only: {sorted(set(v1) - set(entries))}"))

    for did in sorted(entries):
        d = entries[did]
        # --- field completeness --------------------------------
        for f in REQUIRED_FIELDS:
            if f not in d or (d[f] is None
                              and f not in NULLABLE_FIELDS):
                lines.append(("FIELD GAP", f"{did}: {f}"))
        for i, r in enumerate(d.get("rejected") or []):
            for f in REJECTED_REQUIRED:
                if f not in r:
                    lines.append(("FIELD GAP",
                                  f"{did}: rejected[{i}].{f}"))
        oc = d.get("outcome") or {}
        if oc.get("status") != "recorded":
            lines.append(("OUTCOME GAP",
                          f"{did}: no outcome recorded — the "
                          f"gap stays visible, per the spec"))
        # --- verbatim drift against v1 --------------------------
        src = v1.get(did)
        if src:
            for f in ("title", "status", "decided", "decided_by",
                      "current_form"):
                if d.get(f) != src.get(f):
                    lines.append(("REGISTER DRIFT",
                                  f"{did}: {f} no longer matches "
                                  f"the v1 register"))
            if d.get("redecided") != src.get("redecided"):
                lines.append(("REGISTER DRIFT",
                              f"{did}: redecided no longer "
                              f"matches the v1 register"))
            v1_forms = [{"form_id": f["form_id"],
                         "superseded_on": f.get("superseded_on")}
                        for f in src.get("superseded_forms", [])]
            if d.get("form_supersessions") != v1_forms:
                lines.append(("CHAIN BROKEN",
                              f"{did}: form_supersessions "
                              f"diverge from the v1 register"))
        # --- decision-level chain symmetry ----------------------
        sb = d.get("superseded_by")
        if sb:
            other = entries.get(sb.get("decision"), {})
            if (other.get("supersedes") or {}).get("decision") \
                    != did:
                lines.append(("CHAIN BROKEN",
                              f"{did}: superseded_by "
                              f"{sb.get('decision')} but that "
                              f"entry does not supersede it back"))
        sp = d.get("supersedes")
        if sp:
            other = entries.get(sp.get("decision"), {})
            if (other.get("superseded_by") or {}).get(
                    "decision") != did:
                lines.append(("CHAIN BROKEN",
                              f"{did}: supersedes "
                              f"{sp.get('decision')} but that "
                              f"entry is not superseded_by it"))
        # --- basis, recomputed against the basis artefact -------
        b = basis_by_id.get(did)
        basis_changed = False
        if b and b.get("basis_status") == "derived":
            recorded_paths = [e["path"] for e in b["basis"]]
            if (d.get("basis") or {}).get("files") != \
                    recorded_paths:
                lines.append(("REGISTER DRIFT",
                              f"{did}: basis file list diverges "
                              f"from {BASIS_REL}"))
            for e in b["basis"]:
                p = root / e["path"]
                if not p.is_file():
                    lines.append(("BASIS MISSING",
                                  f"{did}: {e['path']} — a "
                                  f"basis file is gone "
                                  f"(recorded "
                                  f"{e['sha256_now'][:16]}…)"))
                    basis_changed = True
                elif sha256_file(p) != e["sha256_now"]:
                    lines.append(("BASIS CHANGED",
                                  f"{did}: {e['path']} — bytes "
                                  f"moved since the basis "
                                  f"baseline "
                                  f"{basis_doc.get('generated')} "
                                  f"(recorded "
                                  f"{e['sha256_now'][:16]}… → "
                                  f"current "
                                  f"{sha256_file(p)[:16]}…). "
                                  f"The decision stands; its "
                                  f"basis moved."))
                    basis_changed = True
        # --- reopen_when, re-evaluated against stored facts -----
        for cond in d.get("reopen_when") or []:
            ctype = cond.get("type")
            if ctype == "owner-ruling":
                lines.append(("REOPEN MANUAL",
                              f"{did}: reopen condition is an "
                              f"owner ruling — it cannot fire "
                              f"mechanically"))
            elif ctype == "date":
                if today >= (cond.get("date") or "9999"):
                    lines.append(("REOPEN TRIGGERED",
                                  f"{did}: reopen date "
                                  f"{cond.get('date')} has "
                                  f"arrived — the question "
                                  f"re-opens; the decision "
                                  f"itself is the owner's to "
                                  f"revisit"))
            elif ctype == "basis-changed":
                if basis_changed:
                    lines.append(("REOPEN TRIGGERED",
                                  f"{did}: a basis file "
                                  f"changed — the reopen "
                                  f"condition recorded on "
                                  f"this entry has fired"))
            else:
                lines.append(("FIELD GAP",
                              f"{did}: reopen_when type "
                              f"{ctype!r} is outside the "
                              f"closed vocabulary"))
    # --- reproposal measurement over the ideas board -----------
    bullets = waiting_bullets(root)
    board = [normalise(b) for b in bullets]
    total_rejected = 0
    measured = 0
    for did in sorted(entries):
        for r in entries[did].get("rejected") or []:
            total_rejected += 1
            phrases = [normalise(p)
                       for p in r.get("match_phrases") or []]
            if not phrases:
                continue
            hits = sum(1 for b in board
                       if any(p and p in b for p in phrases))
            if hits:
                measured += 1
                lines.append(("REPROPOSAL CANDIDATE",
                              f"{did}: rejected option "
                              f"{r['option'][:60]!r} is "
                              f"mentioned by {hits} "
                              f"waiting-list bullet(s) — a "
                              f"candidate re-proposal for "
                              f"human judgement, never an "
                              f"automatic merge"))
    lines.append(("REPROPOSALS MEASURED",
                  f"{measured} of {total_rejected} rejected "
                  f"options carry at least one candidate "
                  f"mention on the ideas board's waiting list"))
    return lines


def cmd_check(root: Path, report_only: bool, today: str):
    lines = check_lines(root, today)
    hard = 0
    for kind, text in sorted(lines, key=lambda kt: (kt[0], kt[1])):
        if kind == "REPROPOSALS MEASURED":
            print(f"{kind}: {text}")
        else:
            print(f"{kind} {text}")
        if kind in HARD_KINDS:
            hard += 1
    n = len([1 for k, _ in lines if k != "REPROPOSALS MEASURED"])
    print(f"Result: {'CLEAN of hard findings' if hard == 0 else f'{hard} hard finding(s)'} "
          f"({n} surfacing line(s))")
    return 0 if (report_only or hard == 0) else 1


def cmd_overlap(root: Path, text: str, top: int):
    reg = load_json(root, OUT_REL)
    mine = tokens(text)
    scored = []
    for d in reg["decisions"]:
        body_tokens = tokens(d["title"] + " " +
                             (d["current_form"] or ""))
        inter = len(mine & body_tokens)
        if inter:
            score = inter / max(1, min(len(mine),
                                       len(body_tokens)))
            scored.append((score, 0, d["id"],
                           "SETTLED DECISION",
                           d["title"]))
        for r in d.get("rejected") or []:
            rt = tokens(r["option"])
            inter = len(mine & rt)
            if inter:
                score = inter / max(1, min(len(mine), len(rt)))
                scored.append((score, 1, d["id"],
                               "REJECTED OPTION",
                               f"{d['title']} — rejected: "
                               f"{r['option'][:70]}"))
    for i, b in enumerate(waiting_bullets(root)):
        bt = tokens(b)
        inter = len(mine & bt)
        if inter:
            score = inter / max(1, min(len(mine), len(bt)))
            scored.append((score, 2, f"{i:04d}", "OPEN THREAD",
                           b[2:100]))
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    if not scored:
        print("No overlap above zero with any registered "
              "decision, rejected option, or open thread.")
    for score, _rank, ident, kind, label in scored[:top]:
        print(f"{score:.2f}  {kind:17s} {ident:8s} {label}")
    print("Advisory only: this is a reading list, not a "
          "merge. Nothing is merged, closed or decided by "
          "this tool; a duplicate merge requires human "
          "confirmation — the owner's.")
    return 0


def cmd_template():
    blank = {
        "id": "<decision-id>",
        "title": "<short title>",
        "status": "active",
        "decided": "YYYY-MM-DD",
        "redecided": None,
        "decided_by": "owner",
        "tier": "A | B | C (the tier the decision was taken "
                "under; owner decisions are recorded as "
                "taken, never argued down)",
        "source": {"page": "wiki/<page>.md", "section": "<n>"},
        "current_form": "<the decision as it stands, verbatim "
                        "from the human record>",
        "chosen": "<the option chosen, in one line>",
        "rejected": [{
            "option": "<an option considered and not chosen>",
            "why_lost": "<why it lost, from the record — or "
                        "'not-recorded-at-the-time'>",
            "recorded_rationale": "<verbatim quote from the "
                                  "record, or null>",
            "disposition": "rejected-at-decision | "
                           "superseded-form",
            "match_phrases": ["<phrases the option circulates "
                              "under, for the reproposal "
                              "measurement>"],
        }],
        "reversibility": {
            "class": "reversible | costly | irreversible | "
                     "not-recorded-at-the-time",
            "grounding": "<what on the record grounds the "
                         "class, or null>"},
        "reopen_when": [{
            "type": "owner-ruling | date | basis-changed",
            "text": "<the trigger, in the record's words>"}],
        "basis": {"artefact": BASIS_REL, "files": [],
                  "basis_status": "derived"},
        "commits": [{"hash": "<short hash>",
                     "relation": "<how the commit binds to "
                                 "this decision>"}],
        "outcome": {"status": "recorded | not-recorded",
                    "text": "<what happened, or null>",
                    "source": "<where the outcome is "
                              "recorded>"},
        "supersedes": None,
        "superseded_by": None,
        "form_supersessions": [],
        "watch_records": 0,
    }
    print(json.dumps(blank, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Decision records v2 — register build, "
                    "checker, overlap (wave-5 upgrade).")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help=f"(re)write {OUT_REL}")
    pc = sub.add_parser("check", help="validate the v2 register")
    pc.add_argument("--report", action="store_true",
                    help="surface only; always exit 0")
    pc.add_argument("--today", default=None,
                    help="YYYY-MM-DD for date-condition "
                         "evaluation (default: today)")
    po = sub.add_parser("overlap",
                        help="rank proposed work against "
                             "decisions + open threads")
    po.add_argument("--text", default=None)
    po.add_argument("--file", default=None)
    po.add_argument("--top", type=int, default=8)
    sub.add_parser("template", help="print a blank v2 entry")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "build":
        return cmd_build(root)
    if args.cmd == "check":
        return cmd_check(root, args.report,
                         args.today or date.today().isoformat())
    if args.cmd == "overlap":
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
        elif args.text:
            text = args.text
        else:
            print("overlap needs --text or --file")
            return 2
        return cmd_overlap(root, text, args.top)
    return cmd_template()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
