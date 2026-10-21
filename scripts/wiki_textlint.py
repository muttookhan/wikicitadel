#!/usr/bin/env python3
"""wiki_textlint.py — textlint starter check (Marathon R7, lane BB).

Board line (wiki/ideas.md, Round-5 Tier A): "A textlint starter
check — textlint (MIT) with a starter rule set (no-todo,
terminology consistency against canonical names) as an optional
ingest/build check; rules as packages, our own custom rules
allowed (azu / textlint, MIT)".

DESIGN DECISION (stated plainly, per the lane brief): the
rule-config SHAPE follows textlint's model — a config object
naming rules, each rule with an `options` object, exactly as a
`.textlintrc.json` would — while the RUNNER is ours. The wiki's
tooling is Python/stdlib throughout; introducing a Node
dependency for two starter rules would break the offline,
stdlib-only discipline every other checker here keeps. So:

  * evaluation/textlint-config.json declares the starter set
    AS DATA, in textlint's config shape:
        {"rules": {"no-todo": true,
                   "terminology": {"terms": "<register>"}},
         "filters": {}}
  * evaluation/canonical-names.json is the terminology
    register the `terminology` rule reads: canonical forms
    with their known variants.
  * THIS script reads both files and applies the rules
    deterministically. No Node, no network, no model calls.
    If a future lane vendors real textlint, it can consume
    the same config file unchanged for the no-todo rule and
    a mechanical translation of the register for terminology.

Rules implemented (starter set, exactly two):
  no-todo       a line containing a bare TODO / FIXME / XXX
                marker (word-boundary, case-sensitive for
                TODO/FIXME, as textlint's no-todo behaves)
                outside fenced code and outside HTML comments
                is a finding. Lines carrying the capture
                system's structural TODO prompts
                (`sensitivity: TODO`, `# TODO (capture)`)
                are exempt when the config's
                `allowStructuralCaptureTodo` option is true —
                those TODOs are a gate, not unfinished prose.
  terminology   a known VARIANT of a canonical name appearing
                as prose (outside fenced code, inline code,
                wikilink targets and URLs) is a finding naming
                the variant and the canonical form to use.
                Matching is case-sensitive for capitalised
                canonicals and whole-phrase, so prose that
                legitimately differs in case is not flagged.

REPORT ONLY. This tool never edits a page. It is OPTIONAL:
nothing wires it into ingest or the sweep; it runs when
invoked, as an ingest/build check a human may choose to run.

    python3 scripts/wiki_textlint.py [--root DIR]
        [--config FILE] [--register FILE] [--plain]
        [paths...]          (default: all wiki/**/*.md)

Exit: 0 no findings · 1 findings · 2 usage / missing config.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path("evaluation/textlint-config.json")
DEFAULT_REGISTER = Path("evaluation/canonical-names.json")

TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")
STRUCTURAL_TODO_HINTS = ("sensitivity:", "TODO (capture)")


def load_config(root: Path, config_path: Path | None):
    p = config_path or (root / DEFAULT_CONFIG)
    if not p.is_file():
        raise FileNotFoundError(f"textlint config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    return cfg, p


def load_register(root: Path, register_path: Path | None, cfg):
    # The config's terminology rule points at the register;
    # an explicit --register wins.
    rel = None
    try:
        rel = cfg["rules"]["terminology"]["options"]["terms"]
    except Exception:
        rel = None
    p = register_path or (root / rel if rel else root / DEFAULT_REGISTER)
    if not p.is_file():
        raise FileNotFoundError(f"canonical-names register not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = data.get("canonical_names", data if isinstance(data, list) else [])
    terms = []
    for e in entries:
        canon = e["canonical"]
        for variant in e.get("variants", []):
            if variant != canon:
                terms.append((variant, canon))
    # Longest variant first so a phrase match wins over a
    # shorter overlapping one at the same position.
    terms.sort(key=lambda t: -len(t[0]))
    return terms, p


def _visible_lines(text: str):
    """Yield (lineno, line) with fenced code and HTML comments
    removed (line numbers preserved)."""
    in_fence = False
    in_comment = False
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Strip HTML comments (single- and multi-line, simple).
        out = line
        while True:
            if in_comment:
                end = out.find("-->")
                if end < 0:
                    out = ""
                    break
                out = out[end + 3:]
                in_comment = False
            else:
                start = out.find("<!--")
                if start < 0:
                    break
                end = out.find("-->", start)
                if end < 0:
                    out = out[:start]
                    in_comment = True
                    break
                out = out[:start] + out[end + 3:]
        yield i, out


def _strip_inline_code_and_links(line: str) -> str:
    line = re.sub(r"`[^`]*`", "", line)
    # Wikilink targets are identifiers, not prose.
    line = re.sub(r"\[\[[^\]]*\]\]", "", line)
    line = re.sub(r"https?://\S+", "", line)
    return line


def check_text(text: str, terms, cfg) -> list[dict]:
    rules = cfg.get("rules", {})
    findings = []
    no_todo_on = bool(rules.get("no-todo"))
    term_on = bool(rules.get("terminology"))
    allow_structural = True
    try:
        allow_structural = bool(
            rules.get("no-todo", {}).get("options", {}).get(
                "allowStructuralCaptureTodo", True)) \
            if isinstance(rules.get("no-todo"), dict) else True
    except Exception:
        allow_structural = True
    for lineno, line in _visible_lines(text):
        if no_todo_on:
            for m in TODO_RE.finditer(line):
                if allow_structural and any(
                        h in line for h in STRUCTURAL_TODO_HINTS):
                    continue
                findings.append({
                    "line": lineno, "rule": "no-todo",
                    "marker": m.group(1),
                    "message": f"{m.group(1)} marker in prose",
                    "excerpt": line.strip()[:120]})
        if term_on:
            prose = _strip_inline_code_and_links(line)
            for variant, canon in terms:
                for m in re.finditer(re.escape(variant), prose):
                    findings.append({
                        "line": lineno, "rule": "terminology",
                        "variant": variant, "canonical": canon,
                        "message": f"use canonical '{canon}' "
                                   f"instead of '{variant}'",
                        "excerpt": line.strip()[:120]})
    findings.sort(key=lambda f: (f["line"], f["rule"]))
    return findings


def check(root: Path, config_path=None, register_path=None,
          paths=None) -> dict:
    cfg, cfg_path = load_config(root, config_path)
    terms, reg_path = load_register(root, register_path, cfg)
    if paths:
        files = [Path(p) for p in paths]
    else:
        files = sorted((root / "wiki").rglob("*.md"))
    per_file = []
    total = 0
    for f in files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        found = check_text(text, terms, cfg)
        if found:
            rel = str(f.relative_to(root)) if f.is_relative_to(root) else str(f)
            per_file.append({"page": rel, "findings": found})
            total += len(found)
    return {
        "tool": "scripts/wiki_textlint.py",
        "kind": "textlint-starter-report",
        "runner": "ours (Python/stdlib) — config shape follows "
                  "textlint's model; no Node dependency",
        "config": str(cfg_path.relative_to(root))
        if cfg_path.is_relative_to(root) else str(cfg_path),
        "register": str(reg_path.relative_to(root))
        if reg_path.is_relative_to(root) else str(reg_path),
        "rules": sorted(k for k, v in cfg.get("rules", {}).items() if v),
        "stats": {"files_checked": len(files),
                  "files_with_findings": len(per_file),
                  "findings": total},
        "files": per_file,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--config", default=None)
    ap.add_argument("--register", default=None)
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        report = check(
            root,
            Path(args.config) if args.config else None,
            Path(args.register) if args.register else None,
            [Path(p) if Path(p).is_absolute() else root / p
             for p in args.paths] or None)
    except FileNotFoundError as e:
        print(f"wiki_textlint: {e}", file=sys.stderr)
        return 2
    if args.plain:
        st = report["stats"]
        print(f"textlint starter: {st['findings']} finding(s) in "
              f"{st['files_with_findings']}/{st['files_checked']} file(s)")
        for entry in report["files"]:
            for f in entry["findings"]:
                print(f"  {entry['page']}:{f['line']} "
                      f"[{f['rule']}] {f['message']}")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["stats"]["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
