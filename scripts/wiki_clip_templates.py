#!/usr/bin/env python3
"""wiki_clip_templates.py — clip templates auto-selected by URL
pattern (Marathon Round 3, lane TA4; row: "clip templates
auto-selected by URL pattern").

A clip template is a named extraction profile: which part of a
page is the content (a `keep` selector), which parts are chrome
to strip before conversion (`strip` selectors), and where the
title lives (`title_selector`). Until now every clip ran the
same generic extraction whatever the site. This module is the
registry the clip path consults FIRST: templates are keyed by
URL patterns (regexes, matched in registry order — most
specific first), and the selection is automatic.

THE FALLBACK IS STATED, NEVER SILENT: when no pattern matches,
select_template() returns the template named "generic" with
fallback=True — the same whole-page extraction (minus the
universal chrome strips) the clip path always did. The chosen
template's name and whether it was the fallback are recorded
in the clip's ingest sidecar, so a capture always says which
extraction produced it.

A tree may override or extend the built-in registry with
templates/clip-templates.json — a JSON list of template
objects with the same fields; a file template with the same
name replaces the built-in one, and file templates are tried
before built-ins (a site the owner clips often earns its own
template). A malformed override file is a loud error, never a
silent fallback to the built-ins.

Selectors are the small vocabulary of
scripts/wiki_site_rules.py: `tag`, `.class`, `#id`, `tag.class`,
`tag#id`. Application of a profile to HTML lives there too
(apply_profile) — this module is the registry and the
selection, that module is the mechanics, and
scripts/wiki_clip.py wires both into the clip path.

    python3 scripts/wiki_clip_templates.py list [--root DIR]
    python3 scripts/wiki_clip_templates.py match <url> [--root DIR]

Exit codes: 0 ok · 1 refusal · 2 usage error. Output is JSON
for `match`, plain lines for `list`.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = Path("templates/clip-templates.json")

# Registry order is selection order: specific shapes first,
# the generic fallback last (it has no patterns and matches
# everything by construction of select_template()).
BUILTIN_TEMPLATES = [
    {
        "name": "reference-wiki",
        "patterns": [r"wikipedia\.org/wiki/", r"/wiki/[^/]+$"],
        "keep": "#mw-content-text",
        "strip": ["nav", "footer", ".mw-editsection", ".navbox",
                  "#toc", ".infobox"],
        "title_selector": "h1",
        "note": "encyclopedia/reference pages: the article body "
                "is the content; navigation boxes and edit "
                "links are chrome",
    },
    {
        "name": "docs",
        "patterns": [r"^https?://docs\.", r"/docs/", r"/documentation/",
                     r"readthedocs\.io", r"/reference/"],
        "keep": "main",
        "strip": ["nav", "footer", "aside", ".sidebar", ".toc"],
        "title_selector": "h1",
        "note": "documentation: <main> carries the text; side "
                "navigation and footers are chrome",
    },
    {
        "name": "article",
        "patterns": [r"/(article|articles|post|posts|blog|news|story)/",
                     r"\d{4}/\d{2}/\d{2}/"],
        "keep": "article",
        "strip": ["nav", "footer", "aside", ".sidebar", ".share",
                  ".comments", ".related", ".ad-slot"],
        "title_selector": "h1",
        "note": "news/blog articles: the <article> element is "
                "the content; share bars, comment blocks and "
                "related-story rails are chrome",
    },
    {
        "name": "generic",
        "patterns": [],
        "keep": None,
        "strip": ["nav", "footer", "aside", ".cookie-banner",
                  ".popup", ".newsletter-signup"],
        "title_selector": None,
        "note": "THE STATED FALLBACK: no URL pattern matched, "
                "so the whole page is extracted with only the "
                "universal chrome stripped — the extraction "
                "the clip path always did",
    },
]


class TemplateError(Exception):
    pass


def load_registry(root=ROOT):
    """Built-in templates with the tree's optional
    templates/clip-templates.json applied: file templates
    come first (tried first), and a file template with a
    built-in's name replaces that built-in."""
    root = Path(root)
    templates = []
    override = root / REGISTRY_FILE
    if override.is_file():
        try:
            data = json.loads(override.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TemplateError(
                "clip template registry %s is unreadable: %s"
                % (override, exc)) from exc
        if not isinstance(data, list):
            raise TemplateError(
                "clip template registry %s must be a JSON list "
                "of template objects" % override)
        for entry in data:
            if not isinstance(entry, dict) or not entry.get("name"):
                raise TemplateError(
                    "clip template registry %s: every entry "
                    "needs a name" % override)
            templates.append(entry)
    replaced = {t["name"] for t in templates}
    for builtin in BUILTIN_TEMPLATES:
        if builtin["name"] not in replaced:
            templates.append(builtin)
    return templates


def select_template(url, root=ROOT, registry=None):
    """The template for `url`: the first registry entry (in
    order) with a pattern matching the URL, else the generic
    fallback. Returns a copy of the template plus
    "matched_pattern" (None on the fallback) and "fallback"
    (True only for the generic template)."""
    registry = registry if registry is not None \
        else load_registry(root)
    for template in registry:
        for pattern in template.get("patterns") or []:
            if re.search(pattern, url or ""):
                chosen = dict(template)
                chosen["matched_pattern"] = pattern
                chosen["fallback"] = False
                return chosen
    for template in registry:
        if template["name"] == "generic":
            chosen = dict(template)
            chosen["matched_pattern"] = None
            chosen["fallback"] = True
            return chosen
    raise TemplateError("the registry has no 'generic' "
                        "fallback template")


def profile_of(template):
    """The extraction profile (keep / strip / title_selector)
    a template contributes to wiki_site_rules.apply_profile."""
    return {"keep": template.get("keep"),
            "strip": list(template.get("strip") or []),
            "title_selector": template.get("title_selector")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("match")
    p.add_argument("url")
    args = ap.parse_args(argv)
    try:
        registry = load_registry(args.root)
        if args.cmd == "list":
            for t in registry:
                pats = ", ".join(t.get("patterns") or []) \
                    or "(fallback — matches everything)"
                print("%s: %s" % (t["name"], pats))
                print("  %s" % (t.get("note") or ""))
        else:
            print(json.dumps(select_template(args.url,
                                             registry=registry),
                             indent=2, sort_keys=True))
    except TemplateError as exc:
        print("wiki_clip_templates: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
