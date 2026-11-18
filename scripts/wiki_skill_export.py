#!/usr/bin/env python3
"""wiki_skill_export.py — the Skill Factory export.

Pattern: VectifyAI/OpenKB (Apache-2.0)
compiles a knowledge base into portable agent SKILL packages.
This tool distils the wiki into a versioned, self-contained
skill package under exports/skill-v<N>/ — OUTSIDE the wiki page
layer, so an export can never be mistaken for a page:

  SKILL.md      orientation: what this wiki is (from
                wiki/overview.md), the operating rules that keep
                it trustworthy, and a complete index of the
                compiled pages with one-line ledes;
  pages/        the compiled wiki layer itself (content pages
                only — no raw/, no access ledgers, no log/index
                machinery beyond overview);
  manifest.json name, version, build date, the git commit the
                export was distilled from, and a SHA-256 of every
                shipped file.

Versions are append-only: exports/skill-v1/, skill-v2/, ... each
run mints the next integer version unless --version N rebuilds
that version in place. An export is a snapshot: it never syncs
back (the two-engine rule that governs every copy of this wiki).

    python3 scripts/wiki_skill_export.py [--version N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORTS = ROOT / "exports"
EXCLUDED_PARTS = {"access", "talk"}
STRUCTURAL = {"index", "log"}

RULES = """## Operating rules (distilled from AGENTS.md)

- raw/ is the immutable evidence layer; the wiki layer is the
  compiled knowledge built on it. Cite sources; never invent.
- Status is lifecycle (draft/verified/published/archived);
  confidence is evidence strength (observed/inferred/low/medium/
  high). `confidence: high` is reserved for claims the Owner has
  personally verified — no agent awards it.
- Contradictions between sources are preserved and flagged on
  talk pages (wiki/talk/), never smoothed over.
- Writes to the canonical wiki go through the governed gateway
  (propose -> review -> separate owner authorisation). This
  export is a read-only snapshot: nothing flows back from it.
"""


def content_pages(root: Path):
    wiki = root / "wiki"
    out = []
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        parts = set(Path(rel).parts[1:-1])
        if parts & EXCLUDED_PARTS:
            continue
        if p.stem in STRUCTURAL and p.parent == wiki:
            continue
        out.append((rel, p))
    return out


def parse_fm(text: str):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
            if mm:
                fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, (text[m.end():] if m else text)


def lede(body: str) -> str:
    for para in re.split(r"\n\s*\n", body):
        t = " ".join(para.split())
        if t and not t.startswith("#") and not t.startswith("---"):
            return t[:220]
    return ""


def existing_versions(exports_dir: Path) -> list[int]:
    versions = []
    if exports_dir.is_dir():
        for d in exports_dir.glob("skill-v*"):
            m = re.fullmatch(r"skill-v(\d+)", d.name)
            if m:
                versions.append(int(m.group(1)))
    return versions


def build_export(root: Path = ROOT, version: int | None = None) -> Path:
    exports_dir = root / "exports"
    if version is None:
        vs = existing_versions(exports_dir)
        version = (max(vs) + 1) if vs else 1
    out = exports_dir / f"skill-v{version}"
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except subprocess.CalledProcessError:
        head = "unknown"

    pages = content_pages(root)
    overview_text = ""
    index_lines = []
    shipped = {}
    for rel, p in pages:
        text = p.read_text(encoding="utf-8", errors="ignore")
        fm, body = parse_fm(text)
        dest = pages_dir / Path(rel).relative_to("wiki")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        shipped[f"pages/{dest.relative_to(pages_dir).as_posix()}"] = \
            hashlib.sha256(text.encode("utf-8")).hexdigest()
        if rel == "wiki/overview.md":
            overview_text = body.strip()
            continue
        title = fm.get("title") or p.stem
        index_lines.append(
            f"- **{title}** ({fm.get('type') or 'page'}) — "
            f"`{dest.relative_to(out).as_posix()}` — {lede(body)}")

    purpose = ""
    purpose_path = root / "purpose.md"
    if purpose_path.is_file():
        purpose = purpose_path.read_text(encoding="utf-8",
                                          errors="ignore").strip()

    skill = "\n".join([
        "---",
        "name: wikicitadel",
        f"version: {version}",
        'description: "A private LLM Wiki, distilled: the '
        'compiled knowledge layer of a personal knowledge base — '
        'sources, entities, concepts, syntheses and decisions, '
        'each cited to an immutable raw layer."',
        "---",
        "",
        "# LLM Wiki — distilled skill export",
        "",
        f"Export version {version}, built {date.today()} from wiki "
        f"commit `{head}`. This package is a read-only snapshot of "
        "the compiled layer; the canonical wiki lives elsewhere and "
        "nothing in this package syncs back to it.",
        "",
        "## Purpose",
        "",
        purpose or "(purpose.md not present at export time)",
        "",
        "## What this wiki is",
        "",
        overview_text or "(wiki/overview.md not present)",
        "",
        RULES,
        "## Page index",
        "",
        *index_lines,
        "",
    ])
    (out / "SKILL.md").write_text(skill, encoding="utf-8")
    shipped["SKILL.md"] = hashlib.sha256(skill.encode("utf-8")).hexdigest()

    manifest = {
        "name": "llm-wiki",
        "version": version,
        "built": str(date.today()),
        "source_commit": head,
        "page_count": len(pages),
        "files": dict(sorted(shipped.items())),
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", type=int, default=None,
                    help="rebuild this version in place (default: "
                         "mint the next version)")
    args = ap.parse_args(argv)
    out = build_export(ROOT, args.version)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    print(f"exported {out.relative_to(ROOT)}: version {m['version']}, "
          f"{m['page_count']} pages, from commit {m['source_commit'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
