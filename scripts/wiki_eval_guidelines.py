#!/usr/bin/env python3
"""Annotation-guidelines coverage checker (Argilla pattern).

Marathon R8 lane BB (ideas board R6 deep-dive, Tier A): Argilla
(Apache-2.0) - pattern only. Convention: every evaluation dataset
carries its labelling/answering guidelines as a NAMED, VERSIONED
field, so labels can be re-read against the instructions in
force when they were made:

  guidelines: {"name": <str>, "version": <str>,
               "text": <str> | "ref": <path>}

Where a dataset's own format has a header/settings record (a
JSONL ``kind: header`` first line, or a JSON object's top level)
the field lives there. Where it has neither, the field lives in
the sidecar settings record
evaluation/guidelines-settings.json, keyed by dataset path -
existing dataset files are NEVER rewritten by this lane.

This checker is REPORT-ONLY: it lists which existing eval
datasets carry guidelines (in-file or sidecar) and which lack
one. Missing guidelines are a finding to remedy deliberately,
not a failure of any gate. Exit 0 = report produced (even with
findings); --strict exits 1 when any dataset lacks guidelines;
2 = usage error. Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "evaluation"
SIDECAR = EVAL_DIR / "guidelines-settings.json"
FIELD_SPEC = {"name": str, "version": str}


def guidelines_ok(value):
    if not isinstance(value, dict):
        return False
    if not value.get("name") or not value.get("version"):
        return False
    return bool(value.get("text") or value.get("ref"))


def in_file_guidelines(path):
    """Guidelines declared inside the dataset file itself."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix == ".json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        return obj.get("guidelines") if isinstance(obj, dict) \
            else None
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict) and obj.get("kind") == "header":
            return obj.get("guidelines")
        return None  # first record is not a header: none declared
    return None


def discover_datasets(eval_dir=None):
    base = Path(eval_dir) if eval_dir else EVAL_DIR
    found = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in (".jsonl", ".json") \
                and p.name != "guidelines-settings.json" \
                and "__pycache__" not in p.parts:
            found.append(p.relative_to(base).as_posix())
    return found


def coverage(eval_dir=None, sidecar_path=None):
    base = Path(eval_dir) if eval_dir else EVAL_DIR
    side = Path(sidecar_path) if sidecar_path else SIDECAR
    entries = {}
    if side.is_file():
        data = json.loads(side.read_text(encoding="utf-8"))
        entries = data.get("datasets") or {}
    rows = []
    for rel in discover_datasets(base):
        declared = in_file_guidelines(base / rel)
        source, value = None, declared
        if guidelines_ok(declared):
            source = "in-file"
        elif guidelines_ok((entries.get(rel) or {})
                           .get("guidelines")):
            source, value = "sidecar", \
                entries[rel]["guidelines"]
        rows.append({"dataset": rel, "has_guidelines":
                     source is not None, "source": source,
                     "guidelines_name": (value or {}).get("name")
                     if isinstance(value, dict) else None,
                     "guidelines_version": (value or {})
                     .get("version") if isinstance(value, dict)
                     else None})
    missing = [r["dataset"] for r in rows
               if not r["has_guidelines"]]
    return {"datasets": rows, "total": len(rows),
            "with_guidelines": len(rows) - len(missing),
            "missing": missing}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Report eval datasets lacking annotation "
                    "guidelines (Argilla pattern).")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    report = coverage()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in report["datasets"]:
            state = f"guidelines ({r['source']}: " \
                    f"{r['guidelines_name']} " \
                    f"v{r['guidelines_version']})" \
                    if r["has_guidelines"] else "NO GUIDELINES"
            print(f"  {r['dataset']}: {state}")
        print(f"eval-guidelines: {report['with_guidelines']}/"
              f"{report['total']} datasets carry guidelines; "
              f"{len(report['missing'])} lack one (report-only)")
    if args.strict and report["missing"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
