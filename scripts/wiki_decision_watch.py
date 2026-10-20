#!/usr/bin/env python3
"""Decision watches for the LLM Wiki — linchpins, key
assumptions and watch conditions on the decision record
(WikiCitadel v1 + the fold-in).

Patterns, from the survey record:

  - Linchpin analysis (find 6, MacEachin / Heuer):
    every judgment rests on more assumptions than can be
    audited; the LINCHPIN subset is those whose failure
    FLIPS the judgment. The test is counterfactual: "if
    this were false, does the conclusion change?"
  - Key Assumptions Check (find 4, CIA Tradecraft
    Primer): the load-bearing premises under the linchpin,
    each stated with how it would be checked — an unlisted
    assumption's cost is that the contradicting evidence
    gets filtered out as noise when it arrives.
  - Watch conditions (find 9, "Fresh at Decision,
    Stale at Action"): a decision ledger stores WATCH
    CONDITIONS WRITTEN AT DECISION TIME — the arrivals
    that should be routed back to the decision and
    re-open it. Freshness at decision time cannot protect
    action time; routing can.

The decisions register (evaluation/decisions-register.jsonl)
is NOT rewritten by this machinery. The watch records live
in a sidecar register, evaluation/decision-watches.jsonl
(hash-chained like the checkpoint register), one record per
CURRENT decision form, citing the basis files the
decision-basis hashing derived (evaluation/decision-
basis.json) — composed with, never duplicating, that file.

`check` evaluates the trip tests that are mechanically
evaluable against the wiki's own records and reports the
rest as MANUAL:

  register-form  trips when the register's current_form
                 text no longer hashes to the value the
                 watch record was authored against (the
                 decision was re-ruled; this record is
                 stale and must be re-authored);
  branch-scope   trips when a commit on the named branch
                 touches a path outside the allowed
                 prefixes (diffed against the merge-base
                 with master); MANUAL when the branch ref
                 is not present in this clone;
  git-remote     trips when the remote set differs from
                 the expected one, or a remote's URL does
                 not contain the expected substring;
  git-object     trips when the named git object is gone;
  path-exists    trips when the path exists;
  path-absent    trips when the path is absent;
  manual         never evaluated; reported as MANUAL with
                 the evidence a human should look at.

A TRIPPED condition RE-OPENS the question. It never
un-decides anything: decisions are the owner's, and this
tool's only powers are to watch and to surface.

Exit codes: check exits 1 when any condition is TRIPPED
(or the sidecar chain is broken), 0 otherwise; --report
always exits 0 (surfacing only). verify exits 0/1 on the
chain. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/decisions-register.jsonl"
BASIS_REL = "evaluation/decision-basis.json"
WATCHES_REL = "evaluation/decision-watches.jsonl"
GENESIS_PREV = "0" * 64


# -- hashing / chaining (the checkpoint register's pattern) ----

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def line_digest(prev_hash: str, line_without_hash: dict) -> str:
    return sha256_hex(prev_hash.encode("utf-8")
                      + canonical(line_without_hash))


def load_jsonl(path: Path):
    """(header | None, [non-header lines]) from a jsonl file."""
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
    _header, lines = load_jsonl(path)
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


# -- the registers ------------------------------------------------

def load_decisions(root: Path):
    path = root / REGISTER_REL
    if not path.is_file():
        raise SystemExit(f"no decisions register at {REGISTER_REL}")
    decisions = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            obj = json.loads(raw)
            if obj.get("kind") == "decision":
                decisions[obj["id"]] = obj
    return decisions


def form_sha256(decision: dict) -> str:
    return sha256_hex((decision.get("current_form") or "")
                      .encode("utf-8"))


def load_basis_paths(root: Path):
    """{decision id: [basis paths]} from the
    decision-basis.json — cited, never re-derived here."""
    path = root / BASIS_REL
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {d["id"]: [b["path"] for b in d.get("basis", [])]
            for d in data.get("decisions", [])}


# -- trip tests -----------------------------------------------------
# Each returns (status, evidence): status TRIPPED / CLEAR / MANUAL.

def git(root: Path, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, timeout=60)


def t_register_form(root, test, record):
    decisions = test["_decisions"]
    current = decisions.get(record["decision"])
    if current is None:
        return "TRIPPED", ("the decision no longer appears in "
                           "the register at all")
    if form_sha256(current) != record["form_sha256"]:
        return "TRIPPED", ("the register's current_form differs "
                           "from the form this watch was authored "
                           "against — the decision was re-ruled "
                           "and this record must be re-authored")
    return "CLEAR", "current_form unchanged since authoring"


def t_branch_scope(root, test, record):
    branch = test["branch"]
    ref = None
    for cand in (f"refs/heads/{branch}",
                 f"refs/remotes/azure/{branch}",
                 f"refs/remotes/origin/{branch}"):
        if git(root, "rev-parse", "--verify", "--quiet",
               cand).returncode == 0:
            ref = cand
            break
    if ref is None:
        return "MANUAL", (f"branch ref {branch} is not present in "
                          f"this clone — scope cannot be evaluated "
                          f"here")
    base = git(root, "merge-base", ref, "master")
    if base.returncode != 0:
        return "MANUAL", f"no merge-base between {branch} and master"
    base = base.stdout.strip()
    diff = git(root, "diff", "--name-only", f"{base}..{ref}")
    if diff.returncode != 0:
        return "MANUAL", f"diff {base[:12]}..{branch} failed"
    allowed = test["allowed_prefixes"]
    offenders = [p for p in diff.stdout.splitlines()
                 if p and not any(p == a or p.startswith(a)
                                  for a in allowed)]
    if offenders:
        shown = ", ".join(offenders[:5])
        return "TRIPPED", (f"{len(offenders)} path(s) on {branch} "
                           f"outside the allowed area: {shown}")
    return "CLEAR", (f"every path on {branch} since the merge-base "
                     f"sits inside the allowed area")


def t_git_remote(root, test, record):
    r = git(root, "remote")
    if r.returncode != 0:
        return "MANUAL", "git remote failed"
    remotes = sorted(x for x in r.stdout.splitlines() if x)
    expected = sorted(test["expected_remotes"])
    if remotes != expected:
        return "TRIPPED", (f"remote set is {remotes}, expected "
                           f"{expected}")
    for name, needle in (test.get("url_contains") or {}).items():
        u = git(root, "remote", "get-url", name)
        if u.returncode != 0 or needle not in u.stdout:
            return "TRIPPED", (f"remote {name} URL does not contain "
                               f"{needle!r}")
    return "CLEAR", f"remote set is exactly {expected} with the " \
                    f"expected URLs"


def t_git_object(root, test, record):
    r = git(root, "cat-file", "-t", test["ref"])
    if r.returncode != 0:
        return "TRIPPED", (f"git object {test['ref']} is not "
                           f"reachable in this clone")
    return "CLEAR", f"git object {test['ref']} present ({r.stdout.strip()})"


def t_path_exists(root, test, record):
    if (root / test["path"]).exists():
        return "TRIPPED", f"{test['path']} exists"
    return "CLEAR", f"{test['path']} absent"


def t_path_absent(root, test, record):
    if not (root / test["path"]).exists():
        return "TRIPPED", f"{test['path']} is absent"
    return "CLEAR", f"{test['path']} present"


def t_manual(root, test, record):
    return "MANUAL", test.get("evidence", "a human reads the record")


TRIP_TESTS = {
    "register-form": t_register_form,
    "branch-scope": t_branch_scope,
    "git-remote": t_git_remote,
    "git-object": t_git_object,
    "path-exists": t_path_exists,
    "path-absent": t_path_absent,
    "manual": t_manual,
}


# -- commands ---------------------------------------------------------

def cmd_verify(root: Path):
    _h, lines = load_jsonl(root / WATCHES_REL)
    ok, bad, why = verify_chain(lines)
    if ok:
        print(f"decision-watches chain: OK ({len(lines)} record(s))")
        return 0
    print(f"decision-watches chain: BROKEN at record {bad}: {why}")
    return 1


def cmd_check(root: Path, report_only: bool):
    watches_path = root / WATCHES_REL
    if not watches_path.is_file():
        print(f"no {WATCHES_REL} — no watch records authored yet")
        return 2
    _h, records = load_jsonl(watches_path)
    ok, bad, why = verify_chain(records)
    if not ok:
        print(f"WATCH CHAIN BROKEN at record {bad}: {why} — the "
              f"sidecar itself cannot be trusted until this is "
              f"explained")
        return 0 if report_only else 1
    decisions = load_decisions(root)
    n_trip = n_clear = n_manual = 0
    for record in records:
        if record.get("kind") != "watch":
            continue
        dec = decisions.get(record["decision"])
        title = (dec or {}).get("title", record["decision"])
        form_test = {"kind": "register-form", "_decisions": decisions}
        form_status, form_ev = t_register_form(root, form_test, record)
        counts = {"TRIPPED": 0, "CLEAR": 0, "MANUAL": 0}
        lines = []
        for w in record.get("watches", []):
            test = dict(w.get("trip_test") or {"kind": "manual"})
            fn = TRIP_TESTS.get(test.get("kind", "manual"), t_manual)
            test["_decisions"] = decisions
            status, evidence = fn(root, test, record)
            counts[status] += 1
            if status != "CLEAR":
                lines.append(f"  {status} {w['id']}: "
                             f"{w['condition']} — {evidence}")
        n_trip += counts["TRIPPED"]
        n_clear += counts["CLEAR"]
        n_manual += counts["MANUAL"]
        form_word = ("unchanged" if form_status == "CLEAR"
                     else "CHANGED")
        print(f"{record['decision']} {title} — form {form_word}; "
              f"watches: {counts['TRIPPED']} tripped, "
              f"{counts['CLEAR']} clear, {counts['MANUAL']} manual")
        for ln in lines:
            print(ln)
    print(f"Result: {n_trip} tripped, {n_clear} clear, "
          f"{n_manual} manual across {len(records)} decision "
          f"record(s). A tripped watch re-opens the question; "
          f"it never un-decides anything.")
    return 0 if (report_only or n_trip == 0) else 1


def main(argv):
    ap = argparse.ArgumentParser(
        description="Decision watches: linchpins, key assumptions, "
                    "watch conditions.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="verify the sidecar hash chain")
    pc = sub.add_parser("check", help="evaluate the trip tests")
    pc.add_argument("--report", action="store_true",
                    help="surface only; always exit 0")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "verify":
        return cmd_verify(root)
    return cmd_check(root, args.report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
