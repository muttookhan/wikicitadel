#!/usr/bin/env python3
"""wiki_notice.py — the Notice layer + protocol-tier checker.

WikiCitadel v1, pattern: Local Contexts Notices
(governance lane, finds 5-6) + Mukurtu protocol tiers (find 8).

A Notice is a FIXED, non-customisable marker stating a standing
condition a reader must know BEFORE relying on a page. The
vocabulary lives in evaluation/notice-vocabulary.json; the rules
page is wiki/rules/notices.md, which quotes the same fixed text
verbatim. A notice is:

  * applied by the agent on its own observation, WITHOUT
    waiting for an owner ruling (the ruling is what the notice
    waits for, not what it needs);
  * composed ONLY from the vocabulary's fixed text — this tool
    takes no wording from the caller, so a notice can never be
    softened per page;
  * retired ONLY by an owner ruling, recorded in the register
    (evaluation/notices.jsonl, append-only) — `retire` refuses
    without a --ruling reference.

Commands:

    python3 scripts/wiki_notice.py apply <page> <notice-id> \
        --reason "..." [--by agent] [--date YYYY-MM-DD]
    python3 scripts/wiki_notice.py retire <page> <notice-id> \
        --ruling "<owner ruling reference>" [--date ...]
    python3 scripts/wiki_notice.py list     # active notices,
                                            # verified on-page
    python3 scripts/wiki_notice.py check    # drift: register
                                            # vs pages (exit 1)
    python3 scripts/wiki_notice.py suggest  # mechanical
                                            # applicability scan
    python3 scripts/wiki_notice.py tiers <identity>
                                            # protocol-tier
                                            # composition check

Exit codes: 0 ok · 1 refusal/drift found · 2 usage error.
"""
import argparse
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
VOCAB = ROOT / "evaluation" / "notice-vocabulary.json"
REGISTER = ROOT / "evaluation" / "notices.jsonl"
IDENTITY_SCOPES = ROOT / "wiki" / "access" / "identity-scopes.md"
BLACK_BOX_GLOB = "black-box-*.jsonl"


def _black_box_path(root):
    """The deployment's Black Box ledger: the newest
    black-box-*.jsonl under wiki/access/, or None."""
    hits = sorted((root / "wiki" / "access").glob(BLACK_BOX_GLOB))
    return hits[-1] if hits else None

sys.path.insert(0, str(SCRIPTS))
import wiki_validate as _validate  # noqa: E402  (frontmatter parser)

ALL_SCOPES = ("wiki:read", "wiki:propose", "wiki:publish",
              "wiki:admin")
# wiki:admin implies every lesser scope (tools/gateway/gateway/
# scopes.py: each check passes on SCOPE_ADMIN alone).
IMPLIES = {"wiki:read": (), "wiki:propose": (),
           "wiki:publish": (), "wiki:admin": ALL_SCOPES[:3]}


class NoticeError(Exception):
    pass


# ---------------------------------------------------------------- vocab

def load_vocab(root=ROOT):
    path = root / "evaluation" / "notice-vocabulary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {n["id"]: n for n in data["notices"]}


# ---------------------------------------------------------------- blocks

BEGIN = "<!-- notice:begin id=%s -->"
END = "<!-- notice:end id=%s -->"


def compose_block(notice, applied, by, reason):
    """The on-page block. The notice's wording comes ONLY from
    the vocabulary; the caller supplies the application line's
    facts (date, applier, reason), never text."""
    text = notice["fixed_text"].replace("\n", " ")
    lines = [
        BEGIN % notice["id"],
        "> [!warning] **Notice — %s.**" % notice["title"],
        "> " + text,
        ">",
        "> Applied %s by %s — %s. This notice is retired only "
        "by an owner ruling, recorded in "
        "`evaluation/notices.jsonl`." % (applied, by, reason),
        END % notice["id"],
    ]
    return "\n".join(lines) + "\n"


def find_block(text, notice_id):
    """(start, end) char span of the notice block, or None."""
    b = text.find(BEGIN % notice_id)
    if b < 0:
        return None
    e = text.find(END % notice_id, b)
    if e < 0:
        return None
    return b, e + len(END % notice_id)


def block_fixed_text_ok(block_text, notice):
    """The block's fixed-text line matches the vocabulary
    verbatim (the applied-line may differ; the text may not)."""
    want = "> " + notice["fixed_text"].replace("\n", " ")
    return want in block_text


# ---------------------------------------------------------------- register

def load_register(root=ROOT):
    path = root / "evaluation" / "notices.jsonl"
    events = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def append_event(root, event):
    path = root / "evaluation" / "notices.jsonl"
    if not path.exists():
        header = {
            "kind": "header", "register": "notices", "version": 1,
            "created": _date.today().isoformat(),
            "purpose": "Append-only record of Notice applications "
                       "and retirements (WikiCitadel v1; "
                       "scripts/wiki_notice.py). A notice is "
                       "applied by the agent on observation and "
                       "retired ONLY by an owner ruling, whose "
                       "reference the retired event carries. "
                       "Vocabulary: evaluation/notice-vocabulary"
                       ".json; rules: wiki/rules/notices.md.",
        }
        path.write_text(json.dumps(header, sort_keys=True) + "\n",
                        encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def active_applications(root=ROOT):
    """Fold the register: latest event per (page, notice)."""
    active = {}
    for ev in load_register(root):
        if ev.get("kind") == "applied":
            active[(ev["page"], ev["notice"])] = ev
        elif ev.get("kind") == "retired":
            active.pop((ev["page"], ev["notice"]), None)
    return active


# ---------------------------------------------------------------- apply/retire

def apply_notice(page_rel, notice_id, reason, by="agent",
                 on=None, root=ROOT):
    vocab = load_vocab(root)
    if notice_id not in vocab:
        raise NoticeError("unknown notice id: %s" % notice_id)
    if not reason or not reason.strip():
        raise NoticeError("apply requires a --reason")
    page = root / page_rel
    if not page.exists():
        raise NoticeError("no such page: %s" % page_rel)
    text = page.read_text(encoding="utf-8")
    fields, body = _validate.parse_frontmatter(text)
    if fields is None:
        raise NoticeError("%s has no frontmatter; a notice "
                          "anchors after it" % page_rel)
    if find_block(text, notice_id):
        raise NoticeError("%s already carries notice %s"
                          % (page_rel, notice_id))
    applied = on or _date.today().isoformat()
    block = compose_block(vocab[notice_id], applied, by, reason)
    # Insert at the head of the body: right after the closing
    # frontmatter fence, before everything else.
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    head, rest = text[:m.end()], text[m.end():]
    new = head + "\n" + block + "\n" + rest.lstrip("\n")
    page.write_text(new, encoding="utf-8")
    append_event(root, {
        "kind": "applied", "page": page_rel, "notice": notice_id,
        "date": applied, "by": by, "reason": reason,
    })
    return applied


def retire_notice(page_rel, notice_id, ruling, on=None, root=ROOT):
    if not ruling or not ruling.strip():
        raise NoticeError(
            "retire requires --ruling: a notice is retired only "
            "by an owner ruling, recorded here. Refused.")
    page = root / page_rel
    if not page.exists():
        raise NoticeError("no such page: %s" % page_rel)
    text = page.read_text(encoding="utf-8")
    span = find_block(text, notice_id)
    if not span:
        raise NoticeError("%s does not carry notice %s"
                          % (page_rel, notice_id))
    retired = on or _date.today().isoformat()
    trace = ("<!-- notice:retired id=%s date=%s ruling=%s -->\n"
             % (notice_id, retired, ruling))
    new = text[:span[0]] + trace + text[span[1]:].lstrip("\n")
    page.write_text(new, encoding="utf-8")
    append_event(root, {
        "kind": "retired", "page": page_rel, "notice": notice_id,
        "date": retired, "ruling": ruling,
    })
    return retired


# ---------------------------------------------------------------- list/check

def list_notices(root=ROOT):
    vocab = load_vocab(root)
    rows = []
    for (page_rel, notice_id), ev in sorted(
            active_applications(root).items()):
        page = root / page_rel
        status = "ok"
        if not page.exists():
            status = "PAGE MISSING"
        else:
            text = page.read_text(encoding="utf-8")
            span = find_block(text, notice_id)
            if not span:
                status = "BLOCK MISSING from page"
            elif not block_fixed_text_ok(text[span[0]:span[1]],
                                         vocab[notice_id]):
                status = "FIXED TEXT ALTERED on page"
        rows.append((page_rel, notice_id, ev.get("date"),
                     ev.get("reason"), status))
    return rows


def unregistered_blocks(root=ROOT):
    """Blocks on pages that the register holds no active
    application for — drift in the other direction."""
    active = active_applications(root)
    found = []
    for page in sorted((root / "wiki").rglob("*.md")):
        rel = page.relative_to(root).as_posix()
        text = page.read_text(encoding="utf-8")
        for nid in re.findall(r"<!-- notice:begin id=([\w-]+) -->",
                              text):
            if (rel, nid) not in active:
                found.append((rel, nid))
    return found


# ---------------------------------------------------------------- suggest

def _pages(root):
    out = {}
    for page in sorted((root / "wiki").rglob("*.md")):
        rel = page.relative_to(root).as_posix()
        fields, _ = _validate.parse_frontmatter(
            page.read_text(encoding="utf-8"))
        out[rel] = fields or {}
    return out


def _fold_grades(root):
    latest = {}
    path = root / "evaluation" / "source-grades.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("kind") == "grade":
                latest[(ev["source"], ev["axis"])] = ev["grade"]
    return latest


def suggest(root=ROOT):
    pages = _pages(root)
    active = active_applications(root)
    cand = {nid: [] for nid in load_vocab(root)}

    # source-integrity-questioned
    grades = _fold_grades(root)
    questioned = {src for (src, axis), g in grades.items()
                  if axis == "integrity" and g == "questioned"}
    raw_of_questioned = set()
    for src in questioned:
        raw_of_questioned.update(
            _validate.as_list(pages.get(src, {}).get("sources")))
    for rel, fields in pages.items():
        srcs = set(_validate.as_list(fields.get("sources")))
        if rel in questioned or srcs & raw_of_questioned:
            cand["source-integrity-questioned"].append(rel)

    # claim-negative-treatment
    tpath = root / "evaluation" / "treatment-register.jsonl"
    if tpath.exists():
        for line in tpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("kind") == "treatment" \
                    and ev.get("grade") == "negative":
                cand["claim-negative-treatment"].append(
                    ev["subject"]["page"])

    # personal-export-material
    for rel, fields in pages.items():
        srcs = _validate.as_list(fields.get("sources"))
        if any("personal-export" in str(s) for s in srcs):
            cand["personal-export-material"].append(rel)

    # as-written-design — pages the decision gate calls LIVE
    try:
        import wiki_decision_gate
        result = wiki_decision_gate.scan(root)
        for hit in result["hits"]:
            if hit.get("classification") == "LIVE":
                cand["as-written-design"].append(hit["file"])
    except Exception as exc:  # gate unavailable: say so
        cand["as-written-design"] = ["<gate scan failed: %s>" % exc]

    # attribution-incomplete
    for rel, fields in pages.items():
        if fields.get("type") in ("source", "entity", "concept",
                                  "synthesis", "query"):
            if not _validate.as_list(fields.get("sources")):
                cand["attribution-incomplete"].append(rel)

    out = {}
    for nid, rels in cand.items():
        rows = []
        for rel in sorted(set(rels)):
            rows.append((rel, (rel, nid) in active))
        out[nid] = rows
    return out


# ---------------------------------------------------------------- tiers

def _identity_rows(root):
    """Parse the identity/scope table on the activation record."""
    path = root / "wiki" / "access" / "identity-scopes.md"
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|")
                 .split("|")]
        if len(cells) < 5 or cells[0] in ("Identity", "") \
                or set(cells[0]) <= set("-: "):
            continue
        scopes = [s.strip() for s in cells[1].split(",")
                  if s.strip() in ALL_SCOPES]
        rows[cells[0].lower()] = {
            "scopes": scopes, "token_note": cells[4],
            "raw_scopes": cells[1],
        }
    return rows


def evaluate_tiers(identity, root=ROOT):
    """The composition, evaluated from the record:

    access(I, scope) = ALL of
        { I is admitted (an owner act on record),
          I holds a channel grant for the gateway }
      AND ANY of
        { the scope is among I's granted scopes,
          wiki:admin is (it implies every lesser scope) }.

    Admission evidence: the activation record's table or a
    filings ledger (the branch-seat route). Gateway grant
    evidence: a token row on the activation record. A filings
    seat is a DIFFERENT channel (branch + email), reported
    separately — it grants no gateway scope.
    """
    ident = identity.lower()
    rows = _identity_rows(root)
    row = rows.get(ident)
    ledger = root / "wiki" / "filings" / ("%s-filings.md" % ident)
    has_ledger = ledger.exists()
    admitted = row is not None or has_ledger
    evidence = []
    if row is not None:
        evidence.append("wiki/access/identity-scopes.md table row")
    if has_ledger:
        evidence.append("wiki/filings/%s-filings.md (branch seat)"
                        % ident)
    token_scopes = list(row["scopes"]) if row else []
    token_issued = bool(row) and "issued" in row["token_note"] \
        and "none" not in row["raw_scopes"].lower()
    if ident == "owner":
        token_issued = True  # the owner's own ceremony, per record
    verdicts = {}
    for scope in ALL_SCOPES:
        granted = scope in token_scopes or any(
            scope in IMPLIES.get(g, ()) for g in token_scopes)
        verdicts[scope] = bool(admitted and token_issued and granted)
    bb_acts = 0
    bb = _black_box_path(root)
    if bb is not None and bb.exists():
        for line in bb.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ev = json.loads(line)
                if str(ev.get("actor", "")).lower() == ident:
                    bb_acts += 1
    return {
        "identity": ident, "admitted": admitted,
        "admission_evidence": evidence,
        "gateway_token_issued": token_issued,
        "gateway_scopes_on_record": token_scopes,
        "verdicts": verdicts,
        "branch_channel": has_ledger,
        "black_box_entries_as_actor": bb_acts,
    }


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("apply")
    p.add_argument("page"); p.add_argument("notice")
    p.add_argument("--reason", required=True)
    p.add_argument("--by", default="agent")
    p.add_argument("--date")

    p = sub.add_parser("retire")
    p.add_argument("page"); p.add_argument("notice")
    p.add_argument("--ruling")
    p.add_argument("--date")

    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("suggest")

    p = sub.add_parser("tiers")
    p.add_argument("identity")

    args = ap.parse_args(argv)
    root = args.root
    try:
        if args.cmd == "apply":
            d = apply_notice(args.page, args.notice, args.reason,
                             by=args.by, on=args.date, root=root)
            print("applied %s to %s (%s)"
                  % (args.notice, args.page, d))
        elif args.cmd == "retire":
            d = retire_notice(args.page, args.notice, args.ruling,
                              on=args.date, root=root)
            print("retired %s from %s (%s) — ruling: %s"
                  % (args.notice, args.page, d, args.ruling))
        elif args.cmd == "list":
            rows = list_notices(root)
            if not rows:
                print("no active notices")
            for page_rel, nid, d, reason, status in rows:
                print("%s  %s  applied %s  [%s]\n    reason: %s"
                      % (page_rel, nid, d, status, reason))
            bad = [r for r in rows if r[4] != "ok"]
            return 1 if bad else 0
        elif args.cmd == "check":
            rows = list_notices(root)
            bad = [r for r in rows if r[4] != "ok"]
            extra = unregistered_blocks(root)
            for r in bad:
                print("DRIFT %s %s: %s" % (r[0], r[1], r[4]))
            for rel, nid in extra:
                print("DRIFT %s %s: block on page, no register "
                      "application" % (rel, nid))
            if bad or extra:
                return 1
            print("notices check: %d active, all blocks verbatim"
                  % len(rows))
        elif args.cmd == "suggest":
            for nid, rows in suggest(root).items():
                print("## %s" % nid)
                if not rows:
                    print("  (no candidates)")
                for rel, already in rows:
                    print("  %s%s" % (rel,
                                       "  [applied]" if already
                                       else ""))
        elif args.cmd == "tiers":
            r = evaluate_tiers(args.identity, root)
            print("identity: %s" % r["identity"])
            print("  admitted (ALL-1): %s — %s"
                  % (r["admitted"],
                     "; ".join(r["admission_evidence"]) or "none"))
            print("  gateway token issued (ALL-2): %s — scopes "
                  "on record: %s"
                  % (r["gateway_token_issued"],
                     ", ".join(r["gateway_scopes_on_record"])
                     or "none"))
            for scope in ALL_SCOPES:
                print("  %s %s: %s"
                      % ("ANY" if scope != "wiki:read" else "   ",
                         scope,
                         "ALLOW" if r["verdicts"][scope]
                         else "DENY"))
            print("  branch channel (filings seat): %s"
                  % ("yes — separate channel, no gateway scope"
                     if r["branch_channel"] else "no"))
            print("  black box entries as actor: %d"
                  % r["black_box_entries_as_actor"])
    except NoticeError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
