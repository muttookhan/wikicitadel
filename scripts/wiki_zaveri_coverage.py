#!/usr/bin/env python3
"""Zaveri quality-dimension coverage register — a static
table, checked for completeness (Marathon R12 lane BA).

Pattern: Zaveri, Rula, Maurino, Pietrobon, Lehmann & Auer,
"Quality Assessment for Linked Open Data: A Survey",
Semantic Web 7(1), 2016 — the paper's 23 quality dimensions
in six groups (accessibility / intrinsic / trust / dataset
dynamicity / contextual / representational), used here as a
VOCABULARY ONLY: dimension names and grouping are the
paper's; every coverage judgement is this wiki's own, stated
against checks that exist in this tree. No text is copied
beyond the dimension names themselves.

THE REGISTER — evaluation/zaveri-coverage.json, a STATIC
TABLE AS DATA: one row per dimension, naming the existing
checks (scripts/ paths) that cover it, a coverage state
(covered / partial / gap), the basis for the judgement, and
— for partial and gap rows — the gap note saying what is NOT
covered. Uncovered dimensions are listed as gaps on the
register's face; they are not softened into partials.

THIS TOOL IS A CHECKER OF THE TABLE, NOT AN ENGINE: it
measures nothing, runs none of the named checks, and invents
no coverage. `check` verifies the table stays complete and
honest against the canonical dimension list carried below:
exactly one row per dimension, no row for a dimension that
does not exist, category agreeing with the canonical list,
coverage in the closed vocabulary, covered/partial rows
naming at least one check whose file actually exists in
this tree, gap rows naming no checks and carrying a gap
note, partial rows carrying a gap note too. `report`
renders the table (plain or --json) including the gap list.

Commands: check / report. Exit 0 = table complete and
honest (report: rendered) · 1 = check findings · 2 = usage.
Stdlib only, no network, no model calls.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "zaveri-coverage.json"

# The canonical dimension list: Zaveri et al. 2016, section 4
# (5 + 3 + 4 + 3 + 3 + 5 = 23 dimensions, six groups).
CANONICAL = [
    ("accessibility", "availability"),
    ("accessibility", "licensing"),
    ("accessibility", "interlinking"),
    ("accessibility", "security"),
    ("accessibility", "performance"),
    ("intrinsic", "accuracy"),
    ("intrinsic", "consistency"),
    ("intrinsic", "conciseness"),
    ("trust", "reputation"),
    ("trust", "believability"),
    ("trust", "verifiability"),
    ("trust", "objectivity"),
    ("dataset-dynamicity", "currency"),
    ("dataset-dynamicity", "volatility"),
    ("dataset-dynamicity", "timeliness"),
    ("contextual", "completeness"),
    ("contextual", "amount-of-data"),
    ("contextual", "relevancy"),
    ("representational", "representational-conciseness"),
    ("representational", "representational-consistency"),
    ("representational", "understandability"),
    ("representational", "interpretability"),
    ("representational", "versatility"),
]
COVERAGE = ["covered", "partial", "gap"]


def load_register(path=None):
    p = Path(path) if path else REGISTER
    if not p.is_file():
        return None, [f"register missing: {p}"]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"register is not valid JSON: {e}"]
    return data, []


def check_register(data, root=None):
    """All completeness/honesty findings; [] means the table
    is complete against the canonical list and every claim
    it makes is anchored in a file that exists."""
    root = Path(root) if root else ROOT
    errors = []
    if not isinstance(data, dict):
        return ["register is not a JSON object"]
    if data.get("kind") != "zaveri-coverage-register":
        errors.append("kind must be 'zaveri-coverage-register'")
    dims = data.get("dimensions")
    if not isinstance(dims, list):
        errors.append("dimensions must be a list")
        dims = []
    declared = [(d.get("category"), d.get("dimension"))
                for d in dims if isinstance(d, dict)]
    if declared != CANONICAL:
        errors.append(
            "dimensions list does not match the canonical "
            "Zaveri et al. list (23 dimensions, six groups, "
            f"in canonical order); declared: {declared}")
    rows = data.get("rows")
    if not isinstance(rows, list):
        errors.append("rows must be a list")
        rows = []
    canon = dict((dim, cat) for cat, dim in CANONICAL)
    seen = {}
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"row {i}: not an object")
            continue
        dim = row.get("dimension")
        if dim not in canon:
            errors.append(f"row {i}: dimension {dim!r} is not "
                          "a Zaveri et al. dimension")
            continue
        if dim in seen:
            errors.append(f"row {i}: duplicate row for "
                          f"dimension {dim!r} (first on row "
                          f"{seen[dim]}); exactly one row per "
                          "dimension")
        else:
            seen[dim] = i
        if row.get("category") != canon[dim]:
            errors.append(f"row {i} ({dim}): category "
                          f"{row.get('category')!r} != canonical "
                          f"{canon[dim]!r}")
        cov = row.get("coverage")
        if cov not in COVERAGE:
            errors.append(f"row {i} ({dim}): coverage {cov!r} "
                          f"not in {COVERAGE}")
            continue
        checks = row.get("checks")
        if not isinstance(checks, list):
            errors.append(f"row {i} ({dim}): checks must be "
                          "a list")
            checks = []
        if cov in ("covered", "partial"):
            if not checks:
                errors.append(f"row {i} ({dim}): {cov} row "
                              "names no existing check")
            for c in checks:
                if not isinstance(c, str) or \
                        not c.startswith("scripts/"):
                    errors.append(f"row {i} ({dim}): check "
                                  f"{c!r} is not a scripts/ path")
                elif not (root / c).is_file():
                    errors.append(f"row {i} ({dim}): named check "
                                  f"{c} does not exist in this tree")
        if cov == "gap":
            if checks:
                errors.append(f"row {i} ({dim}): gap row names "
                              f"checks {checks}; a dimension "
                              "with a check is partial or "
                              "covered, never a gap")
            if not (row.get("gap_note") or "").strip():
                errors.append(f"row {i} ({dim}): gap row "
                              "carries no gap_note")
        if cov == "partial" and \
                not (row.get("gap_note") or "").strip():
            errors.append(f"row {i} ({dim}): partial row "
                          "carries no gap_note saying what "
                          "remains uncovered")
        if not (row.get("basis") or "").strip():
            errors.append(f"row {i} ({dim}): row carries no "
                          "basis for its coverage judgement")
    for _cat, dim in CANONICAL:
        if dim not in seen:
            errors.append(f"no row for dimension {dim!r}; "
                          "the table must account for every "
                          "dimension, uncovered ones as gaps")
    return errors


def build_report(data):
    rows = data.get("rows") or []
    by_coverage = {c: [] for c in COVERAGE}
    for r in rows:
        if r.get("coverage") in by_coverage:
            by_coverage[r["coverage"]].append(r["dimension"])
    return {
        "dimensions_total": len(CANONICAL),
        "rows": len(rows),
        "covered": sorted(by_coverage["covered"]),
        "partial": sorted(by_coverage["partial"]),
        "gaps": [{"dimension": r["dimension"],
                  "category": r.get("category"),
                  "gap_note": r.get("gap_note", "")}
                 for r in rows if r.get("coverage") == "gap"],
        "table": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Zaveri quality-dimension coverage "
                    "register checker / report (static table; "
                    "no engine).")
    sub = ap.add_subparsers(dest="command")
    for name in ("check", "report"):
        p = sub.add_parser(name)
        p.add_argument("--register", default=None)
        p.add_argument("--root", default=None)
        if name == "report":
            p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    data, errors = load_register(args.register)
    if data is None:
        for e in errors:
            print(f"zaveri-coverage: {e}", file=sys.stderr)
        return 1 if cmd == "check" else 2
    root = Path(args.root) if getattr(args, "root", None) else ROOT
    if cmd == "check":
        errs = check_register(data, root)
        for e in errs:
            print(f"zaveri-coverage: {e}", file=sys.stderr)
        print(f"zaveri-coverage: register "
              f"{'INVALID' if errs else 'complete'} "
              f"({len(data.get('rows') or [])} row(s) over "
              f"{len(CANONICAL)} dimensions)")
        return 1 if errs else 0
    rep = build_report(data)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"zaveri-coverage: {rep['rows']} row(s) over "
              f"{rep['dimensions_total']} dimensions; "
              f"covered {len(rep['covered'])}, "
              f"partial {len(rep['partial'])}, "
              f"gaps {len(rep['gaps'])}")
        for r in rep["table"]:
            checks = ", ".join(r.get("checks") or []) or "-"
            print(f"  [{r.get('category')}] {r.get('dimension')}: "
                  f"{r.get('coverage')} ({checks})")
        for g in rep["gaps"]:
            print(f"  GAP {g['dimension']}: {g['gap_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
