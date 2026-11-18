#!/usr/bin/env python3
"""wiki_ontology_check.py - controlled-vocabulary term-page checker.

Marathon R13 lane BB (ideas board line 201, deep-study batch 8,
Tier A): the Protege / WebProtege PATTERN only - a page type
with typed relations, revision history and discussion-on-term.
Protege itself is NOT deployed. The contract lives AS DATA in
evaluation/ontology-page-contract.json; the template is
templates/ontology-term.md (frontmatter type: ontology-term).
This checker validates term pages against the contract:
required frontmatter, status in the closed set, relations using
only the allowed predicates with wikilink targets, at least one
dated revision-history entry, and a Discussion section.
Asymmetry of a declared symmetric relation is REPORTED, never
enforced and never auto-fixed. Commands: contract / check PAGE...
Exit 0 clean; 1 findings; 2 usage. Stdlib only.
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "evaluation" / "ontology-page-contract.json"
REL_RE = re.compile(r"^-\s+([a-z-]+):\s+\[\[([^\]|#]+)", re.M)
REV_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}:", re.M)


def load_contract(path=None):
    return json.loads(Path(path or CONTRACT).read_text(encoding="utf-8"))


def parse_fm(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm, text[end + 4:]


def check_page(path, contract, pages=None):
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_fm(text)
    errs = []
    spec = contract["frontmatter"]
    for f in spec["required"]:
        if f not in fm:
            errs.append(f"missing frontmatter field {f!r}")
    if fm.get("type") not in (None, spec["type_value"]):
        errs.append(f"type must be {spec['type_value']!r}")
    if fm.get("status") and fm["status"] not in spec["status_values"]:
        errs.append(f"status {fm['status']!r} not in "
                    f"{spec['status_values']}")
    allowed = set(contract["relations"]["allowed_predicates"])
    rels = REL_RE.findall(body)
    for pred, _t in rels:
        if pred not in allowed:
            errs.append(f"relation predicate {pred!r} not allowed")
    if "## Revision history" not in body or not REV_RE.search(body):
        errs.append("no dated revision-history entry")
    if "## Discussion" not in body:
        errs.append("no ## Discussion section")
    notes = []
    if pages:
        sym = contract["relations"]["symmetry_expectations"]
        by_stem = {Path(p).stem: Path(p).read_text(encoding="utf-8")
                   for p in pages}
        for pred, target in rels:
            inv = sym.get(pred)
            stem = target.split("/")[-1]
            if inv and stem in by_stem and stem != Path(path).stem:
                back = REL_RE.findall(by_stem[stem])
                if not any(p2 == inv for p2, _ in back):
                    notes.append(f"asymmetry (reported): {stem} lacks "
                                 f"inverse {inv!r} relation")
    return errs, notes, fm


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contract")
    c = sub.add_parser("check"); c.add_argument("pages", nargs="+")
    a = ap.parse_args(argv)
    contract = load_contract()
    if a.cmd == "contract":
        print(json.dumps(contract, indent=2))
        return 0
    bad = 0
    for page in a.pages:
        errs, notes, _fm = check_page(page, contract, a.pages)
        for e in errs:
            print(f"ERROR {page}: {e}"); bad += 1
        for n in notes:
            print(f"NOTE {page}: {n}")
    print(f"{bad} error(s) across {len(a.pages)} page(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
