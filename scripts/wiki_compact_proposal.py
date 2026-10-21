#!/usr/bin/env python3
"""wiki_compact_proposal.py — compaction as a recoverable PROPOSAL.

Marathon Round 3, Lane TA5 (Tier A). Pattern: ReMe-style
compaction, re-implemented from the idea (no code copied):
long pages (and long log segments) accumulate until nobody
reads them, and the tempting fix — rewrite the page shorter
in place — destroys the original. This tool instead drafts
a compaction as a proposal artefact and NEVER touches the
target page:

  * the draft is extractive and deterministic: the page's
    heading skeleton, the first paragraph of each section
    (trimmed at a sentence boundary to <= SECTION_CHARS),
    and the section's wikilinks preserved as a link list;
  * the artefact records the original's path, SHA-256,
    line/char counts and the draft's, so a reviewer can
    verify nothing else changed;
  * the RESTORE PATH is stated in the artefact itself: the
    original was never modified, so "restoring" is simply
    rejecting the proposal; if a reviewer later applies a
    compaction by hand, the original text remains in git
    history at the recorded SHA-256.

Artefacts land under wiki/filings/: compact-<stem>-<date>.md
(the draft + restore statement) and .json (the manifest,
kind "compaction-proposal"). A page must reach --min-lines
lines (default 120) to be proposed, unless --force.

    python3 scripts/wiki_compact_proposal.py <page> \
        [--root DIR] [--date YYYY-MM-DD] [--min-lines N]
        [--dry-run]

Exit codes: 0 proposed (or dry-run printed) · 1 refused
(no such page / below the line threshold) · 2 usage error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION_CHARS = 280        # per-section extract budget
DEFAULT_MIN_LINES = 120

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_sections(text: str) -> list[dict]:
    """Sections split on ATX headings: [{level, heading,
    lines}] with the pre-heading preamble as level 0."""
    sections = [{"level": 0, "heading": "", "lines": []}]
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            sections.append({"level": len(m.group(1)),
                             "heading": m.group(2).strip(),
                             "lines": []})
        else:
            sections[-1]["lines"].append(line)
    return sections


def trim_extract(lines: list[str]) -> str:
    """The first paragraph of a section, trimmed at a
    sentence boundary to <= SECTION_CHARS (hard cut with an
    ellipsis marker when no boundary fits)."""
    para = []
    for line in lines:
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    text = " ".join(para).strip()
    if len(text) <= SECTION_CHARS:
        return text
    cut = ""
    for m in SENTENCE_RE.finditer(text):
        if m.end() <= SECTION_CHARS:
            cut = text[:m.end()].strip()
        else:
            break
    return cut or (text[:SECTION_CHARS].rstrip() + " […]")


def draft_compaction(text: str) -> str:
    """The deterministic extractive draft described above."""
    out = []
    for sec in split_sections(text):
        if sec["level"] == 0:
            fm = "\n".join(sec["lines"])
            if fm.startswith("---"):
                out.append("_(frontmatter carried over unchanged "
                           "if the proposal is applied)_")
            extract = trim_extract(sec["lines"]) \
                if not fm.startswith("---") else ""
        else:
            out.append("#" * sec["level"] + " " + sec["heading"])
            extract = trim_extract(sec["lines"])
        if extract:
            out.append(extract)
        links = sorted({m.group(1).strip()
                        for line in sec["lines"]
                        for m in LINK_RE.finditer(line)})
        if sec["level"] > 0 and links:
            out.append("Links: " + ", ".join(f"[[{l}]]" for l in links))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_proposal(root: Path, rel: str, today: date | None = None,
                   min_lines: int = DEFAULT_MIN_LINES,
                   force: bool = False) -> dict:
    """The proposal manifest for one page. Raises ValueError
    with the refusal reason for a missing/short page."""
    root = Path(root)
    today = today or date.today()
    path = root / rel
    if not path.is_file():
        raise ValueError(f"no such page: {rel}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    if not force and lines < min_lines:
        raise ValueError(
            f"{rel} has {lines} lines, below the {min_lines}-line "
            "threshold (pass --force to propose anyway)")
    draft = draft_compaction(text)
    stem = Path(rel).stem
    return {
        "tool": "scripts/wiki_compact_proposal.py",
        "kind": "compaction-proposal",
        "pattern": "ReMe-style compaction as a recoverable "
                   "proposal — the original is never modified",
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "date": today.isoformat(),
        "status": "proposed",
        "target": rel,
        "original": {"sha256": sha256_text(text), "lines": lines,
                     "chars": len(text)},
        "draft": {"lines": draft.count("\n"), "chars": len(draft)},
        "restore_path": (
            f"The original page {rel} was NOT modified by this "
            "tool (verify: sha256 "
            f"{sha256_text(text)}). Rejecting this proposal "
            "restores the status quo exactly — there is nothing "
            "to undo. If a reviewer applies a compaction by "
            "hand, the pre-compaction text remains recoverable "
            "from git history; check a candidate recovery "
            "against the recorded sha256 before trusting it."),
        "artefact": f"wiki/filings/compact-{stem}-{today.isoformat()}.md",
        "draft_text": draft,
    }


def render_artefact(manifest: dict) -> str:
    d = manifest["date"]
    o, dr = manifest["original"], manifest["draft"]
    return "\n".join([
        "---",
        f"title: Compaction proposal — {manifest['target']}",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources: []",
        "tags: [compaction, proposal, filings]",
        "status: draft",
        "stage: seedling",
        f"planted: {d}",
        f"tended: {d}",
        "work_type: record",
        "---",
        "",
        f"# Compaction proposal — {manifest['target']}",
        "",
        "> [!warning] PROPOSAL ONLY — the original page is untouched",
        "> Drafted by `scripts/wiki_compact_proposal.py` "
        "(Marathon R3 TA5; ReMe pattern). Applying anything "
        "here is a separate, human, recorded act.",
        "",
        f"Original: {o['lines']} lines / {o['chars']} chars · "
        f"sha256 `{o['sha256']}`",
        f"Draft: {dr['lines']} lines / {dr['chars']} chars",
        "",
        "## Restore path",
        "",
        manifest["restore_path"],
        "",
        "## Draft compaction",
        "",
        manifest["draft_text"],
    ])


def write_proposal(root: Path, manifest: dict) -> tuple[Path, Path]:
    stem = Path(manifest["target"]).stem
    base = Path(root) / "wiki" / "filings" / \
        f"compact-{stem}-{manifest['date']}"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_artefact(manifest), encoding="utf-8")
    stored = {k: v for k, v in manifest.items() if k != "draft_text"}
    json_path.write_text(json.dumps(stored, indent=2, sort_keys=True)
                         + "\n", encoding="utf-8")
    return md_path, json_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("page", help="repo-relative path of the page")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None)
    ap.add_argument("--min-lines", type=int, default=DEFAULT_MIN_LINES)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the manifest JSON; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    today = date.fromisoformat(args.date) if args.date else date.today()
    try:
        manifest = build_proposal(root, args.page, today=today,
                                  min_lines=args.min_lines,
                                  force=args.force)
    except ValueError as exc:
        print(f"compaction refused: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    md_path, json_path = write_proposal(root, manifest)
    o, dr = manifest["original"], manifest["draft"]
    print(f"compaction proposal: {args.page} {o['lines']} lines -> "
          f"draft {dr['lines']} lines (original untouched, "
          f"sha256 {o['sha256'][:12]}…)")
    print(f"artefact: {md_path.relative_to(root)}")
    print(f"manifest: {json_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
