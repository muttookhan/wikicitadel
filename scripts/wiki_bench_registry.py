#!/usr/bin/env python3
"""Benchmark reproducibility grading + traced-or-null checker.

Marathon R9 lane BB (ideas board R7 deep-dive, Tier A):
memory-bench-registry pattern (MIT; its data under a
separate LICENSE-DATA — pattern only, no data imported).

Two disciplines, both as a SIDECAR + checker after the
guidelines-settings precedent (Marathon R8 lane BB):
existing benchmark/eval files are NEVER rewritten.

1. Reproducibility grading: every benchmark/eval record may
   carry a reproducibility level from the closed vocabulary
       paper_only / data_public / official_script /
       smoke_tested / full_run
   in the sidecar evaluation/bench-reproducibility.json, keyed by
   dataset path. null records, honestly, that the record has
   not been graded — the shipped sidecar grades nothing, so
   the first coverage report is all-null and that is the
   correct output.
2. Traced-or-null: every externally-sourced field on a
   record (source, upstream, upstream_url, paper, dataset_url)
   carries its source trace or is null. A record that asserts
   an external field while its `source` trace is null is a
   finding; an invalid reproducibility value is a finding.

Commands:
  generate [--eval-dir DIR] [--out FILE]  write the sidecar
        covering every discovered eval dataset (all null)
  check [--json] [--strict]              report-only check
        (exit 0; --strict exits 1 on findings)
Exit 2 usage error. Stdlib only, no network.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "evaluation"
SIDECAR = EVAL_DIR / "bench-reproducibility.json"
LEVELS = ("paper_only", "data_public", "official_script",
          "smoke_tested", "full_run")
EXTERNAL_FIELDS = ("upstream", "upstream_url", "paper",
                   "dataset_url")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover(eval_dir=None):
    guide = _load("wiki_eval_guidelines",
                  Path(__file__).resolve().parent /
                  "wiki_eval_guidelines.py")
    base = Path(eval_dir) if eval_dir else EVAL_DIR
    return [d for d in guide.discover_datasets(base)
            if d != "bench-reproducibility.json"]


def empty_entry():
    return {"reproducibility": None, "source": None,
            "upstream": None, "upstream_url": None,
            "paper": None, "dataset_url": None}


def generate(eval_dir=None, out=None):
    base = Path(eval_dir) if eval_dir else EVAL_DIR
    data = {"kind": "bench-registry", "version": 1,
            "convention": {
                "reproducibility_levels": list(LEVELS),
                "placement": "Sidecar only "
                             "(evaluation/bench-reproducibility.json); "
                             "existing benchmark/eval files are "
                             "never rewritten to add the field.",
                "null_means": "reproducibility: null records "
                              "the record has not been graded; "
                              "externally-sourced fields are "
                              "their source trace or null "
                              "(traced-or-null)."},
            "datasets": {rel: empty_entry()
                         for rel in discover(base)}}
    target = Path(out) if out else SIDECAR
    target.write_text(json.dumps(data, indent=2,
                                 ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return data


def check(eval_dir=None, sidecar_path=None):
    base = Path(eval_dir) if eval_dir else EVAL_DIR
    side = Path(sidecar_path) if sidecar_path else SIDECAR
    datasets = {}
    if side.is_file():
        datasets = (json.loads(side.read_text(encoding="utf-8"))
                    .get("datasets") or {})
    findings = []
    rows = []
    for rel in discover(base):
        entry = datasets.get(rel)
        if entry is None:
            findings.append(f"{rel}: no bench-registry entry")
            rows.append({"dataset": rel, "reproducibility": None,
                         "graded": False})
            continue
        level = entry.get("reproducibility")
        if level is not None and level not in LEVELS:
            findings.append(
                f"{rel}: reproducibility {level!r} not in the "
                f"closed vocabulary")
        asserted = [f for f in EXTERNAL_FIELDS if entry.get(f)]
        if asserted and not entry.get("source"):
            findings.append(
                f"{rel}: traced-or-null violation — external "
                f"field(s) {asserted} asserted but source is "
                f"null")
        rows.append({"dataset": rel, "reproducibility": level,
                     "graded": level is not None})
    extra = sorted(set(datasets) - set(discover(base)))
    for rel in extra:
        findings.append(f"{rel}: registry entry names no "
                        f"discovered dataset")
    graded = sum(1 for r in rows if r["graded"])
    return {"datasets": rows, "total": len(rows),
            "graded": graded, "ungraded": len(rows) - graded,
            "findings": findings}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Benchmark reproducibility / traced-or-null "
                    "registry checker (memory-bench-registry).")
    sub = ap.add_subparsers(dest="command")
    pg = sub.add_parser("generate")
    pg.add_argument("--eval-dir", default=None)
    pg.add_argument("--out", default=None)
    pc = sub.add_parser("check")
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    command = args.command or "check"
    if command == "generate":
        data = generate(args.eval_dir, args.out)
        print(f"wiki_bench_registry: wrote sidecar covering "
              f"{len(data['datasets'])} dataset(s), all "
              f"reproducibility null (ungraded)")
        return 0
    rep = check()
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"bench-registry: {rep['graded']}/{rep['total']} "
              f"records graded; {rep['ungraded']} ungraded "
              f"(reproducibility null)")
        for f in rep["findings"]:
            print(f"  FINDING: {f}")
        if not rep["findings"]:
            print("  traced-or-null: no violations")
    if args.strict and rep["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
