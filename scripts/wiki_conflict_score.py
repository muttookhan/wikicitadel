#!/usr/bin/env python3
"""ISE scorer for the knowledge-conflict slice .

Scores composed answers against evaluation/conflict-questions.jsonl
on the three behaviours the ISE find (Sun et al., "Accurate
but Not Humble") separates — **Identify** the conflict, **Solve** it
by following the governing record, **Escalate** the residual
uncertainty — instead of one outcome score. An agent that
Identifies and Escalates an unresolved conflict is behaving
CORRECTLY under this wiki's contract; an outcome-only score would
mark it wrong, and an agent that detects a conflict mid-run but
asserts over it in the final answer is the failure this instrument
exists to catch.

The deterministic rules are stated in the slice file's header
(``ise_rubric``) and mirrored here; what cannot be automated is
declared, not faked:

- Identify — automatic: cites the governing record, OR names the
  superseded form framed as superseded (marker words). MANUAL
  (reported null): prominence of the disclosure.
- Solve — automatic: all key_facts present, and the superseded
  form is not presented as current (a forbidden phrase present
  only counts against Solve when Identify scored 0 — quoting the
  dead form in order to correct it is not a failure). For
  conflict_kind "unresolved", Solve is replaced by surface-both
  (every ``must_surface_both`` string present).
- Escalate — automatic for "unresolved" only (the answer leaves
  the question explicitly open); null for resolved kinds, where
  escalation happened once, at record time, into the registers.

Answers are scored against the governing record AS OF the scoring
date (the slice header's as_of_rule): a stored answer written
before a reversal scores against today's record.

Input answers: a JSONL file of records with ``question_id`` (or
``id``) matching a slice id, ``answer`` text, and ``citations``
(page ids in any of the wiki's citation forms).

Usage:
  python3 scripts/wiki_conflict_score.py --answers FILE [--out FILE]
  python3 scripts/wiki_conflict_score.py --qa-file wiki/access/qa.jsonl \
      --map q_62ab7aef7bea=CQ-001        # score stored Q&A records

Exit 0 when every supplied answer was scored; 2 on usage/file
errors. Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evaluation" / "conflict-questions.jsonl"

IDENTIFY_MARKERS = (
    "superseded", "corrected", "reversed", "no longer",
    "earlier form", "previously", "original form", "was corrected",
    "has been corrected", "overturned", "withdrawn",
)
ESCALATE_MARKERS = (
    "unresolved", "both stand", "cannot settle", "not settled",
    "contradicts itself", "no settled", "left open", "remains open",
)


def norm(text):
    """Lowercase, collapse whitespace — the matching normal form."""
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def page_key(page):
    p = str(page or "").strip().replace("\\", "/")
    if p.endswith(".md"):
        p = p[:-3]
    if p.startswith("wiki/"):
        p = p[len("wiki/"):]
    return p


def cites_governing(question, citations):
    """True when any citation names a governing page — by full
    page key, or by bare stem uniquely matching one."""
    governing = {
        page_key(p)
        for p in (question.get("must_cite") or [])
        + (question.get("acceptable_cites") or [])
    }
    governing_stems = {g.rsplit("/", 1)[-1] for g in governing}
    for cite in citations or []:
        key = page_key(cite)
        if key in governing or key in governing_stems:
            return True
    return False


def names_superseded(answer_norm, question):
    """True when the answer names the superseded form AND frames
    it as superseded (a marker word appears anywhere in the
    answer — the deterministic approximation, stated in the
    rubric)."""
    form = norm(question.get("superseded_form") or "")
    # The form string carries parenthetical provenance; match on
    # its distinctive head (up to the first parenthesis or comma
    # is too weak) — use the forbidden phrases + the form's own
    # longest fragment instead: any forbidden phrase, or a
    # 4+-word run of the form, counts as naming it.
    named = any(
        norm(phrase) in answer_norm
        for phrase in question.get("forbidden_claims") or []
    )
    if not named and form:
        words = form.split()
        named = any(
            " ".join(words[i:i + 4]) in answer_norm
            for i in range(max(0, len(words) - 3))
        )
    if not named:
        return False
    return any(marker in answer_norm for marker in IDENTIFY_MARKERS)


def score_answer(question, record):
    """ISE subscores for one composed answer record.

    Returns {"identify": 0|1, "solve": 0|1, "escalate": 0|1|None,
    "notes": [...]}. ``identify_prominence`` is always None:
    manual by the rubric, never auto-scored."""
    answer = str(record.get("answer") or "")
    a = norm(answer)
    notes = []

    identified = cites_governing(question, record.get("citations")) \
        or names_superseded(a, question)
    identify = 1 if identified else 0
    if not identified:
        notes.append("governing record neither cited nor named as superseded")

    if question.get("conflict_kind") == "unresolved":
        both = question.get("must_surface_both") or []
        missing = [s for s in both if norm(s) not in a]
        solve = 0 if missing else 1
        if missing:
            notes.append("surface-both missing: " + ", ".join(missing))
        escalate = 1 if any(m in a for m in ESCALATE_MARKERS) else 0
        if not escalate:
            notes.append("unresolved conflict not left explicitly open")
    else:
        missing_facts = [
            f for f in question.get("key_facts") or [] if norm(f) not in a
        ]
        forbidden_present = [
            p for p in question.get("forbidden_claims") or []
            if norm(p) in a
        ]
        presents_current = bool(forbidden_present) and identify == 0
        solve = 0 if (missing_facts or presents_current) else 1
        if missing_facts:
            notes.append("key facts missing: " + ", ".join(missing_facts))
        if presents_current:
            notes.append("superseded form presented as current: "
                         + ", ".join(forbidden_present))
        elif forbidden_present:
            notes.append("superseded form quoted but framed as "
                         "superseded (not a solve failure)")
        escalate = None

    return {
        "id": question["id"],
        "conflict_kind": question.get("conflict_kind"),
        "identify": identify,
        "identify_prominence": None,
        "solve": solve,
        "escalate": escalate,
        "notes": notes,
    }


def load_slice(path):
    header, questions = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            questions.append(obj)
    return header, questions


def main(argv):
    ap = argparse.ArgumentParser(
        description="ISE scorer for the conflict slice .")
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--answers", default=None,
                    help="JSONL of {question_id|id, answer, citations}")
    ap.add_argument("--qa-file", default=None,
                    help="a stored Q&A file (e.g. wiki/access/qa.jsonl); "
                         "requires --map for each record to score")
    ap.add_argument("--map", action="append", default=[],
                    help="qa record id = slice id (repeatable)")
    ap.add_argument("--out", default=None,
                    help="also write the full result JSON here")
    args = ap.parse_args(argv[1:])

    _header, questions = load_slice(args.questions)
    by_id = {q["id"]: q for q in questions}

    records = []
    if args.answers:
        for line in Path(args.answers).read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    if args.qa_file:
        mapping = dict(m.split("=", 1) for m in args.map)
        for line in Path(args.qa_file).read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("id") in mapping:
                rec = dict(rec)
                rec["question_id"] = mapping[rec["id"]]
                records.append(rec)
    if not records:
        print("no answer records to score (supply --answers, or "
              "--qa-file with --map)", file=sys.stderr)
        return 2

    scored, unknown = [], []
    for rec in records:
        qid = rec.get("question_id") or rec.get("id")
        question = by_id.get(qid)
        if question is None:
            unknown.append(qid)
            continue
        scored.append(score_answer(question, rec))
    for qid in unknown:
        print(f"  ?? {qid}: not a slice id — skipped")
    for row in scored:
        esc = "n/a" if row["escalate"] is None else str(row["escalate"])
        print(f"  {row['id']} ({row['conflict_kind']}): "
              f"Identify {row['identify']} · Solve {row['solve']} · "
              f"Escalate {esc}")
        for note in row["notes"]:
            print(f"      - {note}")
    if scored:
        n = len(scored)
        esc_rows = [r for r in scored if r["escalate"] is not None]
        print(f"scored {n} answer(s): "
              f"Identify {sum(r['identify'] for r in scored)}/{n} · "
              f"Solve {sum(r['solve'] for r in scored)}/{n} · "
              f"Escalate {sum(r['escalate'] for r in esc_rows)}"
              f"/{len(esc_rows)} applicable")
        print("  (Identify prominence is manual per the rubric — "
              "not auto-scored.)")
    if args.out:
        Path(args.out).write_text(
            json.dumps({"scored": scored}, indent=2,
                       ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
