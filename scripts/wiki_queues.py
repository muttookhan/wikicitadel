#!/usr/bin/env python3
"""Obligation-queue health: inflow caps, drain rates, and the
unopened-queue signal (WikiCitadel v1).

Why this exists — two findings from the PKM
anti-patterns survey (docs/research-notes.md,
finds 19 + 20):

  - Review debt (find 20, the Anki evidence): "Because there
    is no input rate limiting your backlog can grow at an
    unbounded rate." Every admitted obligation is a future
    review; a queue whose intake outruns its clearing
    capacity does not become a backlog, it becomes an
    abandonment. Guard: a stated inflow cap per queue, and a
    warning when additions outpace closures over 14 days.
  - Review avoidance (find 19, the GTD evidence): the
    weekly review is the load-bearing ritual and the most
    skipped. Guard: two consecutive surfacing cycles whose
    items went unacted are a HEALTH SIGNAL ("unopened") to
    surface plainly — never a reason to double the batch.
    Mechanically: an unacted batch is FROZEN. The next
    surfacing carries the same items; obligations that come
    due behind it are counted and named as pending
    admission, not silently added.

Why a sibling tool and not an extension of wiki_reverify.py:
the reverify tool owns ONE queue's schedule (the FSRS claim
schedule: record / seed / due). Queue health is a
cross-queue instrument — it reads the reverify schedule,
the staged-proposal staging area + the ideas board's
Waiting section, and the retention policy's review clock —
and writes its own artefact. Each existing tool keeps its
single surface; this one composes them in-process, the
established pattern (wiki_rot imports wiki_stale the same
way).

The queues:

  reverify          Claim pages on the FSRS schedule
                    (scripts/wiki_reverify.py). Open = every
                    anchored claim (each carries a standing
                    re-verification obligation); due = the
                    overdue + due-today subset — the batch.
                    Additions are dated by a claim's as_of,
                    closures are verification events in
                    evaluation/reverify-history.jsonl.
  decisions         What waits on the owner: staged gateway
                    proposals whose sidecar state is "draft"
                    (staging/proposed/prop-*.json), plus the
                    bullets in wiki/ideas.md's "Waiting for
                    your call" section. Every open item is
                    due (it awaits a ruling). Additions and
                    closures are measured by snapshot diff —
                    a ruled item leaves the set — so they
                    are null until an earlier snapshot old
                    enough exists, and the report says so.
  retention-review  Files whose retention clock has expired
                    with the policy action "review"
                    (evaluation/retention-policy.json, via
                    scripts/wiki_retention.py's own
                    machinery). Open = due = the expired
                    set. Additions are dated by each item's
                    computed expiry date; closures by
                    snapshot diff (null until measurable).
                    Erase-eligible items are NOT this queue:
                    erasure is the owner's certificated act,
                    not a review obligation.

Inflow caps (stated policy, not measurements — the same
status as wiki_reverify.py's FSRS constants): new
obligations admitted per week — reverify 5, decisions 5,
retention-review 10. The 5s mirror the owner's demonstrated
review serving (the weekly five decisions); the 10 is
agent-side labour, reviewed in batches by the agent and
only surfaced. Exceeding a cap is a warning in the report,
never a refusal: this tool reports, it does not gate.

The artefact: evaluation/queue-health.json — both the
report and the state the mechanics need (per-date snapshots
of each queue's open/due item ids, and each queue's current
batch). One snapshot per date; a same-date re-run replaces
that date's snapshot. A surfacing cycle = one snapshot
date. The batch mechanics:

  - A queue's batch is its due set when first surfaced.
  - The batch re-forms only when a batch item is ACTED on
    (reverify: a verification event for it lands in the
    history; decisions / retention-review: it leaves the
    open set). Until then the batch is frozen: the report
    lists the batch items, and names due items held behind
    it as pending admission.
  - Health is "unopened" when a non-empty batch has been
    surfaced on >= 2 snapshot dates with zero actions on
    its items since it formed. Health is "ok" otherwise.

Commands:

  report   Compute the queues, update the artefact
           (unless --no-write), and print the report.
           --today D computes as of D (default: today).
           --root R overrides the repo root (the reverify
           adapter reads the sibling module's own repo —
           the same tree in every real layout).

Exit codes: 0 = report ran (warnings are findings in the
report, not failures); 2 = usage error.
Stdlib only (sibling tools imported in-process).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
ARTEFACT_REL = "evaluation/queue-health.json"

CAPS_PER_WEEK = {"reverify": 5, "decisions": 5,
                 "retention-review": 10}
QUEUES = ("reverify", "decisions", "retention-review")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reverify = _load("wiki_reverify")
retention = _load("wiki_retention")


def _parse_date(value):
    if not value:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)),
                    int(m.group(3)))
    except ValueError:
        return None


def _in_window(day, today, days):
    """day in (today - days, today] — the trailing window."""
    return day is not None and today - timedelta(days=days) < day <= today


# -- adapters: each returns {items, due, added_dates, closure_dates,
#    actions} where dates are lists of `date`; snapshot-diff queues
#    return added_dates/closure_dates = None (measured generically).
#    `actions` = [(item_id, date)] dated acts ON items, for the
#    batch mechanics (reverify only; others use set departure).

def reverify_adapter(today):
    rows = reverify.due_claims(today)
    items, due, added = [], [], []
    for r in rows:
        if r["status"] == "unanchored":
            continue
        items.append(r["page"])
        if r["status"] in ("overdue", "due"):
            due.append(r["page"])
        added.append(_parse_date(r.get("as_of")))
    events = reverify.load_history()
    closures, actions = [], []
    for ev in events:
        day = _parse_date(ev.get("date"))
        if day is None:
            continue
        closures.append(day)
        if ev.get("claim"):
            actions.append((ev["claim"], day))
    return {"items": sorted(items), "due": sorted(due),
            "added_dates": added, "closure_dates": closures,
            "actions": actions,
            "detail": {r["page"]: r["status"] for r in rows
                       if r["status"] != "unanchored"}}


def decisions_adapter(root, today):
    items = {}   # id -> since date or None
    proposed = root / "staging" / "proposed"
    if proposed.is_dir():
        for sidecar in sorted(proposed.glob("prop-*.json")):
            try:
                data = json.loads(
                    sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("state") != "draft":
                continue   # promoted / otherwise ruled: not waiting
            md = sidecar.with_suffix(".md")
            rel = md.relative_to(root).as_posix()
            items[rel] = _parse_date(data.get("submitted_at"))
    ideas = root / "wiki" / "ideas.md"
    if ideas.is_file():
        text = ideas.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^## Waiting for your call\s*$", text, re.M)
        if m:
            section = text[m.end():]
            nxt = re.search(r"^## ", section, re.M)
            if nxt:
                section = section[:nxt.start()]
            for line in section.splitlines():
                line = line.strip()
                if not line.startswith("- "):
                    continue
                title = re.search(r"\*\*(.+?)\*\*", line)
                label = (title.group(1) if title
                         else line[2:60]).strip()
                slug = re.sub(r"[^a-z0-9]+", "-",
                              label.lower()).strip("-")[:48]
                items[f"wiki/ideas.md#waiting:{slug}"] = None
    ids = sorted(items)
    return {"items": ids, "due": list(ids),
            "added_dates": None, "closure_dates": None,
            "actions": [],
            "detail": {i: (items[i].isoformat() if items[i]
                           else "undated") for i in ids}}


def retention_adapter(root, today):
    policy = retention.load_policy(root / retention.POLICY_REL)
    classes = policy["classes"]
    add_dates = retention.git_add_dates(root)
    items, added = [], []
    for rel in retention.iter_record_files(root):
        cls = retention.classify(rel, classes)
        if cls is None or cls.get("on_expiry") != "review":
            continue
        filed, _basis = retention.filed_date(root, rel, add_dates)
        expiry = retention.expiry_for(cls, filed)
        if expiry is not None and expiry <= today:
            items.append(rel)
            added.append(expiry)
    return {"items": sorted(items), "due": sorted(items),
            "added_dates": added, "closure_dates": None,
            "actions": [], "detail": {}}


ADAPTERS = {"reverify": lambda root, today: reverify_adapter(today),
            "decisions": decisions_adapter,
            "retention-review": retention_adapter}


# -- rates ---------------------------------------------------------------------

def _count_window(dates, today, days):
    if dates is None:
        return None
    return sum(1 for d in dates if _in_window(d, today, days))


def _snapshot_near(history, queue, today, days):
    """The latest snapshot dated <= today - days + 1 ... precisely:
    the most recent snapshot whose date is at least `days` before
    today, or None."""
    target = today - timedelta(days=days)
    best = None
    for snap in history:
        day = _parse_date(snap.get("date"))
        if day is not None and day <= target:
            if best is None or day > _parse_date(best["date"]):
                best = snap
    if best is None:
        return None
    return best["queues"].get(queue)


def _diff_rates(history, queue, current_ids, today, days):
    """(added, closed) by snapshot diff, or (None, None) when no
    snapshot old enough exists to diff against."""
    old = _snapshot_near(history, queue, today, days)
    if old is None:
        return None, None
    old_ids = set(old.get("open", []))
    now_ids = set(current_ids)
    return len(now_ids - old_ids), len(old_ids - now_ids)


def queue_metrics(name, data, history, today):
    added7 = _count_window(data["added_dates"], today, 7)
    added14 = _count_window(data["added_dates"], today, 14)
    closed7 = _count_window(data["closure_dates"], today, 7)
    closed14 = _count_window(data["closure_dates"], today, 14)
    if added7 is None or closed7 is None:
        d7 = _diff_rates(history, name, data["items"], today, 7)
        if added7 is None:
            added7 = d7[0]
        if closed7 is None:
            closed7 = d7[1]
    if added14 is None or closed14 is None:
        d14 = _diff_rates(history, name, data["items"], today, 14)
        if added14 is None:
            added14 = d14[0]
        if closed14 is None:
            closed14 = d14[1]
    net7 = (added7 - closed7
            if added7 is not None and closed7 is not None else None)
    warnings = []
    if (added14 is not None and closed14 is not None
            and added14 > closed14):
        warnings.append(
            f"additions outpace closures over 14 days "
            f"(added {added14}, closed {closed14}) — the review-debt"
            f" pattern: intake without a drain ends in abandonment")
    cap = CAPS_PER_WEEK[name]
    if added7 is not None and added7 > cap:
        warnings.append(
            f"inflow cap exceeded: {added7} admitted in 7 days,"
            f" cap is {cap}/week")
    return {"open": len(data["items"]), "due": len(data["due"]),
            "added_7d": added7, "closed_7d": closed7,
            "added_14d": added14, "closed_14d": closed14,
            "net_7d": net7, "cap_per_week": cap,
            "warnings": warnings}


# -- batch mechanics -------------------------------------------------------------

def update_batch(name, data, prev_batch, history, today):
    """The frozen-batch rule. Returns (batch, health,
    pending_admission). `history` includes today's snapshot."""
    due = list(data["due"])
    if not prev_batch or not prev_batch.get("items"):
        batch = {"formed": today.isoformat(), "items": due}
        acted = False
    else:
        batch = {"formed": prev_batch["formed"],
                 "items": list(prev_batch["items"])}
        formed = _parse_date(batch["formed"])
        acted = False
        for item, day in data["actions"]:
            if item in batch["items"] and formed and day > formed:
                acted = True
        if not data["actions"]:
            # Snapshot-diff queues: an item leaving the open set
            # IS the action on it.
            gone = [i for i in batch["items"]
                    if i not in set(data["items"])]
            acted = bool(gone)
        if acted:
            batch = {"formed": today.isoformat(), "items": due}
    pending = [i for i in due if i not in set(batch["items"])]
    cycles = sum(1 for snap in history
                 if (_parse_date(snap.get("date")) or date.min)
                 >= (_parse_date(batch["formed"]) or date.min))
    closures_since = 0
    formed = _parse_date(batch["formed"])
    for item, day in data["actions"]:
        if item in batch["items"] and formed and day > formed:
            closures_since += 1
    if not data["actions"]:
        closures_since = sum(
            1 for i in batch["items"] if i not in set(data["items"]))
    health = "ok"
    if batch["items"] and cycles >= 2 and closures_since == 0 \
            and not acted:
        health = "unopened"
    return batch, health, pending, cycles


# -- report -----------------------------------------------------------------------

def build_report(root, today, prev):
    history = list(prev.get("history", [])) if prev else []
    batches_prev = prev.get("batches", {}) if prev else {}
    snapshot = {"date": today.isoformat(), "queues": {}}
    queues, batches, datas = {}, {}, {}
    for name in QUEUES:
        data = ADAPTERS[name](root, today)
        datas[name] = data
        snapshot["queues"][name] = {
            "open": data["items"], "due": data["due"]}
        metrics = queue_metrics(name, data, history, today)
        queues[name] = {**metrics, "items": data["items"],
                        "due_items": data["due"],
                        "detail": data["detail"]}
    # Replace/append today's snapshot, then batches (they count
    # surfacing cycles from the snapshot history).
    history = [s for s in history
               if s.get("date") != today.isoformat()] + [snapshot]
    history.sort(key=lambda s: s["date"])
    for name in QUEUES:
        data = datas[name]
        batch, health, pending, cycles = update_batch(
            name, data, batches_prev.get(name), history, today)
        batches[name] = batch
        queues[name].update({
            "batch": batch, "health": health,
            "pending_admission": pending,
            "surfacing_cycles_on_batch": cycles})
    return {"kind": "queue-health", "version": 1,
            "generated": today.isoformat(),
            "caps_per_week": CAPS_PER_WEEK,
            "queues": queues, "batches": batches,
            "history": history}


def _fmt(value):
    return "n/a" if value is None else str(value)


def render(rep):
    lines = [f"Obligation-queue health — {rep['generated']}", ""]
    for name in QUEUES:
        q = rep["queues"][name]
        lines.append(f"## {name} (cap {q['cap_per_week']}/week)")
        lines.append(
            f"  open {q['open']} · due {q['due']} ·"
            f" added-7d {_fmt(q['added_7d'])} ·"
            f" closed-7d {_fmt(q['closed_7d'])} ·"
            f" net-7d {_fmt(q['net_7d'])} ·"
            f" added-14d {_fmt(q['added_14d'])} ·"
            f" closed-14d {_fmt(q['closed_14d'])}")
        lines.append(
            f"  HEALTH: {q['health']} · batch of"
            f" {len(q['batch']['items'])} formed"
            f" {q['batch']['formed']} · surfaced"
            f" {q['surfacing_cycles_on_batch']} cycle(s)")
        if q["health"] == "unopened":
            lines.append(
                "  the batch has been surfaced unacted through"
                " >= 2 cycles — surfaced as a health signal;"
                " the next surfacing carries THE SAME items"
                " (never a doubled batch):")
            for item in q["batch"]["items"]:
                lines.append(f"    - {item}")
        if q["pending_admission"]:
            lines.append(
                f"  pending admission (due, held behind the"
                f" frozen batch): {len(q['pending_admission'])}")
            for item in q["pending_admission"]:
                lines.append(f"    - {item}")
        for w in q["warnings"]:
            lines.append(f"  WARN: {w}")
        lines.append("")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Obligation-queue health: inflow caps,"
                    " drain rates, unopened-queue signal"
                    " .")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rep = sub.add_parser("report", help="compute + file the"
                                        " queue-health report")
    p_rep.add_argument("--today", default=None)
    p_rep.add_argument("--root", default=None)
    p_rep.add_argument("--no-write", action="store_true",
                       help="print only; do not update the"
                            " artefact or the snapshot history")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    today = _parse_date(args.today) if args.today else date.today()
    if today is None:
        print(f"bad --today: {args.today!r}")
        return 2
    artefact = root / ARTEFACT_REL
    prev = None
    if artefact.is_file():
        try:
            prev = json.loads(artefact.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
    rep = build_report(root, today, prev)
    if not args.no_write:
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text(
            json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    print(render(rep), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
