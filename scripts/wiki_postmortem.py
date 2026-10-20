#!/usr/bin/env python3
"""Post-mortem action-item discipline for the LLM Wiki.

The post-mortems register (evaluation/post-mortems.jsonl,
human copy wiki/filings/post-mortems.md) already records agent
failures: what happened, the root-cause class, the rule that
changed. What it did not do — the failure mode that killed
NASA's LLIS (GAO-02-195; OIG 2012: ~$750k/yr, ~1 lesson/yr at
most centers, "not an effective tool" — via the
survey) — is make lessons TRAVEL: tracked action items with
measurable end-states, a completion metric someone reads,
and lessons pushed into the pages where the work recurs
instead of waiting to be pulled from a register nobody
consults at decision time. This tool is that discipline:

  ACTION ITEMS — every post-mortem's actions are items with
    a tracking id (<PM id>-A<n>), a measurable END STATE
    (a checkable condition, never "be careful"), a CHECK
    (how the end state is observed), an owner
    (agent / owner / system), and a status:
    open -> done -> verified. `done` asserts the work
    happened; `verified` asserts a check observed the end
    state. Both transitions record the date and the
    evidence offered.
  COMPLETION METRIC — `metrics` reports, over trailing
    windows (30d / 90d / all), the item counts by status
    and the % verified (and % done-or-verified). A register
    whose completion ratio is never read repeats LLIS's
    fate at small scale.
  PUSH AT ENTRY — filing a new post-mortem (`add`) prints
    the still-open action items from all earlier entries:
    open items surface at the next related entry, not in a
    report someone must remember to ask for. `open` lists
    them at any time.
  PREMORTEM SCORING — when a post-mortem names the thing
    that failed (failure_subject: a staged proposal file)
    and the failure reason, the tool checks the subject's
    premortem (scripts/wiki_decision_gate.py's
    has_written_premortem): did a written premortem exist,
    and was this reason on its list? Matching is a stated
    heuristic (content-token Jaccard >= 0.25 against the
    premortem's numbered reasons) — it answers "was the
    failure foreseen in writing", never "was the premortem
    good". The result is stored on the entry as
    premortem_check and re-derivable with `premortem-check`.

Usage:
  python3 scripts/wiki_postmortem.py list
  python3 scripts/wiki_postmortem.py add --title T
      --trigger-kind K --trigger-ref R --what-happened W
      --root-cause-class C --rule-changed X
      [--see-also a,b] [--failure-subject PATH]
      [--failure-reason TEXT]
      [--action "END STATE | CHECK | OWNER"] ...
  python3 scripts/wiki_postmortem.py add-action PM-2026-001
      --end-state E --check C --owner agent
  python3 scripts/wiki_postmortem.py actions [--status open]
  python3 scripts/wiki_postmortem.py complete <item-id>
      [--evidence TEXT]
  python3 scripts/wiki_postmortem.py verify <item-id>
      [--evidence TEXT]
  python3 scripts/wiki_postmortem.py metrics [--as-of DATE]
  python3 scripts/wiki_postmortem.py open
  python3 scripts/wiki_postmortem.py premortem-check [PM-id]

Stdlib only. Importable in-process (tests drive the
functions against fixture roots).
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/post-mortems.jsonl"

STATUSES = ("open", "done", "verified")
OWNERS = ("agent", "owner", "system")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""the a an and or of to in is are was were be been for on
with as by at from this that it its has have had not no do does did will
would can could should may might must shall than then so such into over
under more most other some any only also just very what did does do is
are was were about""".split())
PREMORTEM_MATCH_JACCARD = 0.25


# -- register I/O -----------------------------------------------------------

def register_path(root=ROOT):
    return Path(root) / REGISTER_REL


def load_entries(root=ROOT):
    path = register_path(root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def save_entries(root, entries):
    path = register_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(e, sort_keys=True) + "\n"
                   for e in entries)
    path.write_text(text, encoding="utf-8")


def next_id(entries, today):
    prefix = f"PM-{today.year}-"
    nums = []
    for e in entries:
        eid = str(e.get("id") or "")
        if eid.startswith(prefix):
            try:
                nums.append(int(eid[len(prefix):]))
            except ValueError:
                continue
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


# -- action items -----------------------------------------------------------

def iter_items(entries):
    """Yield (entry, item) for every action item, register order."""
    for entry in entries:
        for item in entry.get("action_items") or []:
            yield entry, item


def action_items(entries, status=None):
    out = []
    for entry, item in iter_items(entries):
        if status is None or item.get("status") == status:
            out.append({"pm_id": entry.get("id"),
                        "pm_title": entry.get("title"),
                        "pm_date": entry.get("date"),
                        **item})
    return out


def add_action_item(entries, pm_id, end_state, check, owner,
                    today=None):
    """Append an action item to one entry; returns the item.
    Ids are <PM id>-A<n>, n per-entry in filing order."""
    if owner not in OWNERS:
        raise ValueError(f"owner must be one of {OWNERS}")
    if not end_state.strip() or not check.strip():
        raise ValueError("an action item needs a measurable end "
                         "state and the check that observes it")
    for entry in entries:
        if entry.get("id") == pm_id:
            items = entry.setdefault("action_items", [])
            item = {
                "id": f"{pm_id}-A{len(items) + 1}",
                "end_state": end_state.strip(),
                "check": check.strip(),
                "owner": owner,
                "status": "open",
                "filed": (today or date.today()).isoformat(),
                "done_on": None, "done_evidence": None,
                "verified_on": None, "verified_evidence": None,
            }
            items.append(item)
            return item
    raise ValueError(f"no post-mortem {pm_id} on the register")


def set_item_status(entries, item_id, status, evidence=None,
                    today=None):
    """open -> done -> verified (verify may follow done or
    open). Records the date and the evidence offered; the
    end state is what is checked, the evidence is what the
    transition claims — the parent/auditor re-runs checks."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    for _entry, item in iter_items(entries):
        if item.get("id") == item_id:
            when = (today or date.today()).isoformat()
            item["status"] = status
            if status in ("done", "verified"):
                item["done_on"] = item.get("done_on") or when
                if evidence and not item.get("done_evidence"):
                    item["done_evidence"] = evidence
            if status == "verified":
                item["verified_on"] = when
                if evidence:
                    item["verified_evidence"] = evidence
            return item
    raise ValueError(f"no action item {item_id} on the register")


# -- completion metric ------------------------------------------------------

def completion_metrics(entries, as_of=None, windows=(30, 90, None)):
    """Per trailing window: items filed by post-mortems dated
    inside the window, counted by status, with the %
    verified and the % done-or-verified. Windows are read
    off the POST-MORTEM's date (when the lesson was filed),
    so an old register with new items still reads honestly."""
    as_of = as_of or date.today()
    items = action_items(entries)
    out = {}
    for window in windows:
        label = "all" if window is None else f"{window}d"
        if window is None:
            scoped = items
        else:
            cutoff = as_of - timedelta(days=window)
            scoped = []
            for it in items:
                try:
                    filed = date.fromisoformat(
                        str(it.get("pm_date") or "")[:10])
                except ValueError:
                    continue
                if filed >= cutoff:
                    scoped.append(it)
        total = len(scoped)
        by_status = {s: sum(1 for it in scoped
                            if it.get("status") == s)
                     for s in STATUSES}
        out[label] = {
            "total": total, "by_status": by_status,
            "pct_verified": (round(100.0 * by_status["verified"]
                                   / total, 1) if total else None),
            "pct_done_or_verified": (
                round(100.0 * (by_status["done"]
                               + by_status["verified"]) / total, 1)
                if total else None),
        }
    return out


# -- premortem scoring --------------------------------------------------------

def _content_tokens(text):
    return {t for t in TOKEN_RE.findall(str(text).lower())
            if len(t) >= 3 and t not in STOPWORDS}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def premortem_reasons(text):
    """The numbered reasons of a file's premortem section,
    as plain strings (markdown emphasis stripped). The
    section runs from the `## Premortem (YYYY-MM-DD)`
    heading to the next `## ` heading or end of file; its
    reasons are the numbered list items under it (a reason
    may wrap and carry a mitigation after an em dash — the
    whole item is the reason text the failure is matched
    against)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wiki_decision_gate",
        Path(__file__).resolve().parent / "wiki_decision_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    m = gate.PREMORTEM_HEADING_RE.search(text)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    section = rest[:nxt.start()] if nxt else rest
    reasons = []
    current = None
    for line in section.splitlines():
        item = re.match(r"^\d+\.\s+(.*)$", line)
        if item:
            if current is not None:
                reasons.append(current)
            current = item.group(1)
        elif current is not None and line.strip():
            current += " " + line.strip()
    if current is not None:
        reasons.append(current)
    clean = []
    for r in reasons:
        r = re.sub(r"[*_`]+", "", r)
        r = re.sub(r"\s+", " ", r).strip()
        if r:
            clean.append(r)
    return clean


def score_against_premortem(root, subject_rel, failure_reason):
    """Did the failed thing carry a written premortem, and
    was this failure reason on its list? Deterministic and
    stated: token-Jaccard of the failure reason against each
    numbered premortem reason; on-list at >=
    PREMORTEM_MATCH_JACCARD. A proposal with no written
    premortem (none, or the generator placeholder) scores
    premortem_present False — the placeholder is a marker,
    not a premortem."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wiki_decision_gate",
        Path(__file__).resolve().parent / "wiki_decision_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    path = Path(root) / subject_rel
    result = {"subject": subject_rel, "premortem_present": False,
              "reasons_found": 0, "on_list": None,
              "matched_reason": None, "best_jaccard": None}
    if not path.is_file():
        result["note"] = "subject file not found"
        return result
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not gate.has_written_premortem(text):
        return result
    reasons = premortem_reasons(text)
    result["premortem_present"] = True
    result["reasons_found"] = len(reasons)
    want = _content_tokens(failure_reason)
    best, best_idx = 0.0, None
    for i, reason in enumerate(reasons, start=1):
        score = _jaccard(want, _content_tokens(reason))
        if score > best:
            best, best_idx = score, i
    result["best_jaccard"] = round(best, 3)
    result["on_list"] = best >= PREMORTEM_MATCH_JACCARD
    result["matched_reason"] = best_idx if result["on_list"] else None
    return result


def premortem_checks(root, entries):
    """Score every register entry that names a failure
    subject + reason. Returns one row per such entry."""
    rows = []
    for entry in entries:
        subject = entry.get("failure_subject")
        reason = entry.get("failure_reason")
        if not subject or not reason:
            continue
        scored = score_against_premortem(root, subject, reason)
        rows.append({"pm_id": entry.get("id"), **scored,
                     "stored": entry.get("premortem_check")})
    return rows


# -- filing -------------------------------------------------------------------

def file_postmortem(root, fields, actions=(), today=None):
    """Append one entry to the register. Returns
    (entry, still_open) where still_open is every action
    item left open by EARLIER entries — the push: open
    items surface at the next related entry (LLIS's
    remedy was dissemination, not storage). When the
    entry names a failure subject + reason, its
    premortem_check is computed and stored."""
    entries = load_entries(root)
    today = today or date.today()
    entry = {
        "id": next_id(entries, today),
        "date": today.isoformat(),
        "title": fields["title"],
        "trigger_kind": fields["trigger_kind"],
        "trigger_ref": fields["trigger_ref"],
        "what_happened": fields["what_happened"],
        "root_cause_class": fields["root_cause_class"],
        "rule_changed": fields["rule_changed"],
    }
    if fields.get("see_also"):
        entry["see_also"] = fields["see_also"]
    if fields.get("failure_subject"):
        entry["failure_subject"] = fields["failure_subject"]
    if fields.get("failure_reason"):
        entry["failure_reason"] = fields["failure_reason"]
    entry["action_items"] = []
    entries.append(entry)
    for end_state, check, owner in actions:
        add_action_item(entries, entry["id"], end_state, check,
                        owner, today=today)
    if entry.get("failure_subject") and entry.get("failure_reason"):
        entry["premortem_check"] = score_against_premortem(
            root, entry["failure_subject"], entry["failure_reason"])
    still_open = [it for it in action_items(entries, status="open")
                  if it["pm_id"] != entry["id"]]
    save_entries(root, entries)
    return entry, still_open


def _fmt_open(items):
    if not items:
        return ["Open action items from earlier post-mortems: none."]
    lines = ["Open action items from earlier post-mortems "
             "(surfaced at this entry — the push, not a pull):"]
    for it in items:
        lines.append(f"  [{it['status']}] {it['id']} ({it['owner']})"
                     f" — {it['end_state']}")
        lines.append(f"      check: {it['check']}")
    return lines


# -- CLI ----------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Post-mortem action-item discipline: "
                    "tracked items, completion metric, push at "
                    "entry, premortem scoring.")
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="register entries + item counts")
    p_open = sub.add_parser("open", help="still-open action items")
    p_open.add_argument("--status", default="open",
                        choices=STATUSES)

    p_add = sub.add_parser("add", help="file a new post-mortem")
    for flag in ("--title", "--trigger-kind", "--trigger-ref",
                 "--what-happened", "--root-cause-class",
                 "--rule-changed"):
        p_add.add_argument(flag, required=True)
    p_add.add_argument("--see-also", default="")
    p_add.add_argument("--failure-subject", default="")
    p_add.add_argument("--failure-reason", default="")
    p_add.add_argument("--action", action="append", default=[],
                       metavar="END|CHECK|OWNER",
                       help="action item: end state | check | owner")

    p_act = sub.add_parser("add-action",
                           help="add an action item to an entry")
    p_act.add_argument("pm_id")
    p_act.add_argument("--end-state", required=True)
    p_act.add_argument("--check", required=True)
    p_act.add_argument("--owner", required=True, choices=OWNERS)

    for name in ("complete", "verify"):
        p_st = sub.add_parser(name, help=f"mark an item "
                                         f"{'done' if name == 'complete' else 'verified'}")
        p_st.add_argument("item_id")
        p_st.add_argument("--evidence", default="")

    p_met = sub.add_parser("metrics", help="completion metric")
    p_met.add_argument("--as-of", default="")

    p_pm = sub.add_parser("premortem-check",
                          help="score entries against premortems")
    p_pm.add_argument("pm_id", nargs="?")

    args = ap.parse_args(argv[1:])
    root = Path(args.root)
    entries = load_entries(root)

    if args.command == "list":
        for e in entries:
            items = e.get("action_items") or []
            counts = {s: sum(1 for i in items
                             if i.get("status") == s)
                      for s in STATUSES}
            print(f"{e.get('id')}  {e.get('date')}  "
                  f"{e.get('title')}")
            print(f"    action items: {len(items)} "
                  f"(open {counts['open']} · done {counts['done']}"
                  f" · verified {counts['verified']})")
        if not entries:
            print("register is empty")
        return 0

    if args.command == "open":
        items = action_items(entries, status=args.status)
        for line in _fmt_open(items) if args.status == "open" \
                else [f"  [{it['status']}] {it['id']} — "
                      f"{it['end_state']}" for it in items]:
            print(line)
        return 0

    if args.command == "add":
        actions = []
        for raw in args.action:
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) != 3:
                print("error: --action must be "
                      "'END STATE | CHECK | OWNER'", file=sys.stderr)
                return 2
            actions.append(tuple(parts))
        fields = {
            "title": args.title,
            "trigger_kind": args.trigger_kind,
            "trigger_ref": args.trigger_ref,
            "what_happened": args.what_happened,
            "root_cause_class": args.root_cause_class,
            "rule_changed": args.rule_changed,
            "see_also": [s.strip() for s in
                         args.see_also.split(",") if s.strip()],
            "failure_subject": args.failure_subject or None,
            "failure_reason": args.failure_reason or None,
        }
        try:
            entry, still_open = file_postmortem(
                root, fields, actions=actions)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"filed {entry['id']}: {entry['title']}")
        if entry.get("premortem_check"):
            pc = entry["premortem_check"]
            print(f"premortem check: subject {pc['subject']} — "
                  f"written premortem: "
                  f"{'yes' if pc['premortem_present'] else 'no'}"
                  + (f"; failure reason on its list: "
                     f"{'yes (reason ' + str(pc['matched_reason']) + ')' if pc['on_list'] else 'no'}"
                     if pc["premortem_present"] else ""))
        for line in _fmt_open(still_open):
            print(line)
        return 0

    if args.command == "add-action":
        try:
            item = add_action_item(entries, args.pm_id,
                                   args.end_state, args.check,
                                   args.owner)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        save_entries(root, entries)
        print(f"added {item['id']} (open) to {args.pm_id}")
        return 0

    if args.command in ("complete", "verify"):
        status = "done" if args.command == "complete" else "verified"
        try:
            item = set_item_status(entries, args.item_id, status,
                                   evidence=args.evidence or None)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        save_entries(root, entries)
        print(f"{item['id']}: {status}")
        return 0

    if args.command == "metrics":
        as_of = (date.fromisoformat(args.as_of) if args.as_of
                 else date.today())
        metrics = completion_metrics(entries, as_of=as_of)
        print(f"Post-mortem action-item completion (as of {as_of}):")
        for label, m in metrics.items():
            if m["total"] == 0:
                print(f"  trailing {label}: no action items")
                continue
            bs = m["by_status"]
            print(f"  trailing {label}: {m['total']} item(s) — "
                  f"open {bs['open']} · done {bs['done']} · "
                  f"verified {bs['verified']} → "
                  f"{m['pct_verified']}% verified, "
                  f"{m['pct_done_or_verified']}% done-or-verified")
        return 0

    if args.command == "premortem-check":
        rows = premortem_checks(root, entries)
        if args.pm_id:
            rows = [r for r in rows if r["pm_id"] == args.pm_id]
        if not rows:
            print("no entries name a failure subject + reason")
            return 0
        for r in rows:
            verdict = ("no written premortem"
                       if not r["premortem_present"] else
                       f"premortem present ({r['reasons_found']} "
                       f"reasons); failure "
                       f"{'WAS' if r['on_list'] else 'was NOT'} on "
                       f"its list"
                       + (f" (reason {r['matched_reason']}, "
                          f"jaccard {r['best_jaccard']})"
                          if r["on_list"] else
                          f" (best jaccard {r['best_jaccard']})"))
            print(f"{r['pm_id']} → {r['subject']}: {verdict}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
