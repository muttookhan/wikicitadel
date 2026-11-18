#!/usr/bin/env python3
"""Forgetting battery: does severance actually forget — and only
what it should? (Landscape weekly, 2026-10-27; Bemula pattern.)

Pattern: Bemula — Xie et al., "Can Agents Forget When Asked?"
(arXiv:2610.18052, 2026-10-13): the first benchmark dedicated to
memory unlearning found no evaluated system passing more than
1.5% of forget requests end to end; failures are two-sided —
requested information stays extractable, OR far more than
requested is deleted. Re-implemented from the paper's design in
this wiki's own terms; no code copied (the paper's code was not
opened; the benchmark design is restated here from its abstract).

This wiki forgets by DEACTIVATION: a superseded or negatively
treated claim is severed at retrieval time by register lookup
(scripts/wiki_severance.py -> evaluation/retrieval-severance.json),
never silently erased — the page and its history stay (the
deactivate-vs-erase distinction PowerContext v1.3.0 states the
same way). The battery therefore checks the four properties
this architecture promises, deterministically, no model calls:

  STORED       the severed claim's page still exists (history
               preserved; forgetting is deactivation, not a hole)
  SEVERED      the severance entry carries usable cues — a claim
               with no cues cannot be cut at retrieval time
  PARAPHRASE   a reworded probe still matches the entry under
               the severance QUERY-match rule (a cue phrase as a
               contiguous token subsequence, OR at least half
               and at least 3 of the distinctive terms present),
               so the cut survives rewording / simple extraction
  PRESERVATION control pages named in
               evaluation/forgetting-battery.jsonl (live,
               load-bearing pages) exist and are NOT severed —
               the over-deletion half of Bemula's finding

Cases are derived from the severance list present in THIS tree
(never hand-listed), so the battery grows with the register.
Exit codes: 0 = every check passes, 1 = a failure (a finding —
reported, never repaired by this tool), 2 = usage error.
Stdlib only; no network.

Usage:
  python3 scripts/wiki_forgetting_check.py [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEVERANCE_REL = "evaluation/retrieval-severance.json"
BATTERY_REL = "evaluation/forgetting-battery.jsonl"

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def contains_phrase(probe_tokens: list[str], phrase: list[str]) -> bool:
    if not phrase or len(phrase) > len(probe_tokens):
        return False
    n = len(phrase)
    return any(probe_tokens[i:i + n] == phrase
               for i in range(len(probe_tokens) - n + 1))


def query_match(probe: str, entry: dict) -> bool:
    """The severance QUERY-match rule, mirrored from
    scripts/wiki_severance.py: any cue phrase contiguous in the
    probe, or >= half (and >= 3) of the distinctive terms."""
    pt = tokens(probe)
    cues = entry.get("cues") or {}
    for phrase in cues.get("phrases") or []:
        if contains_phrase(pt, list(phrase)):
            return True
    terms = cues.get("distinctive_terms") or cues.get("terms") or []
    if terms:
        present = len(set(terms) & set(pt))
        if present >= 3 and present * 2 >= len(terms):
            return True
    return False


def paraphrase_probes(entry: dict) -> list[str]:
    """Reworded probes for one severance entry: (a) its distinctive
    terms in reverse order inside filler wording — exercises the
    term rule; (b) an alternate cue phrase, when the entry has
    more than one — exercises the phrase rule."""
    cues = entry.get("cues") or {}
    terms = cues.get("distinctive_terms") or cues.get("terms") or []
    probes = []
    if terms:
        probes.append("please explain " + " ".join(reversed(terms)) + " today")
    phrases = cues.get("phrases") or []
    if len(phrases) > 1:
        probes.append(" ".join(phrases[-1]))
    return probes


def load_battery(root: Path) -> list[dict]:
    path = root / BATTERY_REL
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def run(root: Path) -> dict:
    sev_path = root / SEVERANCE_REL
    report = {"severance_entries": 0, "checks": 0, "failures": []}

    def check(kind: str, subject: str, ok: bool, detail: str = ""):
        report["checks"] += 1
        if not ok:
            report["failures"].append(
                {"kind": kind, "subject": subject, "detail": detail})

    if not sev_path.exists():
        check("severed", SEVERANCE_REL, False, "severance list missing")
        return report
    sev = json.loads(sev_path.read_text(encoding="utf-8"))
    entries = sev.get("entries") or []
    report["severance_entries"] = len(entries)
    severed_pages = set()
    for entry in entries:
        eid = entry.get("id", "?")
        page = entry.get("page") or ""
        if page:
            severed_pages.add(page)
            check("stored", eid, (root / page).exists(),
                  f"severed page missing (erasure, not deactivation): {page}")
        cues = entry.get("cues") or {}
        has_cues = bool(cues.get("phrases")) or bool(
            cues.get("distinctive_terms") or cues.get("terms"))
        check("severed", eid, has_cues, "entry carries no usable cues")
        if has_cues:
            for probe in paraphrase_probes(entry):
                check("paraphrase", eid, query_match(probe, entry),
                      f"reworded probe does not match: {probe!r}")
    for row in load_battery(root):
        if row.get("kind") != "control":
            continue
        page = row.get("page", "")
        check("preservation", page, (root / page).exists(),
              "control page missing")
        check("preservation", page, page not in severed_pages,
              "control page is severed (over-deletion)")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="emit the report as JSON")
    args = ap.parse_args(argv)
    report = run(ROOT)
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        print(f"forgetting battery: {report['severance_entries']} severance "
              f"entries, {report['checks']} checks, "
              f"{len(report['failures'])} failures")
        for f in report["failures"]:
            print(f"  FAIL [{f['kind']}] {f['subject']}: {f['detail']}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
