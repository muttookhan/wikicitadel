#!/usr/bin/env python3
"""wiki_quality_track.py — per-page quality tracks, ORKG
pattern (Marathon R6 lane BB).

Pattern: Brack et al., the Open Research Knowledge Graph
(ORKG) distinction between CURATED content — built for
correctness, reviewed claim by claim — and AUTOMATIC content
— built for completeness/coverage, generated broadly and
checked in bulk (Brack et al. 2021; CC BY 4.0 — pattern/idea
only, re-implemented in our own code, no text copied).

THE TRACK — a fifth axis, beside the existing four (`status`
lifecycle, `confidence` evidence, `stage` maturity,
`work_type` kind of work), never conflated with any of them:
a page's QUALITY TRACK says which standard the page is held
to, not how good it currently is:

    quality_track: curated | automatic

    curated    held to CORRECTNESS expectations: its claims
               carry citations a checker can follow;
    automatic  held to COMPLETENESS expectations: its
               record is whole — core frontmatter and the
               standing axes all present — even though no
               claim-by-claim curation is promised.

DERIVATION (pages that predate the field). An explicit
`quality_track:` always wins. Where a page carries none, the
effective track is DERIVED from the existing axes and
signals, by the first matching rule, and the report names
the rule that fired — a derivation is stated, never silent:

    D1  the page carries `verified_until` (owner-attested)
        -> curated: an attested page is curated by act;
    D2  the page carries a frontmatter `claim:` (opted into
        the outcome-verified claim lifecycle)
        -> curated: a lifecycle claim is curated by design;
    D3  `stage: evergreen` AND at least one claim-level
        ^[cite:] marker -> curated: settled maturity that
        carries its citations is treated as curated;
    D4  anything else -> automatic: completeness is the
        honest default promise for an uncurated page.

EXPECTATIONS (the lint half — they differ by track, which
is the point of having tracks):

    curated pages:
      - `sources` non-empty            curated-no-sources
      - >= 1 claim-level ^[cite:]      curated-no-claim-citation
      - work_type synthesis/advice
        carries `methods:`             curated-missing-methods
    automatic pages:
      - title/type/created/updated     automatic-incomplete-core
        all present (missing named)
      - `tags` field present           automatic-missing-tags
      - `stage` present                automatic-missing-stage
      - `work_type` present            automatic-missing-work-type

A declared value outside the vocabulary is an
`invalid-track` finding; the effective track then falls
back to the derivation (stated in the report).

REPORT-ONLY: this tool never edits a page, never assigns a
track in place, and is wired into no gate. Exit 1 means
findings exist, so a sweep can surface the report — the
lint-lane idiom, not a block.

    python3 scripts/wiki_quality_track.py [--root DIR]
        check [--plain]

Exit codes: 0 = no findings · 1 = findings · 2 = usage.
Stdlib only. No model calls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKS = ("curated", "automatic")
FIELD = "quality_track"
CORE_FIELDS = ("title", "type", "created", "updated")
LIST_FIELDS = ("sources", "tags")

KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def parse_page(text: str):
    """(fields, lists, body) — the house minimal parse,
    extended to block lists for sources/tags."""
    if not text.startswith("---"):
        return {}, {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, {}, text
    fields, lists = {}, {}
    lines = text[3:end].splitlines()
    i = 0
    while i < len(lines):
        m = KEY_RE.match(lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip("'\"") for v in
                     val[1:-1].split(",") if v.strip()]
            fields[key] = items
            if key in LIST_FIELDS:
                lists[key] = items
        elif val:
            fields[key] = val.strip("'\"")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                items.append(re.sub(r"^\s+-\s+", "", lines[j])
                             .strip().strip("'\""))
                j += 1
            if items:
                fields[key] = items
                if key in LIST_FIELDS:
                    lists[key] = items
                i = j - 1
            else:
                fields[key] = None
        i += 1
    return fields, lists, text[end + 4:]


def derive_track(fields: dict, cites_n: int):
    """(track, rule) by D1..D4 — see the module docstring."""
    if fields.get("verified_until"):
        return "curated", "D1-owner-attested"
    if fields.get("claim"):
        return "curated", "D2-claim-lifecycle"
    if str(fields.get("stage") or "") == "evergreen" \
            and cites_n >= 1:
        return "curated", "D3-evergreen-with-citations"
    return "automatic", "D4-default"


def expectations(fields: dict, lists: dict, cites_n: int,
                 track: str) -> list:
    """The findings one page earns under its effective
    track's expectations. Empty list = expectations met."""
    out = []
    if track == "curated":
        if not lists.get("sources"):
            out.append("curated-no-sources")
        if cites_n < 1:
            out.append("curated-no-claim-citation")
        if str(fields.get("work_type") or "") \
                in ("synthesis", "advice") \
                and not fields.get("methods"):
            out.append("curated-missing-methods")
    else:  # automatic — completeness of the record itself
        missing = [k for k in CORE_FIELDS if not fields.get(k)]
        if missing:
            out.append("automatic-incomplete-core:"
                       + ",".join(missing))
        if "tags" not in fields:
            out.append("automatic-missing-tags")
        if not fields.get("stage"):
            out.append("automatic-missing-stage")
        if not fields.get("work_type"):
            out.append("automatic-missing-work-type")
    return out


def check(root: Path) -> dict:
    root = Path(root)
    pages = []
    wiki = root / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            text = p.read_text(encoding="utf-8", errors="ignore")
            fields, lists, body = parse_page(text)
            if not fields:
                continue  # structural pages exempt (standing rule)
            cites_n = body.count("^[cite:")
            declared = fields.get(FIELD)
            if isinstance(declared, str):
                declared = declared.strip() or None
            else:
                declared = None
            derived, rule = derive_track(fields, cites_n)
            findings = []
            if declared is not None and declared not in TRACKS:
                findings.append("invalid-track")
                effective, source = derived, "derived-fallback"
            elif declared is not None:
                effective, source = declared, "declared"
            else:
                effective, source = derived, "derived"
            findings += expectations(fields, lists, cites_n,
                                     effective)
            pages.append({
                "page": str(p.relative_to(root)),
                "declared": declared,
                "effective": effective,
                "source": source,
                "derivation": rule if source != "declared"
                else None,
                "cites_n": cites_n,
                "findings": findings,
            })
    return {
        "tool": "scripts/wiki_quality_track.py",
        "kind": "quality-track-report",
        "pattern": "Brack et al. 2021 (CC BY 4.0) ORKG "
                   "curated-vs-automatic quality distinction — "
                   "report-only; this tool never edits a page",
        "tracks": list(TRACKS),
        "derivation_rules":
            "D1 verified_until -> curated; D2 claim: -> "
            "curated; D3 stage evergreen + >=1 claim citation "
            "-> curated; D4 otherwise -> automatic",
        "stats": {
            "pages": len(pages),
            "declared": sum(1 for p in pages
                            if p["source"] == "declared"),
            "derived": sum(1 for p in pages
                           if p["source"] != "declared"),
            "curated": sum(1 for p in pages
                           if p["effective"] == "curated"),
            "automatic": sum(1 for p in pages
                             if p["effective"] == "automatic"),
            "pages_with_findings": sum(1 for p in pages
                                       if p["findings"]),
            "findings": sum(len(p["findings"]) for p in pages),
        },
        "pages": pages,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--plain", action="store_true",
                    help="short human report instead of JSON")
    ap.add_argument("cmd", nargs="?", default="check")
    args = ap.parse_args(argv)
    if args.cmd != "check":
        print(f"wiki_quality_track: unknown command "
              f"{args.cmd!r} (only 'check')", file=sys.stderr)
        return 2
    report = check(Path(args.root).resolve())
    if args.plain:
        st = report["stats"]
        print(f"quality tracks: {st['pages']} page(s); "
              f"{st['curated']} curated, {st['automatic']} "
              f"automatic ({st['declared']} declared, "
              f"{st['derived']} derived); "
              f"{st['findings']} finding(s) on "
              f"{st['pages_with_findings']} page(s)")
        for pg in report["pages"]:
            for f in pg["findings"]:
                print(f"  {f}: {pg['page']} "
                      f"(track={pg['effective']} "
                      f"via {pg['source']})")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["stats"]["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
