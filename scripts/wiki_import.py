#!/usr/bin/env python3
"""wiki_import.py — import an external markdown vault.

15-gap item 10's arrival lane (the pair of wiki_export.py's
departure lane): an Obsidian/Logseq-style folder of .md files
is brought into this wiki as PRESERVATION + STUBS, honestly
labelled — nothing is compiled, summarised or claimed.

    python3 scripts/wiki_import.py [--root DIR] import <dir> \\
        [--apply] [--date YYYY-MM-DD]
    (the `import` verb may be omitted: `wiki_import.py <dir>`)

DRY-RUN by default: the plan is printed and NOTHING is
written — no raw file, no stub, not even a directory.

With --apply, for each .md file under <dir> (recursive,
sorted; non-markdown files are ignored and counted):

  * the file's bytes are preserved VERBATIM at
        raw/sources/imported-<YYYY-MM-DD>/<relative-path>
    under the vault-relative path, exactly as found — the
    raw layer's rule (AGENTS.md) applies from this moment:
    immutable, never edited. An existing destination is
    NEVER overwritten: the file is reported as a COLLISION
    and skipped (raw file and stub alike), which is what
    makes a second run of the same import a clean no-op
    of skips;
  * a stub source page is written at
        wiki/sources/imported-<slug>.md
    (<slug> = the vault-relative path without .md, flattened
    and slugified; same-stub collisions between vault files
    are disambiguated -2, -3, ... in sorted order) with the
    wiki's source-page frontmatter (title / type: source /
    created / updated / sources pointing at the preserved
    raw file / tags incl. `imported`). Its body records the
    original path, the import date, and the honest state of
    the material: preserved raw, pending compile.

Nothing else happens: wiki/index.md and wiki/log.md are not
touched, no entity or concept pages are created, and no claim
about the imported content is made anywhere — compiling an
imported file is a later, deliberate ingest under AGENTS.md.

A stub's title is the source file's own frontmatter title or
first H1 when it carries one, else its filename stem — read
from the file, never invented. --date pins the import date
(default: today) for the destination folder, the stubs'
created/updated and the recorded import date alike.

Exit codes: 0 ok (skips included) · 2 usage error (no such
vault directory, bad --date).

Stdlib only, offline.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WV = _load_module("wiki_validate", SCRIPTS / "wiki_validate.py")
parse_frontmatter = _WV.parse_frontmatter
parse_date = _WV.parse_date

PENDING_LINE = ("preserved raw, pending compile — no part of it has "
                "been compiled into this wiki yet, and no claim on "
                "this page rests on it")


# -------------------------------------------------------------- planning

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unnamed"


def vault_files(vault: Path):
    """(markdown files, ignored count): every .md file under
    the vault, sorted by vault-relative posix path — the file
    list is snapshotted before any write, so an --apply run
    can never re-ingest its own output."""
    md_files = []
    ignored = 0
    for p in sorted(vault.rglob("*")):
        if not p.is_file() or ".git" in p.parts:
            continue
        if p.suffix.lower() == ".md":
            md_files.append(p)
        else:
            ignored += 1
    md_files.sort(key=lambda p: p.relative_to(vault).as_posix())
    return md_files, ignored


def file_title(path: Path, rel: Path) -> str:
    """The file's own title: its frontmatter title, else its
    first H1, else its filename stem."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return rel.stem
    fields, body = parse_frontmatter(text)
    if fields and str(fields.get("title") or "").strip():
        return str(fields["title"]).strip()
    for line in body.splitlines():
        m = re.match(r"^#\s+(.*)$", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return rel.stem


def plan_import(root: Path, vault: Path, date_s: str):
    """The full plan, computed against the current disk state
    (identical for dry-run and --apply): one entry per vault
    markdown file with its raw destination, its stub path,
    and its collision state. Pure: writes nothing."""
    dest_dir_rel = "raw/sources/imported-%s" % date_s
    md_files, ignored = vault_files(vault)
    entries = []
    taken_slugs = set()
    for src in md_files:
        rel = src.relative_to(vault)
        rel_posix = rel.as_posix()
        raw_rel = "%s/%s" % (dest_dir_rel, rel_posix)
        base_slug = slugify(rel.with_suffix("").as_posix())
        slug, n = base_slug, 2
        while slug in taken_slugs:
            slug = "%s-%d" % (base_slug, n)
            n += 1
        taken_slugs.add(slug)
        stub_rel = "wiki/sources/imported-%s.md" % slug
        collisions = []
        if (root / raw_rel).exists():
            collisions.append("raw destination already exists: "
                              + raw_rel)
        if (root / stub_rel).exists():
            collisions.append("stub already exists: " + stub_rel)
        entries.append({
            "source": src, "rel": rel_posix, "raw_rel": raw_rel,
            "stub_rel": stub_rel, "slug": slug,
            "title": file_title(src, rel),
            "collisions": collisions,
        })
    return {"dest_dir_rel": dest_dir_rel, "entries": entries,
            "ignored": ignored}


# ---------------------------------------------------------------- stubs

def stub_text(entry, vault_arg: str, date_s: str) -> str:
    raw_rel = entry["raw_rel"]
    original_rel = entry["rel"]
    original_full = (Path(vault_arg) / original_rel).as_posix()
    title = entry["title"]
    frontmatter = "\n".join([
        "---",
        "title: " + json.dumps(title, ensure_ascii=False),
        "type: source",
        "created: " + date_s,
        "updated: " + date_s,
        "sources:",
        "  - " + raw_rel,
        "tags: [imported]",
        "---",
    ])
    body = "\n".join([
        "",
        "# " + title,
        "",
        "Imported on %s from `%s`." % (date_s, original_full),
        "",
        "- Original path (as given): `%s`" % original_full,
        "- Original path (relative to the imported vault): `%s`"
        % original_rel,
        "- Preserved verbatim at: `%s`" % raw_rel,
        "- Import tool: `scripts/wiki_import.py`",
        "",
        "State: this material is " + PENDING_LINE + ". The stub "
        "exists so the preserved file is accounted for by the "
        "wiki layer; compiling it is a separate, deliberate "
        "ingest.",
        "",
    ])
    return frontmatter + "\n" + body


# ---------------------------------------------------------------- apply

def run_import(root: Path, vault: Path, vault_arg: str,
               date_s: str, apply: bool) -> int:
    plan = plan_import(root, vault, date_s)
    entries = plan["entries"]
    mode = "APPLY" if apply else "DRY RUN — nothing written"
    print("== Vault import (%s) ==" % mode)
    print("vault: %s" % vault_arg)
    print("into: %s (raw under %s/, stubs under wiki/sources/)"
          % (root, plan["dest_dir_rel"]))
    print("import date: %s" % date_s)
    n_ok = n_skip = 0
    for entry in entries:
        if entry["collisions"]:
            n_skip += 1
            print("  SKIP (collision) %s — %s"
                  % (entry["rel"], "; ".join(entry["collisions"])))
            continue
        n_ok += 1
        verb = "import" if apply else "would import"
        print("  %s %s -> %s + stub %s"
              % (verb, entry["rel"], entry["raw_rel"],
                 entry["stub_rel"]))
        if apply:
            raw_dest = root / entry["raw_rel"]
            raw_dest.parent.mkdir(parents=True, exist_ok=True)
            # Bytes verbatim: a byte copy, never a text round-trip.
            shutil.copyfile(entry["source"], raw_dest)
            stub_dest = root / entry["stub_rel"]
            stub_dest.parent.mkdir(parents=True, exist_ok=True)
            stub_dest.write_text(
                stub_text(entry, vault_arg, date_s),
                encoding="utf-8")
    print("files: %d markdown (%d %s, %d skipped on collision); "
          "%d non-markdown ignored"
          % (len(entries), n_ok,
             "imported" if apply else "planned", n_skip,
             plan["ignored"]))
    if not apply:
        print("dry run: re-run with --apply to perform this import")
    return 0


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # The bare form `wiki_import.py <dir> ...` is accepted as
    # well as the canonical `wiki_import.py import <dir> ...`:
    # insert the verb when it is absent (the subparser also
    # carries --root/--date, so options after the directory
    # still parse).
    if "import" not in argv:
        argv.insert(0, "import")
    parser = argparse.ArgumentParser(
        description="Import an external markdown vault as "
                    "preservation + stub source pages (dry-run "
                    "by default; see module docstring).")
    parser.add_argument("--root", default=None,
                        help="repo root (default: this tool's repo); "
                             "may also be given after the verb")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import", help="plan or perform an import")
    p.add_argument("dir", help="the vault directory to import")
    p.add_argument("--apply", action="store_true",
                   help="perform the import (default: dry run, "
                        "writes nothing)")
    p.add_argument("--date", default=None,
                   help="import date YYYY-MM-DD (default: today)")
    p.add_argument("--root", dest="root_sub", default=None)
    args = parser.parse_args(argv)

    root_value = args.root_sub or args.root
    root = Path(root_value) if root_value else ROOT
    vault = Path(args.dir)
    if not vault.is_dir():
        print("wiki_import: %s is not a directory" % args.dir,
              file=sys.stderr)
        return 2
    date_s = args.date or date.today().isoformat()
    if parse_date(date_s) is None or len(date_s) != 10:
        print("wiki_import: bad --date %r (want YYYY-MM-DD)"
              % date_s, file=sys.stderr)
        return 2
    return run_import(root, vault, args.dir, date_s, args.apply)


if __name__ == "__main__":
    sys.exit(main())
