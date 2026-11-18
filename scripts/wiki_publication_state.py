#!/usr/bin/env python3
"""Share / publish / cite-ready vocabulary checker.

Marathon R13 lane BA (ideas board line 196, Round 11 RA find 6,
Tier A): Kuusniemi & Nykyri 2025, "Data as a New Research
Publication Type" (LIBER Quarterly 35; Helsinki / Tampere;
CC BY 4.0) — the terminology distinction only, re-implemented
in our own words. The paper finds data policies using sharing
vs. publishing vs. openness interchangeably, and distinguishes
data PUBLISHING from general data sharing by citability,
quality control, and ethical reuse. This tool holds the
three-state controlled vocabulary as data
(evaluation/share-publish-vocabulary.json):

    share      made available to a named audience, as it
               stands; no test is claimed;
    publish    shared AND passing all three tests —
               citability, quality control, ethical reuse;
    cite-ready published AND carrying a complete citation
               form (identifier, version or date, locator)
               that resolves as written.

A page may declare its state with the frontmatter field
`publication_state`. `check` validates the vocabulary file's
own integrity and reports declared states across wiki pages:
a declared value outside the vocabulary is a finding; a page
with no declaration is counted as undeclared — undeclared is
never read as published, and no state is inferred, promoted
or written by this tool. Report-only; wired into no gate.
Commands: check / report / statement. Exit 0 ok (check: no
findings); 1 findings on check; 2 usage or config error.
Stdlib only, no network, no model calls.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "evaluation" / "share-publish-vocabulary.json"
STATES = ["share", "publish", "cite-ready"]
PUBLISH_TESTS = ["citability", "quality-control", "ethical-reuse"]
FIELD = "publication_state"
FIELD_RE = re.compile(r"^publication_state:\s*(\S+)\s*$", re.M)


def load_vocabulary(path=None):
    p = Path(path) if path else VOCAB
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as e:
        return None, f"vocabulary unreadable: {p} ({e})"


def validate_vocabulary(data):
    errors = []
    if not isinstance(data, dict):
        return ["vocabulary is not a JSON object"]
    if data.get("field") != FIELD:
        errors.append(f"field {data.get('field')!r} != {FIELD!r}")
    states = data.get("states")
    if not isinstance(states, list):
        errors.append("states missing or not a list")
        states = []
    ids = [s.get("id") for s in states if isinstance(s, dict)]
    if ids != STATES:
        errors.append(f"state ids {ids} != {STATES} (closed vocabulary, in order)")
    for s in states:
        if isinstance(s, dict) and not str(s.get("statement") or "").strip():
            errors.append(f"state {s.get('id')!r} has no statement")
    tests = data.get("publish_tests")
    if not isinstance(tests, list):
        errors.append("publish_tests missing or not a list")
        tests = []
    tids = [t.get("id") for t in tests if isinstance(t, dict)]
    if tids != PUBLISH_TESTS:
        errors.append(f"publish test ids {tids} != {PUBLISH_TESTS}")
    return errors


def passes_publish_test(citability, quality_control, ethical_reuse):
    """The publish test: all three legs must hold. Any leg
    failing leaves the item shared, not published."""
    return bool(citability and quality_control and ethical_reuse)


def scan_states(root=None):
    base = Path(root) if root else ROOT
    declared, invalid, undeclared = {}, [], 0
    wiki = base / "wiki"
    pages = sorted(wiki.rglob("*.md")) if wiki.is_dir() else []
    for page in pages:
        try:
            text = page.read_text(encoding="utf-8")
        except OSError:
            continue
        m = FIELD_RE.search(text.split("---", 2)[1] if text.startswith("---") else "")
        if not m:
            undeclared += 1
            continue
        value = m.group(1).strip("'\"")
        rel = page.relative_to(base).as_posix()
        if value in STATES:
            declared.setdefault(value, []).append(rel)
        else:
            invalid.append({"page": rel, "value": value})
    return {"declared": {s: declared.get(s, []) for s in STATES},
            "invalid": invalid, "undeclared": undeclared,
            "pages_scanned": len(pages)}


def build_report(root=None, vocab_path=None):
    data, err = load_vocabulary(vocab_path)
    errors = [err] if err else validate_vocabulary(data)
    scan = scan_states(root)
    return {"states": STATES, "publish_tests": PUBLISH_TESTS,
            "vocabulary_errors": errors, **scan}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Share / publish / cite-ready vocabulary (Kuusniemi & Nykyri slice).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--vocab", default=None)
    sub = ap.add_subparsers(dest="command")

    def root_arg(p):
        p.add_argument("--root", default=argparse.SUPPRESS)
        p.add_argument("--vocab", default=argparse.SUPPRESS)
    pc = sub.add_parser("check"); root_arg(pc)
    pr = sub.add_parser("report"); pr.add_argument("--json", action="store_true")
    root_arg(pr)
    ps = sub.add_parser("statement"); ps.add_argument("state", choices=STATES)
    root_arg(ps)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    root = Path(args.root) if args.root else ROOT
    if cmd == "statement":
        data, err = load_vocabulary(args.vocab)
        if err:
            print(f"publication-state: {err}", file=sys.stderr)
            return 2
        for s in data.get("states", []):
            if s.get("id") == args.state:
                print(f"{s['label']}: {s['statement']}")
                return 0
        print(f"publication-state: no statement for {args.state!r}", file=sys.stderr)
        return 2
    rep = build_report(root, args.vocab)
    if cmd == "check":
        findings = list(rep["vocabulary_errors"])
        for inv in rep["invalid"]:
            findings.append(f"{inv['page']}: publication_state {inv['value']!r} "
                              f"not in {STATES}")
        for f in findings:
            print(f"publication-state: {f}", file=sys.stderr)
        print(f"publication-state: {'INVALID' if findings else 'valid'} "
              f"({rep['pages_scanned']} page(s) scanned, "
              f"{rep['undeclared']} undeclared)")
        return 1 if findings else 0
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"publication-state: {rep['pages_scanned']} page(s) scanned; "
              f"undeclared: {rep['undeclared']}")
        for s in STATES:
            print(f"  {s}: {len(rep['declared'][s])}")
        for inv in rep["invalid"]:
            print(f"  invalid: {inv['page']} declares {inv['value']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
