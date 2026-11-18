#!/usr/bin/env python3
"""Per-claim re-verification scheduling (FSRS-inspired).

WikiCitadel v1 (pattern: FSRS-6 / the DSR
model — Difficulty, Stability, Retrievability — as used by
spaced-repetition schedulers). The claim lifecycle
(scripts/wiki_claims.py) records what reality said about a
claim (outcomes); this tool schedules when a claim should be
RE-CHECKED against its sources, and keeps the verification
history that schedule is computed from. The two logs are
different records: an outcome is reality's say, a verification
is an agent or the owner re-reading the claim against its
evidence and finding it still standing (pass), no longer
standing (fail), or standing in altered form (changed).

History: evaluation/reverify-history.jsonl — append-only, one
JSON object per line:

    {"claim": "wiki/<page>.md", "date": "YYYY-MM-DD",
     "outcome": "pass" | "fail" | "changed",
     "note": "...", "source": "manual" | "seed:outcomes.jsonl"}

`claim` is the claim page's repo-relative path — the claim
registry is the set of pages carrying `claim:` frontmatter,
the same rule scripts/wiki_claims.py uses.

The scheduler (a documented simplification of FSRS-6, not the
fitted model — this corpus is far too small to fit parameters,
so the constants below are stated policy, not measurements):

  Difficulty D in [1, 10], starts at 5.0 for an unverified
  claim. pass: D -= 0.3 (floor 1). changed: D += 0.4.
  fail: D += 0.8 (cap 10).

  Stability S in days — the interval over which predicted
  retrievability decays to 0.90. Starts at S0 = 7 days for an
  unverified claim, anchored at the claim's `as_of` (the date
  it was last stated). On each verification, folded in date
  order:
    pass:    S *= (2.0 - 0.08 * D)   [D after this event's
             difficulty update; at D=5 the factor is 1.6, and
             easier claims grow faster — a pass streak
             lengthens the interval]
    changed: S *= 0.7                [stands, but altered:
             re-check sooner]
    fail:    S *= 0.3, floored at 1 day   [post-lapse]

  Retrievability after t days at stability S (the FSRS
  forgetting curve):  R(t) = (1 + t / (9 * S)) ** -1.
  The next check falls due when R decays to 0.90, which the
  curve reaches at t = S — so due = last anchor + round(S)
  days, with the anchor being the latest verification date,
  or `as_of` when the claim has never been verified.

Operations:

  record   Append one verification event for a claim page
           (--page, --outcome pass|fail|changed, --date,
           --note). The page must carry claim: frontmatter.
  seed     Convert evaluation/outcomes.jsonl into history
           (supports -> pass, contradicts -> fail, marked
           source "seed:outcomes.jsonl"). Idempotent: a
           (claim, date, outcome, source) tuple already in
           the history is not appended twice.
  due      The schedule for every claim: difficulty,
           stability, last verified, due date, current
           retrievability — overdue first, then due today,
           then upcoming by due date. --json for machines.

Sweep wiring (documented, not installed — no cron is edited
by this build): the nightly sweep already runs the lint
lanes, and Lane 2 of scripts/wiki_lint_lanes.py surfaces due
and overdue claims from this module in-process. A caller that
wants the raw list runs `python3 scripts/wiki_reverify.py
due --json`.

Stdlib only.
"""
import argparse
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
HISTORY = ROOT / "evaluation" / "reverify-history.jsonl"
OUTCOMES = ROOT / "evaluation" / "outcomes.jsonl"

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter = _wv.parse_frontmatter
parse_date = _wv.parse_date

OUTCOMES_VOCAB = ("pass", "fail", "changed")
SEED_MAP = {"supports": "pass", "contradicts": "fail"}

D_START = 5.0
D_MIN, D_MAX = 1.0, 10.0
D_STEP = {"pass": -0.3, "changed": 0.4, "fail": 0.8}
S_START = 7.0
S_FLOOR = 1.0
S_FACTOR = {"changed": 0.7, "fail": 0.3}
R_TARGET = 0.90


# -- registry + history ----------------------------------------------------

def claim_pages():
    """[(path, fields)] for wiki pages carrying a claim — the
    same registry rule as scripts/wiki_claims.py."""
    out = []
    if not WIKI.exists():
        return out
    for p in sorted(WIKI.rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("wiki/access/") or rel in ("wiki/index.md",
                                                     "wiki/log.md"):
            continue
        fields, _body = parse_frontmatter(
            p.read_text(encoding="utf-8", errors="ignore"))
        if fields and fields.get("claim"):
            out.append((p, fields))
    return out


def load_history():
    if not HISTORY.exists():
        return []
    out = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_history(record):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# -- the scheduler (pure) ----------------------------------------------------

def fold_history(events):
    """Fold one claim's verification events (any order; sorted
    by date here, stable) into (difficulty, stability)."""
    d, s = D_START, S_START
    for ev in sorted(events, key=lambda e: str(e.get("date") or "")):
        outcome = ev.get("outcome")
        if outcome not in OUTCOMES_VOCAB:
            continue
        d = min(D_MAX, max(D_MIN, d + D_STEP[outcome]))
        if outcome == "pass":
            s = s * (2.0 - 0.08 * d)
        else:
            s = max(S_FLOOR, s * S_FACTOR[outcome])
    return d, s


def retrievability(days_elapsed, stability):
    """R(t) = (1 + t / (9S)) ** -1 — the FSRS forgetting curve."""
    if stability <= 0:
        return 0.0
    return (1.0 + max(0.0, days_elapsed) / (9.0 * stability)) ** -1


def claim_schedule(fields, events, today):
    """The schedule for one claim. `fields` is the claim page's
    frontmatter, `events` its history records (any order)."""
    d, s = fold_history(events)
    dated = [e for e in events if parse_date(str(e.get("date") or ""))]
    if dated:
        anchor = max(parse_date(str(e["date"])) for e in dated)
        last_verified = anchor
    else:
        anchor = None
        for key in ("as_of", "updated", "created"):
            if fields.get(key):
                anchor = parse_date(str(fields[key]))
                if anchor:
                    break
        last_verified = None
    if anchor is None:
        return {"difficulty": d, "stability": s, "anchor": None,
                "last_verified": last_verified, "due": None,
                "status": "unanchored", "days_overdue": 0,
                "retrievability": None}
    interval = max(1, round(s))
    due = anchor + timedelta(days=interval)
    elapsed = (today - anchor).days
    if due < today:
        status, overdue = "overdue", (today - due).days
    elif due == today:
        status, overdue = "due", 0
    else:
        status, overdue = "upcoming", 0
    return {"difficulty": d, "stability": s, "anchor": anchor,
            "last_verified": last_verified, "due": due,
            "status": status, "days_overdue": overdue,
            "retrievability": retrievability(elapsed, s)}


def due_claims(today):
    """The full schedule: one dict per claim page, overdue
    first (most overdue first), then due today, then upcoming
    by due date; unanchored claims last."""
    history = load_history()
    by_claim = {}
    for ev in history:
        by_claim.setdefault(ev.get("claim"), []).append(ev)
    rows = []
    for p, fields in claim_pages():
        rel = p.relative_to(ROOT).as_posix()
        sched = claim_schedule(fields, by_claim.get(rel, []), today)
        rows.append({"page": rel, "claim": str(fields["claim"]),
                     "as_of": str(fields.get("as_of") or ""),
                     "verifications": len(by_claim.get(rel, [])),
                     **sched})
    rank = {"overdue": 0, "due": 1, "upcoming": 2, "unanchored": 3}
    rows.sort(key=lambda r: (rank[r["status"]],
                             -(r["days_overdue"] or 0)
                             if r["status"] == "overdue" else 0,
                             r["due"] or date.max, r["page"]))
    return rows


# -- commands ------------------------------------------------------------------

def cmd_record(args):  # provenance: wiki_model_provenance.py (R8)
    page = (ROOT / args.page).resolve()
    if not page.is_file() or ROOT not in page.parents:
        print(f"page not found in repo: {args.page}")
        return 1
    rel = page.relative_to(ROOT).as_posix()
    fields, _body = parse_frontmatter(
        page.read_text(encoding="utf-8", errors="ignore"))
    if not fields or not fields.get("claim"):
        print(f"{rel}: not a claim page (no claim: frontmatter) — "
              f"only claims carry a re-verification schedule")
        return 1
    when = args.date or date.today().isoformat()
    if parse_date(when) is None:
        print(f"bad --date: {when!r}")
        return 1
    record = {"claim": rel, "date": when,
              "outcome": args.outcome,
              "note": args.note or "", "source": "manual"}
    if args.generator_model is not None or args.verifier_model is not None:
        import wiki_model_provenance as _mp
        try:
            record.update(_mp.provenance_fields(
                args.generator_model, args.verifier_model))
        except ValueError as exc:
            print(str(exc)); return 1
    append_history(record)
    sched = claim_schedule(fields, [e for e in load_history()
                                    if e.get("claim") == rel],
                           date.today())
    print(f"recorded {args.outcome} for {rel} ({when})")
    print(f"  difficulty={sched['difficulty']:.1f} "
          f"stability={sched['stability']:.1f}d "
          f"next due: {sched['due']}")
    return 0


def cmd_seed(args):
    if not OUTCOMES.exists():
        print("no outcomes log (evaluation/outcomes.jsonl) — "
              "nothing to seed from")
        return 0
    existing = {(e.get("claim"), e.get("date"), e.get("outcome"),
                 e.get("source")) for e in load_history()}
    seeded = 0
    for line in OUTCOMES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        mapped = SEED_MAP.get(rec.get("outcome"))
        if mapped is None:
            continue
        key = (rec.get("page"), rec.get("date"), mapped,
               "seed:outcomes.jsonl")
        if key in existing:
            continue
        existing.add(key)
        append_history({"claim": rec.get("page"),
                        "date": rec.get("date"), "outcome": mapped,
                        "note": rec.get("note") or "",
                        "source": "seed:outcomes.jsonl"})
        seeded += 1
    print(f"seeded {seeded} verification event(s) from "
          f"evaluation/outcomes.jsonl")
    return 0


def _jsonable(row):
    out = dict(row)
    for key in ("anchor", "last_verified", "due"):
        if isinstance(out.get(key), date):
            out[key] = out[key].isoformat()
    if isinstance(out.get("retrievability"), float):
        out["retrievability"] = round(out["retrievability"], 4)
    out["difficulty"] = round(out["difficulty"], 2)
    out["stability"] = round(out["stability"], 2)
    return out


def cmd_due(args):
    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        print(f"bad --today: {args.today!r}")
        return 1
    rows = due_claims(today)
    if args.json:
        print(json.dumps([_jsonable(r) for r in rows], indent=2,
                         ensure_ascii=False))
        return 0
    if not rows:
        print("no claim pages yet — a page opts in with claim: "
              "frontmatter")
        return 0
    print(f"claim re-verification schedule — {today.isoformat()} "
          f"({len(rows)} claim(s), overdue first)")
    for r in rows:
        if r["status"] == "unanchored":
            print(f"  {r['page']}: NO ANCHOR DATE — cannot "
                  f"schedule (claim carries no as_of)")
            continue
        flag = {"overdue": f"OVERDUE {r['days_overdue']}d",
                "due": "DUE TODAY", "upcoming": "upcoming"}[r["status"]]
        last = (r["last_verified"].isoformat()
                if r["last_verified"] else "never (as_of anchor)")
        print(f"  {r['page']}: {flag} — due {r['due'].isoformat()} "
              f"(D={r['difficulty']:.1f}, S={r['stability']:.1f}d, "
              f"R={r['retrievability']:.2f}, "
              f"verifications={r['verifications']}, last={last})")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Per-claim re-verification scheduling "
                    "(FSRS-inspired).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("record", help="record a verification event")
    p_rec.add_argument("--page", required=True,
                       help="repo-relative claim page path")
    p_rec.add_argument("--outcome", choices=OUTCOMES_VOCAB, required=True)
    p_rec.add_argument("--note", default="")
    p_rec.add_argument("--date", default=None)
    p_rec.add_argument("--generator-model", default=None,
                       help="model that generated the claim (Marathon "
                            "R8 model-identity provenance; must be given "
                            "with --verifier-model)")
    p_rec.add_argument("--verifier-model", default=None,
                       help="model performing this verification; a "
                            "verifier equal to the generator flags the "
                            "line report-only (self-verification)")
    sub.add_parser("seed", help="seed history from the outcomes log")
    p_due = sub.add_parser("due", help="the re-verification schedule")
    p_due.add_argument("--today", default=None,
                       help="schedule as of this date (default: today)")
    p_due.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "seed":
        return cmd_seed(args)
    return cmd_due(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
