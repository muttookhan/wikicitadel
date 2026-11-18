#!/usr/bin/env python3
"""Corrections repetition counter: reads the corrections
ledger and counts recurrences (WikiCitadel v1).

The ledger (wiki/rules/corrections-ledger.md) records each
correction with the standing rule it leaves. Since
WikiCitadel v1 every entry is also CLASSIFIED — by entry class
(correction / update / verdict-change) and by error kind
(wrong-fact, wrong-date, overstated-claim, stale-after-
change, misattributed-source, broken-mechanics, conduct) —
in the classification table appended to the ledger itself.
The taxonomy is stated on that page; this tool only counts.

The point is the Washington Post's "Bottomless Pinocchio"
lesson (media survey, find 6): a correction is not
the end of an error's file — it starts a repetition count.
A failure that recurs AFTER its first entry set a rule
against it is a different fact from a first occurrence, and
it should escalate in visibility instead of quietly
gaining a twin entry. This tool reports:

  - entry counts by class, by error kind, by standing rule;
  - the REPEATED-SINCE-RULED list: every entry whose error
    kind already appeared in an earlier entry (recurrences
    counted in ledger order — the order the entries, and
    their rules, landed);
  - any entries carrying no classification, and any
    classification rows matching no entry, so a new entry
    cannot slip in unclassified unnoticed.

This is a report, not a gate: exit code is always 0
(the wiki_stale.py convention).

Usage:
  python3 scripts/wiki_corrections.py [--json] [--ledger PATH]
Stdlib only.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "wiki" / "rules" / "corrections-ledger.md"

CLASSES = ("correction", "update", "verdict-change")
KINDS = ("wrong-fact", "wrong-date", "overstated-claim",
         "stale-after-change", "misattributed-source",
         "broken-mechanics", "conduct")

ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) — (.+?)\s*$", re.M)
ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def _norm_title(title):
    """Normalise a title for heading/table matching: case,
    quote style and punctuation do not carry meaning here."""
    t = title.lower().replace("“", '"').replace("”", '"')
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def parse_ledger(text):
    """(entries, classifications) from the ledger text.

    entries: [{date, title}] in ledger order — every
    `### YYYY-MM-DD — Title` heading.
    classifications: {normalised 'date title': {class,
    kind, rule}} parsed from the classification table's
    data rows (first cell `YYYY-MM-DD — Title`).
    """
    entries = [{"date": m.group(1), "title": m.group(2)}
               for m in ENTRY_RE.finditer(text)]
    classifications = {}
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 4:
            continue
        head = re.match(r"^(\d{4}-\d{2}-\d{2}) — (.+)$", cells[0])
        if not head:
            continue  # header or separator row
        key = head.group(1) + " " + _norm_title(head.group(2))
        classifications[key] = {
            "class": cells[1].strip("`").lower(),
            "kind": cells[2].strip("`").lower(),
            "rule": cells[3].strip("`"),
        }
    return entries, classifications


def build_report(text):
    """The full repetition report for a ledger text."""
    entries, classifications = parse_ledger(text)
    by_class = Counter()
    by_kind = Counter()
    by_rule = Counter()
    unclassified = []
    classified_entries = []
    for e in entries:
        key = e["date"] + " " + _norm_title(e["title"])
        c = classifications.get(key)
        if c is None:
            unclassified.append(e)
            continue
        classified_entries.append({**e, **c})
        by_class[c["class"]] += 1
        by_kind[c["kind"]] += 1
        by_rule[c["rule"]] += 1
    entry_keys = {e["date"] + " " + _norm_title(e["title"])
                  for e in entries}
    orphan_rows = sorted(k for k in classifications
                         if k not in entry_keys)

    # Recurrences: in ledger order, an entry repeats a kind
    # when that kind already appeared in an earlier entry —
    # i.e. the failure recurred after its first entry set a
    # rule against it.
    first_of_kind = {}
    repeated = []
    for e in classified_entries:
        if e["kind"] in first_of_kind:
            repeated.append({
                "date": e["date"], "title": e["title"],
                "kind": e["kind"], "rule": e["rule"],
                "first_ruled": first_of_kind[e["kind"]],
            })
        else:
            first_of_kind[e["kind"]] = {
                "date": e["date"], "title": e["title"],
                "rule": e["rule"]}
    recurrences_by_kind = Counter(r["kind"] for r in repeated)

    return {
        "entries": len(entries),
        "classified": len(classified_entries),
        "unclassified": unclassified,
        "orphan_classification_rows": orphan_rows,
        "by_class": {c: by_class.get(c, 0) for c in CLASSES},
        "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
        "unknown_kinds": sorted(
            {e["kind"] for e in classified_entries} - set(KINDS)),
        "by_rule": dict(sorted(by_rule.items())),
        "repeated_since_ruled": repeated,
        "recurrences_by_kind": {k: recurrences_by_kind.get(k, 0)
                                  for k in KINDS
                                  if recurrences_by_kind.get(k, 0)},
    }


def render_text(rep):
    lines = [
        "Corrections ledger — repetition report",
        f"Entries: {rep['entries']} · classified:"
        f" {rep['classified']} · unclassified:"
        f" {len(rep['unclassified'])}",
        "",
        "By entry class:",
    ]
    for c in CLASSES:
        lines.append(f"  {c:<16} {rep['by_class'][c]}")
    lines += ["", "By error kind:"]
    for k in KINDS:
        lines.append(f"  {k:<22} {rep['by_kind'][k]}")
    if rep["unknown_kinds"]:
        lines.append(f"  (outside the fixed list:"
                     f" {', '.join(rep['unknown_kinds'])})")
    lines += ["", "By standing rule:"]
    if rep["by_rule"]:
        for rule, n in rep["by_rule"].items():
            lines.append(f"  {rule:<28} {n}")
    else:
        lines.append("  (none)")
    lines += ["", "Repeated since ruled — a kind recurring after"
                  " its first entry set the rule:"]
    if rep["repeated_since_ruled"]:
        for r in rep["repeated_since_ruled"]:
            f0 = r["first_ruled"]
            lines.append(
                f"  - {r['date']} — {r['title']}"
                f" [{r['kind']}] — first ruled {f0['date']}"
                f" ({f0['title']}; rule: {f0['rule']})")
    else:
        lines.append("  (none — no error kind has recurred yet)")
    if rep["unclassified"]:
        lines += ["", "UNCLASSIFIED entries (no row in the"
                      " classification table):"]
        for e in rep["unclassified"]:
            lines.append(f"  - {e['date']} — {e['title']}")
    if rep["orphan_classification_rows"]:
        lines += ["", "Classification rows matching NO entry:"]
        for k in rep["orphan_classification_rows"]:
            lines.append(f"  - {k}")
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Corrections-ledger classification and"
                    " repetition counter.")
    ap.add_argument("--json", action="store_true",
                    help="emit the report as JSON")
    ap.add_argument("--ledger", default=None,
                    help="ledger path (default: the wiki's"
                         " corrections ledger)")
    args = ap.parse_args(argv[1:])
    path = Path(args.ledger) if args.ledger else LEDGER
    if not path.is_file():
        print(f"no ledger at {path}", file=sys.stderr)
        return 2
    rep = build_report(path.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(render_text(rep), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
