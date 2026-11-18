#!/usr/bin/env python3
"""Decision-basis hashing for the LLM Wiki (the Rutter
pattern).

Pattern: Rutter's decision memory (reported in the
survey, find 8) — a decision record that computes the
SHA-256 of every file the decision rests on, rather than
trusting anyone's report of what was read. Our citation
lockfile binds CLAIMS to source lines; nothing bound our
DECISION records (evaluation/decisions-register.jsonl) to
the state of the pages they rested on. This tool is that
missing half. Re-implemented here; no code copied.

DERIVATION — mechanical, from the record only. For each
decision line in the register (kind == "decision"), the
basis set is:

  1. the register's own source.page — the page the
     register names as the decision's record;
  2. every repo-relative path named in the decision's
     current_form text;
  3. every repo-relative path named in a superseded form's
     superseded_by text (where the replacing ruling is
     recorded is part of the current form's basis).

Nothing else is added — no agent judgement about what a
decision "probably" rested on. A named file that does not
exist on disk is reported as named-but-missing, never
silently dropped. If a decision yields NO existing basis
file, its entry says basis_status "underivable-from-record"
and states why, rather than guessing a basis.

For each basis file the tool records:

  - sha256_now — the file's bytes at build time (the
    baseline every later check compares against);
  - sha256_at_decision — the file's bytes as of the
    decision's effective date (redecided when the register
    carries one, else decided), taken from git history:
    the last committed version on or before that date.
    null with a note when git holds no such version (the
    file postdates the decision, or was not yet committed).

`build` writes evaluation/decision-basis.json. `check`
recomputes and reports, Lane-6 style:

  BASIS CHANGED <id>: <path> — the file's bytes moved
    since the basis baseline (recorded → current). The
    decision still stands; its basis moving is a surfaced
    fact, not an invalidation.
  BASIS MISSING <id>: <path> — a basis file is gone.
  BASIS NOTE <id>: <path> — the file's bytes already
    differ from the decision-date state (informational:
    the decisions page itself was amended by later
    rulings, so this is expected there; on a quiet
    evidence page it would be the interesting case).

Exit codes: build 0 = written, 2 = usage error. check
exits 1 when any BASIS CHANGED/MISSING exists, 0
otherwise; --report always exits 0 (surfacing only).

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/decisions-register.jsonl"
BASIS_REL = "evaluation/decision-basis.json"

PATH_RE = re.compile(
    r"(?:wiki|raw|evaluation|scripts|tools)/[^\s,;\)\"'`\]<>]+?"
    r"\.(?:md|jsonl|json|py)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, timeout=60)


def hash_at_date(root: Path, rel: str, on_date: str):
    """(sha256 | None, note) — the file's committed bytes as
    of the END of on_date, from git history."""
    r = git(root, "rev-list", "-1", f"--before={on_date}T23:59:59",
            "HEAD", "--", rel)
    if r.returncode != 0 or not r.stdout.strip():
        return None, (f"no committed version on or before {on_date} "
                      f"(file postdates the decision or was uncommitted)")
    commit = r.stdout.decode().strip()
    r = git(root, "show", f"{commit}:{rel}")
    if r.returncode != 0:
        return None, f"path not present at {commit[:12]}"
    return sha256_bytes(r.stdout), f"as of commit {commit[:12]}"


def load_decisions(root: Path):
    register = root / REGISTER_REL
    if not register.is_file():
        raise SystemExit(f"no decisions register at {REGISTER_REL}")
    decisions = []
    for ln in register.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            obj = json.loads(ln)
            if obj.get("kind") == "decision":
                decisions.append(obj)
    return decisions


def derive_basis(root: Path, decision: dict):
    """Ordered, de-duplicated basis candidate paths for one
    decision, per the mechanical rule in the docstring."""
    named = []

    def add(p):
        p = p.strip().rstrip(".")
        if p and p not in named:
            named.append(p)

    src = (decision.get("source") or {}).get("page")
    if src:
        add(src)
    for m in PATH_RE.finditer(decision.get("current_form") or ""):
        add(m.group(0))
    for form in decision.get("superseded_forms") or []:
        for m in PATH_RE.finditer(form.get("superseded_by") or ""):
            add(m.group(0))
    return named


def build(root: Path):
    decisions = load_decisions(root)
    out = {
        "kind": "decision-basis", "version": 1,
        "generated": date.today().isoformat(),
        "register": REGISTER_REL,
        "derivation": "Per decision: the register's source.page, "
                      "plus every repo-relative path named in "
                      "current_form, plus every path named in a "
                      "superseded form's superseded_by text. "
                      "Nothing else. See scripts/wiki_decision_basis.py.",
        "decisions": [],
    }
    for d in decisions:
        effective = d.get("redecided") or d.get("decided")
        entries, missing = [], []
        for rel in derive_basis(root, d):
            path = root / rel
            if not path.is_file():
                missing.append(rel)
                continue
            at, note = hash_at_date(root, rel, effective)
            entries.append({
                "path": rel, "sha256_now": sha256_file(path),
                "sha256_at_decision": at,
                "at_decision_effective_date": effective,
                "at_decision_note": note,
            })
        entry = {"id": d["id"], "title": d.get("title"),
                 "status": d.get("status"),
                 "decided": d.get("decided"),
                 "effective_date": effective,
                 "basis": entries,
                 "named_but_missing": missing}
        if not entries:
            entry["basis_status"] = "underivable-from-record"
            entry["basis_reason"] = (
                "the register names no source page and no existing "
                "file in the decision's forms — no basis can be "
                "derived mechanically, and none is guessed")
        else:
            entry["basis_status"] = "derived"
        out["decisions"].append(entry)
    target = root / BASIS_REL
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False)
                      + "\n", encoding="utf-8")
    return out


def cmd_build(root: Path):
    out = build(root)
    print(f"wrote {BASIS_REL}")
    for d in out["decisions"]:
        if d["basis_status"] == "derived":
            print(f"  {d['id']}: {len(d['basis'])} basis file(s)"
                  + (f", {len(d['named_but_missing'])} named-but-missing"
                     if d["named_but_missing"] else ""))
            for b in d["basis"]:
                print(f"    {b['path']}  now {b['sha256_now'][:16]}…  "
                      f"at-decision {str(b['sha256_at_decision'])[:16]}")
        else:
            print(f"  {d['id']}: basis UNDERIVABLE FROM RECORD — "
                  f"{d['basis_reason']}")
    return 0


def cmd_check(root: Path, report_only: bool):
    basis_path = root / BASIS_REL
    if not basis_path.is_file():
        print(f"no {BASIS_REL} — run build first")
        return 2
    recorded = json.loads(basis_path.read_text(encoding="utf-8"))
    changed = 0
    for d in recorded["decisions"]:
        if d["basis_status"] != "derived":
            print(f"BASIS UNDERIVABLE {d['id']}: no basis on record "
                  f"(see decision-basis.json)")
            continue
        for b in d["basis"]:
            path = root / b["path"]
            if not path.is_file():
                print(f"BASIS MISSING {d['id']}: {b['path']} — a basis "
                      f"file is gone (recorded {b['sha256_now'][:16]}…)")
                changed += 1
                continue
            now = sha256_file(path)
            if now != b["sha256_now"]:
                print(f"BASIS CHANGED {d['id']}: {b['path']} — bytes "
                      f"moved since the basis baseline "
                      f"{recorded['generated']} (recorded "
                      f"{b['sha256_now'][:16]}… → current {now[:16]}…). "
                      f"The decision stands; its basis moved.")
                changed += 1
            elif b.get("sha256_at_decision") and \
                    now != b["sha256_at_decision"]:
                print(f"BASIS NOTE {d['id']}: {b['path']} — bytes "
                      f"already differ from the decision-date state "
                      f"({b['at_decision_effective_date']}); unchanged "
                      f"since the baseline.")
    print(f"Result: {'CLEAN' if changed == 0 else f'{changed} basis change(s)'} "
          f"({len(recorded['decisions'])} decisions checked)")
    return 0 if (report_only or changed == 0) else 1


def main(argv):
    ap = argparse.ArgumentParser(
        description="Decision-basis hashing (the Rutter pattern).")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="(re)write evaluation/decision-basis.json")
    pc = sub.add_parser("check", help="recompute + flag basis changes")
    pc.add_argument("--report", action="store_true",
                    help="surface only; always exit 0")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "build":
        return cmd_build(root)
    return cmd_check(root, args.report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
