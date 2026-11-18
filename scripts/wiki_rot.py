#!/usr/bin/env python3
"""Rot census: the four named rot classes over the compiled
layer (WikiCitadel v1).

The vocabulary is the four-class rot taxonomy from the
failure-literature survey (find 20,
docs/research-notes.md), where a 61-page production
knowledge base was audited against its sources of record
and 39% of pages held at least one false statement:

  expired — the page's own date horizon has passed (a
            fact whose price/name/policy changed under it;
            the survey's fix is timestamp + owner + probe —
            here the class is asserted only from a horizon
            the page itself carries, never from age alone);
  ghost   — the page's referent is gone: a source it cites
            is not on disk, so the page still answers for
            something the record no longer holds;
  fork    — two live pages carry the same stem, the same
            title, or the same settled claim, and retrieval
            returns whichever ranks higher;
  orphan  — no page in the compiled layer links to it and
            it links to none: an island, still indexed,
            owned by nobody's reading path.

A class is asserted ONLY from the observable signal named
beside it in the census — never from a vibe, a topic, or a
page's age. A page matching no signal is reported as
"no rot signal", which is the expected majority state.
Classes are not exclusive: a page can be both expired and
orphaned, and the census says so.

The compiled layer is the lint lanes' definition
(scripts/wiki_lint_lanes.py): wiki/**/*.md excluding
wiki/filings/, wiki/talk/, wiki/index.md and wiki/log.md.
Wikilink counting ignores frontmatter and fenced code
(the wiki validator's convention). Source existence uses
the wiki_stale.py resolution semantics: path entries are
checked on disk; bare slugs are matched against
raw/sources/ by file-stem token set.

This is a report, not a gate: exit code is always 0.

Usage:
  python3 scripts/wiki_rot.py [--json] [--filing]
      --filing also writes wiki/filings/rot-census-<date>.md
Stdlib only (wiki_stale imported in-process for its
frontmatter parser).
"""
import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}
CLASSES = ("expired", "ghost", "fork", "orphan")
HORIZON_FIELDS = ("verified_until", "valid_until", "expires",
                  "closes", "deadline")
RETIRED_STATUSES = {"superseded", "deprecated"}

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stale = _load("wiki_stale")
parse_frontmatter = stale.parse_frontmatter


# -- helpers -----------------------------------------------------------------

def _slug_tokens(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _norm_text(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def _parse_date(value):
    if not value:
        return None
    m = DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def body_without_frontmatter(text):
    m = re.match(r"^---\n.*?\n---\n?", text, re.S)
    return text[m.end():] if m else text


def strip_fences(body):
    out, in_fence = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


class SourceIndex:
    """Existence checks for frontmatter source entries,
    under an arbitrary repo root (fixtures included)."""

    def __init__(self, root):
        self.root = Path(root)
        self._slug_index = None

    def _slugs(self):
        if self._slug_index is None:
            idx = {}
            raw_sources = self.root / "raw" / "sources"
            if raw_sources.is_dir():
                for p in sorted(raw_sources.rglob("*")):
                    if p.is_file():
                        idx.setdefault(
                            frozenset(_slug_tokens(p.stem)), p)
            self._slug_index = idx
        return self._slug_index

    def resolves(self, entry):
        """True when the cited source exists on disk."""
        entry = str(entry).strip().strip("\"'")
        if not entry:
            return True
        if "/" in entry:
            return (self.root / entry).is_file()
        hit = self._slugs().get(frozenset(_slug_tokens(entry)))
        return hit is not None


# -- census --------------------------------------------------------------------

def layer_pages(root):
    """The compiled layer under root, repo-relative paths."""
    wiki = Path(root) / "wiki"
    out = []
    if not wiki.is_dir():
        return out
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in EXCLUDED_FILES or rel.startswith(EXCLUDED_DIRS):
            continue
        out.append(p)
    return out


def census(root, today=None):
    """{pages: {rel: {class: [signals]}}, summary: {...}} —
    only pages carrying at least one class appear in pages;
    every layer page is counted in the summary."""
    root = Path(root)
    today = today or date.today()
    sources_idx = SourceIndex(root)
    pages = layer_pages(root)
    info = {}          # rel -> parsed page facts
    stem_map = defaultdict(list)
    for p in pages:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, srcs = parse_frontmatter(text)
        fields = fields or {}
        info[rel] = {
            "fields": fields, "sources": srcs,
            "body": strip_fences(body_without_frontmatter(text)),
            "stem": p.stem,
        }
        stem_map[p.stem].append(rel)

    # Wikilink graph over the layer.
    inbound = Counter()
    outbound = {}
    for rel, d in info.items():
        targets = set()
        for m in LINK_RE.finditer(d["body"]):
            tgt = m.group(1).strip()
            if tgt.endswith(".md"):
                tgt = tgt[:-3]
            stem = Path(tgt).stem if "/" in tgt else tgt
            for hit in stem_map.get(stem, []):
                if hit != rel:
                    targets.add(hit)
        outbound[rel] = targets
        for t in targets:
            inbound[t] += 1

    def retired(rel):
        f = info[rel]["fields"]
        return (str(f.get("status") or "").strip().lower()
                in RETIRED_STATUSES) or bool(f.get("superseded_by"))

    findings = defaultdict(dict)   # rel -> {class: [signals]}

    def flag(rel, cls, signal):
        findings[rel].setdefault(cls, []).append(signal)

    # expired + ghost: per-page signals.
    for rel, d in info.items():
        f = d["fields"]
        for field in HORIZON_FIELDS:
            horizon = _parse_date(f.get(field))
            if horizon is not None and horizon < today:
                flag(rel, "expired",
                     f"frontmatter {field}: {horizon.isoformat()}"
                     f" has passed (today {today.isoformat()})")
        for entry in d["sources"]:
            if not sources_idx.resolves(entry):
                flag(rel, "ghost",
                     f"cited source {entry!r} is not on disk")

    # fork: shared stem / title / claim among live pages.
    def fork_groups(keyfn, label):
        groups = defaultdict(list)
        for rel, d in info.items():
            if retired(rel):
                continue
            key = keyfn(d)
            if key:
                groups[key].append(rel)
        for key, rels in groups.items():
            if len(rels) > 1:
                for rel in rels:
                    others = ", ".join(sorted(r for r in rels
                                              if r != rel))
                    flag(rel, "fork",
                         f"shares {label} {key!r} with {others}"
                         " (neither marked superseded)")

    fork_groups(lambda d: d["stem"], "page stem")
    fork_groups(lambda d: _norm_text(d["fields"].get("title")),
                "title")
    fork_groups(lambda d: _norm_text(d["fields"].get("claim")),
                "claim")

    # orphan: an island in the layer's link graph.
    for rel, d in info.items():
        if inbound[rel] == 0 and not outbound[rel]:
            n_res = sum(1 for s in d["sources"]
                        if sources_idx.resolves(s))
            flag(rel, "orphan",
                 "no inbound wikilinks from the compiled layer"
                 " and no outbound wikilinks to it; its"
                 f" citations point only outside the layer"
                 f" ({n_res} of {len(d['sources'])} cited"
                 " source(s) on disk, none a compiled page)")

    counts = Counter()
    for rel, classes in findings.items():
        for cls in classes:
            counts[cls] += 1
    return {
        "date": today.isoformat(),
        "layer_pages": len(pages),
        "pages_with_signal": len(findings),
        "no_rot_signal": len(pages) - len(findings),
        "counts": {c: counts.get(c, 0) for c in CLASSES},
        "pages": {rel: findings[rel] for rel in sorted(findings)},
    }


# -- rendering -------------------------------------------------------------------

def render_text(rep):
    lines = [
        f"Rot census — {rep['date']}",
        f"Compiled layer: {rep['layer_pages']} pages ·"
        f" with rot signal: {rep['pages_with_signal']} ·"
        f" no rot signal: {rep['no_rot_signal']}",
        "",
        "Counts by class: " + " · ".join(
            f"{c} {rep['counts'][c]}" for c in CLASSES),
    ]
    for cls in CLASSES:
        lines += ["", f"## {cls}"]
        rows = [(rel, sigs) for rel, cs in rep["pages"].items()
                for c, sigs in cs.items() if c == cls]
        if not rows:
            lines.append("(none)")
        for rel, sigs in rows:
            for s in sigs:
                lines.append(f"- `{rel}` — {s}")
    return "\n".join(lines) + "\n"


def render_filing(rep):
    d = rep["date"]
    lines = [
        "---",
        f"title: Rot census — {d}",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [rot, census, filings]",
        "status: draft",
        "confidence: observed",
        "stage: seedling",
        f"planted: {d}",
        f"tended: {d}",
        "work_type: record",
        "---",
        "",
        f"# Rot census — {d}",
        "",
        "> [!warning] AWAITING OWNER — surfaced issues, nothing applied",
        "> Generated by the rot census (`scripts/wiki_rot.py`),"
        " WikiCitadel v1. **Nothing in this file is"
        " canonical, no page has been changed, and nothing here"
        " has been fixed or applied.** Each item moves only when"
        " the owner rules on it.",
        "",
        "The four rot classes (failure-literature survey,"
        " find 20): **expired** (the page's own date horizon has"
        " passed), **ghost** (a source it cites is not on disk —"
        " the referent is gone), **fork** (two live pages share a"
        " stem, title, or settled claim), **orphan** (no page in"
        " the compiled layer links to it, and it links to none)."
        " A class is asserted only from the observable signal"
        " named beside it; a page matching no signal is counted"
        " as **no rot signal**. The compiled layer is the lint"
        " lanes' definition: `wiki/**/*.md` excluding"
        " `wiki/filings/`, `wiki/talk/`, `wiki/index.md` and"
        " `wiki/log.md`.",
        "",
        f"Scale this run: {rep['layer_pages']} pages in the"
        f" layer · {rep['pages_with_signal']} with a rot signal"
        f" · {rep['no_rot_signal']} with no rot signal.",
        "",
        "Counts by class: " + " · ".join(
            f"**{c} {rep['counts'][c]}**" for c in CLASSES) + ".",
    ]
    for cls in CLASSES:
        lines += ["", f"## {cls} ({rep['counts'][cls]})", ""]
        rows = [(rel, sigs) for rel, cs in rep["pages"].items()
                for c, sigs in cs.items() if c == cls]
        if not rows:
            lines.append("No page carries this signal this run.")
        for rel, sigs in rows:
            for s in sigs:
                lines.append(f"- `{rel}` — {s}")
    lines += [
        "",
        "## What this census does not claim",
        "",
        "Absence of a signal is not proof of health: the census"
        " reads only the signals named above. A page whose facts"
        " quietly stopped being true — with no horizon field, no"
        " missing source, no twin, and links intact — carries no"
        " rot signal here; catching that shape is the probe and"
        " re-verification machinery's work, not this census's.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Rot census over the compiled layer:"
                    " expired / ghost / fork / orphan .")
    ap.add_argument("--json", action="store_true",
                    help="emit the census as JSON")
    ap.add_argument("--filing", action="store_true",
                    help="also write the census filing under"
                         " wiki/filings/")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this repo)")
    args = ap.parse_args(argv[1:])
    root = Path(args.root) if args.root else ROOT
    rep = census(root)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(render_text(rep), end="")
    if args.filing:
        out = (root / "wiki" / "filings"
               / f"rot-census-{rep['date']}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_filing(rep), encoding="utf-8")
        print(f"filing: {out.relative_to(root).as_posix()}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
