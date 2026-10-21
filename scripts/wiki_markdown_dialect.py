#!/usr/bin/env python3
"""wiki_markdown_dialect.py — the CommonMark dialect pin, the
RFC 7763 variant label, and the Lens conformance runner
(Marathon Round 6, lane BA, items 1-2).

Item 1 — THE PIN. This wiki's Markdown dialect is pinned as
data, not folklore: evaluation/markdown-dialect.json names
**CommonMark 0.31.2** (spec: https://spec.commonmark.org/
0.31.2/, CC BY-SA 4.0), and AGENTS.md declares the same pin
in its "Markdown dialect and the variant label" section.
`check` verifies the two agree, that the conformance subset
is well-formed and attributed, and that the places that
state content types carry the variant label below.

Item 2 — THE VARIANT LABEL. RFC 7763 registers the
`text/markdown` media type and its `variant` parameter.
Served/exported Markdown from this wiki therefore declares:

    text/markdown; variant=CommonMark

The declaration lives where content types / manifests are
already stated: the RO-Crate sidecar's per-file
`encodingFormat` for `.md` files (scripts/wiki_ro_crate.py),
and the Lens build manifest (tools/lens/build_lens.py,
`build-manifest.json`: top-level `markdown_media_type`).
`encoding_format_for()` here is the canonical helper;
wiki_ro_crate.py carries the same string as a local constant
(it is loaded standalone) and `check` cross-verifies the two
strings agree, so the copies cannot drift silently.

THE CONFORMANCE RUNNER. `conformance` runs the bounded,
attributed subset in evaluation/commonmark-conformance.json
against the Lens renderer (tools/lens/lenslib.py
`render_markdown`) and REPORTS pass / diverge per case. The
spec does not mandate presentation details, so comparison
first strips the Lens's documented presentation attributes
(heading `id=` anchors, `target=`/`rel=` on external links),
normalises `<hr />` vs `<hr>` and self-closing spelling,
and collapses whitespace runs; structure, text, href/src
and nesting are then compared exactly. A divergence is a
FINDING, recorded in the subset's `known_divergences` list
with its observed output: this tool never edits the
renderer, and the standing test (tools/lens/tests/
test_commonmark_conformance.py) fails when the actual
divergence set differs from the recorded set in either
direction — a new divergence and a quietly fixed one both
surface. Renderer changes are a separate, gated act.

Commands:
  show                     the pin as JSON
  check                    pin + subset shape + variant
                           label cross-checks
  conformance [--json]     run the subset against the Lens
                           renderer and report

Exit codes: 0 ok, 1 check found problems / conformance
divergence set differs from the recorded set, 2 usage
error. Stdlib only. No model calls.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = ROOT / "evaluation" / "markdown-dialect.json"
CASES_PATH = ROOT / "evaluation" / "commonmark-conformance.json"
LENSLIB_PATH = ROOT / "tools" / "lens" / "lenslib.py"
RO_CRATE_PATH = ROOT / "scripts" / "wiki_ro_crate.py"
BUILD_LENS_PATH = ROOT / "tools" / "lens" / "build_lens.py"
AGENTS_PATH = ROOT / "AGENTS.md"

DIALECT = "CommonMark"
SPEC_VERSION = "0.31.2"
MEDIA_TYPE = "text/markdown"
VARIANT_LABEL = "text/markdown; variant=CommonMark"
MARKDOWN_ENCODING_FORMAT = VARIANT_LABEL


# ---------------------------------------------------------------- pin

def load_pin(path=PIN_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_cases(path=CASES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def encoding_format_for(name):
    """The encodingFormat a manifest states for a file: the
    RFC 7763 variant label for Markdown, the plain MIME type
    otherwise (same fallback as the RO-Crate generator)."""
    import mimetypes
    if str(name).lower().endswith(".md"):
        return MARKDOWN_ENCODING_FORMAT
    return mimetypes.guess_type(str(name))[0] \
        or "application/octet-stream"


def check_pin(pin, cases):
    """Validate pin + subset dicts; returns problem strings."""
    problems = []
    if pin.get("kind") != "markdown-dialect-pin":
        problems.append(f"pin kind is {pin.get('kind')!r}, "
                        f"expected 'markdown-dialect-pin'")
    if pin.get("dialect") != DIALECT:
        problems.append(f"pin dialect is {pin.get('dialect')!r}, "
                        f"expected {DIALECT!r}")
    if pin.get("spec_version") != SPEC_VERSION:
        problems.append(f"pin spec_version is "
                        f"{pin.get('spec_version')!r}, expected "
                        f"{SPEC_VERSION!r}")
    if pin.get("variant_label") != VARIANT_LABEL:
        problems.append(f"pin variant_label is "
                        f"{pin.get('variant_label')!r}, expected "
                        f"{VARIANT_LABEL!r}")
    if pin.get("media_type") != MEDIA_TYPE:
        problems.append(f"pin media_type is "
                        f"{pin.get('media_type')!r}, expected "
                        f"{MEDIA_TYPE!r}")
    if pin.get("spec_licence") != "CC BY-SA 4.0":
        problems.append("pin spec_licence must record the "
                        "spec's CC BY-SA 4.0 licence")

    if cases.get("kind") != "commonmark-conformance-subset":
        problems.append(f"cases kind is {cases.get('kind')!r}, "
                        f"expected 'commonmark-conformance-subset'")
    if SPEC_VERSION not in str(cases.get("spec") or ""):
        problems.append("cases do not name spec version "
                        f"{SPEC_VERSION}")
    if "CC BY-SA 4.0" not in str(cases.get("attribution") or ""):
        problems.append("cases attribution does not carry the "
                        "CC BY-SA 4.0 attribution")
    if not cases.get("full_spec_provenance"):
        problems.append("cases state no full-spec provenance")
    rows = cases.get("cases")
    if not isinstance(rows, list) or not rows:
        problems.append("cases list is missing or empty")
        return problems
    seen = set()
    for row in rows:
        cid = row.get("id")
        if cid in seen:
            problems.append(f"duplicate case id: {cid}")
        seen.add(cid)
        for field in ("section", "markdown", "expected_html"):
            if not row.get(field):
                problems.append(f"case {cid or '<no id>'}: "
                                f"required field missing: {field}")
    known = cases.get("known_divergences")
    if not isinstance(known, list):
        problems.append("known_divergences is not a list")
    else:
        for entry in known:
            if entry.get("id") not in seen:
                problems.append(f"known divergence names an "
                                f"unknown case: {entry.get('id')}")
            if not entry.get("observed"):
                problems.append(f"known divergence "
                                f"{entry.get('id')} records no "
                                f"observed output")
    return problems


def check_tree_texts():
    """Cross-checks against the tree's own declaration sites:
    AGENTS.md states the pin and the label; the RO-Crate
    generator and the Lens build carry the label. Returns
    problem strings."""
    problems = []
    agents = AGENTS_PATH.read_text(encoding="utf-8") \
        if AGENTS_PATH.is_file() else ""
    for needle in ("CommonMark 0.31.2", VARIANT_LABEL):
        if needle not in agents:
            problems.append(f"AGENTS.md does not state "
                            f"{needle!r}")
    for path, label in ((RO_CRATE_PATH, "wiki_ro_crate.py"),
                        (BUILD_LENS_PATH, "build_lens.py")):
        text = path.read_text(encoding="utf-8") \
            if path.is_file() else ""
        if VARIANT_LABEL not in text:
            problems.append(f"{label} does not carry the "
                            f"variant label {VARIANT_LABEL!r}")
    return problems


# ---------------------------------------------------------------- conformance

def _load_lenslib():
    spec = importlib.util.spec_from_file_location(
        "lenslib", LENSLIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalise(html_text):
    """The documented comparison normalisation (see the
    subset file's comparison_normalisation note)."""
    t = html_text
    t = re.sub(r'(<h[1-6])\s+id="[^"]*"', r"\1", t)
    t = re.sub(r'(<a\s+href="[^"]*")\s+target="_blank"'
               r'\s+rel="noopener"', r"\1", t)
    t = t.replace("<hr />", "<hr>").replace("<hr/>", "<hr>")
    t = re.sub(r"<(img|br)([^>]*?)\s*/>", r"<\1\2>", t)
    t = re.sub(r">\s+<", "><", t)        # inter-tag whitespace
    t = re.sub(r"\s+</", "</", t)        # trailing ws in an element
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def run_conformance(cases_data=None, lenslib=None):
    """Run every case through the Lens renderer. Returns
    {total, passed: [ids], diverged: [{id, section,
    expected, observed}], results: [...]}. Report-only: this
    function never edits the renderer or the case file."""
    cases_data = cases_data or load_cases()
    lenslib = lenslib or _load_lenslib()
    results = []
    for row in cases_data["cases"]:
        rendered, _wl = lenslib.render_markdown(row["markdown"])
        ok = normalise(rendered) == normalise(row["expected_html"])
        results.append({
            "id": row["id"], "section": row["section"],
            "status": "pass" if ok else "diverge",
            "expected": row["expected_html"],
            "observed": rendered,
        })
    return {
        "total": len(results),
        "passed": [r["id"] for r in results
                   if r["status"] == "pass"],
        "diverged": [{"id": r["id"], "section": r["section"],
                      "expected": r["expected"],
                      "observed": r["observed"]}
                     for r in results if r["status"] == "diverge"],
        "results": results,
    }


def divergence_drift(cases_data, report):
    """(new, healed) divergence ids: actual vs the subset's
    recorded known_divergences. Both directions are drift —
    a silently fixed divergence is as much a record error as
    a new one."""
    recorded = {e["id"] for e in cases_data.get("known_divergences")
                or []}
    actual = {d["id"] for d in report["diverged"]}
    return sorted(actual - recorded), sorted(recorded - actual)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("check")
    conf = sub.add_parser("conformance")
    conf.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)

    if ns.cmd == "show":
        print(json.dumps(load_pin(), indent=2, ensure_ascii=False))
        return 0
    if ns.cmd == "check":
        problems = check_pin(load_pin(), load_cases()) \
            + check_tree_texts()
        for prob in problems:
            print(prob)
        print(f"{len(problems)} problem(s)")
        return 1 if problems else 0
    # conformance
    data = load_cases()
    report = run_conformance(data)
    new, healed = divergence_drift(data, report)
    if ns.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in report["results"]:
            print(f"{r['status']:7s} {r['id']} "
                  f"({r['section']})")
        print(f"{len(report['passed'])}/{report['total']} pass; "
              f"{len(report['diverged'])} recorded divergence(s)")
        for d in report["diverged"]:
            print(f"  DIVERGE {d['id']}: observed "
                  f"{d['observed']!r}")
    if new or healed:
        print(f"DRIFT: new divergences {new}; recorded but no "
              f"longer diverging {healed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
