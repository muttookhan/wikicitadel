#!/usr/bin/env python3
"""wiki_schema.py — versioned-schema tooling for the wiki profile.

WikiCitadel v1 (pattern: pyrite-wiki/pyrite, MIT —
versioned field schemas with grandfathering, migrations emitted
as a reviewable git diff).

Subcommands:
  show                print the profile's schema version and its
                      versioned (since_version) fields.
  migrate --dry-run   print, as unified diffs, exactly what would
                      change to bring every legacy page up to the
                      profile's current schema version: declare
                      `_schema_version` and add the since-versioned
                      required fields (with the state machine's
                      entry state as the default for `status`).

The migrate command NEVER applies anything — there is no apply
mode. A human reviews the diff, and any real migration goes
through the gateway like every other write. Running without
--dry-run refuses, so the tool cannot be fired by accident.

    python3 scripts/wiki_schema.py migrate --dry-run
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "tools" / "gateway" / "profiles" / "wiki-default.json"
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}
EXCLUDED_DIRS = {"access", "talk"}
FIELD_DEFAULTS = {"status": "draft"}  # the state machine's entry state


def _load_profile_mod():
    spec = importlib.util.spec_from_file_location(
        "gw_profile", ROOT / "tools" / "gateway" / "gateway" / "profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_profile(path: Path = PROFILE_PATH):
    mod = _load_profile_mod()
    return mod.load_profile(path), mod


def versioned_fields(profile: dict, mod) -> list[tuple[str, str, int]]:
    """(page_type, field, since_version) for every versioned field."""
    out = []
    for ptype, spec in (profile.get("page_types") or {}).items():
        for fname, since in mod._field_specs(spec.get("required_fields")):
            if since is not None:
                out.append((ptype, fname, since))
    return out


def migrated_text(text: str, profile: dict, mod) -> str | None:
    """The page text as the current schema would have it, or None
    when the page is already current (or has no frontmatter)."""
    fields = mod.frontmatter_of(text)
    if fields is None:
        return None
    target = int(profile.get("schema_version") or 1)
    pver = mod.page_schema_version(fields)
    if pver >= target:
        return None
    ptype = fields.get("type")
    additions = []
    for t, fname, since in versioned_fields(profile, mod):
        if t != ptype or since > target:
            continue
        v = fields.get(fname)
        if v is None or v == "":
            default = FIELD_DEFAULTS.get(fname)
            if default is not None:
                additions.append(f"{fname}: {default}")
            else:
                additions.append(f"{fname}: \"\"  # TODO: required since "
                                   f"schema v{since} — fill in")
    m = re.match(r"^(---\n)(.*?)(\n---\n?)", text, re.S)
    if not m:
        return None
    fm_lines = m.group(2).splitlines()
    new_lines = []
    inserted_version = False
    for line in fm_lines:
        new_lines.append(line)
        if line.startswith("type:") and not inserted_version:
            new_lines.append(f"_schema_version: {target}")
            inserted_version = True
    if not inserted_version:
        new_lines.insert(0, f"_schema_version: {target}")
    new_lines.extend(additions)
    return m.group(1) + "\n".join(new_lines) + m.group(3) \
        + text[m.end():]


def iter_content_pages(root: Path):
    wiki = root / "wiki"
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in STRUCTURAL:
            continue
        if any(part in EXCLUDED_DIRS for part in Path(rel).parts[1:-1]):
            continue
        yield rel, p


def migrate_dry_run(root: Path = ROOT, profile: dict | None = None,
                    mod=None) -> tuple[int, list[str]]:
    """-> (pages_that_would_change, [diff_text, ...]). Pure: reads
    only, never writes."""
    if profile is None or mod is None:
        profile, mod = load_profile()
    diffs = []
    for rel, p in iter_content_pages(root):
        text = p.read_text(encoding="utf-8", errors="ignore")
        new = migrated_text(text, profile, mod)
        if new is None or new == text:
            continue
        diff = difflib.unified_diff(
            text.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}")
        diffs.append("".join(diff))
    return len(diffs), diffs


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    mg = sub.add_parser("migrate")
    mg.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    profile, mod = load_profile()
    if profile is None:
        print("profile missing or malformed", file=sys.stderr)
        return 2
    if args.cmd == "show":
        print(f"profile {profile.get('name')}: schema_version "
              f"{profile.get('schema_version')}, mode {profile.get('mode')}")
        for ptype, fname, since in versioned_fields(profile, mod):
            print(f"  {ptype}.{fname} — required since v{since}")
        return 0
    if args.cmd == "migrate":
        if not args.dry_run:
            print("refused: migrate is dry-run only. This tool never "
                  "applies changes; review the diff, then migrate "
                  "through the gateway.", file=sys.stderr)
            return 2
        n, diffs = migrate_dry_run()
        for d in diffs:
            print(d)
        print(f"# migrate --dry-run: {n} page(s) would change; "
              "nothing was written.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
