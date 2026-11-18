#!/usr/bin/env python3
"""CITATION.cff generator + validator (CFF 1.2.0 shape).

Marathon R9 lane BB (ideas board R7 research, Tier A): the
Zettlr-slice citation file for WikiCitadel. The generator
builds a Citation File Format 1.2.0 record from REPOSITORY
FACTS ONLY — project name (README title), repository URL
(README clone URL / git remote), licence (LICENSE file),
version and release date where the repo states them.

OWNER BOUNDARY (binding): the committed file's credit
contents — author names/form and preferred-citation text —
are the OWNER's decision. The generator therefore OMITS the
authors field and any preferred-citation block, and says so
on the generated file's companion note. CFF 1.2.0 REQUIRES
authors, so validate() reports the generated file as NOT
YET VALID — the honest state until the owner rules on the
credit contents. Nothing is invented to make it pass.

Commands:
  generate [--root DIR] [--out FILE]   emit the CFF text
  validate [--file PATH]               check a CFF file's
        shape; exit 0 valid, 1 findings, 2 usage error
The validator is a stdlib shape checker for the flat subset
this generator emits (top-level key: value lines) — it is
not a full YAML/CFF schema implementation, and says so.
Stdlib only, no network.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ALWAYS = ("cff-version", "message", "title", "type")
# Required by CFF 1.2.0 but owner-gated in this repository.
REQUIRED_OWNER_GATED = ("authors",)
NOTE_NAME = "CITATION.cff.OWNER-NOTE.md"


def repo_facts(root=None):
    root = Path(root) if root else ROOT
    facts = {"type": "software"}
    readme = root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            facts["title"] = m.group(1).strip()
        m = re.search(r"git clone\s+(\S+)", text)
        if m:
            facts["repository-code"] = m.group(1).strip()
            facts["url"] = m.group(1).strip()
        m = re.search(r"\bv1\b", text)
        if m and "WikiCitadel v1" in text:
            facts["version"] = "1.0.0"  # repo states "v1"
    lic = root / "LICENSE"
    if lic.is_file():
        head = lic.read_text(encoding="utf-8",
                             errors="ignore")[:200]
        if "MIT License" in head:
            facts["license"] = "MIT"
        elif "Apache License" in head:
            facts["license"] = "Apache-2.0"
    if "repository-code" not in facts:
        try:
            url = subprocess.run(
                ["git", "-C", str(root), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=10).stdout.strip()
            if url.startswith("git@github.com:"):
                url = "https://github.com/" + url.split(":", 1)[1]
                url = url[:-4] if url.endswith(".git") else url
            if url:
                facts["repository-code"] = url
                facts.setdefault("url", url)
        except Exception:
            pass
    try:
        date = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cs"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            facts["date-released"] = date
    except Exception:
        pass
    return facts


def generate_cff(root=None):
    f = repo_facts(root)
    lines = ["cff-version: 1.2.0",
             'message: "If you use this software, please cite it '
             'as below."']
    # authors deliberately omitted — owner decision (see module
    # docstring); validate() reports this as the open finding.
    for key in ("title", "type", "version", "date-released",
                "url", "repository-code", "license"):
        if f.get(key):
            lines.append(f"{key}: {f[key]}")
    return "\n".join(lines) + "\n"


def owner_note():
    return ("# CITATION.cff — owner note\n\n"
            "The generated `CITATION.cff` carries only facts "
            "already public in this repository (project name, "
            "repository URL, licence, version/date as stated). "
            "It OMITS the `authors` field and any "
            "`preferred-citation` text: the credit contents of "
            "the citation file are the OWNER's decision and "
            "await the owner's ruling. CFF 1.2.0 requires "
            "`authors`, so `scripts/wiki_cff.py validate` "
            "reports the file as not yet valid until the owner "
            "supplies the credit contents. No author names were "
            "invented to make it pass.\n")


def parse_cff(text):
    """Flat top-level keys of the emitted subset."""
    keys = {}
    for line in text.splitlines():
        m = re.match(r"^([a-z][a-z0-9-]*):\s*(.*)$", line)
        if m:
            keys[m.group(1)] = m.group(2).strip().strip('"')
    return keys


def validate_cff(text):
    keys = parse_cff(text)
    findings = []
    for key in REQUIRED_ALWAYS:
        if not keys.get(key):
            findings.append(f"missing required field: {key}")
    if keys.get("cff-version") not in (None, "1.2.0"):
        findings.append(
            f"cff-version is {keys.get('cff-version')!r}, not 1.2.0")
    for key in REQUIRED_OWNER_GATED:
        if key not in keys:  # value may be a YAML list below
            findings.append(
                f"missing required field: {key} — OWNER-GATED: "
                f"credit contents await the owner's ruling; "
                f"not invented by the generator")
    return {"keys": sorted(keys), "findings": findings,
            "valid": not findings}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate / validate a CITATION.cff (CFF 1.2.0).")
    ap.add_argument("command", choices=("generate", "validate"))
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--file", default=None)
    args = ap.parse_args(argv)
    if args.command == "generate":
        text = generate_cff(args.root)
        if args.out:
            out = Path(args.out)
            out.write_text(text, encoding="utf-8")
            (out.parent / NOTE_NAME).write_text(
                owner_note(), encoding="utf-8")
            print(f"wiki_cff: wrote {out} + {NOTE_NAME} "
                  f"(authors omitted — owner-gated)")
        else:
            sys.stdout.write(text)
        return 0
    path = Path(args.file) if args.file else (
        Path(args.root) / "CITATION.cff" if args.root
        else ROOT / "CITATION.cff")
    if not path.is_file():
        print(f"wiki_cff: no such file: {path}", file=sys.stderr)
        return 2
    rep = validate_cff(path.read_text(encoding="utf-8"))
    for f in rep["findings"]:
        print(f"  FINDING: {f}")
    print(f"wiki_cff: {'VALID' if rep['valid'] else 'NOT VALID'} "
          f"({len(rep['keys'])} top-level keys: "
          f"{', '.join(rep['keys'])})")
    return 0 if rep["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
