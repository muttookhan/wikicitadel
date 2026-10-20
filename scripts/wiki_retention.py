#!/usr/bin/env python3
"""Retention schedules: report the corpus against its policy.

WikiCitadel v1 (WikiCitadel v1). Two patterns,
re-implemented:

  - Retention is a property of the CLASS, and the review /
    destruction date is computed when the record is filed, so
    nobody ever re-researches the rule (AdminBooks records-
    retention practice, the survey —
    docs/research-notes.md, find 15).
  - The rules live in a POLICY FILE IN GIT
    (evaluation/retention-policy.json): per-class scopes,
    first match wins; an item's expiry is stamped with the
    date AND the name of the rule that retired it; expired
    is a STATE, not a disappearance — and `restore` and
    hard-delete are separate acts that this tool never
    performs (Memanto's retention mechanics, the survey —
    docs/research-notes.md, finds 7–9; the system itself
    was NOT FOR US and no code is copied).

Commands:

  policy            Show the policy (the show-policy step of
                    the governed act: read the rules before
                    any report is run against them).
  check [--as-of D] List every item whose clock has expired
                    as of D (default: today), each stamped
                    with its class, the rule name, the date
                    it was filed, the computed expiry date,
                    and the action the policy names. The
                    filed date is the item's first-commit
                    date in git; an untracked working file
                    falls back to its mtime (the basis is
                    printed with the stamp).
  recall --as-of D  List what the corpus held at a past
                    date: the git tree at the last commit on
                    or before D, classified by the policy,
                    with items whose clock had ALREADY run
                    out by D marked. This is the reference
                    implementation for the owner's pending
                    bi-temporal decision — point-in-
                    time recall over git history, labelled as
                    such; it adds no valid-time / transacted-
                    time fields to any page.

REPORT ONLY, by design: this tool never deletes, restores,
tombstones, or edits anything. What expiry leads to is a
separate act by separate machinery — a review recorded by
whoever performs it; a tombstone by scripts/wiki_tombstone.py;
an erasure by the owner's act with its certificate from
scripts/wiki_erasure.py. Retention composes with that
machinery; it does not duplicate it.

Exit codes: 0 = report ran, nothing expired and no coverage
gap; 3 = report ran, items expired and/or files matched no
class; 2 = usage or policy error (the leak-lint convention).

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_REL = "evaluation/retention-policy.json"
SCHEMA = "retention-policy/1"
RECORD_TREES = ("raw", "wiki", "evaluation", "staging", "exports")
SKIP_DIRS = {".git", "__pycache__"}
RETENTION_KINDS = ("keep-forever", "review-after", "expire-after")
EXPIRY_ACTIONS = ("review", "tombstone", "erase-eligible")


def display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# -- Policy ------------------------------------------------------------------

def glob_to_regex(pat: str) -> re.Pattern:
    """Path glob -> regex. `**/` matches any number of leading
    directories (including zero), `**` any characters, `*` any
    characters except `/`. Deterministic; no fnmatch surprises."""
    out = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


class PolicyError(Exception):
    pass


def load_policy(path: Path) -> dict:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PolicyError(f"policy at {path} is unreadable: {exc}")
    if policy.get("schema") != SCHEMA:
        raise PolicyError(
            f"policy schema is {policy.get('schema')!r}, expected {SCHEMA!r}")
    classes = policy.get("classes")
    if not isinstance(classes, list) or not classes:
        raise PolicyError("policy has no classes list")
    seen = set()
    for cls in classes:
        name = cls.get("name")
        if not name or name in seen:
            raise PolicyError(f"class name missing or duplicated: {name!r}")
        seen.add(name)
        scope = cls.get("scope")
        if not isinstance(scope, list) or not scope:
            raise PolicyError(f"class {name}: scope must be a non-empty list")
        for pat in scope:
            if pat.startswith("/") or ".." in pat.split("/"):
                raise PolicyError(
                    f"class {name}: scope patterns are repo-relative: {pat!r}")
            cls.setdefault("_matchers", []).append(glob_to_regex(pat))
        ret = cls.get("retention") or {}
        kind = ret.get("kind")
        if kind not in RETENTION_KINDS:
            raise PolicyError(f"class {name}: retention kind {kind!r} "
                              f"not one of {RETENTION_KINDS}")
        action = cls.get("on_expiry")
        if kind == "keep-forever":
            if action is not None:
                raise PolicyError(
                    f"class {name}: keep-forever carries no on_expiry action")
        else:
            period = ret.get("period_days")
            if not isinstance(period, int) or period <= 0:
                raise PolicyError(
                    f"class {name}: {kind} needs a positive period_days")
            if action not in EXPIRY_ACTIONS:
                raise PolicyError(
                    f"class {name}: on_expiry {action!r} not one of "
                    f"{EXPIRY_ACTIONS}")
    return policy


def classify(rel: str, classes):
    """First match wins (the policy file's order is the rule)."""
    for cls in classes:
        if any(m.match(rel) for m in cls["_matchers"]):
            return cls
    return None


def rule_label(cls) -> str:
    """The named rule an expiry is stamped with."""
    ret = cls["retention"]
    if ret["kind"] == "keep-forever":
        return f"{cls['name']}/keep-forever"
    return f"{cls['name']}/{ret['kind']}-{ret['period_days']}d"


# -- Corpus ------------------------------------------------------------------

def iter_record_files(root: Path):
    """Every file under the record trees, repo-relative, sorted.
    Generated caches are not records and are skipped."""
    out = []
    for tree in RECORD_TREES:
        base = root / tree
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file():
                out.append(p.relative_to(root).as_posix())
    return sorted(out)


def git_add_dates(root: Path):
    """{relpath: earliest add date (YYYY-MM-DD)} from one pass
    over `git log --diff-filter=A`. The log is newest-first, so
    letting later (older) entries overwrite leaves the earliest
    add date per path. Best-effort: {} outside a git repo."""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "log", "--diff-filter=A",
             "--format=@@@%cs", "--name-only"],
            capture_output=True, text=True, timeout=120)
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    current = None
    for line in r.stdout.splitlines():
        if line.startswith("@@@"):
            current = line[3:].strip()
        elif line.strip() and current:
            out[line.strip()] = current
    return out


def filed_date(root: Path, rel: str, add_dates):
    """(date, basis): the git first-add date, else the file's
    mtime date for an untracked working file."""
    stamp = add_dates.get(rel)
    if stamp:
        return date.fromisoformat(stamp), "git"
    mtime = (root / rel).stat().st_mtime
    return date.fromtimestamp(mtime), "mtime"


def expiry_for(cls, filed: date):
    """The computed expiry date, or None for keep-forever."""
    ret = cls["retention"]
    if ret["kind"] == "keep-forever":
        return None
    return filed + timedelta(days=ret["period_days"])


# -- Commands ----------------------------------------------------------------

def cmd_policy(args, root, policy_path):
    policy = load_policy(policy_path)
    print(f"Retention policy — {display_path(root, policy_path)}"
          f" (schema {policy['schema']}, version {policy.get('version')},"
          f" adopted {policy.get('adopted')})")
    print("Classes, in evaluation order (first match wins):")
    for cls in policy["classes"]:
        ret = cls["retention"]
        if ret["kind"] == "keep-forever":
            clock = "keep-forever"
        else:
            clock = f"{ret['kind']} {ret['period_days']}d" \
                    f" -> on expiry: {cls['on_expiry']}"
        print(f"  {cls['name']:<22} {clock:<38}"
              f" scope: {', '.join(cls['scope'])}")
    print("\nReport only: this policy deletes nothing. Expiry is a"
          " stamped line in a check report; the act it names is"
          " performed separately.")
    return 0


def cmd_check(args, root, policy_path):
    policy = load_policy(policy_path)
    classes = policy["classes"]
    as_of = args.as_of or date.today()
    add_dates = git_add_dates(root)
    expired, unclassed, class_counts = [], [], {}
    files = iter_record_files(root)
    for rel in files:
        cls = classify(rel, classes)
        if cls is None:
            unclassed.append(rel)
            continue
        class_counts[cls["name"]] = class_counts.get(cls["name"], 0) + 1
        filed, basis = filed_date(root, rel, add_dates)
        expiry = expiry_for(cls, filed)
        if expiry is not None and expiry <= as_of:
            expired.append((rel, cls, filed, basis, expiry))
    print(f"== Retention check — policy "
          f"{display_path(root, policy_path)} v{policy.get('version')}"
          f", as of {as_of.isoformat()} ==")
    for rel, cls, filed, basis, expiry in expired:
        ret = cls["retention"]
        print(f"EXPIRED  {rel}")
        print(f"         class {cls['name']} · rule {rule_label(cls)}"
              f" · filed {filed.isoformat()} ({basis})"
              f" · {ret['kind']} {ret['period_days']}d"
              f" · expiry {expiry.isoformat()}"
              f" · action: {cls['on_expiry']}")
    if unclassed:
        print("UNCLASSED (no policy class matches — a coverage gap"
              " in the policy, not an expiry):")
        for rel in unclassed:
            print(f"  {rel}")
    held = ", ".join(f"{k} {v}" for k, v in sorted(class_counts.items()))
    print(f"Summary: {len(files)} file(s) scanned · {len(class_counts)}"
          f" class(es) held files ({held}) · {len(expired)} expired"
          f" · {len(unclassed)} unclassed")
    print("Report only: nothing was deleted, restored, or"
          " tombstoned. Erasure is a separate act with its"
          " certificate (scripts/wiki_erasure.py).")
    return 3 if (expired or unclassed) else 0


def cmd_recall(args, root, policy_path):
    policy = load_policy(policy_path)
    classes = policy["classes"]
    as_of = args.as_of
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-list", "-1",
             f"--before={as_of.isoformat()} 23:59:59", "HEAD"],
            capture_output=True, text=True, timeout=60)
        commit = r.stdout.strip()
    except Exception:
        commit = ""
    print("Recall — what the corpus held as of "
          f"{as_of.isoformat()}")
    print("Reference implementation for the owner's pending"
          " bi-temporal decision: point-in-time recall"
          " over git history. No page carries valid-time /"
          " transacted-time fields; this reads history, it"
          " does not add them.")
    if r.returncode != 0 or not commit:
        print(f"No commit exists on or before {as_of.isoformat()}"
              " — the corpus held nothing yet.")
        return 0
    meta = subprocess.run(
        ["git", "-C", str(root), "show", "-s", "--format=%cs %h", commit],
        capture_output=True, text=True, timeout=60).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", commit],
        capture_output=True, text=True, timeout=60).stdout.splitlines()
    add_dates = git_add_dates(root)
    by_class = {}
    for rel in sorted(tree):
        if not any(rel.startswith(t + "/") for t in RECORD_TREES):
            continue
        cls = classify(rel, classes)
        key = cls["name"] if cls else "(unclassed)"
        filed = None
        stamp = add_dates.get(rel)
        if stamp:
            filed = date.fromisoformat(stamp)
        expiry = expiry_for(cls, filed) if (cls and filed) else None
        state = "held"
        if expiry is not None and expiry <= as_of:
            state = f"EXPIRED (expiry {expiry.isoformat()})"
        by_class.setdefault(key, []).append((rel, filed, state))
    print(f"Tree at commit {meta}:")
    total = 0
    for key in sorted(by_class):
        rows = by_class[key]
        total += len(rows)
        print(f"\n[{key}] — {len(rows)} file(s)")
        for rel, filed, state in rows:
            filed_s = filed.isoformat() if filed else "unknown"
            print(f"  {rel}  (filed {filed_s}; {state})")
    print(f"\nTotal: {total} record file(s) held as of"
          f" {as_of.isoformat()}.")
    print("Note: untracked working artefacts (e.g. the gitignored"
          " exports/okf-bundle) have no git history and cannot"
          " appear in a recall; the check command covers them"
          " on disk.")
    return 0


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"not a YYYY-MM-DD date: {value!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Retention schedules: report the corpus against"
                    " its git-kept policy file.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    ap.add_argument("--policy", default=None,
                    help=f"policy path (default: <root>/{POLICY_REL})")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("policy", help="show the policy classes")
    p_check = sub.add_parser("check", help="list items whose clock"
                                           " has expired")
    p_check.add_argument("--as-of", type=parse_date, default=None,
                         help="YYYY-MM-DD (default: today)")
    p_recall = sub.add_parser("recall", help="what the corpus held"
                                             " at a past date")
    p_recall.add_argument("--as-of", type=parse_date, required=True,
                          help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    policy_path = Path(args.policy) if args.policy else root / POLICY_REL
    try:
        if args.command == "policy":
            return cmd_policy(args, root, policy_path)
        if args.command == "check":
            if args.as_of is None:
                args.as_of = date.today()
            return cmd_check(args, root, policy_path)
        if args.command == "recall":
            return cmd_recall(args, root, policy_path)
    except PolicyError as exc:
        print(f"retention: {exc}")
        return 2
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # A downstream consumer (head, a closed pipe) went away;
        # the report itself is complete.
        raise SystemExit(0)
