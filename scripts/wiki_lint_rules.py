#!/usr/bin/env python3
"""Linter rule catalogue — cherry-picked rules, rule by rule.

Item: "the Linter rule catalogue, cherry-picked rule by
rule" from the standing Tier A queue (Marathon Round 2
record). Source catalogue: the Obsidian Linter plugin's
~70-rule catalogue, noted in the project's feature
survey with the
standing discipline "licence not seen -> implement the
rules, don't copy code". Every rule below is implemented
here from its one-line idea, in this wiki's own terms;
no Linter code or text is copied.

This is a NEW checker, not a seventh lint lane:
scripts/wiki_lint_lanes.py is untouched. The rules surface
findings for review and never rewrite a page — the same
surfacing discipline as the lanes. Each rule can be run
alone (--only) or skipped (--skip); the default run is
the whole adopted set:

  orphan-media            a media file under wiki/ or raw/
                          that no page references (by repo
                          path, wiki-relative path, or file
                          name, in markdown or wikilink form)
  frontmatter-completeness
                          a compiled page missing one of the
                          schema's required frontmatter keys
                          (title, type, created, updated,
                          sources, tags), or carrying no
                          frontmatter at all. Structural
                          pages (wiki/index.md, wiki/log.md)
                          are exempt — the schema gives them
                          no frontmatter.
  link-text-quality       a wikilink or markdown link whose
                          visible text is empty, a bare URL,
                          "here", "click here", "link" or
                          "this" — text that tells a reader
                          nothing about its target
  heading-structure       heading levels that skip (an H3
                          directly under an H1), more than
                          one H1, or a first heading that is
                          not H1 — over body headings, fences
                          excluded
  image-alt               an image embed (![[...]] or
                          ![alt](...)) with empty alt text
  tag-vocabulary          a tag in use that is not a
                          prefLabel or altLabel on the tag
                          registry (evaluation/tag-registry
                          .jsonl), or a deprecated registry
                          tag still in use. When no registry
                          exists the rule reports itself
                          skipped — it never invents a
                          vocabulary.

Findings name page, line (where the rule has one), rule,
and a short detail. Output: human summary or JSON (--json).
Exit codes: 0 = no findings, 1 = findings, 2 = usage error
(including an unknown --only/--skip rule name).

Usage:
  python3 scripts/wiki_lint_rules.py [--root DIR]
      [--only RULE,RULE] [--skip RULE,RULE] [--json]

Stdlib only.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}
REQUIRED_KEYS = ("title", "type", "created", "updated", "sources", "tags")
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg",
                  ".webp", ".mp3", ".mp4", ".wav", ".ogg"}
BAD_LINK_TEXTS = {"", "here", "click here", "link", "this",
                  "click", "page", "website"}
RULES = ("orphan-media", "frontmatter-completeness",
         "link-text-quality", "heading-structure",
         "image-alt", "tag-vocabulary")

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")
MDLINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
IMG_WIKI_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
MEDIA_REF_RE = re.compile(
    r"[^\s\]\)\"']+\.(?:png|jpe?g|gif|svg|webp|mp3|mp4|wav|ogg)",
    re.I)


def _load_validate():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finding(rule, page, line, detail):
    return {"rule": rule, "page": page, "line": line, "detail": detail}


def _pages(root):
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    return sorted(wiki.rglob("*.md"))


def _body_lines(text):
    """(lineno, line) over the body only: frontmatter skipped,
    fenced code blocks skipped (a heading or link inside a
    fence is documentation, not structure)."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    in_fence = False
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield i + 1, lines[i]


# -- individual rules -------------------------------------------------------

def rule_orphan_media(root, texts):
    """Media files (wiki/ + raw/) no page references."""
    referenced = set()
    haystacks = []
    for _rel, text in texts:
        haystacks.append(text)
        for m in MEDIA_REF_RE.finditer(text):
            ref = m.group(0).strip("([<")
            referenced.add(ref)
            referenced.add(Path(ref).name)
    findings = []
    checked = 0
    for base in ("wiki", "raw"):
        top = root / base
        if not top.is_dir():
            continue
        for path in sorted(top.rglob("*")):
            if not path.is_file() \
                    or path.suffix.lower() not in MEDIA_SUFFIXES:
                continue
            checked += 1
            rel = path.relative_to(root).as_posix()
            wiki_rel = (path.relative_to(root / "wiki").as_posix()
                        if base == "wiki" else rel)
            if rel in referenced or wiki_rel in referenced \
                    or path.name in referenced:
                continue
            findings.append(_finding(
                "orphan-media", rel, None,
                "media file referenced by no page (checked repo "
                "path, layer-relative path and file name)"))
    return findings, {"media_checked": checked}


def rule_frontmatter(root, texts, fields_by_page):
    findings = []
    for rel, _text in texts:
        if rel in EXCLUDED_FILES:
            continue
        fields = fields_by_page.get(rel)
        if not fields:
            findings.append(_finding(
                "frontmatter-completeness", rel, 1,
                "page carries no frontmatter block"))
            continue
        missing = [k for k in REQUIRED_KEYS if k not in fields]
        if missing:
            findings.append(_finding(
                "frontmatter-completeness", rel, 1,
                "missing required frontmatter key(s): "
                + ", ".join(missing)))
    return findings, {}


def rule_link_text(root, texts):
    findings = []
    for rel, text in texts:
        for lineno, line in _body_lines(text):
            visible = re.sub(r"`[^`\n]*`", "", line)
            for m in WIKILINK_RE.finditer(visible):
                if m.group(2) is None:
                    continue  # bare [[stem]]: the stem IS the text
                label = m.group(2).strip()
                if label.lower() in BAD_LINK_TEXTS \
                        or label.startswith(("http://", "https://")):
                    findings.append(_finding(
                        "link-text-quality", rel, lineno,
                        f"wikilink text {label!r} does not describe "
                        f"its target [[{m.group(1).strip()}]]"))
            for m in MDLINK_RE.finditer(visible):
                label = m.group(1).strip()
                if label.lower() in BAD_LINK_TEXTS \
                        or label == m.group(2):
                    findings.append(_finding(
                        "link-text-quality", rel, lineno,
                        f"link text {label!r} does not describe "
                        f"its target {m.group(2)}"))
    return findings, {}


def rule_headings(root, texts):
    findings = []
    for rel, text in texts:
        prev = 0
        h1_seen = 0
        first = True
        for lineno, line in _body_lines(text):
            m = HEADING_RE.match(line)
            if not m:
                continue
            level = len(m.group(1))
            if first and level != 1:
                findings.append(_finding(
                    "heading-structure", rel, lineno,
                    f"first heading is H{level}, not H1"))
            first = False
            if level == 1:
                h1_seen += 1
                if h1_seen > 1:
                    findings.append(_finding(
                        "heading-structure", rel, lineno,
                        "second H1 heading (a page has one H1)"))
            if prev and level > prev + 1:
                findings.append(_finding(
                    "heading-structure", rel, lineno,
                    f"heading level skips from H{prev} to H{level}"))
            prev = level
    return findings, {}


def rule_image_alt(root, texts):
    findings = []
    for rel, text in texts:
        for lineno, line in _body_lines(text):
            for m in IMG_WIKI_RE.finditer(line):
                alt = (m.group(2) or "").strip()
                # a |<number> suffix is a size, not alt text
                if not alt or re.fullmatch(r"\d+(x\d+)?", alt):
                    findings.append(_finding(
                        "image-alt", rel, lineno,
                        f"image embed ![[{m.group(1).strip()}]] "
                        f"carries no alt text"))
            for m in IMG_MD_RE.finditer(line):
                if not m.group(1).strip():
                    findings.append(_finding(
                        "image-alt", rel, lineno,
                        f"image {m.group(2)} carries empty alt text"))
    return findings, {}


def load_tag_registry(root):
    """(labels:set, deprecated:set, present:bool) from
    evaluation/tag-registry.jsonl (SKOS concepts)."""
    path = root / "evaluation" / "tag-registry.jsonl"
    if not path.is_file():
        return set(), set(), False
    labels, deprecated = set(), set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("kind") != "concept":
            continue
        pref = entry.get("prefLabel")
        if pref:
            labels.add(str(pref))
            if str(entry.get("status", "")).lower() == "deprecated":
                deprecated.add(str(pref))
        for alt in entry.get("altLabels") or []:
            labels.add(str(alt))
    return labels, deprecated, True


def rule_tag_vocabulary(root, texts, fields_by_page):
    labels, deprecated, present = load_tag_registry(root)
    if not present:
        return [], {"registry_present": False, "skipped": True}
    findings = []
    for rel, _text in texts:
        fields = fields_by_page.get(rel) or {}
        tags = fields.get("tags")
        if tags is None:
            continue
        if not isinstance(tags, list):
            tags = [tags]
        for tag in tags:
            tag = str(tag).strip()
            if not tag:
                continue
            if tag in deprecated:
                findings.append(_finding(
                    "tag-vocabulary", rel, 1,
                    f"tag {tag!r} is deprecated on the registry "
                    f"and still in use"))
            elif tag not in labels:
                findings.append(_finding(
                    "tag-vocabulary", rel, 1,
                    f"tag {tag!r} is not registered (no prefLabel "
                    f"or altLabel on the tag registry)"))
    return findings, {"registry_present": True,
                      "registered_labels": len(labels)}


# -- driver -------------------------------------------------------------------

def run_rules(root, only=None, skip=()):
    root = Path(root)
    validate = _load_validate()
    texts, fields_by_page = [], {}
    for path in _pages(root):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(EXCLUDED_DIRS):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        texts.append((rel, text))
        fields, _b = validate.parse_frontmatter(text)
        fields_by_page[rel] = fields
    active = [r for r in RULES
              if (only is None or r in only) and r not in skip]
    findings, stats = [], {}
    for rule in active:
        if rule == "orphan-media":
            f, s = rule_orphan_media(root, texts)
        elif rule == "frontmatter-completeness":
            f, s = rule_frontmatter(root, texts, fields_by_page)
        elif rule == "link-text-quality":
            f, s = rule_link_text(root, texts)
        elif rule == "heading-structure":
            f, s = rule_headings(root, texts)
        elif rule == "image-alt":
            f, s = rule_image_alt(root, texts)
        else:
            f, s = rule_tag_vocabulary(root, texts, fields_by_page)
        findings.extend(f)
        stats[rule] = {"findings": len(f), **s}
    findings.sort(key=lambda f: (f["rule"], f["page"],
                                 f["line"] or 0, f["detail"]))
    counts = {r: stats[r]["findings"] for r in active}
    return {"tool": "wiki_lint_rules", "pages_scanned": len(texts),
            "rules_run": active, "counts": counts,
            "total": len(findings), "stats": stats,
            "findings": findings}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Cherry-picked Linter-catalogue rules over "
                    "the compiled layer (report-only).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--only", default=None,
                    help="comma-separated rule names to run")
    ap.add_argument("--skip", default=None,
                    help="comma-separated rule names to skip")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        bad = only - set(RULES)
        if bad:
            print(f"error: unknown rule(s): {', '.join(sorted(bad))}; "
                  f"known: {', '.join(RULES)}", file=sys.stderr)
            return 2
    skip = set()
    if args.skip:
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        bad = skip - set(RULES)
        if bad:
            print(f"error: unknown rule(s): {', '.join(sorted(bad))}",
                  file=sys.stderr)
            return 2
    report = run_rules(root, only=only, skip=skip)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("== Lint rules (Linter catalogue, cherry-picked) ==")
        print(f"pages scanned: {report['pages_scanned']}   "
              f"findings: {report['total']}")
        for rule in report["rules_run"]:
            note = ""
            st = report["stats"].get(rule, {})
            if st.get("skipped"):
                note = " (skipped: no tag registry in this tree)"
            print(f"  {rule}: {report['counts'][rule]}{note}")
        for f in report["findings"]:
            loc = f"{f['page']}:{f['line']}" if f["line"] else f["page"]
            print(f"  - [{f['rule']}] {loc} — {f['detail']}")
    return 1 if report["total"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
