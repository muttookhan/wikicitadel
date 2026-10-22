#!/usr/bin/env python3
"""wiki_skill_governance.py — the Skill Governance pack:
a census/register of the wiki's own skill records plus a
validator for the ones that declare governance.

Build-list wave 5 (2026-10-22), "Skill governance pack".
Idea sources (governance concepts restated in our own
words, no code copied): the gated-evolution and probationary
-lifecycle patterns of agentic-stack, brito-cli, Ebony-Vinyl
/ZX-code and omdsh-dev/dsh-mnemon (survey rows; see the
wave-5 build-list item). Clean re-implementation in the
house register style of scripts/wiki_curation.py and
scripts/wiki_corrections_lifecycle.py.

WHAT A SKILL RECORD IS HERE. A `SKILL.md` file anywhere in
the tree outside `raw/` (the immutable evidence layer —
mirrored foreign skills in raw are evidence, not governed
records) and outside `.git/`. Forms, by location:
  tool-skill        under tools/ — a door's taught skill
  generated-export  under exports/ — distilled by
                    scripts/wiki_skill_export.py
  skill-record      anywhere else
A record's identity fields (name / version / description)
come from its frontmatter's top level.

GOVERNANCE IS OPT-IN AND DECLARED IN THE RECORD. A record
governs itself by carrying a `governance:` block in its
frontmatter. A record with no block is census-only: the
register lists it as `undeclared` and the validator raises
no violations for it. A record with a block is checked in
full — a partial block fails by name for every missing
field. The grammar is a tight YAML subset: indentation
mappings, flow lists `[a, b]`, block lists, plain or
quoted scalars, true/false. Comments are not in the
grammar. A block outside the grammar is reported as
`unparseable-governance-block`, never guessed over.

THE BLOCK.

    governance:
      state: active            # one of STATES
      proposed_by: mehmed      # provenance: who proposed
      evidence: "..."          # provenance: on what
                               # evidence (the paired-screen
                               # result, the failure diagnosis
                               # — the record names it)
      scope: [traverse-door]   # doors/agents that may
                               # use the skill; non-empty
      destructive: false       # true if the skill can run
                               # destructive commands
      review:
        state: current         # unreviewed/current/stale
        by: owner
        date: 2026-10-22
        evidence: "..."
      history:                 # every state change, in
                               # order, each with its own
                               # provenance
        - to: proposed
          by: mehmed
          date: 2026-10-21
          evidence: "..."
        - from: proposed
          to: active
          by: owner
          date: 2026-10-22
          evidence: "..."
          review: "owner approval recorded in chat"
          approved_by: owner   # required on activation
                               # when destructive: true

LIFECYCLE — a closed set, enforced exactly as tabled here:

    STATES = proposed, active, deprecated, retired
    birth      -> proposed     (the first history entry;
                                carries no `from`)
    proposed   -> active       (requires the entry's
                                `review:` — activation is
                                a recorded review act: the
                                backtest/paired-screen
                                evidence rides in `evidence:`)
    proposed   -> retired      (withdrawn before use)
    active     -> deprecated
    active     -> retired
    deprecated -> active       (requires the entry's
                                `review:` — a recorded
                                review act, nothing else
                                reopens a deprecated skill)
    deprecated -> retired
    retired    -> (terminal: no exits, ever)

Plus: the history must be a continuous chain (each
entry's `from` is the previous entry's `to`), its last
`to` must equal the record's `state`, dates must be ISO
and non-decreasing along the chain, and every entry
carries by/date/evidence. A skill declared
`destructive: true` may only be brought to `active` —
first activation or reactivation alike — by an entry
with `approved_by: owner`: the mandatory human approval
for destructive commands, checked as form; the pack
never judges the approval's wisdom.

DESCRIPTIVE + CHECKING ONLY. This tool never activates,
deprecates or retires anything, and never edits a record:
state changes are acts of the owner/Mehmed recorded in the
record itself; the validator merely verifies they are
well-formed. `check` and `census` write nothing. Only
`register` writes, and only its own artefact
(evaluation/skill-register.json by default).

Determinism: the register carries no wall-clock and no
git state — same corpus, identical bytes. Its
`content_hash` is the SHA-256 of the canonical record
rows. Validator output is stable-sorted by (path, name).

    python3 scripts/wiki_skill_governance.py census
        [--root DIR] [--json]
    python3 scripts/wiki_skill_governance.py check
        [--root DIR] [--json]
    python3 scripts/wiki_skill_governance.py register
        [--root DIR] [--out PATH]

Exit codes: check 0 clean · 1 violations · 2 usage.
census/register 0 (2 usage).
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

STATES = ("proposed", "active", "deprecated", "retired")
REVIEW_STATES = ("unreviewed", "current", "stale")

# The closed transition table. None is birth (no prior
# state). Retired is terminal. Enforced exactly, no more.
TRANSITIONS = {
    None: {"proposed"},
    "proposed": {"active", "retired"},
    "active": {"deprecated", "retired"},
    "deprecated": {"active", "retired"},
    "retired": set(),
}

EXCLUDED_PARTS = {".git", "raw"}

KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(\s+(.*)|\s*)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class GovParseError(Exception):
    """A governance block outside the stated grammar."""


# ------------------------------------------------------------
# frontmatter + the governance-block grammar
# ------------------------------------------------------------

def split_frontmatter(text: str):
    """The frontmatter lines of a document, or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return lines[1:i]
    return None


def top_level_scalars(fm_lines):
    """name/version/description-style indent-0 scalars."""
    out = {}
    for line in fm_lines:
        if not line.strip() or line[0] in " \t":
            continue
        m = KEY_RE.match(line)
        if m and m.group(3) is not None:
            out[m.group(1)] = _scalar(m.group(3))
    return out


def _split_flow(inner: str):
    parts, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _scalar(tok):
    tok = tok.strip()
    if tok == "":
        return None
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_flow(inner)]
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
        return tok[1:-1]
    low = tok.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    return tok


def _parse_node(lines, i, indent):
    """Parse one node from (indent, text) lines at `indent`.
    Returns (value, next_index)."""
    text = lines[i][1]
    if text.startswith("- ") or text == "-":
        items = []
        while i < len(lines) and lines[i][0] == indent and \
                (lines[i][1].startswith("- ") or lines[i][1] == "-"):
            first = lines[i][1][1:].strip()
            j = i + 1
            sub = []
            while j < len(lines) and lines[j][0] > indent:
                sub.append(lines[j])
                j += 1
            if first == "":
                if not sub:
                    items.append(None)
                else:
                    value, used = _parse_node(sub, 0, sub[0][0])
                    if used != len(sub):
                        raise GovParseError("trailing lines in list item")
                    items.append(value)
            elif KEY_RE.match(first):
                virtual = [(indent + 2, first)] + sub
                value, used = _parse_node(virtual, 0, indent + 2)
                if used != len(virtual):
                    raise GovParseError("trailing lines in list item")
                items.append(value)
            else:
                if sub:
                    raise GovParseError(
                        "indented lines under a scalar list item")
                items.append(_scalar(first))
            i = j
        return items, i
    mapping = {}
    while i < len(lines) and lines[i][0] == indent and \
            not (lines[i][1].startswith("- ") or lines[i][1] == "-"):
        m = KEY_RE.match(lines[i][1])
        if not m:
            raise GovParseError("expected 'key: value', got %r"
                                % lines[i][1])
        key = m.group(1)
        if key in mapping:
            raise GovParseError("duplicate key %r" % key)
        val = m.group(3)
        if val is not None and val.strip() != "":
            mapping[key] = _scalar(val)
            i += 1
        else:
            j = i + 1
            sub = []
            while j < len(lines) and lines[j][0] > indent:
                sub.append(lines[j])
                j += 1
            if not sub:
                mapping[key] = None
            else:
                value, used = _parse_node(sub, 0, sub[0][0])
                if used != len(sub):
                    raise GovParseError("trailing lines under key %r"
                                        % key)
                mapping[key] = value
            i = j
    if not mapping:
        raise GovParseError("empty block")
    return mapping, i


def parse_governance(fm_lines):
    """The governance mapping of a frontmatter, or None
    when no block is declared. Raises GovParseError for a
    declared block outside the grammar."""
    for idx, line in enumerate(fm_lines):
        if line and line[0] not in " \t":
            m = KEY_RE.match(line)
            if m and m.group(1) == "governance":
                inline = (m.group(3) or "").strip()
                if inline == "{}":
                    return {}
                if inline:
                    raise GovParseError(
                        "governance must be a block, not an inline value")
                block = []
                for rest in fm_lines[idx + 1:]:
                    if rest.strip() == "":
                        continue
                    indent = len(rest) - len(rest.lstrip(" "))
                    if indent == 0:
                        break
                    block.append((indent, rest.strip()))
                if not block:
                    return {}
                value, used = _parse_node(block, 0, block[0][0])
                if used != len(block):
                    raise GovParseError("unparsed lines in governance "
                                        "block")
                if not isinstance(value, dict):
                    raise GovParseError("governance block is not a "
                                        "mapping")
                return value
    return None


# ------------------------------------------------------------
# validation — the closed rules, violations named
# ------------------------------------------------------------

def _is_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_governance(gov: dict):
    """Violation names for one parsed governance block.
    Pure: the same block always yields the same list."""
    out = []
    if not isinstance(gov, dict):
        return ["unparseable-governance-block:not-a-mapping"]

    for field in ("state", "proposed_by", "evidence", "scope",
                  "review", "history"):
        if field not in gov or gov[field] is None:
            out.append("missing-field:%s" % field)

    state = gov.get("state")
    if state is not None and state not in STATES:
        out.append("unknown-state:%s" % state)

    scope = gov.get("scope")
    if scope is not None:
        if not isinstance(scope, list):
            out.append("bad-type:scope")
        elif not scope:
            out.append("empty-scope")

    review = gov.get("review")
    if review is not None:
        if not isinstance(review, dict):
            out.append("bad-type:review")
        else:
            rstate = review.get("state")
            if rstate is None:
                out.append("missing-field:review.state")
            elif rstate not in REVIEW_STATES:
                out.append("unknown-review-state:%s" % rstate)
            if rstate in ("current", "stale"):
                for sub in ("by", "date"):
                    if not review.get(sub):
                        out.append("missing-field:review.%s" % sub)
            if review.get("date") is not None and \
                    not _is_date(review["date"]):
                out.append("bad-date:%s@review" % review["date"])

    history = gov.get("history")
    if history is not None:
        if not isinstance(history, list):
            out.append("bad-type:history")
        elif not history:
            out.append("empty-history")
        else:
            _validate_history(gov, history, state, out)
    return sorted(out)


def _validate_history(gov, history, state, out):
    destructive = gov.get("destructive") is True
    prev_to = None
    prev_date = None
    for i, entry in enumerate(history):
        if not isinstance(entry, dict):
            out.append("bad-type:history-entry@%d" % i)
            prev_to = None
            continue
        for key in ("to", "by", "date", "evidence"):
            if not entry.get(key):
                out.append("history-entry-missing-field:%s@%d"
                           % (key, i))
        frm = entry.get("from")
        to = entry.get("to")
        when = entry.get("date")
        if when is not None and not _is_date(when):
            out.append("bad-date:%s@history-%d" % (when, i))
        if _is_date(when) and prev_date and when < prev_date:
            out.append("history-date-regression@%d" % i)
        if _is_date(when):
            prev_date = when
        if i == 0:
            if frm not in (None, "") or to != "proposed":
                out.append("history-not-birth-first")
        else:
            if frm is None:
                out.append("history-entry-missing-field:from@%d" % i)
            elif prev_to is not None and frm != prev_to:
                out.append("history-chain-break@%d" % i)
        allowed = TRANSITIONS.get(frm if i else None, set())
        if i == 0:
            allowed = TRANSITIONS[None]
        if to is not None and to not in allowed:
            out.append("illegal-transition:%s->%s@%d"
                       % (frm if i else "birth", to, i))
        if frm == "proposed" and to == "active" and \
                not entry.get("review"):
            out.append("unrecorded-activation-review@%d" % i)
        if frm == "deprecated" and to == "active" and \
                not entry.get("review"):
            out.append("unrecorded-reactivation-review@%d" % i)
        if to == "active" and destructive and \
                entry.get("approved_by") != "owner":
            out.append(
                "destructive-activation-without-owner-approval@%d" % i)
        prev_to = to
    if history and isinstance(history[-1], dict) and \
            state is not None and history[-1].get("to") != state:
        out.append("history-state-mismatch")


# ------------------------------------------------------------
# census + register
# ------------------------------------------------------------

def find_skill_records(root: Path):
    found = []
    for path in sorted(root.rglob("SKILL.md")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        found.append(path)
    return found


def record_form(rel: Path):
    if rel.parts[0] == "tools":
        return "tool-skill"
    if rel.parts[0] == "exports":
        return "generated-export"
    return "skill-record"


def read_record(root: Path, path: Path):
    rel = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    fm = split_frontmatter(text)
    scalars = top_level_scalars(fm) if fm is not None else {}
    row = {
        "path": rel,
        "form": record_form(Path(rel)),
        "name": scalars.get("name"),
        "version": scalars.get("version"),
        "description": bool(scalars.get("description")),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "governance": "undeclared",
        "state": None,
        "proposed_by": None,
        "scope": None,
        "review_state": None,
        "violations": [],
    }
    if fm is None:
        row["governance"] = "no-frontmatter"
        return row
    try:
        gov = parse_governance(fm)
    except GovParseError as exc:
        row["governance"] = "declared-unparseable"
        row["violations"] = ["unparseable-governance-block:%s" % exc]
        return row
    if gov is None:
        return row
    row["governance"] = "governed"
    row["state"] = gov.get("state")
    row["proposed_by"] = gov.get("proposed_by")
    row["scope"] = gov.get("scope")
    review = gov.get("review")
    row["review_state"] = review.get("state") \
        if isinstance(review, dict) else None
    row["violations"] = validate_governance(gov)
    return row


def build_register(root: Path):
    rows = [read_record(root, p) for p in find_skill_records(root)]
    rows.sort(key=lambda r: r["path"])
    by_form, by_state = {}, {}
    flat = []
    for row in rows:
        by_form[row["form"]] = by_form.get(row["form"], 0) + 1
        key = row["state"] if row["governance"] == "governed" \
            else row["governance"]
        by_state[key] = by_state.get(key, 0) + 1
        for name in row["violations"]:
            flat.append({"path": row["path"], "violation": name})
    flat.sort(key=lambda v: (v["path"], v["violation"]))
    content_hash = hashlib.sha256(json.dumps(
        rows, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "tool": "scripts/wiki_skill_governance.py",
        "kind": "skill-register",
        "schema": "skill-governance/1",
        "states": list(STATES),
        "review_states": list(REVIEW_STATES),
        "transitions": sorted(
            "%s->%s" % (frm if frm is not None else "birth", to)
            for frm, tos in TRANSITIONS.items() for to in tos),
        "records_total": len(rows),
        "governed_total": sum(1 for r in rows
                              if r["governance"] == "governed"),
        "by_form": by_form,
        "by_state": by_state,
        "violations_total": len(flat),
        "violations": flat,
        "records": rows,
        "content_hash": content_hash,
    }


def render_register(register: dict) -> str:
    return json.dumps(register, indent=2, sort_keys=True) + "\n"


def _summary(register):
    return ("skill records: %d (governed %d) · by form %s · "
            "by state %s · violations %d"
            % (register["records_total"], register["governed_total"],
               register["by_form"], register["by_state"],
               register["violations_total"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("census", "check", "register"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None)
        p.add_argument("--json", action="store_true")
    sub.choices["register"].add_argument(
        "--out", default=None,
        help="artefact path; default evaluation/skill-register.json "
             "under the root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    register = build_register(root)

    if args.cmd == "census":
        if args.json:
            print(json.dumps(
                {"records": register["records"],
                 "records_total": register["records_total"],
                 "by_form": register["by_form"],
                 "by_state": register["by_state"]},
                indent=2, sort_keys=True))
        else:
            for row in register["records"]:
                print("%s · %s · name=%s · governance=%s state=%s"
                      % (row["path"], row["form"], row["name"],
                         row["governance"], row["state"]))
            print(_summary(register))
        return 0

    if args.cmd == "check":
        if args.json:
            print(json.dumps(
                {"violations": register["violations"],
                 "violations_total": register["violations_total"],
                 "records_total": register["records_total"],
                 "governed_total": register["governed_total"]},
                indent=2, sort_keys=True))
        else:
            print(_summary(register))
            for v in register["violations"]:
                print("VIOLATION %s: %s" % (v["path"], v["violation"]))
        return 1 if register["violations_total"] else 0

    out = Path(args.out) if args.out else \
        root / "evaluation" / "skill-register.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_register(register), encoding="utf-8")
    print("wrote %s · %s · content_hash %s"
          % (out, _summary(register), register["content_hash"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
