#!/usr/bin/env python3
"""Validator for the RAGBench-style sentence-support row schema.

Marathon R8 lane BB (ideas board R6 deep-dive, Tier A): our
labelled set's row format, declared AS DATA in
evaluation/ragbench-row-schema.json - response sentences x
support verdict x supporting keys x per-scorer columns, with
generator/annotator provenance per row. The external RAGBench
dataset is NOT imported (its licence was unverified on the
opened page); this is the schema only, in our vocabulary.

Usage:
  python3 scripts/wiki_ragbench_schema.py ROWS.jsonl
          [--schema FILE]
Exit: 0 = every row valid; 1 = findings; 2 = usage error.
Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = ROOT / "evaluation" / "ragbench-row-schema.json"


def load_schema(path=None):
    return json.loads((Path(path) if path else DEFAULT_SCHEMA)
                      .read_text(encoding="utf-8"))


def validate_row(row, schema):
    """Return a list of findings (empty = row conforms)."""
    spec = schema["row"]
    findings = []
    for field in spec["required_fields"]:
        if field not in row:
            findings.append(f"missing required field {field}")
    if findings:
        return findings
    verdicts = set(spec["support_verdicts"])
    sentences = row.get("response_sentences")
    if not isinstance(sentences, list) or not sentences:
        findings.append("response_sentences must be a non-empty "
                        "list")
        sentences = []
    for i, s in enumerate(sentences):
        if not isinstance(s, dict):
            findings.append(f"sentence {i}: not an object")
            continue
        for f in spec["sentence_fields"]:
            if f not in s:
                findings.append(f"sentence {i}: missing {f}")
        v = s.get("support_verdict")
        if v is not None and v not in verdicts:
            findings.append(
                f"sentence {i}: support_verdict {v!r} not in "
                f"{sorted(verdicts)}")
        if v in ("supported", "partially-supported") and \
                not s.get("supporting_keys"):
            findings.append(
                f"sentence {i}: verdict {v} requires non-empty "
                f"supporting_keys")
        if v == "unsupported" and s.get("supporting_keys"):
            findings.append(
                f"sentence {i}: unsupported verdict must carry "
                f"no supporting_keys")
    scorers = row.get("scorer_columns")
    if not isinstance(scorers, dict):
        findings.append("scorer_columns must be an object keyed "
                        "by scorer name")
    prov = row.get("provenance") or {}
    for who in ("generator", "annotator"):
        entry = prov.get(who)
        if not isinstance(entry, dict) or not entry.get("kind") \
                or not entry.get("name"):
            findings.append(
                f"provenance.{who} must name kind and name")
    return findings


def validate_file(path, schema):
    rows, all_findings = 0, []
    for line in Path(path).read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows += 1
        row = json.loads(line)
        for f in validate_row(row, schema):
            all_findings.append(f"{row.get('id', '?')}: {f}")
    return rows, all_findings


def main(argv):
    ap = argparse.ArgumentParser(
        description="Validate sentence-support rows against "
                    "the declared row schema.")
    ap.add_argument("rows")
    ap.add_argument("--schema", default=None)
    args = ap.parse_args(argv[1:])
    if not Path(args.rows).is_file():
        print(f"ragbench-schema: rows file missing: {args.rows}",
              file=sys.stderr)
        return 2
    schema = load_schema(args.schema)
    rows, findings = validate_file(args.rows, schema)
    for f in findings:
        print(f"  [FINDING] {f}")
    print(f"ragbench-schema: {rows} rows, "
          f"{len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
