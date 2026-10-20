#!/usr/bin/env python3
"""ACH matrices for the LLM Wiki — Analysis of Competing
Hypotheses kept as BOOKKEEPING, not as an accuracy technology
(WikiCitadel v1).

What ACH is, per the intel-tradecraft find (find 5):
Heuer's matrix — hypotheses across the top, evidence down the
side, each cell rated consistent / inconsistent / not
applicable, worked across rows so the point is DIAGNOSTICITY:
evidence consistent with every hypothesis discriminates
nothing. Tentative conclusions come by disproof: the
hypothesis to take seriously is the one with the LEAST
evidence against it, not the most evidence for it.

Why it is adopted in this deliberately reduced form — the
evaluation literature, stated on the label as the find states
it: Karvetski & Mandel (2020, N=227) found the ACH group
showed NO coherence advantage over a no-technique control,
and additionally showed pseudo-diagnostic weighting;
Mandel, Karvetski & Dhami (2018) found analysts using ACH
less coherent and marginally less accurate than controls;
Whitesmith (2019) found it did not mitigate confirmation bias.
What ACH demonstrably produces even when it does not improve
the judge is an AUDITABLE RECORD: the full hypothesis set
considered, the evidence arrayed against all of them at once,
the non-diagnostic evidence visibly flagged, the losers kept
on the page with their inconsistency counts. That record is
what this tool keeps. Its output is an ordinal survivor
ranking for the owner's decision — never a probability,
never a verdict the agent acts on alone.

Hard rules of this implementation, imported from the find's
guardrails:

  * The CALLER scores every cell. The tool contains no
    text-similarity scoring, no suggestion engine, nothing
    that fills a cell. An unscored cell is shown as unscored.
  * Correlated evidence is marked as ONE witness, not two
    rows: evidence items may carry a shared `witness` group;
    counts are reported both raw and witness-adjusted (a
    shared-witness group contributes at most one inconsistency
    per hypothesis). The genealogy lane's
    shared-informant rule is the same law.
  * Hypotheses are capped small: create WARNS above 7 (the
    expert-witness literature's practicality limit).
  * Every evidence item carries a source citation; every
    scored cell carries the citation its scoring rests on.

Register: evaluation/ach-matrices.jsonl — append-only, one
header line + one line per matrix revision; a matrix's
current state is its latest revision (the source-grades
fold). Commands: create, add-evidence, score, render, list,
check. Stdlib only.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_PATH = ROOT / "evaluation" / "ach-matrices.jsonl"

HEADER = {
    "kind": "header",
    "register": "ach-matrices",
    "version": 1,
    "created": "WikiCitadel v1",
    "purpose": ("ACH (Analysis of Competing Hypotheses) matrices "
                "for the LLM Wiki (WikiCitadel v1; "
                "Heuer's matrix via the intel-tradecraft "
                "survey, find 5). Adopted as BOOKKEEPING, not as "
                "an accuracy technology: Karvetski & Mandel "
                "(2020) found no coherence advantage for ACH "
                "over a no-technique control, so a matrix here "
                "is an auditable record — hypotheses considered, "
                "evidence arrayed against all of them, "
                "non-diagnostic evidence flagged, losers kept "
                "with their inconsistency counts — and its "
                "output is an ordinal survivor ranking for the "
                "owner's decision, never a probability and "
                "never a verdict the agent acts on alone."),
    "maintenance": ("Append-only, maintained with "
                    "scripts/wiki_ach.py. The caller scores "
                    "every cell; the tool never scores. "
                    "Correlated evidence is marked with a "
                    "shared witness group and counts once in "
                    "witness-adjusted counts. A matrix's "
                    "current state is its latest revision line; "
                    "revisions are never edited in place."),
}

CELL_VALUES = ("C", "I", "NA")
HYPOTHESIS_SOFT_CAP = 7

CAVEAT = (
    "Reading this matrix (Heuer, with the evidence label on): "
    "the hypothesis to take seriously is the one with the "
    "LEAST evidence against it, not the most evidence for it. "
    "And the standing caveat — Karvetski & Mandel (2020) "
    "found ACH gave no coherence advantage over no technique "
    "at all: this matrix ORGANISES judgement and preserves "
    "the alternatives and the evidence that cut against the "
    "survivor; it does not improve the judgement's accuracy "
    "by itself, and it certifies no conclusion.")


# ------------------------------------------------------------- register io

def load_lines(path=REGISTER_PATH):
    if not Path(path).is_file():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def fold(lines):
    """{matrix_id: latest revision dict}, in first-seen order."""
    matrices = {}
    for row in lines:
        if row.get("kind") == "matrix":
            matrices[row["id"]] = row
    return matrices


def append_revision(matrix, path=REGISTER_PATH):
    path = Path(path)
    lines = load_lines(path)
    if not any(r.get("kind") == "header" for r in lines):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(HEADER, ensure_ascii=False) + "\n")
    matrix = dict(matrix)
    matrix["revision"] = matrix.get("revision", 0) + 1
    matrix["updated"] = date.today().isoformat()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(matrix, ensure_ascii=False) + "\n")
    return matrix


def get_matrix(matrix_id, path=REGISTER_PATH):
    matrices = fold(load_lines(path))
    if matrix_id not in matrices:
        raise SystemExit(f"no matrix with id {matrix_id!r} in {path}")
    return matrices[matrix_id]


# ------------------------------------------------------------- operations

def new_matrix(matrix_id, question, hypotheses, by, note=None):
    if len(hypotheses) > HYPOTHESIS_SOFT_CAP:
        print(f"warning: {len(hypotheses)} hypotheses — above "
              f"{HYPOTHESIS_SOFT_CAP} a matrix rots combinatorially "
              f"(the find's guardrail); recorded anyway, the "
              f"cap is the caller's call.", file=sys.stderr)
    return {
        "kind": "matrix",
        "id": matrix_id,
        "question": question,
        "created": date.today().isoformat(),
        "by": by,
        "note": note,
        "hypotheses": [
            {"id": f"H{i + 1}", "text": h}
            for i, h in enumerate(hypotheses)],
        "evidence": [],
        "cells": {},
        "revision": 0,
    }


def add_evidence(matrix, text, cite, witness=None):
    eid = f"E{len(matrix['evidence']) + 1}"
    matrix["evidence"].append({
        "id": eid, "text": text, "cite": cite, "witness": witness})
    return eid


def score_cell(matrix, evidence_id, hypothesis_id, value, cite,
               by, note=None):
    if value not in CELL_VALUES:
        raise SystemExit(f"cell value must be one of {CELL_VALUES}")
    ev_ids = {e["id"] for e in matrix["evidence"]}
    hy_ids = {h["id"] for h in matrix["hypotheses"]}
    if evidence_id not in ev_ids:
        raise SystemExit(f"no evidence {evidence_id!r} in matrix")
    if hypothesis_id not in hy_ids:
        raise SystemExit(f"no hypothesis {hypothesis_id!r} in matrix")
    matrix["cells"][f"{evidence_id}|{hypothesis_id}"] = {
        "value": value, "cite": cite, "by": by,
        "date": date.today().isoformat(), "note": note}


# ------------------------------------------------------------- bookkeeping

def inconsistency_counts(matrix):
    """Per-hypothesis inconsistency counts: (raw, witness-
    adjusted). Witness-adjusted: within one witness group, a
    hypothesis collects at most one inconsistency — correlated
    evidence is one witness, not several rows."""
    raw = {h["id"]: 0 for h in matrix["hypotheses"]}
    witnesses = {}  # (witness_key, hypothesis) -> bool any I
    ev_by_id = {e["id"]: e for e in matrix["evidence"]}
    for key, cell in matrix["cells"].items():
        if cell["value"] != "I":
            continue
        eid, hid = key.split("|")
        raw[hid] += 1
        wkey = ev_by_id[eid].get("witness") or eid
        witnesses[(wkey, hid)] = True
    adjusted = {h["id"]: 0 for h in matrix["hypotheses"]}
    for (_w, hid), _v in witnesses.items():
        adjusted[hid] += 1
    return raw, adjusted


def diagnosticity(matrix):
    """Classify each evidence item by how it discriminates:
    - non-diagnostic: scored, and consistent with EVERY
      hypothesis (Heuer step 4: it discriminates nothing)
    - discriminating: scored, with at least one I
    - unscored / all-NA: named separately, never silently
      counted as either."""
    hy_ids = [h["id"] for h in matrix["hypotheses"]]
    out = {}
    for e in matrix["evidence"]:
        vals = [matrix["cells"].get(f"{e['id']}|{h}", {}).get("value")
                for h in hy_ids]
        scored = [v for v in vals if v in ("C", "I")]
        if not scored:
            out[e["id"]] = "unscored" if all(v is None for v in vals) \
                else "all-na"
        elif all(v == "C" for v in scored) and len(scored) == len(hy_ids):
            out[e["id"]] = "non-diagnostic"
        elif any(v == "I" for v in scored):
            out[e["id"]] = "discriminating"
        else:
            out[e["id"]] = "partial"
    return out


def render(matrix):
    hy = matrix["hypotheses"]
    raw, adjusted = inconsistency_counts(matrix)
    diag = diagnosticity(matrix)
    lines = []
    lines.append(f"ACH matrix {matrix['id']} — {matrix['question']}")
    lines.append(f"Created {matrix['created']} by {matrix['by']}; "
                 f"revision {matrix['revision']}"
                 + (f"; note: {matrix['note']}" if matrix.get("note")
                    else ""))
    lines.append("")
    lines.append("Hypotheses:")
    for h in hy:
        lines.append(f"  {h['id']}. {h['text']}")
    lines.append("")
    lines.append("Matrix (C = consistent, I = inconsistent, "
                 "NA = not applicable, . = unscored):")
    width = max([len(e["id"]) for e in matrix["evidence"]] + [2])
    head = " " * (width + 2) + "  ".join(h["id"].center(3) for h in hy)
    lines.append(head)
    for e in matrix["evidence"]:
        cells = []
        for h in hy:
            cell = matrix["cells"].get(f"{e['id']}|{h['id']}")
            cells.append((cell["value"] if cell else ".").center(3))
        w = f" [witness: {e['witness']}]" if e.get("witness") else ""
        lines.append(f"{e['id']:>{width}}  " + "  ".join(cells)
                     + f"  {e['text']}{w}")
        lines.append(f"{'':>{width}}  cited: {e['cite']}")
    lines.append("")
    lines.append("Inconsistency counts (the ACH discipline reads "
                 "these, not the consistency counts):")
    for h in hy:
        lines.append(f"  {h['id']}: {raw[h['id']]} inconsistent "
                     f"({adjusted[h['id']]} witness-adjusted)")
    if hy:
        survivor = min(hy, key=lambda h: (adjusted[h["id"]],
                                          raw[h["id"]]))
        lines.append(f"Least-inconsistent (witness-adjusted): "
                     f"{survivor['id']} — {survivor['text']}")
    lines.append("")
    lines.append("Diagnosticity (evidence that is consistent with "
                 "every hypothesis discriminates nothing):")
    labels = {"non-diagnostic": "NON-DIAGNOSTIC — consistent with "
                                "every hypothesis; it cannot "
                                "separate them",
              "discriminating": "discriminating — cuts against at "
                                "least one hypothesis",
              "partial": "partially scored — consistent wherever "
                         "scored, but not scored against all",
              "all-na": "scored NA wherever scored — bears on "
                        "none of them as framed",
              "unscored": "UNSCORED — no cell filled; the matrix "
                          "takes no position on it yet"}
    for e in matrix["evidence"]:
        lines.append(f"  {e['id']}: {labels[diag[e['id']]]}")
    lines.append("")
    lines.append(CAVEAT)
    return "\n".join(lines)


# ------------------------------------------------------------- check

def citation_ok(cite):
    """A citation resolves: a repo-relative path that exists,
    or a git:<hash> ref naming a real commit."""
    if cite.startswith("git:"):
        ref = cite[4:].split()[0]
        try:
            out = subprocess.run(
                ["git", "-C", str(ROOT), "cat-file", "-t", ref],
                capture_output=True, text=True, timeout=30)
            return out.returncode == 0 and out.stdout.strip() == "commit"
        except (OSError, subprocess.SubprocessError):
            return False
    return (ROOT / cite.split("#")[0]).exists()


def check_register(path=REGISTER_PATH):
    problems = []
    lines = load_lines(path)
    if not lines or lines[0].get("kind") != "header":
        problems.append("register has no header line")
    matrices = fold(lines)
    for mid, m in matrices.items():
        hy_ids = {h["id"] for h in m["hypotheses"]}
        ev_ids = {e["id"] for e in m["evidence"]}
        if len(hy_ids) != len(m["hypotheses"]):
            problems.append(f"{mid}: duplicate hypothesis ids")
        if len(ev_ids) != len(m["evidence"]):
            problems.append(f"{mid}: duplicate evidence ids")
        for e in m["evidence"]:
            if not citation_ok(e["cite"]):
                problems.append(
                    f"{mid}/{e['id']}: evidence citation does not "
                    f"resolve: {e['cite']}")
        for key, cell in m["cells"].items():
            eid, _, hid = key.partition("|")
            if eid not in ev_ids or hid not in hy_ids:
                problems.append(f"{mid}: cell {key} names unknown "
                                f"evidence/hypothesis")
            if cell["value"] not in CELL_VALUES:
                problems.append(f"{mid}: cell {key} has bad value "
                                f"{cell['value']!r}")
            if not citation_ok(cell["cite"]):
                problems.append(
                    f"{mid}: cell {key} citation does not resolve: "
                    f"{cell['cite']}")
    return problems, matrices


# ------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(
        description="ACH matrices as bookkeeping : "
                    "hypotheses x evidence, caller-scored, "
                    "least-inconsistent survivor, non-diagnostic "
                    "evidence flagged.")
    ap.add_argument("--register", default=str(REGISTER_PATH),
                    help="register path (default evaluation/"
                         "ach-matrices.jsonl)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create")
    p.add_argument("--id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--hypothesis", action="append", required=True,
                   dest="hypotheses")
    p.add_argument("--by", default="agent")
    p.add_argument("--note")

    p = sub.add_parser("add-evidence")
    p.add_argument("--id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--cite", required=True)
    p.add_argument("--witness",
                   help="shared-witness group name: evidence in "
                        "one group counts once in adjusted counts")
    p.add_argument("--by", default="agent")

    p = sub.add_parser("score")
    p.add_argument("--id", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--value", required=True, choices=CELL_VALUES)
    p.add_argument("--cite", required=True)
    p.add_argument("--by", default="agent")
    p.add_argument("--note")

    p = sub.add_parser("render")
    p.add_argument("--id", required=True)

    sub.add_parser("list")
    sub.add_parser("check")
    args = ap.parse_args(argv[1:])
    path = Path(args.register)

    if args.cmd == "create":
        existing = fold(load_lines(path))
        if args.id in existing:
            print(f"matrix {args.id} already exists", file=sys.stderr)
            return 2
        m = new_matrix(args.id, args.question, args.hypotheses,
                       args.by, args.note)
        m = append_revision(m, path)
        print(f"created {m['id']} (revision {m['revision']}) with "
              f"{len(m['hypotheses'])} hypotheses")
        return 0

    if args.cmd == "add-evidence":
        m = get_matrix(args.id, path)
        eid = add_evidence(m, args.text, args.cite, args.witness)
        m = append_revision(m, path)
        print(f"{args.id}: evidence {eid} added "
              f"(revision {m['revision']})")
        return 0

    if args.cmd == "score":
        m = get_matrix(args.id, path)
        score_cell(m, args.evidence, args.hypothesis, args.value,
                   args.cite, args.by, args.note)
        m = append_revision(m, path)
        print(f"{args.id}: cell {args.evidence}|{args.hypothesis} = "
              f"{args.value} (revision {m['revision']})")
        return 0

    if args.cmd == "render":
        print(render(get_matrix(args.id, path)))
        return 0

    if args.cmd == "list":
        matrices = fold(load_lines(path))
        if not matrices:
            print("no matrices in the register")
            return 0
        for mid, m in matrices.items():
            raw, _adj = inconsistency_counts(m)
            print(f"{mid}  {m['question']}  "
                  f"({len(m['hypotheses'])} hypotheses, "
                  f"{len(m['evidence'])} evidence, "
                  f"{len(m['cells'])} cells scored, "
                  f"inconsistencies {raw})")
        return 0

    if args.cmd == "check":
        problems, matrices = check_register(path)
        if problems:
            print("ACH register check: PROBLEMS")
            for prob in problems:
                print(f"  - {prob}")
            return 1
        print(f"ACH register check: OK ({len(matrices)} matrices, "
              f"all citations resolve, all cells well-formed)")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
