#!/usr/bin/env python3
"""Correction heed-rate reporting (AgentRecall-X pattern).

Marathon R9 lane BB (ideas board R7 deep-dive, Tier A):
AgentRecall-X (MIT) — pattern only. A correction's
effectiveness is measured, not asserted. Beside the
corrections ledger (wiki/rules/corrections-ledger.md, never
rewritten by this tool) sits an ADDITIVE outcome register,
evaluation/correction-outcomes.jsonl: one appended line per
correction whose outcome was observed, keyed by the ledger
entry's "YYYY-MM-DD — Title", recording:

  retrieved: was the correction retrieved when the corrected
             ground was next worked? (true / false / null)
  heeded:    did the work honour the correction's standing
             rule? (true / false / null)
  recurred:  did the same error recur after the correction?
             (true / false / null)

The report joins the register to the ledger (parsed with
wiki_corrections.parse_ledger by import — one ledger
semantics): ledger entries with NO outcome line, or with
heeded null, are UNMEASURED and reported as such. The heed
rate is computed over measured entries only, with a Wilson
score interval (z = 1.96). The first honest report over a
fresh register says "unmeasured" for nearly everything —
that is the correct output, not a failure.

Commands:
  report [--json] [--ledger PATH] [--register PATH]
  record --entry "YYYY-MM-DD — Title" [--retrieved T/F]
         [--heeded T/F] [--recurred T/F] [--note TEXT]
         [--recorded YYYY-MM-DD]   (append-only; refuses an
         entry that names no ledger entry)
Exit 0 report produced; 1 on --strict with unmeasured
entries; 2 usage error. Stdlib only, no network.
"""
import argparse
import importlib.util
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "wiki" / "rules" / "corrections-ledger.md"
REGISTER = ROOT / "evaluation" / "correction-outcomes.jsonl"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wilson(successes, n, z=1.96):
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (None, None)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
            / denom)
    return (round(max(0.0, centre - half), 4),
            round(min(1.0, centre + half), 4))


def load_outcomes(path=None):
    p = Path(path) if path else REGISTER
    outcomes = {}
    if not p.is_file():
        return outcomes
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and obj.get("entry"):
            outcomes[obj["entry"]] = obj  # latest line wins
    return outcomes


def build_report(ledger_text, outcomes):
    corr = _load("wiki_corrections",
                 Path(__file__).resolve().parent /
                 "wiki_corrections.py")
    entries, _cls = corr.parse_ledger(ledger_text)
    rows = []
    for e in entries:
        key = f"{e['date']} — {e['title']}"
        o = outcomes.get(key)
        measured = bool(o) and o.get("heeded") is not None
        rows.append({"entry": key,
                     "outcome": o,
                     "measured": measured})
    measured_rows = [r for r in rows if r["measured"]]
    heeded = sum(1 for r in measured_rows
                 if r["outcome"].get("heeded") is True)
    lo, hi = wilson(heeded, len(measured_rows))
    recurred = sum(1 for r in rows if r["outcome"]
                   and r["outcome"].get("recurred") is True)
    retrieved = sum(1 for r in rows if r["outcome"]
                    and r["outcome"].get("retrieved") is True)
    return {"ledger_entries": len(rows),
            "with_outcome_record": sum(
                1 for r in rows if r["outcome"]),
            "measured": len(measured_rows),
            "unmeasured": len(rows) - len(measured_rows),
            "heeded": heeded,
            "heed_rate": (round(heeded / len(measured_rows), 4)
                          if measured_rows else None),
            "wilson_95": [lo, hi],
            "retrieved_count": retrieved,
            "recurred_count": recurred,
            "rows": rows,
            "orphan_outcomes": sorted(
                set(outcomes) - {r["entry"] for r in rows})}


def _tf(value):
    if value is None:
        return None
    return {"true": True, "false": False}[value]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Correction heed-rate report (AgentRecall-X).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("--strict", action="store_true")
    pr.add_argument("--ledger", default=None)
    pr.add_argument("--register", default=None)
    pc = sub.add_parser("record")
    pc.add_argument("--entry", required=True)
    pc.add_argument("--retrieved", choices=("true", "false"))
    pc.add_argument("--heeded", choices=("true", "false"))
    pc.add_argument("--recurred", choices=("true", "false"))
    pc.add_argument("--note", default="")
    pc.add_argument("--recorded", default=None)
    pc.add_argument("--ledger", default=None)
    pc.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    command = args.command or "report"
    ledger_path = Path(getattr(args, "ledger", None) or LEDGER)
    register_path = Path(getattr(args, "register", None) or REGISTER)
    if not ledger_path.is_file():
        print(f"wiki_heed_rate: no ledger at {ledger_path}",
              file=sys.stderr)
        return 2
    ledger_text = ledger_path.read_text(encoding="utf-8")
    if command == "record":
        corr = _load("wiki_corrections",
                     Path(__file__).resolve().parent /
                     "wiki_corrections.py")
        entries, _ = corr.parse_ledger(ledger_text)
        known = {f"{e['date']} — {e['title']}" for e in entries}
        if args.entry not in known:
            print(f"wiki_heed_rate: no ledger entry named "
                  f"{args.entry!r} — refused", file=sys.stderr)
            return 2
        line = {"entry": args.entry,
                "retrieved": _tf(args.retrieved),
                "heeded": _tf(args.heeded),
                "recurred": _tf(args.recurred),
                "recorded": args.recorded or date.today().isoformat(),
                "note": args.note}
        with register_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(f"wiki_heed_rate: recorded outcome for {args.entry}")
        return 0
    rep = build_report(ledger_text, load_outcomes(register_path))
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"heed-rate: {rep['measured']}/{rep['ledger_entries']} "
              f"ledger entries measured; {rep['unmeasured']} "
              f"unmeasured")
        if rep["measured"]:
            print(f"  heeded {rep['heeded']}/{rep['measured']} "
                  f"(rate {rep['heed_rate']}, Wilson 95% "
                  f"{rep['wilson_95']}); retrieved "
                  f"{rep['retrieved_count']}; recurred "
                  f"{rep['recurred_count']}")
        else:
            print("  heed rate: unmeasured — no correction "
                  "outcomes recorded yet (the honest first report)")
        for k in rep["orphan_outcomes"]:
            print(f"  ORPHAN outcome (no ledger entry): {k}")
    if getattr(args, "strict", False) and rep["unmeasured"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
