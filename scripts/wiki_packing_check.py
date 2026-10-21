#!/usr/bin/env python3
"""Position check for Lost-in-the-Middle evidence packing
(Marathon R4 lane D, item 1).

The packing RULE itself lives in ``tools/ask/evidence_packing.py``
(built Marathon R2 lane B1): once selection is settled, a pack of
four or more is rearranged so the strongest passages sit at the
head and the tail and the weakest sit in the middle (Liu et al.,
"Lost in the Middle: How Language Models Use Long Contexts").

This script CHECKS an already-assembled pack against that rule —
it packs nothing and changes nothing.

Input: a JSON file holding either

- a ``pack_evidence`` result dict (``{"packed": [...], ...}``), or
- a bare list of packed passages.

Each packed passage is a dict with at least ``page`` and normally
a numeric ``score``.

The rule holds when:

- the pack has three or fewer passages (every position is
  edge-adjacent; the packing module leaves such packs in
  consideration order by design), or
- the head passage is among the strongest and the tail passage
  is the next strongest — precisely: the two end positions hold
  the pack's two highest scores, and no interior passage scores
  higher than the weaker end. When every score is distinct this
  is strengthened to an exact check: the pack's page order must
  equal ``arrange_lost_in_middle`` applied to the
  relevance-descending order of the same passages.

Usage:
  python3 scripts/wiki_packing_check.py PACK.json [--json]

Exit 0 = the rule holds; 1 = it is violated (the strongest
passage is buried mid-pack, or an end is not an edge score);
2 = usage / input error. Pure stdlib; no network.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _packing_module():
    spec = importlib.util.spec_from_file_location(
        "evidence_packing", ROOT / "tools" / "ask" / "evidence_packing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _score(entry):
    score = entry.get("score") if isinstance(entry, dict) else None
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score)
    return None


def check_pack(packed) -> dict:
    """Check *packed* (a list of passage dicts) against the rule.

    Returns {"holds": bool, "applied": bool, "n": int,
    "problems": [str], "order": [page, ...]}.
    """
    packed = list(packed or [])
    order = [str(p.get("page", "")) if isinstance(p, dict) else ""
             for p in packed]
    result = {"holds": True, "applied": False, "n": len(packed),
              "problems": [], "order": order}
    if len(packed) < 4:
        result["reason"] = (
            "pack of %d: every position is edge-adjacent, the "
            "packing module leaves it in consideration order"
            % len(packed))
        return result
    result["applied"] = True
    scores = [_score(p) for p in packed]
    if any(s is None for s in scores):
        result["holds"] = False
        result["problems"].append(
            "packed passages without numeric scores cannot be "
            "position-checked")
        return result
    ranked = sorted(scores, reverse=True)
    ends = [scores[0], scores[-1]]
    interior = scores[1:-1]
    if sorted(ends, reverse=True) != ranked[:2]:
        result["holds"] = False
        result["problems"].append(
            "the two end positions do not hold the pack's two "
            "strongest passages (ends=%s, strongest=%s)"
            % (ends, ranked[:2]))
    if interior and max(interior) > min(ends):
        result["holds"] = False
        result["problems"].append(
            "an interior passage (score %s) is stronger than the "
            "weaker end (score %s) — a strongest passage is "
            "buried mid-pack" % (max(interior), min(ends)))
    if len(set(scores)) == len(scores):
        module = _packing_module()
        by_score = sorted(packed, key=lambda p: -_score(p))
        expected = [str(p.get("page", "")) for p in
                    module.arrange_lost_in_middle(list(by_score))]
        if order != expected:
            result["holds"] = False
            result["problems"].append(
                "page order %s is not the Lost-in-the-Middle "
                "arrangement %s of the relevance-descending order"
                % (order, expected))
        result["expected_order"] = expected
    return result


def load_pack(path) -> list:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("packed"), list):
        return data["packed"]
    raise ValueError(
        "pack file must be a list of passages or a pack_evidence "
        "result dict with a 'packed' list")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check an assembled evidence pack against the "
                    "Lost-in-the-Middle packing rule.")
    ap.add_argument("pack", help="JSON file: pack_evidence result "
                                 "dict or bare list of passages")
    ap.add_argument("--json", action="store_true",
                    help="print the check result as JSON")
    ns = ap.parse_args(argv)
    try:
        packed = load_pack(ns.pack)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("packing check: cannot read pack: %s" % exc,
              file=sys.stderr)
        return 2
    result = check_pack(packed)
    if ns.json:
        print(json.dumps(result, indent=2))
    elif result["holds"]:
        print("packing check: HOLDS — %d passage(s), order: %s"
              % (result["n"], ", ".join(result["order"]) or "(empty)"))
        if result.get("reason"):
            print("  " + result["reason"])
    else:
        print("packing check: VIOLATED — %d passage(s)" % result["n"])
        for problem in result["problems"]:
            print("  - " + problem)
    return 0 if result["holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
