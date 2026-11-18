#!/usr/bin/env python3
"""The forecast register — Brier scoring of the agent's
own estimative judgments (WikiCitadel v1).

Pattern: find 17 (Brier 1950; Tetlock's Good
Judgment Project). The Brier score is a strictly proper
scoring rule — BS = mean of (f − o)² over resolved
forecasts, f the stated probability, o the outcome
(1 true, 0 false) — so honesty about one's actual
belief is the score-maximising strategy, and a forecaster
who always says 50% scores 0.25. The register's early
value is not the score; it is forcing forecasts to be
stated resolvably at all, and making the agent's misses
retrievable instead of forgotten. Scores are always
reported WITH their N; no skill claim is made at small N
(the reference literature wants very large samples to
discriminate skill on rare events).

THE RULE — stated here, in the register's header, and
enforced by the add guard: THE REGISTER SCORES THE
AGENT'S JUDGEMENTS ONLY, NEVER THE OWNER'S. The owner's
decisions and judgments are never entered and never
scored: the register scores the analyst, never the
customer (find 17, "Deliberately excluded").
`add` refuses any forecaster naming the owner.

Probabilities are stated under the estimative lexicon
(wiki/rules/estimative-lexicon.md, ICD 203's seven
bands): the numeric probability is the forecast, and
the band it falls in is recorded beside it. The lexicon
runs 1–99%, so `add` refuses p ≤ 0 and p ≥ 1 — a
certainty is not an estimate.

Register: evaluation/forecasts.jsonl, append-only and
hash-chained like the checkpoint register. A forecast
line is never edited; resolution is a NEW line
{kind: "resolution", forecast, outcome, brier} appended
by `resolve`, which computes the Brier score of that
forecast, (p − o)². `score` folds forecasts and
resolutions: mean Brier over resolved forecasts, the
open count, and a calibration table by lexicon band
(n, mean forecast, observed frequency).

Exit codes: 0 ok; 1 chain broken (verify) or score over
a broken chain; 2 usage error (unknown id, already
resolved, refused forecaster, out-of-range probability).
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/forecasts.jsonl"
GENESIS_PREV = "0" * 64

# EXAMPLE SET — a deployment lists the owner's name forms here
# so forecasts phrased with the owner's name resolve to them.
OWNER_NAMES = {"owner", "the owner"}

# ICD 203's seven bands (wiki/rules/estimative-lexicon.md).
BANDS = [
    (0.95, "almost certain(ly)"),
    (0.80, "very likely"),
    (0.55, "likely / probable"),
    (0.45, "roughly even chance"),
    (0.20, "unlikely"),
    (0.05, "very unlikely"),
    (0.0, "almost no chance / remote"),
]


def band_for(p: float) -> str:
    for floor, name in BANDS:
        if p >= floor:
            return name
    return BANDS[-1][1]


def brier(p: float, outcome: bool) -> float:
    return round((p - (1.0 if outcome else 0.0)) ** 2, 6)


# -- hashing / chaining (the checkpoint register's pattern) ----

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def line_digest(prev_hash: str, line_without_hash: dict) -> str:
    return sha256_hex(prev_hash.encode("utf-8")
                      + canonical(line_without_hash))


def load_register(path: Path):
    header, lines = None, []
    if not path.is_file():
        return header, lines
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if obj.get("kind") == "header":
            header = obj
        else:
            lines.append(obj)
    return header, lines


def append_chained(path: Path, body: dict) -> dict:
    _header, lines = load_register(path)
    prev = lines[-1]["line_hash"] if lines else GENESIS_PREV
    line = dict(body)
    line["prev_hash"] = prev
    line["line_hash"] = line_digest(prev, line)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(canonical(line).decode("utf-8") + "\n")
    return line


def verify_chain(lines):
    prev = GENESIS_PREV
    for i, line in enumerate(lines):
        if line.get("prev_hash") != prev:
            return False, i, "prev_hash mismatch"
        body = {k: v for k, v in line.items() if k != "line_hash"}
        if line_digest(prev, body) != line.get("line_hash"):
            return False, i, "line_hash mismatch (line altered)"
        prev = line["line_hash"]
    return True, None, None


HEADER = {
    "kind": "header", "register": "forecasts", "version": 1,
    "created": "WikiCitadel v1",
    "purpose": "Brier-scored register of the agent's own "
               "estimative judgments (WikiCitadel v1; "
               "find 17). Maintained by "
               "scripts/wiki_forecast.py.",
    "rule": "THIS REGISTER SCORES THE AGENT'S JUDGEMENTS ONLY, "
            "NEVER THE OWNER'S. The owner's decisions and "
            "judgments are never entered and never scored: the "
            "register scores the analyst, never the customer. "
            "The add command refuses a forecaster naming the "
            "owner.",
    "scoring": "Brier score per forecast, (p − o)^2, computed "
               "at resolution and appended as a resolution line; "
               "the forecast line is never edited. Scores are "
               "reported with their N; no skill claim at small N.",
    "lexicon": "Probabilities are stated with their ICD 203 "
               "band (wiki/rules/estimative-lexicon.md) beside "
               "them; the numeric probability is the forecast.",
}


def ensure_header(path: Path):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(HEADER, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def fold(lines):
    """forecasts: {id: entry}, resolutions: {id: resolution}"""
    forecasts, resolutions = {}, {}
    for line in lines:
        if line.get("kind") == "forecast":
            forecasts[line["id"]] = line
        elif line.get("kind") == "resolution":
            resolutions[line["forecast"]] = line
    return forecasts, resolutions


# -- commands ---------------------------------------------------------

def cmd_add(root: Path, args):
    who = (args.forecaster or "").strip()
    if who.lower() in OWNER_NAMES:
        print(f"REFUSED: forecaster {who!r} names the owner. This "
              f"register scores the AGENT'S judgements only, never "
              f"the owner's — the register scores the analyst, "
              f"never the customer.")
        return 2
    if not who:
        print("REFUSED: --forecaster is required (an agent identity)")
        return 2
    p = args.probability
    if not (0.0 < p < 1.0):
        print(f"REFUSED: probability {p} is outside (0, 1). The "
              f"estimative lexicon runs 1–99%: a certainty is not "
              f"an estimate, and an impossibility is not either.")
        return 2
    path = root / REGISTER_REL
    ensure_header(path)
    _h, lines = load_register(path)
    ok, bad, why = verify_chain(lines)
    if not ok:
        print(f"REFUSED: the register chain is broken at line "
              f"{bad} ({why}); nothing appended")
        return 2
    forecasts, _r = fold(lines)
    fid = f"fc-{len(forecasts) + 1:04d}"
    entry = {
        "kind": "forecast", "id": fid,
        "date": args.date or date.today().isoformat(),
        "forecaster": who,
        "statement": args.statement,
        "probability": p,
        "lexicon_band": band_for(p),
        "basis": args.basis or "",
        "resolution_rule": args.resolution_rule or "",
        "resolution_date": args.resolution_date,
        "resolution": "unresolved",
    }
    line = append_chained(path, entry)
    print(f"added {fid}: p={p} ({entry['lexicon_band']}) — "
          f"{args.statement} [resolves {args.resolution_date}; "
          f"chain {line['line_hash'][:12]}…]")
    return 0


def cmd_resolve(root: Path, args):
    path = root / REGISTER_REL
    if not path.is_file():
        print(f"no {REGISTER_REL} yet")
        return 2
    _h, lines = load_register(path)
    ok, bad, why = verify_chain(lines)
    if not ok:
        print(f"REFUSED: the register chain is broken at line "
              f"{bad} ({why}); nothing appended")
        return 2
    forecasts, resolutions = fold(lines)
    entry = forecasts.get(args.id)
    if entry is None:
        print(f"REFUSED: no forecast {args.id} in the register")
        return 2
    if args.id in resolutions:
        print(f"REFUSED: {args.id} is already resolved "
              f"({resolutions[args.id]['outcome']}) — a resolution "
              f"is append-only and is never revised in place")
        return 2
    outcome = args.outcome == "true"
    score = brier(entry["probability"], outcome)
    line = append_chained(path, {
        "kind": "resolution", "forecast": args.id,
        "resolved_date": args.date or date.today().isoformat(),
        "outcome": outcome, "brier": score,
        "note": args.note or "",
    })
    print(f"resolved {args.id}: outcome "
          f"{'true' if outcome else 'false'} — Brier {score} "
          f"(p was {entry['probability']}); chain "
          f"{line['line_hash'][:12]}…")
    return 0


def cmd_score(root: Path):
    path = root / REGISTER_REL
    if not path.is_file():
        print(f"no {REGISTER_REL} yet")
        return 2
    _h, lines = load_register(path)
    ok, bad, why = verify_chain(lines)
    if not ok:
        print(f"forecasts chain: BROKEN at line {bad}: {why}")
        return 1
    forecasts, resolutions = fold(lines)
    resolved = [(forecasts[fid], resolutions[fid])
                for fid in forecasts if fid in resolutions]
    open_ = [fid for fid in forecasts if fid not in resolutions]
    print(f"Forecast register: {len(forecasts)} forecast(s), "
          f"{len(resolved)} resolved, {len(open_)} open.")
    if resolved:
        mean = sum(r["brier"] for _f, r in resolved) / len(resolved)
        print(f"Mean Brier over resolved: {mean:.4f} "
              f"(N={len(resolved)} — a large-sample instrument; "
              f"no skill claim at this N)")
        by_band = {}
        for f, r in resolved:
            by_band.setdefault(f["lexicon_band"], []).append((f, r))
        print("Calibration by band:")
        for _floor, name in BANDS:
            rows = by_band.get(name)
            if not rows:
                continue
            mean_p = sum(f["probability"] for f, _r in rows) \
                / len(rows)
            freq = sum(1 for _f, r in rows if r["outcome"]) \
                / len(rows)
            print(f"  {name:<24} n={len(rows)}  mean forecast "
                  f"{mean_p:.2f}  observed {freq:.2f}")
    else:
        print("No resolved forecasts yet — nothing to score. "
              "The register's present value is that the forecasts "
              "are stated resolvably at all.")
    if open_:
        print(f"Open: {', '.join(sorted(open_))}")
    return 0


def cmd_verify(root: Path):
    _h, lines = load_register(root / REGISTER_REL)
    ok, bad, why = verify_chain(lines)
    if ok:
        print(f"forecasts chain: OK ({len(lines)} chained line(s))")
        return 0
    print(f"forecasts chain: BROKEN at line {bad}: {why}")
    return 1


def main(argv):
    ap = argparse.ArgumentParser(
        description="Forecast register with Brier scoring — the "
                    "AGENT'S judgements only, never the owner's "
                    ".")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add", help="append a forecast")
    pa.add_argument("--forecaster", required=True,
                    help="an AGENT identity (the owner is refused)")
    pa.add_argument("--statement", required=True)
    pa.add_argument("--probability", type=float, required=True)
    pa.add_argument("--resolution-date", required=True)
    pa.add_argument("--basis", default="",
                    help="one line: the reasoning from the record")
    pa.add_argument("--resolution-rule", default="",
                    help="what record settles it, and how")
    pa.add_argument("--date", default=None,
                    help="forecast date (default: today)")
    pr = sub.add_parser("resolve", help="append a resolution")
    pr.add_argument("id")
    pr.add_argument("outcome", choices=["true", "false"])
    pr.add_argument("--date", default=None)
    pr.add_argument("--note", default="")
    sub.add_parser("score", help="mean Brier + calibration by band")
    sub.add_parser("verify", help="verify the hash chain")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "add":
        return cmd_add(root, args)
    if args.cmd == "resolve":
        return cmd_resolve(root, args)
    if args.cmd == "score":
        return cmd_score(root)
    return cmd_verify(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
