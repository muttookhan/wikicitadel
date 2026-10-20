#!/usr/bin/env python3
"""OKF bundle audit (WikiCitadel v1).

Runs the OKF export FRESH into a scratch directory and audits
the resulting bundle against the conformance points the
export claims — independently: every verdict is re-derived
from the bundle bytes and the source pages, never read from
the export's own report. The export's `check` tallies over
the same fresh bundle are printed beside the audit's, and a
disagreement is itself a finding.

The conformance point under audit is the OKF §4.1 round-trip
preservation requirement (interchange find): source
frontmatter survives the round trip. In this export's
mapping, that means concretely — and the audit verifies each
point from the bundle bytes:

* every compiled page has a bundle file (completeness vs
  the compiled layer's page count, in both directions: no
  page missing, no bundle file unexplained);
* `type` and `title` survive at the top level with the same
  values; `tags` survive as the same set;
* `sources` survive as the bundle's source list with the
  same resource values;
* `status` survives through the export's status mapping,
  with the raw value preserved in the `llm_wiki` namespace
  whenever the mapping changed it;
* every other source frontmatter key survives under the
  `llm_wiki` namespace with the same value — nothing is
  silently dropped;
* the body survives byte-for-byte.

(Reserved files — bundle `index.md` / `log.md` — are
transformed by design; the audit checks their presence
only.) Per-file verdicts use the export's vocabulary:
PASS / PASS-WITH-OMISSIONS / FAIL, with omissions re-derived
the same way the format defines them (OKF-recommended
fields absent, the extension namespace in use, verbatim
wikilinks/citation markers, sources pointing outside the
bundle).

Usage:
    python3 scripts/wiki_okf_audit.py [--out DIR]

Exit 0 = no FAIL; 1 = at least one FAIL (or the audit and
the export's own check disagree); 2 = the audit could not
run (export failed, PyYAML missing).
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "scripts" / "wiki_okf_export.py"
WIKI = ROOT / "wiki"

sys.path.insert(0, str(ROOT / "scripts"))
import wiki_okf_export as okf  # noqa: E402  (page inventory only)

try:
    import yaml
except ImportError:
    yaml = None


def _load_source_parser():
    """The corpus's own frontmatter grammar (the validator's
    parser) — used for SOURCE pages only. The bundle side is
    parsed independently below: machine-emitted YAML gets a
    strict YAML read, while source pages are read in the
    grammar the corpus itself is written and validated in
    (an unquoted title containing ' #' is a full literal
    line there, where a YAML read would truncate it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_frontmatter


PARSE_SOURCE = _load_source_parser()

CITE_RE = re.compile(r"\^\[cite:")
WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
TOP_LEVEL_KEYS = {"title", "type", "tags", "sources", "status"}


def split_frontmatter(text):
    """Independent splitter: (frontmatter dict | None, body)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except Exception:
        return None, text
    if not isinstance(data, dict):
        return None, text
    return data, text[end + 5:]


def norm(value):
    """YAML-value normal form for equality across the round trip."""
    if isinstance(value, dict):
        return {str(k): norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [norm(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # dates, datetimes


def audit_concept(root, out_dir, rel):
    """(verdict, problems, omissions) for one concept page.
    rel is wiki-relative (e.g. rules/succession.md)."""
    problems, omissions = [], []
    src_fm, src_body = PARSE_SOURCE(
        (root / "wiki" / rel).read_text(encoding="utf-8"))
    if src_fm is None:
        return "FAIL", ["source frontmatter unparseable (audit-side)"], []
    bundle_path = out_dir / rel
    if not bundle_path.is_file():
        return "FAIL", ["bundle file missing"], []
    b_fm, b_body = split_frontmatter(
        bundle_path.read_text(encoding="utf-8"))
    if b_fm is None:
        return "FAIL", ["bundle frontmatter unparseable"], []

    # Top-level mapped fields.
    if not str(b_fm.get("type") or "").strip():
        problems.append("bundle type missing/empty")
    elif norm(b_fm.get("type")) != norm(src_fm.get("type")):
        problems.append("type changed in round trip")
    if src_fm.get("title") is not None and \
            norm(b_fm.get("title")) != norm(src_fm.get("title")):
        problems.append("title lost or changed in round trip")
    if src_fm.get("tags"):
        if sorted(map(str, b_fm.get("tags") or [])) != \
                sorted(map(str, src_fm.get("tags") or [])):
            problems.append("tags changed in round trip")
    src_sources = [str(s) for s in (src_fm.get("sources") or [])]
    if src_sources:
        resources = [str(e.get("resource")) for e in
                     (b_fm.get("sources") or []) if isinstance(e, dict)]
        if sorted(resources) != sorted(src_sources):
            problems.append("sources resources changed in round trip")

    # §4.1 preservation: every source key recoverable, same value.
    namespace = b_fm.get("llm_wiki") or {}
    raw_status = src_fm.get("status")
    if raw_status is not None:
        mapped = okf.STATUS_MAP.get(str(raw_status))
        if mapped is not None:
            if b_fm.get("status") != mapped:
                problems.append("status mapping not applied")
            if mapped != str(raw_status) and \
                    norm(namespace.get("status")) != norm(raw_status):
                problems.append("raw status not preserved in namespace")
        elif norm(namespace.get("status")) != norm(raw_status):
            problems.append("unmapped status not preserved in namespace")
    for key, value in src_fm.items():
        if key in TOP_LEVEL_KEYS:
            continue
        if norm(namespace.get(key)) != norm(value):
            problems.append(
                f"source field {key!r} not preserved under llm_wiki")

    if b_body != src_body:
        problems.append("body differs from source body "
                        "(not byte-identical)")

    # Omissions, re-derived in the format's own terms.
    if not b_fm.get("description"):
        omissions.append("no description")
    if not b_fm.get("resource"):
        omissions.append("no resource URI")
    if "generated" not in b_fm and "verified" not in b_fm:
        omissions.append("no generated/verified trust family")
    if namespace:
        omissions.append("llm_wiki extension namespace in use")
    if WIKILINK_RE.search(b_body):
        omissions.append("body keeps [[wikilinks]] verbatim")
    if CITE_RE.search(b_body):
        omissions.append("body keeps ^[cite:] markers verbatim")
    for entry in b_fm.get("sources") or []:
        if isinstance(entry, dict):
            resource = str(entry.get("resource") or "")
            if resource and not resource.startswith(
                    ("http://", "https://", "/")) \
                    and not (out_dir / resource).exists():
                omissions.append("sources point outside the bundle")
                break

    verdict = "FAIL" if problems else \
        "PASS-WITH-OMISSIONS" if omissions else "PASS"
    return verdict, problems, omissions


def export_check_tallies(bundle_dir):
    """The export's own check over the same bundle (comparison)."""
    proc = subprocess.run(
        [sys.executable, str(EXPORT), "check", "--bundle",
         str(bundle_dir)],
        capture_output=True, text=True)
    m = re.search(
        r"Counts: PASS (\d+) · PASS-WITH-OMISSIONS (\d+) · FAIL (\d+) "
        r"\(of (\d+) files\)", proc.stdout)
    if not m:
        return None
    p, o, f, total = (int(x) for x in m.groups())
    return {"PASS": p, "PASS-WITH-OMISSIONS": o, "FAIL": f, "total": total}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None,
                    help="bundle directory (default: a fresh temp dir)")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repository root (default: this repo)")
    args = ap.parse_args(argv)
    if yaml is None:
        print("AUDIT ERROR: PyYAML is required to parse frontmatter")
        return 2
    root = args.root.resolve()
    tmp = None
    if args.out is None:
        tmp = tempfile.TemporaryDirectory(prefix="okf-audit-")
        out_dir = Path(tmp.name) / "okf-bundle"
    else:
        out_dir = args.out

    proc = subprocess.run(
        [sys.executable, str(EXPORT), "export", "--out", str(out_dir)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print("AUDIT ERROR: fresh export failed:\n"
              + (proc.stdout + proc.stderr)[-2000:])
        return 2

    concepts, structural = okf.page_paths(root / "wiki")
    tally = {"PASS": 0, "PASS-WITH-OMISSIONS": 0, "FAIL": 0}
    fail_names = []
    omission_kinds = {}
    expected = set()
    for rel in concepts:
        rel = rel.as_posix()
        expected.add(rel)
        verdict, problems, omissions = audit_concept(root, out_dir, rel)
        tally[verdict] += 1
        if verdict == "FAIL":
            fail_names.append((rel, problems))
        for note in omissions:
            omission_kinds[note] = omission_kinds.get(note, 0) + 1
    for rel in structural:
        rel = rel.as_posix()
        expected.add(rel)
        if (out_dir / rel).is_file():
            tally["PASS"] += 1
        else:
            tally["FAIL"] += 1
            fail_names.append((rel, ["reserved bundle file missing"]))
    total = len(expected)
    extra = sorted(
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*.md") if p.is_file()) \
        if out_dir.is_dir() else []
    unexplained = [p for p in extra if p not in expected]
    for rel in unexplained:
        tally["FAIL"] += 1
        fail_names.append((rel, ["bundle file with no source page"]))

    print(f"OKF bundle audit — fresh export into {out_dir}")
    print(f"compiled pages audited: {total} "
          f"({len(concepts)} concepts, {len(structural)} reserved)")
    print(f"PASS {tally['PASS']} · PASS-WITH-OMISSIONS "
          f"{tally['PASS-WITH-OMISSIONS']} · FAIL {tally['FAIL']}")
    if omission_kinds:
        print("omission kinds: " + ", ".join(
            f"{k} ×{n}" for k, n in
            sorted(omission_kinds.items(), key=lambda kv: -kv[1])))
    for rel, problems in fail_names:
        print(f"FAIL {rel}: " + "; ".join(problems))

    theirs = export_check_tallies(out_dir)
    disagreement = False
    if theirs is not None:
        print(f"export's own check: PASS {theirs['PASS']} · "
              f"PASS-WITH-OMISSIONS {theirs['PASS-WITH-OMISSIONS']} · "
              f"FAIL {theirs['FAIL']} (of {theirs['total']} files)")
        if theirs["total"] != total + len(unexplained) or \
                theirs["PASS"] != tally["PASS"] or \
                theirs["PASS-WITH-OMISSIONS"] != \
                tally["PASS-WITH-OMISSIONS"] or \
                theirs["FAIL"] != tally["FAIL"]:
            disagreement = True
            print("DISAGREEMENT: audit tallies differ from the export's "
                  "own check — per-file verdicts can differ where the "
                  "two derivations weigh a point differently (the audit "
                  "checks source round-trip preservation; the check "
                  "checks spec conformance of the bundle alone). The "
                  "tallies disagreeing is a finding to read, file by "
                  "file, before trusting either.")
    if tmp is not None:
        tmp.cleanup()
    return 1 if (tally["FAIL"] or disagreement) else 0


if __name__ == "__main__":
    sys.exit(main())
