#!/usr/bin/env python3
"""wiki_release_block.py — FAIR4RS release blocks for this
wiki's own software (build wave 6, item W6: FAIR4RS release
block + version-citation machinery).

A release block is the metadata record that makes a release
of the wiki's tooling Findable, Accessible, Interoperable
and Reusable in the FAIR-for-Research-Software sense: a
persistent-identifier slot, the version, the licence read
from the tree itself, a dependency manifest derived from
the code, provenance (the commit the release was cut
from), related identifiers as recorded, and a
version-citation entry that cites the specific version.

Licence route: clean re-implementation (idea only from the
Round 12 filing). The FAIR4RS principles themselves are a
published community standard — Barker et al., "Introducing
the FAIR Principles for research software", Scientific
Data 9, 622 (2022), CC-BY 4.0 — restated here in our own
words and code; no upstream text or code is taken.

OWNER SLOTS, BY DESIGN: this tool has no way to fill the
identifier or the credit fields. Minting a persistent
identifier (a DOI or equivalent) is the owner's act, and
the authorship / preferred-citation contents are the
owner's parked decision (build list, wave 6 guardrail).
The generator emits those slots EMPTY and labelled; the
checker accepts a filled value only when the block marks
it filled-by the owner, and fails by name
(identifier-invented / credit-invented) on any value that
appears without that mark. A block is a DRAFT: it is
labelled "draft release block" on its face, and cutting
or publishing a release is the owner's act, never this
tool's.

LICENCE HONESTY: the licence field is DERIVED, never
asserted — the generator looks for a licence file inside
the release scope and at the tree root and records what it
finds (path + sha256 + the name the file itself carries).
This private tree currently carries NO project licence
file (only font licences under tools/lens/assets/fonts/,
which are not the project's licence); a block generated
for a scope in this tree therefore records
"none-recorded" — an absence stated, not a licence
invented. The checker recomputes the lookup and fails on
any drift between the block and the tree.

DETERMINISM: same scope + version + date + tree state →
byte-identical block. Dates and versions are caller
inputs; the provenance commit is read from git HEAD
unless --commit pins it; no wall clock is read anywhere.

Usage:
  python3 scripts/wiki_release_block.py build
      --title T --version V --date YYYY-MM-DD
      --scope path[,path...] [--commit SHA]
      [--out-dir DIR] [--root DIR]
  python3 scripts/wiki_release_block.py check
      BLOCK.json [--root DIR]

Exit codes: 0 done / check clean · 1 check findings ·
2 usage error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOOL = "scripts/wiki_release_block.py"
DRAFT_STATUS = ("draft release block — not a release; "
                "cutting a release is the owner's act")
IDENTIFIER_NOTE = ("unfilled — no persistent identifier "
                   "has been minted; minting one (a DOI or "
                   "equivalent) is the owner's act")
CREDIT_NOTE = ("awaiting owner — the authorship and "
               "preferred-citation contents are the "
               "owner's decision and ship empty")

CONTEXT = {
    "schema": "https://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "codemeta": "https://codemeta.github.io/terms/",
}

LICENCE_NAMES = ("LICENSE", "LICENCE", "COPYING",
                 "LICENSE.md", "LICENCE.md", "COPYING.md",
                 "LICENSE.txt", "LICENCE.txt", "COPYING.txt")
# A licence file for a scope is one inside the scope or at
# the tree root. Font/component licences deeper in the
# tree are NOT the project's licence and are never picked
# up: the lookup only looks in these two places.

_VERSION_JSON_FILES = ("server.json", "manifest.json")
_SIBLING_RE = re.compile(r"scripts/([A-Za-z0-9_\-]+\.py)")


# -- derivation helpers ------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scope_files(root: Path, scope: list[str]) -> list[Path]:
    """Expand scope entries (files or directories) to a
    sorted file list. Directories walk recursively,
    skipping __pycache__. Missing entries are returned in
    the second element so callers can name them."""
    files, missing = [], []
    for entry in scope:
        p = root / entry
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file() and "__pycache__" not in \
                        sub.parts:
                    files.append(sub)
        else:
            missing.append(entry)
    files.sort(key=lambda f: f.relative_to(root).as_posix())
    return files, missing


def find_licence(root: Path, scope: list[str]) -> dict:
    """The licence lookup: a licence file inside a scope
    directory (or a scope file's directory), else at the
    tree root, else none. Returns the derived record."""
    candidates = []
    for entry in scope:
        p = root / entry
        d = p if p.is_dir() else p.parent
        candidates.append(d)
    candidates.append(root)
    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        for name in LICENCE_NAMES:
            f = d / name
            if f.is_file():
                text = f.read_text(encoding="utf-8",
                                   errors="replace")
                first = next(
                    (ln.strip() for ln in
                     text.splitlines() if ln.strip()), "")
                spdx = None
                low = text[:4000].lower()
                if "mit license" in low:
                    spdx = "MIT"
                elif "apache license" in low and \
                        "version 2.0" in low:
                    spdx = "Apache-2.0"
                elif "gnu general public license" in low:
                    spdx = "GPL (version per file text)"
                return {
                    "status": "recorded",
                    "file": f.relative_to(root).as_posix(),
                    "sha256": _sha256(f),
                    "name_as_carried": first,
                    "spdx": spdx,
                }
    return {
        "status": "none-recorded",
        "file": None,
        "sha256": None,
        "name_as_carried": None,
        "spdx": None,
        "note": "no licence file exists in the release "
                "scope or at the tree root; no licence is "
                "asserted for this release",
    }


def version_markers(root: Path, files: list[Path]) -> list:
    """Version markers the scope itself carries: a
    "version" key in server.json / manifest.json, a
    frontmatter version: in SKILL.md / *.md, or a
    __version__ assignment in a .py file."""
    out = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        try:
            text = f.read_text(encoding="utf-8",
                               errors="replace")
        except OSError:
            continue
        if f.name in _VERSION_JSON_FILES:
            try:
                doc = json.loads(text)
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("version"):
                out.append({"file": rel,
                            "version": str(doc["version"]),
                            "via": f"{f.name} \"version\""})
        elif f.suffix == ".py":
            m = re.search(
                r"^__version__\s*=\s*[\"']([^\"']+)[\"']",
                text, re.M)
            if m:
                out.append({"file": rel,
                            "version": m.group(1),
                            "via": "__version__"})
        elif f.suffix == ".md":
            head = text[:2000]
            if head.startswith("---"):
                m = re.search(r"^version:\s*(\S+)\s*$",
                              head, re.M)
                if m:
                    out.append({"file": rel,
                                "version": m.group(1),
                                "via": "frontmatter version"})
    return out


def dependencies(root: Path, files: list[Path]) -> list:
    """The dependency manifest, derived from the code:
    every import root in the scope's Python files,
    classified stdlib vs external by the interpreter's
    own stdlib table, plus the sibling tools a file
    delegates to at runtime (scripts/*.py paths named in
    its text — delegation is a real dependency even when
    it is not an import)."""
    stdlib = sys.stdlib_module_names
    in_scope = {f.stem for f in files if f.suffix == ".py"}
    imports, siblings = set(), set()
    for f in files:
        if f.suffix != ".py":
            continue
        text = f.read_text(encoding="utf-8",
                           errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        imports.add(a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        imports.add(
                            node.module.split(".")[0])
        for m in _SIBLING_RE.finditer(text):
            sib = "scripts/" + m.group(1)
            if sib != f.relative_to(root).as_posix():
                siblings.add(sib)
    out = []
    for name in sorted(imports):
        if name == "__future__":
            continue  # a compiler directive, not a package
        if name in in_scope:
            kind = "in-scope-module"
        elif name in stdlib:
            kind = "python-stdlib"
        else:
            kind = "python-external"
        out.append({"name": name, "kind": kind})
    for sib in sorted(siblings):
        out.append({"name": sib, "kind": "sibling-tool"})
    return out


def related_identifiers(root: Path, files: list[Path]) -> list:
    """Repo locations AS RECORDED in the scope's own
    files (e.g. a server.json "repository" block). Each
    entry names the file it was read from — the claim's
    provenance travels with it."""
    out = []
    for f in files:
        if f.name not in _VERSION_JSON_FILES:
            continue
        try:
            doc = json.loads(f.read_text(
                encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        repo = doc.get("repository") if isinstance(
            doc, dict) else None
        if isinstance(repo, dict) and repo.get("url"):
            out.append({
                "relation": "isPartOf / codeRepository as "
                            "recorded",
                "url": repo["url"],
                "as_recorded_in":
                    f.relative_to(root).as_posix(),
            })
        elif isinstance(repo, str) and repo:
            out.append({
                "relation": "codeRepository as recorded",
                "url": repo,
                "as_recorded_in":
                    f.relative_to(root).as_posix(),
            })
    return out


def git_head(root: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


# -- the block ---------------------------------------------------------------

def build_block(root: Path, title: str, version: str,
                date: str, scope: list[str],
                commit: str | None) -> dict:
    files, missing = scope_files(root, scope)
    if missing:
        raise ValueError(
            "scope paths do not exist: "
            + ", ".join(missing))
    manifest = [{
        "path": f.relative_to(root).as_posix(),
        "bytes": f.stat().st_size,
        "sha256": _sha256(f),
    } for f in files]
    deps = dependencies(root, files)
    external = [d["name"] for d in deps
                if d["kind"] == "python-external"]
    block = {
        "@context": CONTEXT,
        "@type": "schema:SoftwareSourceCode",
        "kind": "fair4rs-release-block",
        "status": DRAFT_STATUS,
        "name": title,
        "version": version,
        "datePublished": date,
        "identifier": {"value": None,
                       "status": "unfilled",
                       "note": IDENTIFIER_NOTE},
        "license": find_licence(root, scope),
        "author": {"value": None,
                   "status": "awaiting-owner",
                   "note": CREDIT_NOTE},
        "credit": {"value": None,
                   "status": "awaiting-owner",
                   "note": CREDIT_NOTE},
        "citation": {
            "citesVersion": version,
            "identifier": "unfilled",
            "text": _citation_text(title, version, date),
        },
        "dependencies": deps,
        "runtime": {
            "interpreter": "python3",
            "externalPackages": external,
            "statement": (
                "Python 3 standard library only"
                if not external else
                "external packages: " + ", ".join(external)),
        },
        "codeRepository": related_identifiers(root, files),
        "versionMarkers": version_markers(root, files),
        "provenance": {
            "wasDerivedFrom": "the wiki tree at the "
                              "commit below",
            "commit": commit,
            "generatedBy": TOOL,
            "scope": manifest,
        },
        "fair4rs": {
            "F": "this block is the findable metadata "
                 "record; its persistent-identifier slot "
                 "stands unfilled, awaiting the owner",
            "A": "the scope's repository locations, as "
                 "recorded in the scope's own files, are "
                 "listed under codeRepository",
            "I": "schema.org / CodeMeta terms as JSON-LD; "
                 "dependencies and provenance in stated "
                 "vocabularies",
            "R": "licence as recorded from the tree "
                 "itself; provenance pins the commit and "
                 "every file hash",
        },
    }
    return block


def _citation_text(title: str, version: str,
                   date: str) -> str:
    """The version-citation entry: it cites the SPECIFIC
    version, and states its own gaps on its face."""
    return (f"{title}, version {version} ({date}). "
            f"Authors: awaiting owner. "
            f"Persistent identifier: unfilled.")


def render_md(block: dict) -> str:
    lic = block["license"]
    if lic["status"] == "recorded":
        lic_line = (f"{lic['name_as_carried']} "
                    f"(`{lic['file']}`, sha256 "
                    f"{lic['sha256'][:12]}…)")
    else:
        lic_line = ("none recorded — " + lic["note"])
    lines = [
        f"# Release block — {block['name']} "
        f"{block['version']}",
        "",
        f"> **{block['status']}**",
        "",
        f"- **Version:** {block['version']}",
        f"- **Date (as supplied):** "
        f"{block['datePublished']}",
        f"- **Persistent identifier:** unfilled — "
        f"{IDENTIFIER_NOTE}",
        f"- **Licence (as recorded from the tree):** "
        f"{lic_line}",
        f"- **Authors / credit:** awaiting owner",
        f"- **Provenance commit:** "
        f"`{block['provenance']['commit']}`",
        f"- **Runtime:** {block['runtime']['statement']}",
        "",
        "## Cite this version",
        "",
        f"> {block['citation']['text']}",
        "",
        "## Dependencies",
        "",
    ]
    if block["dependencies"]:
        for d in block["dependencies"]:
            lines.append(f"- `{d['name']}` ({d['kind']})")
    else:
        lines.append("- none (no Python files in scope)")
    lines += ["", "## Files in scope", "",
              "| path | bytes | sha256 |",
              "|---|---|---|"]
    for m in block["provenance"]["scope"]:
        lines.append(f"| `{m['path']}` | {m['bytes']} | "
                     f"`{m['sha256'][:16]}…` |")
    lines += ["", "## Open slots (the owner's)", "",
              f"- persistent identifier: "
              f"{IDENTIFIER_NOTE}",
              f"- authorship / preferred citation: "
              f"{CREDIT_NOTE}"]
    if lic["status"] != "recorded":
        lines.append("- licence: no licence file stands "
                     "in the scope or at the tree root; "
                     "adding one is the owner's act")
    lines.append("")
    return "\n".join(lines)


# -- the checker -------------------------------------------------------------

def check_block(root: Path, block: dict) -> list[str]:
    """Verify a block against the tree it describes.
    Returns a list of named findings ([] = clean)."""
    findings = []
    if block.get("status") != DRAFT_STATUS:
        findings.append(
            "status-not-draft: a release block must "
            "carry the draft label; cutting a release is "
            "the owner's act, not this tool's")
    prov = block.get("provenance") or {}
    scope_paths = []
    for m in prov.get("scope") or []:
        scope_paths.append(m["path"])
        p = root / m["path"]
        if not p.is_file():
            findings.append(f"scope-path-missing:{m['path']}")
            continue
        if _sha256(p) != m["sha256"]:
            findings.append(f"scope-hash-drift:{m['path']}")
        if p.stat().st_size != m["bytes"]:
            findings.append(f"scope-size-drift:{m['path']}")
    # Licence: recompute the lookup over the same ground
    # (the scope's directories + root) and compare.
    entries = sorted({str(Path(p).parent) for p in
                      scope_paths})
    derived = find_licence(root, entries)
    lic = block.get("license") or {}
    if lic.get("status") != derived["status"] or \
            lic.get("file") != derived["file"] or \
            lic.get("sha256") != derived["sha256"]:
        findings.append(
            "licence-mismatch: the block records "
            f"{lic.get('status')}:{lic.get('file')} but "
            f"the tree gives {derived['status']}:"
            f"{derived['file']}")
    # Version markers the scope itself carries.
    files, _ = scope_files(root, scope_paths)
    for mk in version_markers(root, files):
        if mk["version"] != block.get("version"):
            findings.append(
                f"version-marker-mismatch:{mk['file']}:"
                f"{mk['version']}!={block.get('version')}")
    # Provenance commit must resolve in git.
    commit = prov.get("commit")
    if not commit:
        findings.append("provenance-commit-missing")
    else:
        try:
            r = subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e",
                 f"{commit}^{{commit}}"],
                capture_output=True, timeout=30)
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if not ok:
            findings.append(
                f"provenance-commit-unresolvable:{commit}")
    # Owner slots: a value is acceptable only marked as
    # filled by the owner.
    ident = block.get("identifier") or {}
    if ident.get("value") and \
            ident.get("filled_by") != "owner":
        findings.append(
            "identifier-invented: an identifier value is "
            "present without filled_by: owner — minting "
            "an identifier is the owner's act")
    for slot in ("author", "credit"):
        s = block.get(slot) or {}
        if s.get("value") and \
                s.get("filled_by") != "owner":
            findings.append(
                f"credit-invented:{slot}: a credit value "
                "is present without filled_by: owner — "
                "the credit contents are the owner's "
                "decision")
    cit = block.get("citation") or {}
    if block.get("version") and \
            block["version"] not in cit.get("text", ""):
        findings.append(
            "citation-version-missing: the citation entry "
            "does not cite the block's version")
    return findings


# -- CLI ---------------------------------------------------------------------

def _dump(doc) -> str:
    return json.dumps(doc, ensure_ascii=False,
                      sort_keys=True, indent=1) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="FAIR4RS release blocks: build / "
                    "check")
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("build")
    pb.add_argument("--title", required=True)
    pb.add_argument("--version", required=True)
    pb.add_argument("--date", required=True)
    pb.add_argument("--scope", required=True,
                    help="comma-separated paths (files or "
                         "directories), tree-relative")
    pb.add_argument("--commit")
    pb.add_argument("--out-dir", type=Path)
    pc = sub.add_parser("check")
    pc.add_argument("block")
    args = ap.parse_args(argv)
    root = args.root

    if args.cmd == "build":
        scope = [s.strip() for s in
                 args.scope.split(",") if s.strip()]
        commit = args.commit or git_head(root)
        if not commit:
            print("no provenance commit: pass --commit or "
                  "run inside the git tree", file=sys.stderr)
            return 2
        try:
            block = build_block(root, args.title,
                                args.version, args.date,
                                scope, commit)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        markers = block["versionMarkers"]
        clash = [m for m in markers
                 if m["version"] != args.version]
        for m in clash:
            print(f"warning: {m['file']} carries version "
                  f"{m['version']} ({m['via']}) — the "
                  f"block's {args.version} will fail "
                  f"check", file=sys.stderr)
        out_dir = args.out_dir or root
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "release-block.json").write_text(
            _dump(block), encoding="utf-8")
        (out_dir / "release-block.md").write_text(
            render_md(block), encoding="utf-8")
        print(f"built: {out_dir / 'release-block.json'} "
              f"({len(block['provenance']['scope'])} "
              f"files, licence "
              f"{block['license']['status']}, identifier "
              f"unfilled, credit awaiting owner)")
        return 0
    if args.cmd == "check":
        block = json.loads(Path(args.block).read_text(
            encoding="utf-8"))
        findings = check_block(root, block)
        if findings:
            for f in findings:
                print(f"FINDING {f}")
            return 1
        print("check: clean — the block matches the tree "
              "it describes")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
