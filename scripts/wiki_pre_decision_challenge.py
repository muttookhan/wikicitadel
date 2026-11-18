#!/usr/bin/env python3
"""Pre-decision challenge (build-list wave 5, 2026-10-22).

Before a decision is taken — or re-taken — this tool faces
the proposal with everything the record already holds
about its ground, in one pack:

  OVERLAP — the settled decisions the proposal touches
  (re-litigation risk), the REJECTED OPTIONS of those
  decisions it resembles, and the OPEN THREADS (the ideas
  board's waiting list) it overlaps. Ranking reuses the
  decision register's own overlap machinery
  (scripts/wiki_decision_records.py): the same tokeniser,
  the same containment score, the same tie-breaking. This
  tool forks none of it.
  RE-PROPOSED REJECTIONS — two readings: (a) proposal-
  specific — the proposal's own text is scanned for the
  recorded match phrases of every rejected option in the
  v2 register, and any hit is flagged with the option it
  names and the reason the record gives for its loss;
  (b) the register-wide measurement the decision checker
  itself reports over the ideas board, quoted verbatim
  from its own lines.
  LESSONS — the corrections-ledger lessons whose ground
  the proposal touches, matched by the lesson engine
  (tools/ask/lessons.py) under its stated rule, each with
  its lifecycle state and gate posture: a lesson whose
  rule has hardened to a blocking gate is the pack's
  loudest line, and it is labelled as such.

ADVISORY ONLY. The pack challenges; it never blocks,
registers, amends or decides anything, and it writes
nothing. It is a reading list for the owner BEFORE ruling
— the ruling, as always, is his.

Determinism: the pack is a pure function of the proposal
text, the registers and the ledger. The only date in play
is --today (an input, used solely where the decision
checker itself evaluates a date condition); nothing in
the output carries a wall-clock reading.

Clean re-implementation: the pre-decision challenge and
lesson-surface patterns of the item's idea sources were
taken as ideas only; no code or text was copied. The
machinery reused is this wiki's own (decision records,
corrections lifecycle, the lesson engine).

Usage:
  python3 scripts/wiki_pre_decision_challenge.py challenge \\
      --text "the proposal" [--root DIR] [--today YYYY-MM-DD]
      [--top N] [--json]
  python3 scripts/wiki_pre_decision_challenge.py challenge \\
      --file proposal.md [...]
Exit 0: a pack was produced (advisory — findings never
fail it). Exit 2: usage error, or a register the pack
needs is absent (named).
Stdlib only, no network.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
PATH_RE = re.compile(r"(?:[\w.\-]+/)+[\w.\-]+\.md\b")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _modules(root):
    root = Path(root)
    dr = _load("wiki_decision_records",
               root / "scripts" / "wiki_decision_records.py")
    lessons = _load("ask_lessons",
                    root / "tools" / "ask" / "lessons.py")
    return dr, lessons


def _mentioned_pages(text):
    """Pages a proposal names: wikilink targets and
    repo-style .md paths, as bare stems/paths."""
    pages = [w.strip() for w in WIKILINK_RE.findall(text or "")]
    pages += [p[:-3] for p in PATH_RE.findall(text or "")]
    return pages


def build_challenge(root, text, today, top=8):
    """The challenge pack for one proposal text, as a dict.
    ``today`` is a YYYY-MM-DD string (an input)."""
    root = Path(root)
    dr, lessons_mod = _modules(root)
    reg_path = root / dr.OUT_REL
    if not reg_path.is_file():
        raise FileNotFoundError(
            f"no {dr.OUT_REL} — run "
            f"scripts/wiki_decision_records.py build first")
    reg = dr.load_json(root, dr.OUT_REL)

    # --- overlap: the register's own scoring, restated
    # only in that it also keeps the rejected option's
    # recorded loss reason beside the row.
    mine = dr.tokens(text)
    scored = []
    for d in reg["decisions"]:
        body_tokens = dr.tokens(d["title"] + " " +
                                (d["current_form"] or ""))
        inter = len(mine & body_tokens)
        if inter:
            scored.append({
                "score": round(inter / max(1, min(len(mine),
                                                  len(body_tokens))), 4),
                "kind": "SETTLED DECISION", "rank": 0,
                "id": d["id"], "label": d["title"],
            })
        for r in d.get("rejected") or []:
            rt = dr.tokens(r["option"])
            inter = len(mine & rt)
            if inter:
                scored.append({
                    "score": round(inter / max(1, min(len(mine),
                                                      len(rt))), 4),
                    "kind": "REJECTED OPTION", "rank": 1,
                    "id": d["id"],
                    "label": f"{d['title']} — rejected: "
                             f"{r['option'][:70]}",
                    "why_lost": r.get("why_lost"),
                })
    waiting = dr.waiting_bullets(root)
    for i, b in enumerate(waiting):
        bt = dr.tokens(b)
        inter = len(mine & bt)
        if inter:
            scored.append({
                "score": round(inter / max(1, min(len(mine),
                                                  len(bt))), 4),
                "kind": "OPEN THREAD", "rank": 2,
                "id": f"{i:04d}", "label": b[2:100],
            })
    scored.sort(key=lambda s: (-s["score"], s["rank"], s["id"]))
    overlap = scored[:top]

    # --- re-proposed rejections: the proposal's own text
    # against every rejected option's recorded phrases,
    # plus the checker's own board-wide lines, verbatim.
    norm_text = dr.normalise(text)
    proposal_flags = []
    for d in reg["decisions"]:
        for r in d.get("rejected") or []:
            hits = [p for p in r.get("match_phrases") or []
                    if p and dr.normalise(p) in norm_text]
            if hits:
                proposal_flags.append({
                    "decision": d["id"],
                    "decision_title": d["title"],
                    "option": r["option"],
                    "phrases": hits,
                    "why_lost": r.get("why_lost"),
                    "recorded_rationale": r.get("recorded_rationale"),
                })
    check = dr.check_lines(root, today)
    board_candidates = [t for k, t in check
                        if k == "REPROPOSAL CANDIDATE"]
    measured = [t for k, t in check
                if k == "REPROPOSALS MEASURED"]

    # --- lessons whose ground the proposal touches
    all_lessons = lessons_mod.load_lessons(root, today=today)
    matched = lessons_mod.match_by_tokens(
        all_lessons,
        lessons_mod.question_tokens(root, text),
        pages=_mentioned_pages(text),
    )

    return {
        "kind": "pre-decision-challenge",
        "version": 1,
        "advisory": True,
        "proposal": text,
        "overlap": overlap,
        "reproposal": {
            "proposal_flags": proposal_flags,
            "board_candidates": board_candidates,
            "measured": measured[0] if measured else None,
        },
        "lessons": matched,
        "lessons_considered": len(all_lessons),
        "open_threads_considered": len(waiting),
    }


def render_text(pack):
    lines = ["Pre-decision challenge — advisory only. This pack "
             "blocks, registers and decides nothing; it is the "
             "reading list to face BEFORE ruling.",
             "", "Proposal:", "  " + pack["proposal"], ""]
    lines.append("Settled ground this touches (overlap, the "
                 "decision register's own scoring):")
    if pack["overlap"]:
        for row in pack["overlap"]:
            lines.append(f"  {row['score']:.2f}  {row['kind']:<17} "
                         f"{row['id']:<8} {row['label']}")
            if row.get("why_lost"):
                lines.append(f"        why it lost, per the record: "
                             f"{row['why_lost']}")
    else:
        lines.append("  (no overlap above zero with any registered "
                     "decision, rejected option, or open thread)")
    lines += ["", "Re-proposed rejections:"]
    flags = pack["reproposal"]["proposal_flags"]
    if flags:
        for f in flags:
            lines.append(f"  - this proposal re-proposes phrases of "
                         f"{f['decision']}'s rejected option "
                         f"{f['option'][:70]!r} (matched: "
                         f"{', '.join(f['phrases'])})")
            lines.append(f"      why it lost, per the record: "
                         f"{f['why_lost']}")
            if f.get("recorded_rationale"):
                lines.append(f"      recorded rationale: "
                             f"{f['recorded_rationale']}")
    else:
        lines.append("  (the proposal names no rejected option's "
                     "recorded phrases)")
    if pack["reproposal"]["measured"]:
        lines.append(f"  Register-wide, over the ideas board: "
                     f"{pack['reproposal']['measured']}")
    for c in pack["reproposal"]["board_candidates"]:
        lines.append(f"  Board candidate: {c}")
    lines += ["", f"Lessons on record that bear on it "
                  f"({pack['lessons_considered']} considered):"]
    if pack["lessons"]:
        for m in pack["lessons"]:
            gate = (m.get("gate") or "").upper()
            head = f"  - {m['title']} ({m['date']})"
            facts = []
            if m.get("rule"):
                facts.append("rule `" + str(m["rule"]) + "`")
            if m.get("state"):
                facts.append("state " + str(m["state"]))
            if gate:
                facts.append("gate " + gate
                             + (" — this rule has recurred and "
                                "hardened" if gate == "BLOCKING"
                                else ""))
            lines.append(head + (" — " + ", ".join(facts)
                                 if facts else ""))
            if m.get("rule_text"):
                lines.append(f"      Standing rule: {m['rule_text']}")
            basis = []
            for b in m.get("basis") or []:
                if b.get("signal") == "page-overlap":
                    basis.append("names page(s) in the lesson's "
                                 "record: " + ", ".join(b["pages"]))
                elif b.get("signal") == "shared-terms":
                    basis.append("shares terms: "
                                 + ", ".join(b["terms"]))
            if basis:
                lines.append("      Why shown: " + "; ".join(basis)
                             + f". Ledger: {m['citation']}.")
    else:
        lines.append("  (no recorded lesson matches this proposal "
                     "under the stated rule)")
    lines += ["", f"Open owner-threads considered: "
                  f"{pack['open_threads_considered']} (the ideas "
                  f"board's waiting list; overlaps are in the "
                  f"overlap section above)."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pre-decision challenge pack (wave 5) — "
                    "advisory only.")
    sub = ap.add_subparsers(dest="command")
    pc = sub.add_parser("challenge")
    pc.add_argument("--text", default=None)
    pc.add_argument("--file", default=None)
    pc.add_argument("--root", default=None)
    pc.add_argument("--today", default=None,
                    help="YYYY-MM-DD (default: today); used only "
                         "where the decision checker evaluates a "
                         "date condition")
    pc.add_argument("--top", type=int, default=8)
    pc.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if (args.command or "challenge") != "challenge":
        return 2
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        print("challenge needs --text or --file", file=sys.stderr)
        return 2
    root = Path(args.root).resolve() if args.root else ROOT
    today = args.today or date.today().isoformat()
    try:
        pack = build_challenge(root, text, today, top=args.top)
    except FileNotFoundError as exc:
        print(f"wiki_pre_decision_challenge: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(pack, indent=2, ensure_ascii=False,
                         sort_keys=True))
    else:
        print(render_text(pack), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
