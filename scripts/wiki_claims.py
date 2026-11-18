#!/usr/bin/env python3
"""Outcome-verified claim lifecycle .

Adapted from helicerat/llm-wiki-loop (MIT): a claim is not
finished when it is written — it is finished when reality has
had its say, repeatedly. A wiki page opts into the lifecycle by
carrying claim frontmatter:

    claim: "One falsifiable sentence."     (required to opt in)
    as_of: 2030-01-01                      (required: when the
                                            claim was last stated)
    outcome_n: 0                           (outcomes recorded)
    outcome_supports: 0
    outcome_contradicts: 0
    outcome_status: candidate              (candidate|rule|retired)

Operations:

  check            Verify every claim page in the wiki: claim +
                   as_of present, frontmatter counters agree with
                   the outcomes log, status agrees with the rule.
                   `check <draft.md>` additionally holds one draft
                   page (anywhere) against the same rules before
                   it ships, and reports whether its claim
                   duplicates an existing claim page's statement.
  measure          Record a real-world outcome for a claim page:
                   appends to evaluation/outcomes.jsonl (the
                   append-only outcomes log) and updates the page's
                   counters + status in place.
  list             Show every claim page and its status.

The status rule (llm-wiki-loop's, kept): a claim is a CANDIDATE
while fewer than 3 outcomes are recorded (it may not block a
decision), a RULE at 3+ outcomes, and RETIRED — never deleted —
when the three most recent outcomes all contradict it.

Stdlib only. The validator carries the companion lint rule: a
present-tense quantitative claim without as_of draws a warning.
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
OUTCOMES = ROOT / "evaluation" / "outcomes.jsonl"

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter = _wv.parse_frontmatter

CLAIM_FIELDS = ("outcome_n", "outcome_supports", "outcome_contradicts",
                "outcome_status")


def load_outcomes():
    if not OUTCOMES.exists():
        return []
    out = []
    for line in OUTCOMES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def status_for(records):
    """records: outcome dicts for one page, in log order."""
    n = len(records)
    if n >= 3 and all(r["outcome"] == "contradicts" for r in records[-3:]):
        return "retired"
    if n >= 3:
        return "rule"
    return "candidate"


def counters_for(records):
    return {
        "outcome_n": len(records),
        "outcome_supports": sum(1 for r in records if r["outcome"] == "supports"),
        "outcome_contradicts": sum(1 for r in records if r["outcome"] == "contradicts"),
        "outcome_status": status_for(records),
    }


def claim_pages():
    """[(path, fields, body)] for wiki pages carrying a claim."""
    out = []
    if not WIKI.exists():
        return out
    for p in sorted(WIKI.rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("wiki/access/") or rel in ("wiki/index.md", "wiki/log.md"):
            continue
        fields, body = parse_frontmatter(
            p.read_text(encoding="utf-8", errors="ignore"))
        if fields and fields.get("claim"):
            out.append((p, fields, body))
    return out


def check_one(rel, fields, outcomes_by_page, problems):
    records = outcomes_by_page.get(rel, [])
    expected = counters_for(records)
    claim = str(fields.get("claim") or "").strip()
    if not claim:
        problems.append(f"{rel}: claim field is empty")
    if not fields.get("as_of"):
        problems.append(f"{rel}: claim page without as_of "
                        f"(a claim must say when it was last stated)")
    elif _wv.parse_date(str(fields["as_of"])) is None:
        problems.append(f"{rel}: as_of {fields['as_of']!r} is not an ISO date")
    for key in CLAIM_FIELDS:
        want = expected[key]
        got = fields.get(key)
        if got is None:
            if want not in (0, "candidate"):
                problems.append(f"{rel}: missing {key} (log implies {want})")
            continue
        got_v = int(got) if key != "outcome_status" else str(got)
        if got_v != want:
            problems.append(f"{rel}: {key} is {got_v!r} but the outcomes "
                            f"log implies {want!r} — run measure or fix the "
                            f"frontmatter, never edit the log")


def cmd_check(args):
    outcomes = load_outcomes()
    by_page = {}
    for r in outcomes:
        by_page.setdefault(r["page"], []).append(r)
    problems = []
    pages = claim_pages()
    for p, fields, _body in pages:
        check_one(p.relative_to(ROOT).as_posix(), fields, by_page, problems)
    if args.draft:
        dp = Path(args.draft)
        if not dp.is_file():
            print(f"draft not found: {dp}")
            return 1
        fields, _body = parse_frontmatter(
            dp.read_text(encoding="utf-8", errors="ignore"))
        if not fields or not fields.get("claim"):
            problems.append(f"{dp}: draft carries no claim: frontmatter — "
                            f"nothing to hold against the lifecycle")
        else:
            rel = str(dp)
            check_one(rel, fields, by_page, problems)
            norm = re.sub(r"\s+", " ", str(fields["claim"]).strip().lower())
            for p, f2, _b in pages:
                if re.sub(r"\s+", " ", str(f2["claim"]).strip().lower()) == norm:
                    problems.append(
                        f"{dp}: claim duplicates the claim page "
                        f"{p.relative_to(ROOT).as_posix()} — measure an "
                        f"outcome on the existing page instead of "
                        f"restating the claim")
    print(f"claim pages: {len(pages)}   outcomes recorded: {len(outcomes)}")
    for p, fields, _b in pages:
        rel = p.relative_to(ROOT).as_posix()
        recs = by_page.get(rel, [])
        exp = counters_for(recs)
        print(f"  {rel}: {exp['outcome_status']} "
              f"(n={exp['outcome_n']}, supports={exp['outcome_supports']}, "
              f"contradicts={exp['outcome_contradicts']}) — {fields['claim']}")
    if problems:
        print(f"\nPROBLEMS ({len(problems)}):")
        for pr in problems:
            print(f"  - {pr}")
        return 1
    print("check: OK")
    return 0


def _set_fm_fields(text, updates):
    """Set scalar fields in the frontmatter block of `text`,
    preserving everything else byte-for-byte. Fields that do not
    exist yet are inserted before the closing fence, after the
    claim line when there is one."""
    m = re.match(r"^(---\n)(.*?)(\n---\n?)", text, re.S)
    if not m:
        raise ValueError("page has no frontmatter block")
    head, fm, tail = m.group(1), m.group(2), m.group(3)
    lines = fm.split("\n")
    remaining = dict(updates)
    for i, line in enumerate(lines):
        km = re.match(r"^([A-Za-z_]+):", line)
        if km and km.group(1) in remaining:
            lines[i] = f"{km.group(1)}: {remaining.pop(km.group(1))}"
    if remaining:
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("claim:"):
                insert_at = i + 1
                break
        for key in CLAIM_FIELDS:
            if key in remaining:
                lines.insert(insert_at, f"{key}: {remaining.pop(key)}")
                insert_at += 1
        for key, val in remaining.items():
            lines.insert(insert_at, f"{key}: {val}")
            insert_at += 1
    return head + "\n".join(lines) + tail + text[m.end():]


def cmd_measure(args):
    page = (ROOT / args.page).resolve()
    if not page.is_file() or ROOT not in page.parents:
        print(f"page not found in repo: {args.page}")
        return 1
    rel = page.relative_to(ROOT).as_posix()
    text = page.read_text(encoding="utf-8")
    fields, _body = parse_frontmatter(text)
    if not fields or not fields.get("claim"):
        print(f"{rel}: not a claim page (no claim: frontmatter) — "
              f"opt the page into the lifecycle first")
        return 1
    when = args.date or date.today().isoformat()
    if _wv.parse_date(when) is None:
        print(f"bad --date: {when!r}")
        return 1
    record = {"page": rel, "date": when, "outcome": args.outcome,
              "note": args.note or ""}
    if args.generator_model is not None or args.verifier_model is not None:
        import wiki_model_provenance as _mp
        try:
            record.update(_mp.provenance_fields(
                args.generator_model, args.verifier_model))
        except ValueError as exc:
            print(str(exc)); return 1
    OUTCOMES.parent.mkdir(parents=True, exist_ok=True)
    with OUTCOMES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    records = [r for r in load_outcomes() if r["page"] == rel]
    updates = counters_for(records)
    updates["updated"] = when
    page.write_text(_set_fm_fields(text, updates), encoding="utf-8")
    print(f"recorded {args.outcome} for {rel} ({when})")
    print(f"  n={updates['outcome_n']} supports={updates['outcome_supports']} "
          f"contradicts={updates['outcome_contradicts']} "
          f"-> status: {updates['outcome_status']}")
    return 0


def cmd_list(args):
    outcomes = load_outcomes()
    by_page = {}
    for r in outcomes:
        by_page.setdefault(r["page"], []).append(r)
    pages = claim_pages()
    if not pages:
        print("no claim pages yet — a page opts in with claim: frontmatter")
        return 0
    for p, fields, _b in pages:
        rel = p.relative_to(ROOT).as_posix()
        exp = counters_for(by_page.get(rel, []))
        print(f"{rel}: {exp['outcome_status']} (n={exp['outcome_n']}) "
              f"as_of={fields.get('as_of')} — {fields['claim']}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Outcome-verified claim lifecycle.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="verify claim pages against the outcomes log")
    p_check.add_argument("draft", nargs="?", default=None,
                         help="optional draft page to hold against the rules")
    p_meas = sub.add_parser("measure", help="record a real-world outcome")
    p_meas.add_argument("--page", required=True, help="repo-relative claim page path")
    p_meas.add_argument("--outcome", choices=("supports", "contradicts"), required=True)
    p_meas.add_argument("--note", default="")
    p_meas.add_argument("--date", default=None)
    p_meas.add_argument("--generator-model", default=None,
                        help="model that generated the claim (Marathon "
                             "R8 model-identity provenance; must be given "
                             "with --verifier-model)")
    p_meas.add_argument("--verifier-model", default=None,
                        help="model measuring this outcome; equal to "
                             "the generator flags the line report-only")
    sub.add_parser("list", help="list claim pages and statuses")
    args = ap.parse_args(argv[1:])
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "measure":
        return cmd_measure(args)
    return cmd_list(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
