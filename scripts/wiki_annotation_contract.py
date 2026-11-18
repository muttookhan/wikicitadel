#!/usr/bin/env python3
"""wiki_annotation_contract.py - annotation interaction contract checker.

Marathon R13 lane BB (ideas board line 202, deep-study batch 8,
Tier A): the INCEpTION PATTERN as a standing contract -
recommender-suggests / human-accepts states, agreement-measured
double annotation on golden-set pages, KB-linked mentions.
The contract lives AS DATA in evaluation/annotation-contract.json;
records live in evaluation/annotation-agreement.jsonl.
HARD BOUNDARY, stated on the machinery's face: the LABELLING
itself is the owner's and is NOT performed here; no command
creates a label. `check` validates record shapes and states;
`agreement` computes Cohen's kappa over records humans supplied.
Commands: contract / check [FILE] / agreement [FILE].
Exit 0 ok; 1 invalid; 2 usage. Stdlib only, no network.
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "evaluation" / "annotation-contract.json"
REGISTER = ROOT / "evaluation" / "annotation-agreement.jsonl"


def load_contract(path=None):
    return json.loads(Path(path or CONTRACT).read_text(encoding="utf-8"))


def load_records(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})"); continue
        if obj.get("kind") == "header":
            continue
        records.append(obj)
    return records, errors


def validate(records, contract):
    errs = []
    shape = contract["mention_shape"]
    states = set(contract["states"]["lifecycle"])
    for i, r in enumerate(records, 1):
        for f in shape["required"]:
            if f not in r:
                errs.append(f"record {i}: missing field {f!r}")
        if r.get("state") not in states:
            errs.append(f"record {i}: state {r.get('state')!r} not in "
                        f"{sorted(states)}")
        if r.get("annotator") == "recommender" and \
                r.get("state") not in ("suggested", "accepted",
                                       "rejected", "adjudicated"):
            errs.append(f"record {i}: recommender record in bad state")
        if r.get("state") == "adjudicated" and not (
                r.get("adjudicator") and r.get("adjudication_note")):
            errs.append(f"record {i}: adjudicated without adjudicator/"
                        "adjudication_note")
        if "kb_target" not in r and "kb_unlinked_reason" not in r:
            errs.append(f"record {i}: neither kb_target nor "
                        "kb_unlinked_reason (mentions are KB-linked "
                        "or the gap is explained)")
        s, e = r.get("span_start"), r.get("span_end")
        if isinstance(s, int) and isinstance(e, int) and e <= s:
            errs.append(f"record {i}: span_end must exceed span_start")
    return errs


def cohens_kappa(pairs):
    """pairs: list of (label_a, label_b). Returns kappa or None."""
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    labels = set(ca) | set(cb)
    pe = sum((ca.get(l, 0) / n) * (cb.get(l, 0) / n) for l in labels)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def agreement(records):
    by_unit = {}
    for r in records:
        if r.get("state") in (None, "suggested", "rejected"):
            continue
        key = (r.get("page"), r.get("span_start"), r.get("span_end"))
        by_unit.setdefault(key, {})[r.get("annotator")] = r.get("label")
    pairs, single = [], 0
    annotators = sorted({r.get("annotator") for r in records} - {None})
    for _key, labs in by_unit.items():
        if len(labs) >= 2:
            vals = [labs[a] for a in sorted(labs)[:2]]
            pairs.append((vals[0], vals[1]))
        else:
            single += 1
    return {"units_double_annotated": len(pairs),
            "units_single_annotated": single,
            "annotators": annotators,
            "cohens_kappa": cohens_kappa(pairs)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contract")
    for name in ("check", "agreement"):
        p = sub.add_parser(name); p.add_argument("file", nargs="?")
    a = ap.parse_args(argv)
    contract = load_contract()
    if a.cmd == "contract":
        print(json.dumps(contract, indent=2))
        return 0
    records, errors = load_records(a.file)
    errors += validate(records, contract)
    if a.cmd == "check":
        for e in errors:
            print(f"ERROR {e}")
        print(f"{len(records)} record(s), {len(errors)} error(s)")
        return 1 if errors else 0
    rep = agreement(records)
    rep["errors"] = errors
    print(json.dumps(rep, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
