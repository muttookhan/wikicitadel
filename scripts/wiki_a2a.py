#!/usr/bin/env python3
"""wiki_a2a.py — the A2A handoff vocabulary + agent
cards (implementation wave 2026-10-22, wave 6; build-list
item "Anchored review threads + A2A handoff vocabulary
and agent cards").

Clean re-implementation. Idea source: the A2A
(Agent2Agent) protocol (Apache-2.0 — signed Agent Cards
as a capability directory and a formal Task lifecycle;
per the build list's licence route the pattern is
adapted, no code taken). The gap this closes is the one
the gap map names: no shared lifecycle vocabulary across
our queues, and "waiting on a decision" vs "waiting on
a grant" undistinguished. No transport is built and
nothing is sent anywhere: the vocabulary governs RECORDS
in this repo, the way the handoff register's does.

THE VOCABULARY (closed). A review message between
agents is a record in the append-only register
evaluation/review-messages.jsonl (the handoff
register's shape: a header line, then one JSON object
per record; created by the first message recorded).
Every message carries the base fields

  id (rm-NNNNNN), act, from, to, state, date, summary

plus its act's required fields:

  request-review      page
      Ask the receiver to review a page. Opens in
      state `submitted`.
  raise-finding       page, finding
      Put a finding on a page (optionally anchored to
      a passage via thread_id once a thread stands).
  contest-finding     in_reply_to, grounds
      Dispute a finding or a resolution, with the
      grounds stated — never a bare disagreement.
  propose-resolution  thread_id, resolution
      Propose the resolution of a review thread.
  accept-resolution   thread_id
      Accept a proposed resolution. The thread itself
      resolves only by the resolution record in
      scripts/wiki_review_threads.py — this act is the
      receiver's agreement on the record.
  reject-resolution   thread_id, grounds
      Refuse a proposed resolution, grounds stated.
  hand-off            task, scope
      Hand a piece of work to the receiver, scope
      stated (governing rule 5: the handover completes
      only with the receiver's own synthesis, recorded
      in the handoff register — this act opens it).

Optional on any message: page, thread_id, in_reply_to,
note. NO other fields: an unknown field, an act outside
the vocabulary, a missing required field, or a state
outside the lifecycle is a NAMED REFUSAL
(unknown-field:<f> / unknown-act:<a> /
missing-field:<f> / unknown-state:<s>), never a silent
pass.

THE LIFECYCLE (the A2A Task states, restated): every
message carries one — submitted · working ·
input-required (waiting on a decision — a ruling owed)
· auth-required (waiting on a grant — a permission
owed) · completed · rejected · failed · canceled. The
input-required / auth-required pair is the distinction
the gap map found missing.

AGENT CARDS. evaluation/agent-cards.jsonl is the
machine-readable directory: one card per agent
{agent, name, role, exposure, may_send, may_receive,
tools, declared_on}. Least-privilege form, per the
build-list spec: exactly ONE public card (agent, the
operator whose inbox is the wiki's door); every other
agent is internal-loopback — reachable only through
this repo's own records, no external endpoint declared.
`tools` names the validated doors the role may use —
a card grants nothing by itself; it DECLARES the
interface, and the message checker holds agents to it:
a message whose sender's card does not list the act
under may_send is refused (act-not-permitted), as is a
message from an uncarded agent (sender-not-carded).
The owner is a participant, not an agent: messages may
name "owner" as from/to without a card — his rulings
stand in chat (the schema's rule), these records never
carry one for him.

DETERMINISM: no wall clock. Dates and ids are the
caller's recorded acts; check/cards/vocabulary outputs
are pure functions of the registers.

Usage:
  python3 scripts/wiki_a2a.py vocabulary [--json]
  python3 scripts/wiki_a2a.py cards [--json]
  python3 scripts/wiki_a2a.py seed-cards
  python3 scripts/wiki_a2a.py record MSG.json
  python3 scripts/wiki_a2a.py check [--json]
  (all take [--root DIR])

Exit codes: 0 done / no findings · 1 findings or a
refused record · 2 usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
MESSAGES_REL = "evaluation/review-messages.jsonl"
CARDS_REL = "evaluation/agent-cards.jsonl"
OWNER = "owner"

MESSAGE_ID = re.compile(r"^rm-\d{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The A2A Task lifecycle, restated in our words.
TASK_STATES = ("submitted", "working", "input-required",
               "auth-required", "completed", "rejected",
               "failed", "canceled")
STATE_MEANINGS = {
    "submitted": "lodged, not yet taken up",
    "working": "the receiver is working it",
    "input-required": "waiting on a decision — a "
                      "ruling or an answer is owed",
    "auth-required": "waiting on a grant — a "
                     "permission or a credential is "
                     "owed",
    "completed": "done, on the record",
    "rejected": "refused, grounds on the record",
    "failed": "attempted and failed, the failure on "
              "the record",
    "canceled": "withdrawn by its sender",
}

BASE_FIELDS = ("id", "act", "from", "to", "state",
               "date", "summary")
ACTS = {
    "request-review": {
        "summary": "ask the receiver to review a page",
        "required": ("page",)},
    "raise-finding": {
        "summary": "put a finding on a page",
        "required": ("page", "finding")},
    "contest-finding": {
        "summary": "dispute a finding or resolution, "
                   "grounds stated",
        "required": ("in_reply_to", "grounds")},
    "propose-resolution": {
        "summary": "propose the resolution of a "
                   "review thread",
        "required": ("thread_id", "resolution")},
    "accept-resolution": {
        "summary": "accept a proposed resolution",
        "required": ("thread_id",)},
    "reject-resolution": {
        "summary": "refuse a proposed resolution, "
                   "grounds stated",
        "required": ("thread_id", "grounds")},
    "hand-off": {
        "summary": "hand a piece of work to the "
                   "receiver, scope stated",
        "required": ("task", "scope")},
}
OPTIONAL_FIELDS = ("page", "thread_id", "in_reply_to",
                   "note")
ALLOWED_FIELDS = frozenset(
    ("kind",) + BASE_FIELDS
    + tuple(f for a in ACTS.values() for f in a["required"])
    + OPTIONAL_FIELDS)

EXPOSURES = ("public", "internal-loopback")

ALL_ACTS = sorted(ACTS)
# The declared directory, seeded by `seed-cards` from
# the standing record: the traversal door's admitted
# identities (scripts/wiki_traverse.py) and the filings
# seats (wiki/filings/). A card declares an interface;
# it grants nothing.
SEED_CARDS = [
    {"agent": "agent", "name": "Agent",
     "role": "operator — keeps the wiki, runs the "
             "filings pickup, integrates the agents' "
             "work",
     "exposure": "public",
     "may_send": ALL_ACTS, "may_receive": ALL_ACTS,
     "tools": ["gateway:propose", "gateway:publish",
               "traverse:read", "filings:pickup",
               "review:center"],
     "declared_on": "2026-10-22"},
    {"agent": "galen", "name": "Galen",
     "role": "filings seat — files "
             "insights and proposals for the owner's "
             "ruling",
     "exposure": "internal-loopback",
     "may_send": ["request-review", "raise-finding",
                  "contest-finding",
                  "propose-resolution",
                  "accept-resolution",
                  "reject-resolution"],
     "may_receive": ALL_ACTS,
     "tools": ["filings:file"],
     "declared_on": "2026-10-22"},
    {"agent": "hugo", "name": "Hugo",
     "role": "filings seat — files "
             "audits and proposals for the owner's "
             "ruling",
     "exposure": "internal-loopback",
     "may_send": ["request-review", "raise-finding",
                  "contest-finding",
                  "propose-resolution",
                  "accept-resolution",
                  "reject-resolution"],
     "may_receive": ALL_ACTS,
     "tools": ["filings:file"],
     "declared_on": "2026-10-22"},
    {"agent": "codex", "name": "Codex",
     "role": "admitted traversal-door identity; no "
             "review seat declared yet",
     "exposure": "internal-loopback",
     "may_send": [], "may_receive": [],
     "tools": ["traverse:read"],
     "declared_on": "2026-10-22"},
    {"agent": "chatgpt", "name": "ChatGPT Coordinator",
     "role": "admitted traversal-door identity; no "
             "review seat declared yet",
     "exposure": "internal-loopback",
     "may_send": [], "may_receive": [],
     "tools": ["traverse:read"],
     "declared_on": "2026-10-22"},
    {"agent": "coordinator", "name": "Coordinator",
     "role": "admitted traversal-door identity; no "
             "review seat declared yet",
     "exposure": "internal-loopback",
     "may_send": [], "may_receive": [],
     "tools": ["traverse:read"],
     "declared_on": "2026-10-22"},
    {"agent": "antigravity", "name": "Antigravity",
     "role": "admitted traversal-door identity; no "
             "review seat declared yet",
     "exposure": "internal-loopback",
     "may_send": [], "may_receive": [],
     "tools": ["traverse:read"],
     "declared_on": "2026-10-22"},
]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- registers ------------------------------------------------------------------

def _read_jsonl(path: Path):
    """(present, records, problems) — header lines
    skipped, malformed lines named by number."""
    if not path.is_file():
        return False, [], []
    records, problems = [], []
    for n, line in enumerate(
            path.read_text(encoding="utf-8")
            .splitlines(), 1):
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
                             "detail": "register line is "
                                       "not a JSON object"})
            continue
        if rec.get("kind") == "header":
            continue
        records.append(rec)
    return True, records, problems


def _append(path: Path, header: dict, rec: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False,
                      sort_keys=True) + "\n"
    if not path.is_file():
        path.write_text(
            json.dumps(header, ensure_ascii=False,
                       sort_keys=True) + "\n" + line,
            encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def load_cards(root: Path):
    present, records, problems = _read_jsonl(
        root / CARDS_REL)
    cards = {}
    for rec in records:
        if rec.get("kind") == "agent-card" and \
                rec.get("agent"):
            cards[rec["agent"]] = rec
    return present, cards, records, problems


def load_messages(root: Path):
    return _read_jsonl(root / MESSAGES_REL)


def known_thread_ids(root: Path):
    """Thread ids standing on the review-threads
    register (read directly — the register is data;
    derivation lives in wiki_review_threads.py)."""
    _p, records, _pr = _read_jsonl(
        root / "evaluation/review-threads.jsonl")
    return {r["id"] for r in records
            if r.get("kind") == "thread" and r.get("id")}


# -- validation -------------------------------------------------------------------

def validate_cards(records):
    findings = []

    def note(rec, finding, detail):
        findings.append({"agent": rec.get("agent"),
                         "finding": finding,
                         "detail": detail})

    seen, public = set(), []
    for rec in records:
        if rec.get("kind") != "agent-card":
            note(rec, "unknown-record-kind",
                 "the cards register carries agent-card "
                 "records only")
            continue
        agent = rec.get("agent")
        if not agent:
            note(rec, "missing-field:agent",
                 "a card names its agent")
        elif agent in seen:
            note(rec, "duplicate-card",
                 f"a card for {agent} already stands")
        seen.add(agent)
        for field in ("name", "role", "tools",
                      "declared_on"):
            if rec.get(field) in (None, "", []):
                note(rec, f"missing-field:{field}",
                     f"a card carries {field}")
        if rec.get("exposure") not in EXPOSURES:
            note(rec, f"unknown-exposure:"
                 f"{rec.get('exposure')}",
                 "exposure is public or "
                 "internal-loopback")
        elif rec["exposure"] == "public":
            public.append(agent)
        for field in ("may_send", "may_receive"):
            for act in rec.get(field) or []:
                if act not in ACTS:
                    note(rec, f"unknown-act:{act}",
                         f"{field} names an act outside "
                         f"the vocabulary")
        if rec.get("declared_on") and not DATE_RE.match(
                str(rec["declared_on"])):
            note(rec, "missing-field:declared_on",
                 "declared_on must be YYYY-MM-DD")
    if len(public) > 1:
        findings.append({
            "agent": None,
            "finding": "multiple-public-cards",
            "detail": "the directory declares exactly "
                      "one public card; found "
                      + ", ".join(sorted(
                          str(a) for a in public))})
    findings.sort(key=lambda f: (str(f["finding"]),
                                 str(f["agent"])))
    return findings


def validate_message(root, msg, cards, messages,
                     thread_ids):
    """The named refusals a message earns, in a stable
    order. Empty list = the message stands."""
    refusals = []

    def refuse(name, detail):
        refusals.append({"refused": name,
                         "detail": detail})

    if msg.get("kind") not in (None, "review-message"):
        refuse("bad-kind",
               "kind must be review-message")
    for field in msg:
        if field not in ALLOWED_FIELDS:
            refuse(f"unknown-field:{field}",
                   "the message vocabulary is closed")
    mid = msg.get("id")
    if not MESSAGE_ID.match(str(mid or "")):
        refuse("bad-id", "message id must be rm-NNNNNN")
    elif any(m.get("id") == mid for m in messages):
        refuse("duplicate-id",
               f"message {mid} already stands")
    act = msg.get("act")
    if act not in ACTS:
        refuse(f"unknown-act:{act}",
               "the act is outside the closed "
               "vocabulary")
    else:
        for field in ACTS[act]["required"]:
            if not msg.get(field):
                refuse(f"missing-field:{field}",
                       f"{act} requires {field}")
    if msg.get("state") not in TASK_STATES:
        refuse(f"unknown-state:{msg.get('state')}",
               "the state is outside the A2A Task "
               "lifecycle")
    if not DATE_RE.match(str(msg.get("date") or "")):
        refuse("missing-field:date",
               "date must be YYYY-MM-DD (the recorded "
               "act's date, caller-supplied)")
    if not msg.get("summary"):
        refuse("missing-field:summary",
               "a message carries a one-line summary")
    for party in ("from", "to"):
        if not msg.get(party):
            refuse(f"missing-field:{party}",
                   f"a message names its {party}")
    sender = msg.get("from")
    if sender and sender != OWNER:
        card = cards.get(sender)
        if card is None:
            refuse(f"sender-not-carded:{sender}",
                   "no agent card stands for the sender")
        elif act in ACTS and \
                act not in (card.get("may_send") or []):
            refuse(f"act-not-permitted:{sender}:{act}",
                   "the sender's card does not declare "
                   "this act under may_send")
    receiver = msg.get("to")
    if receiver and receiver != OWNER and \
            receiver not in cards:
        refuse(f"receiver-not-carded:{receiver}",
               "no agent card stands for the receiver")
    if msg.get("page"):
        if not (root / str(msg["page"])).is_file():
            refuse(f"unknown-page:{msg['page']}",
                   "the named page does not exist")
    if msg.get("thread_id") and \
            msg["thread_id"] not in thread_ids:
        refuse(f"unknown-thread:{msg['thread_id']}",
               "no such thread stands on the "
               "review-threads register")
    if msg.get("in_reply_to"):
        known = {m.get("id") for m in messages}
        if msg["in_reply_to"] not in known:
            refuse(f"in-reply-to-unknown:"
                   f"{msg['in_reply_to']}",
                   "the message replied to does not "
                   "stand on the register")
    return refusals


def check_all(root: Path):
    _cp, cards, card_records, card_problems = \
        load_cards(root)
    _mp, messages, msg_problems = load_messages(root)
    thread_ids = known_thread_ids(root)
    findings = validate_cards(card_records)
    for m in messages:
        if m.get("kind") != "review-message":
            findings.append({
                "id": m.get("id"),
                "finding": "unknown-record-kind",
                "detail": "the messages register "
                          "carries review-message "
                          "records only"})
            continue
        others = [x for x in messages if x is not m]
        for r in validate_message(
                root, m, cards, others, thread_ids):
            findings.append({"id": m.get("id"),
                             "finding": r["refused"],
                             "detail": r["detail"]})
    findings.sort(key=lambda f: (str(f["finding"]),
                                 str(f.get("id")
                                     or f.get("agent"))))
    return {"cards": len(cards),
            "messages": len(messages),
            "findings": findings,
            "register_problems": card_problems
            + msg_problems}


# -- vocabulary + cards artefacts -------------------------------------------------

def vocabulary_doc():
    return {
        "tool": "scripts/wiki_a2a.py",
        "kind": "a2a-vocabulary",
        "acts": {a: {"summary": ACTS[a]["summary"],
                     "required": list(
                         ACTS[a]["required"]),
                     "base_fields": list(BASE_FIELDS),
                     "optional": list(OPTIONAL_FIELDS)}
                 for a in sorted(ACTS)},
        "task_states": {s: STATE_MEANINGS[s]
                        for s in TASK_STATES},
        "participants": "carded agents (evaluation/"
                        "agent-cards.jsonl) plus the "
                        "owner, who needs no card and "
                        "whose rulings stand in chat, "
                        "never in these records",
    }


def seed_cards(root: Path):
    path = root / CARDS_REL
    if path.is_file():
        return {"refused": "cards-register-exists",
                "detail": "the directory already "
                          "stands; cards are amended "
                          "by appending a superseding "
                          "card record, never by "
                          "re-seeding"}
    header = {"kind": "header", "register": "agent-cards",
              "version": 1,
              "purpose": "Machine-readable agent "
                         "directory (scripts/wiki_a2a"
                         ".py): the declared "
                         "interface between this "
                         "wiki's agents. Least-"
                         "privilege: one public card, "
                         "the rest internal-loopback. "
                         "Append-only."}
    for card in SEED_CARDS:
        _append(path, header,
                {"kind": "agent-card", **card})
    return {"seeded": [c["agent"] for c in SEED_CARDS]}


def record_message(root: Path, msg: dict):
    _cp, cards, _cr, _pr = load_cards(root)
    _mp, messages, _pr2 = load_messages(root)
    thread_ids = known_thread_ids(root)
    refusals = validate_message(root, msg, cards,
                                messages, thread_ids)
    if refusals:
        return {"refused": refusals[0]["refused"],
                "detail": refusals[0]["detail"],
                "all_refusals": refusals}
    rec = {"kind": "review-message", **msg}
    header = {"kind": "header",
              "register": "review-messages", "version": 1,
              "purpose": "Agent-to-agent review "
                         "messages in the A2A "
                         "vocabulary (scripts/wiki_a2a"
                         ".py): records only — nothing "
                         "is sent anywhere. Append-only."}
    _append(root / MESSAGES_REL, header, rec)
    return rec


# -- CLI -----------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="A2A vocabulary + agent cards")
    ap.add_argument("command",
                    choices=["vocabulary", "cards",
                             "seed-cards", "record",
                             "check"])
    ap.add_argument("record", nargs="?",
                    help="message JSON for record")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = args.root

    if args.command == "vocabulary":
        print(json.dumps(vocabulary_doc(), indent=1,
                         sort_keys=True))
        return 0
    if args.command == "cards":
        present, cards, records, problems = \
            load_cards(root)
        doc = {"register": CARDS_REL,
               "register_present": present,
               "cards": [cards[a] for a in sorted(cards)],
               "findings": validate_cards(records),
               "register_problems": problems}
        print(json.dumps(doc, indent=1, sort_keys=True))
        return 1 if (doc["findings"] or problems) else 0
    if args.command == "seed-cards":
        out = seed_cards(root)
        print(json.dumps(out, indent=1, sort_keys=True))
        return 1 if "refused" in out else 0
    if args.command == "record":
        if not args.record:
            print("record needs a message JSON path",
                  file=sys.stderr)
            return 2
        msg = json.loads(Path(args.record).read_text(
            encoding="utf-8"))
        rec = record_message(root, msg)
        print(json.dumps(rec, indent=1, sort_keys=True))
        return 1 if "refused" in rec else 0
    if args.command == "check":
        out = check_all(root)
        print(json.dumps(out, indent=1, sort_keys=True))
        return 1 if (out["findings"]
                     or out["register_problems"]) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
