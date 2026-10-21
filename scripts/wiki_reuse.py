#!/usr/bin/env python3
"""wiki_reuse.py — per-page FAIR reuse statements (Marathon R6
lane BB).

Pattern: Wilkinson et al., "The FAIR Guiding Principles for
scientific data management and stewardship" (Sci Data 3, 160018,
2016; CC BY 4.0) — the R (Reusable) half, narrowed to the build
the ideas board approved: what a reader may do with a page,
stated per page and linted. Persistent identifiers and rich
metadata already stand in this wiki (frontmatter, the citation
lockfile, the schema profile); this tool adds the missing
reuse-terms leg. Ideas/pattern only, re-implemented in our own
code; no text copied.

THE STATEMENT. A compiled page may carry one frontmatter field:

    reuse: open | cite-only | internal | closed

The vocabulary is tree-neutral and lives as data in
`evaluation/reuse-vocabulary.json`, which also states the
tree's DEFAULT (`default_reuse`): the class a page with no
`reuse:` field is read under. The default is configuration,
never code — this script hardcodes no default, so the same
tool states an honest default for a private corpus and for a
public edition from their own config files. The classes:

    open       reuse, adaptation and redistribution permitted,
               with attribution to the page and its sources;
    cite-only  quotation and citation with attribution
               permitted; wholesale copying, adaptation or
               redistribution not permitted;
    internal   reuse inside this wiki / installation and its
               owner's own work only; no external
               redistribution;
    closed     reading in place only; this statement permits
               no copying, adaptation or redistribution.

THE CHECK. `check` walks `wiki/**/*.md` (pages without
frontmatter — the structural index/log — are exempt, the
standing exemption) and reports, per page: the declared class,
the effective class (declared, else the configured default),
and findings:

    missing-statement   no `reuse:` field — the page is read
                        under the default, and the report says
                        so; stating it is the cure;
    invalid-statement   a `reuse:` value outside the
                        vocabulary (the effective class falls
                        back to the default, stated as such);
    bad-default         the config's own default is outside
                        the vocabulary (a config finding, not
                        a page finding).

REPORTING, NEVER BLOCKING: the tool writes nothing, edits no
page, and is wired into no gate; its exit code (1 = findings)
exists so a sweep can surface the report, the lint-lane idiom.
`statement PAGE` renders the page's effective statement in
words, from the vocabulary file, so a reader (or the Lens, in
a later build) can show the terms without re-deriving them.

    python3 scripts/wiki_reuse.py [--root DIR] check [--plain]
    python3 scripts/wiki_reuse.py [--root DIR] statement PAGE

Exit codes: 0 = no findings · 1 = findings · 2 = usage or
config error. Stdlib only. No model calls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_REL = "evaluation/reuse-vocabulary.json"
FIELD = "reuse"

KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def parse_frontmatter(text: str):
    """(fields, body) — minimal scalar/list parse, the house
    idiom (cf. wiki_factscore_check / wiki_worktypes). Returns
    ({}, text) when the page carries no frontmatter."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[3:end].splitlines():
        m = KEY_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip("'\"") for v in
                       val[1:-1].split(",") if v.strip()]
        elif val:
            fm[key] = val.strip("'\"")
        else:
            fm[key] = None
    return fm, text[end + 4:]


def load_config(root: Path) -> dict:
    """The vocabulary + default, from the tree's own config.
    Raises ValueError with a named problem when the config is
    absent or malformed — never a silent assumed default."""
    path = Path(root) / CONFIG_REL
    if not path.is_file():
        raise ValueError(f"config missing: {CONFIG_REL}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"config unparseable: {CONFIG_REL}: {e}")
    classes = cfg.get("classes")
    if not isinstance(classes, list) or not classes:
        raise ValueError(f"config has no classes: {CONFIG_REL}")
    ids = [c.get("id") for c in classes if isinstance(c, dict)]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"config class ids missing/duplicated: "
                         f"{CONFIG_REL}")
    cfg["_ids"] = ids
    return cfg


def class_map(cfg: dict) -> dict:
    return {c["id"]: c for c in cfg["classes"]}


def effective_reuse(fields: dict, cfg: dict):
    """(effective, source, findings) for one page's fields.
    source is 'declared', 'default' or 'default-fallback'
    (declared value invalid; the default carries the page
    until the statement is fixed — stated, never silent)."""
    ids = cfg["_ids"]
    declared = fields.get(FIELD)
    if isinstance(declared, str):
        declared = declared.strip() or None
    findings = []
    if declared is None:
        findings.append("missing-statement")
        return cfg.get("default_reuse"), "default", findings
    if declared not in ids:
        findings.append("invalid-statement")
        return cfg.get("default_reuse"), "default-fallback", findings
    return declared, "declared", findings


def check(root: Path) -> dict:
    root = Path(root)
    cfg = load_config(root)
    ids = cfg["_ids"]
    default = cfg.get("default_reuse")
    config_findings = []
    if default not in ids:
        config_findings.append(
            {"kind": "bad-default", "default_reuse": default,
             "note": "the configured default is outside the "
                     "vocabulary; no page's effective class can "
                     "be trusted until the config is fixed"})
    pages = []
    wiki = root / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            text = p.read_text(encoding="utf-8", errors="ignore")
            fields, _ = parse_frontmatter(text)
            if not fields:
                continue  # structural pages: no frontmatter, exempt
            eff, source, findings = effective_reuse(fields, cfg)
            pages.append({
                "page": str(p.relative_to(root)),
                "declared": fields.get(FIELD)
                if isinstance(fields.get(FIELD), str) else None,
                "effective": eff,
                "source": source,
                "findings": findings,
            })
    by_effective = {}
    for pg in pages:
        by_effective[pg["effective"]] = \
            by_effective.get(pg["effective"], 0) + 1
    return {
        "tool": "scripts/wiki_reuse.py",
        "kind": "fair-reuse-report",
        "pattern": "Wilkinson et al. 2016 (CC BY 4.0) FAIR "
                   "Reusable, narrowed to a per-page reuse "
                   "statement — report-only; this tool never "
                   "edits a page and blocks nothing",
        "config": CONFIG_REL,
        "vocabulary": ids,
        "default_reuse": default,
        "default_basis": cfg.get("default_basis"),
        "config_findings": config_findings,
        "stats": {
            "pages": len(pages),
            "declared": sum(1 for p in pages
                            if p["source"] == "declared"),
            "missing": sum(1 for p in pages
                           if "missing-statement" in p["findings"]),
            "invalid": sum(1 for p in pages
                           if "invalid-statement" in p["findings"]),
            "by_effective": by_effective,
        },
        "pages": pages,
    }


def statement_for(root: Path, page_rel: str) -> dict:
    root = Path(root)
    cfg = load_config(root)
    path = root / page_rel
    if not path.is_file():
        raise ValueError(f"no such page: {page_rel}")
    fields, _ = parse_frontmatter(
        path.read_text(encoding="utf-8", errors="ignore"))
    eff, source, findings = effective_reuse(fields, cfg)
    entry = class_map(cfg).get(eff) or {}
    return {
        "page": page_rel,
        "declared": fields.get(FIELD)
        if isinstance(fields.get(FIELD), str) else None,
        "effective": eff,
        "source": source,
        "findings": findings,
        "label": entry.get("label"),
        "statement": entry.get("statement"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check")
    c.add_argument("--plain", action="store_true")
    s = sub.add_parser("statement")
    s.add_argument("page")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.cmd == "statement":
            print(json.dumps(statement_for(root, args.page),
                             indent=2, sort_keys=True))
            return 0
        report = check(root)  # default command: check
    except ValueError as e:
        print(f"wiki_reuse: {e}", file=sys.stderr)
        return 2
    if getattr(args, "plain", False):
        st = report["stats"]
        print(f"reuse: {st['pages']} page(s); {st['declared']} "
              f"declared, {st['missing']} missing (read under "
              f"default '{report['default_reuse']}'), "
              f"{st['invalid']} invalid")
        for f in report["config_findings"]:
            print(f"  CONFIG {f['kind']}: {f['note']}")
        for pg in report["pages"]:
            for kind in pg["findings"]:
                print(f"  {kind.upper()}: {pg['page']} "
                      f"(declared={pg['declared']!r}, "
                      f"effective={pg['effective']!r} "
                      f"via {pg['source']})")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    findings = (report["stats"]["missing"]
                + report["stats"]["invalid"]
                + len(report["config_findings"]))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
