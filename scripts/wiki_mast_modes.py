#!/usr/bin/env python3
"""MAST failure-mode field on corrections-ledger entries.

Marathon R9 lane BA (ideas board R7 research, Tier A; pattern:
MAST, Panickssery et al. 2025): when several agents work the
same record, a correction that names only what was wrong
cannot show whether the same WAY of failing keeps recurring
across agents. This build adds a closed failure-mode field:

  evaluation/mast-failure-modes.json — the vocabulary:
      fourteen modes in three families, adapted from MAST's
      fourteen IN THIS WIKI'S OWN WORDS (no MAST wording is
      copied; the count and the family shape are the borrowed
      structure). Closed: a mode enters or changes only by
      amending that file on the record.
  evaluation/corrections-mast.jsonl — the field itself, held
      as a sidecar register keyed by ledger entry (date +
      exact title), one row per classified entry, carrying
      `mode` + `multi_agent: true` + a one-line note. The
      field applies only to entries concerning multi-agent
      work.

ADDITIVE ONLY: the ledger page itself is never rewritten to
carry the field (the guidelines-as-data precedent), and no
existing entry is touched. An entry with no sidecar row has
NO recorded failure mode and is reported as UNCLASSIFIED,
honestly — the report lists them, it does not guess modes
for them. Ledger/counter change only: no agent behaviour
changes, and the existing corrections counter
(scripts/wiki_corrections.py) is untouched.

Usage:
  python3 scripts/wiki_mast_modes.py [--json]
  python3 scripts/wiki_mast_modes.py check
        (vocabulary + assignment integrity; exit 1 on a
        broken vocabulary, an unknown mode, an assignment
        whose ledger entry does not exist, or a duplicate)
Exit: report 0; check 0/1; 2 = a register cannot be read.
Stdlib only. No model calls, no network, writes nothing.
"""
import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "evaluation" / "mast-failure-modes.json"
ASSIGN_PATH = ROOT / "evaluation" / "corrections-mast.jsonl"
LEDGER_PATH = ROOT / "wiki" / "rules" / "corrections-ledger.md"
FAMILIES = ("framing", "handoff", "verification")
EXPECTED_MODES = 14


def load_vocab(path=VOCAB_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_assignments(path=ASSIGN_PATH):
    rows = []
    for line in Path(path).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("kind") == "assignment":
                rows.append(row)
    return rows


def check_vocab(vocab):
    findings = []
    if vocab.get("kind") != "mast-failure-mode-vocabulary":
        findings.append("kind is not "
                        "mast-failure-mode-vocabulary")
    modes = vocab.get("modes")
    if not isinstance(modes, list):
        return findings + ["modes missing or not a list"]
    if len(modes) != EXPECTED_MODES:
        findings.append(f"vocabulary must hold exactly "
                        f"{EXPECTED_MODES} modes, holds "
                        f"{len(modes)}")
    ids = [m.get("id") for m in modes]
    labels = [m.get("label") for m in modes]
    if len(set(ids)) != len(ids):
        findings.append("duplicate mode ids")
    if len(set(labels)) != len(labels):
        findings.append("duplicate mode labels")
    for m in modes:
        for field in ("id", "family", "label", "definition"):
            if not m.get(field):
                findings.append(f"{m.get('id')}: missing "
                                f"{field}")
        if m.get("family") not in FAMILIES:
            findings.append(f"{m.get('id')}: family "
                            f"{m.get('family')!r} not in "
                            f"{FAMILIES}")
    return findings


def _ledger_entries(root):
    """[(date, title)] from the corrections ledger, via the
    corrections counter's own parser; None when this tree
    carries no ledger page."""
    ledger = Path(root) / "wiki" / "rules" / \
        "corrections-ledger.md"
    if not ledger.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "wiki_corrections_for_mast",
        Path(__file__).resolve().parent / "wiki_corrections.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    entries, _cls = mod.parse_ledger(
        ledger.read_text(encoding="utf-8"))
    return [(e["date"], e["title"]) for e in entries]


def build_report(root):
    root = Path(root)
    vocab = load_vocab(root / "evaluation" /
                       "mast-failure-modes.json")
    assignments = load_assignments(
        root / "evaluation" / "corrections-mast.jsonl")
    mode_ids = {m["id"] for m in vocab.get("modes") or []}
    entries = _ledger_entries(root)
    counts = Counter(a.get("mode") for a in assignments)
    problems = []
    seen = set()
    for a in assignments:
        key = (a.get("entry_date"), a.get("entry_title"))
        if key in seen:
            problems.append(f"duplicate assignment for "
                            f"{key[0]} — {key[1]}")
        seen.add(key)
        if a.get("mode") not in mode_ids:
            problems.append(f"{key[0]} — {key[1]}: mode "
                            f"{a.get('mode')!r} not in the "
                            f"closed vocabulary")
        if a.get("multi_agent") is not True:
            problems.append(f"{key[0]} — {key[1]}: the field "
                            f"applies only to multi-agent "
                            f"work; multi_agent must be true")
    unclassified = None
    if entries is None:
        ledger_state = "absent"
    else:
        ledger_state = "present"
        assigned = {(a.get("entry_date"), a.get("entry_title"))
                    for a in assignments}
        for key in assigned:
            if key not in entries:
                problems.append(f"assignment names no ledger "
                                f"entry: {key[0]} — {key[1]}")
        unclassified = [f"{d} — {t}" for (d, t) in entries
                        if (d, t) not in assigned]
    return {
        "vocab_findings": check_vocab(vocab),
        "modes": vocab.get("modes") or [],
        "by_mode": {m["id"]: counts.get(m["id"], 0)
                    for m in vocab.get("modes") or []},
        "assignments": len(assignments),
        "ledger": ledger_state,
        "ledger_entries": None if entries is None
        else len(entries),
        "unclassified": unclassified,
        "problems": problems,
    }


def render_text(rep):
    lines = ["MAST failure modes — corrections-ledger field "
             "report"]
    if rep["vocab_findings"]:
        lines.append("Vocabulary findings: " +
                     "; ".join(rep["vocab_findings"]))
    lines.append(f"Assignments recorded: {rep['assignments']} "
                 f"(ledger: {rep['ledger']}"
                 + (f", {rep['ledger_entries']} entries)"
                    if rep["ledger_entries"] is not None
                    else ")"))
    lines.append("By failure mode (recurrences are the "
                 "counts > 1):")
    by_id = {m["id"]: m for m in rep["modes"]}
    for mid, n in rep["by_mode"].items():
        m = by_id[mid]
        lines.append(f"  {mid} [{m['family']}] "
                     f"{m['label']}: {n}")
    if rep["unclassified"] is None:
        lines.append("Unclassified: this tree carries no "
                     "corrections ledger, so there are no "
                     "entries to classify.")
    else:
        lines.append(f"UNCLASSIFIED entries (no failure mode "
                     f"recorded — reported, never guessed): "
                     f"{len(rep['unclassified'])}")
        for u in rep["unclassified"]:
            lines.append(f"  - {u}")
    if rep["problems"]:
        lines.append("Problems:")
        for p in rep["problems"]:
            lines.append(f"  - {p}")
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Count corrections-ledger entries by "
                    "MAST-adapted failure mode.")
    ap.add_argument("mode", nargs="?", default="report",
                    choices=("report", "check"))
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    root = Path(args.root)
    try:
        rep = build_report(root)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"mast-modes: cannot read registers: {exc}",
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(render_text(rep), end="")
    if args.mode == "check":
        return 1 if (rep["vocab_findings"] or
                     rep["problems"]) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
