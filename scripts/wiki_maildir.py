#!/usr/bin/env python3
"""wiki_maildir.py — the Maildir correspondence check
(WikiCitadel v1; correspondence rule, find 12).

The rule it checks lives on wiki/rules/maildir-correspondence.md:
correspondence is preserved ONE FILE PER MESSAGE, canonical state
in the files, any index rebuildable from them, tag/annotation
layers only as plain-text sidecars inside the same tree (the
notmuch-dump pattern). This tool measures the archive against
that rule. It never edits, renames, or deletes anything —
renames of raw files are custody events; gaps are reported,
with the fix named, for the parent/owner to perform.

THE POPULATIONS (the archive is not one shape):

- Class A — agent-mail message files (raw/filings/<agent>/):
  files the filings pickup preserved under its header line
  (`# Filing from <sender> — received <ts> — message id
  msg_...`). Checked in full: headers intact (sender, received
  timestamp, message id, a Subject: line), filename form
  <YYYY-MM-DD>-<first 8 of message id>.md with the filename
  date agreeing with the header's received date (UTC or the
  local date the header also states), message id unique
  across the archive, and an index entry — the message id or
  the raw path on the agent's ledger page
  (wiki/filings/<agent>-filings.md; found elsewhere in
  wiki/filings/ = a warning, found nowhere = a gap).
- Class B — other filed records under raw/filings/ (verbatim
  material that arrived by branch or by hand: memory notes,
  chat logs, reading shards, READMEs excluded, .gitkeep
  excluded). Not messages; checked only for an index mention
  (the file's name appearing somewhere under wiki/).
- Class C — sealed monoliths: sealed agent-mail inbox
  extractions (raw/sources/*-agent-mail-*-inbox-full.md)
  hold a whole inbox per file, messages delimited in the text.
  They are sealed ingest records, a stated exception class in
  the rule — reported with their thread/message counts, never
  failed for not being per-message. Splitting one is a new
  ingest act, not a fix this check performs.

KNOWN GAP the check cannot see mechanically (on the record in
the project log): OUTBOUND correspondence —
the agent's own sent mail (e.g. a collaborator thread's opening
and rules emails) exists only as message ids cited in
wiki/log.md;
no raw per-message preservation exists for sent mail yet. The
rule covers outbound from the next send onward.

    python3 scripts/wiki_maildir.py check [--root <repo>]
                                          [--json]

Exit codes: 0 no gaps · 1 gaps found · 2 usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER_RE = re.compile(
    r"^# Filing from (?P<sender>.+?) — received "
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"(?: \((?P<local>\d{4}-\d{2}-\d{2}) [^)]*\))?"
    r" — message id (?P<id>msg_[0-9a-f]+)\s*$", re.M)
FNAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{8})\.md$")

# Agent dir slug -> ledger page under wiki/filings/.
# EXAMPLE MAP — deployments name their own seated agents here.
LEDGERS = {
    "galen": "galen-filings.md",
    "codex": "codex-filings.md",
    "chatgpt": "chatgpt-coordinator-filings.md",
    "antigravity": "antigravity-filings.md",
    "hugo": "hugo-filings.md",
}

MONOLITH_GLOB = "*-agent-mail-*-inbox-full.md"


def _ledger_texts(root):
    d = root / "wiki" / "filings"
    texts = {}
    if d.is_dir():
        for p in d.glob("*.md"):
            texts[p.name] = p.read_text(encoding="utf-8",
                                        errors="replace")
    return texts


def _all_wiki_text(root):
    parts = []
    for p in (root / "wiki").rglob("*.md"):
        parts.append(p.read_text(encoding="utf-8",
                                 errors="replace"))
    return "\n".join(parts)


def check(root):
    filings = root / "raw" / "filings"
    ledgers = _ledger_texts(root)
    wiki_text = None  # lazy, class B only
    a_items, b_items, c_items = [], [], []
    gaps, warnings = [], []
    seen_ids = {}

    files = sorted(p for p in filings.rglob("*")
                   if p.is_file() and p.name != ".gitkeep") \
        if filings.is_dir() else []
    for p in files:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="replace")
        m = HEADER_RE.search(text)
        if m:
            item = {"path": rel, "class": "A",
                    "id": m.group("id"), "problems": []}
            slug = p.parent.name
            fm = FNAME_RE.match(p.name)
            if not fm:
                item["problems"].append(
                    "filename not in <date>-<first8>.md form")
            else:
                if fm.group(2) != m.group("id")[4:12]:
                    item["problems"].append(
                        "filename suffix %s != message id "
                        "first8 %s" % (fm.group(2),
                                       m.group("id")[4:12]))
                dates = {m.group("ts")[:10]}
                if m.group("local"):
                    dates.add(m.group("local"))
                if fm.group(1) not in dates:
                    item["problems"].append(
                        "filename date %s agrees with neither "
                        "the UTC nor the local received date %s"
                        % (fm.group(1), sorted(dates)))
            head = "\n".join(text.splitlines()[:5])
            if not re.search(r"^Subject:", head, re.M):
                item["problems"].append(
                    "no Subject: line in the header block")
            if m.group("id") in seen_ids:
                item["problems"].append(
                    "DUPLICATE message id — also at %s"
                    % seen_ids[m.group("id")])
                gaps.append("%s: duplicate message id %s "
                            "(also %s)" % (rel, m.group("id"),
                                           seen_ids[m.group("id")]))
            else:
                seen_ids[m.group("id")] = rel
            ledger = ledgers.get(LEDGERS.get(slug, ""), "")
            if m.group("id") in ledger or rel in ledger:
                item["indexed"] = "ledger"
            elif any(m.group("id") in t or rel in t
                     for t in ledgers.values()):
                item["indexed"] = "elsewhere"
                warnings.append(
                    "%s: indexed outside its ledger page" % rel)
            else:
                item["indexed"] = "nowhere"
                item["problems"].append(
                    "no index entry (message id / raw path "
                    "absent from wiki/filings/)")
            for prob in item["problems"]:
                if not prob.startswith("DUPLICATE"):
                    gaps.append("%s: %s" % (rel, prob))
            a_items.append(item)
        elif p.name == "README.md":
            continue  # structural file, not a filed record
        else:
            if wiki_text is None:
                wiki_text = _all_wiki_text(root)
            item = {"path": rel, "class": "B",
                    "indexed": p.name in wiki_text}
            if not item["indexed"]:
                item.setdefault("problems", []).append(
                    "no index mention of the filename under "
                    "wiki/")
                gaps.append("%s: no index mention under wiki/"
                            % rel)
            b_items.append(item)

    src = root / "raw" / "sources"
    if src.is_dir():
        for p in sorted(src.glob(MONOLITH_GLOB)):
            text = p.read_text(encoding="utf-8",
                               errors="replace")
            # The three extractions delimit in three styles
            # (==== THREAD n ==== / === THREAD n ===;
            # "Message n — Date:" / "— Message n —"): count
            # the union of the delimiter lines.
            c_items.append({
                "path": str(p.relative_to(root)), "class": "C",
                "threads": len(re.findall(r"^=+ THREAD ",
                                          text, re.M)),
                "messages": len(re.findall(
                    r"^(?:Message \d+ — |— Message \d+ —$)",
                    text, re.M)),
            })

    return {"gaps": gaps, "warnings": warnings,
            "a": a_items, "b": b_items, "c": c_items}


def render(rep):
    lines = ["Maildir correspondence check  — "
             "surfacing only, nothing edited"]
    a_bad = [i for i in rep["a"] if i.get("problems")]
    lines.append("  Class A (agent-mail messages): %d file(s), "
                 "%d conforming, %d with problems"
                 % (len(rep["a"]), len(rep["a"]) - len(a_bad),
                    len(a_bad)))
    for i in rep["a"]:
        state = "ok" if not i.get("problems") else \
            "PROBLEMS: " + "; ".join(i["problems"])
        lines.append("    - %s · %s · indexed: %s · %s"
                     % (i["path"], i["id"], i["indexed"], state))
    b_bad = [i for i in rep["b"] if not i["indexed"]]
    lines.append("  Class B (other filed records): %d file(s), "
                 "%d indexed, %d unindexed"
                 % (len(rep["b"]), len(rep["b"]) - len(b_bad),
                    len(b_bad)))
    for i in rep["b"]:
        lines.append("    - %s · indexed: %s"
                     % (i["path"], i["indexed"]))
    lines.append("  Class C (sealed agent-mail extractions — "
                 "exception class, not per-message by design):")
    for i in rep["c"]:
        lines.append("    - %s · %d threads · %d messages"
                     % (i["path"], i["threads"], i["messages"]))
    for w in rep["warnings"]:
        lines.append("  WARNING: %s" % w)
    if rep["gaps"]:
        lines.append("  GAPS (%d):" % len(rep["gaps"]))
        for g in rep["gaps"]:
            lines.append("    - %s" % g)
    else:
        lines.append("  GAPS: none")
    lines.append("  Known gap outside this check's sight: "
                 "outbound correspondence has no raw "
                 "per-message preservation yet (see the rules "
                 "page + the project log).")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wiki_maildir.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check")
    ck.add_argument("--root", default=None)
    ck.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    rep = check(root)
    if args.json:
        print(json.dumps(rep, indent=1, sort_keys=True))
    else:
        print(render(rep))
    return 1 if rep["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())
