#!/usr/bin/env python3
"""Application-profile conformance + sensitivity checks (items 49/51).

The wiki's schema used to live as prose in AGENTS.md plus whatever
scripts/wiki_validate.py and the gateway lifecycle profile happen
to enforce. WikiCitadel v1 recasts it as a Dublin Core APPLICATION
PROFILE (Singapore Framework; survey find 16):
evaluation/schema-profile.json states, per page class (directory)
and per element, an obligation grade — M mandatory, MA mandatory
if applicable, R recommended, O optional — a value space, and a
note. The profile DESCRIBES the schema the corpus actually runs:
where AGENTS.md and the tooling disagree, the disagreement is an
open line in the profile (open_disagreements), never silently
resolved here.

This tool checks the live corpus against that profile:

  check        per class x element conformance. Pages missing an
               M element (or an MA element whose applicability is
               mechanically decidable and holds) are NAMED.
               Grandfathered absence (an element required only
               since a schema version the page predates) is
               reported on its own line — never as a pass, never
               as an error. MA elements whose applicability is not
               mechanically decidable are listed as such, not
               silently skipped.

  sensitivity  the compiled-layer half of the sensitivity
               discipline. Sensitivity
               classes (evaluation/sensitivity.json, the PNAAM
               discipline via find 12) are assigned to raw
               sources at ingest; this check walks every compiled
               page's sources and flags citations a class forbids:
               credential-adjacent cited by ANY page; export-only
               cited by a page outside the sources class. Family-
               sensitive citations are reported as NOTICES (the
               class permits compilation only where the owner
               directed it, which is not mechanically decidable).
               Unclassified sources are counted and named as what
               they are: unclassified — never read as 'public'.

Usage:
  python3 scripts/wiki_profile.py [check|sensitivity|all]
          [--json] [--root PATH]
Exit: 0 = no violations and no flags; 1 = findings; 2 = usage or
profile-load error. Stdlib only. The frontmatter parser and the
source-resolution convention are the validator's (imported, not
re-implemented); resolution here is root-parametric so fixtures
can exercise the same code the real corpus runs.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import wiki_validate as wv  # noqa: E402  (parser + conventions)

STRUCTURAL = {"wiki/index.md", "wiki/log.md"}
VOCAB_SUFFIX = " vocabulary"


# ------------------------------------------------------------ predicates
# MA applicability, by the predicate ids named in the profile.
# Only these are mechanically decidable; anything else in a
# profile must say so and is reported as undecidable.

def _declared_version(fields):
    try:
        return int(str(fields.get("_schema_version") or 1).strip())
    except ValueError:
        return 1


APPLICABILITY = {
    "declared-schema-version->=2":
        lambda f: _declared_version(f) >= 2,
    "work_type-in:synthesis,advice":
        lambda f: str(f.get("work_type") or "").strip()
        in ("synthesis", "advice"),
    "stage-present":
        lambda f: bool(f.get("stage")),
    "claim-present":
        lambda f: bool(f.get("claim")),
    "verified_until-present":
        lambda f: bool(f.get("verified_until")),
    "status-is:tombstoned":
        lambda f: str(f.get("status") or "").strip() == "tombstoned",
}


def page_class(rel):
    """The profile class of a repo-relative wiki page path."""
    if rel in STRUCTURAL:
        return "structural"
    parts = Path(rel).parts
    if len(parts) == 2:  # wiki/<page>.md
        return "root"
    return parts[1]


def _present(fields, name):
    return name in fields and fields[name] is not None \
        and fields[name] != ""


def _value_space(spec, profile, cls_spec):
    """Resolve an element's value space to a list, or None when
    it is descriptive (dates, strings, paths — not enumerable)."""
    vs = spec.get("value_space")
    if isinstance(vs, list):
        return vs
    if isinstance(vs, str):
        if vs == "type vocabulary (per class)":
            return list(cls_spec.get("type_values") or [])
        spaces = profile.get("value_spaces") or {}
        if vs in spaces:
            return list(spaces[vs])
    return None


# ---------------------------------------------------------------- check

def check_profile(root, profile):
    """Conformance of the corpus under `root` against `profile`.
    Returns a report dict (see render_check for the human form)."""
    wiki = Path(root) / "wiki"
    pages = sorted(p for p in wiki.rglob("*.md") if p.is_file())
    classes = profile.get("classes") or {}
    common = profile.get("common_elements") or {}

    report = {
        "pages": 0,
        "by_class": {},
        "violations": [],      # {page, class, element, kind, detail}
        "grandfathered": [],   # {page, class, element}
        "recommendation_gaps": {},  # "class/element" -> count
        "undecidable_ma": [],  # {class, element, applicability}
    }

    for p in pages:
        rel = p.relative_to(root).as_posix()
        cls = page_class(rel)
        if cls == "structural":
            continue
        report["pages"] += 1
        bucket = report["by_class"].setdefault(
            cls, {"pages": 0, "violations": 0, "grandfathered": 0})
        bucket["pages"] += 1
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, _body = wv.parse_frontmatter(text)
        if fields is None:
            report["violations"].append({
                "page": rel, "class": cls, "element": "(frontmatter)",
                "kind": "missing-frontmatter",
                "detail": "no --- frontmatter block"})
            bucket["violations"] += 1
            continue
        cls_spec = classes.get(cls) or {}
        elements = dict(common)
        elements.update(cls_spec.get("elements") or {})

        for name, spec in sorted(elements.items()):
            obligation = spec.get("obligation")
            present = _present(fields, name)
            if present:
                space = _value_space(spec, profile, cls_spec)
                if space is not None:
                    val = fields.get(name)
                    allowed = list(space)
                    if name == "status":
                        # 'tombstoned' is a status value by
                        # AGENTS.md's own tombstone convention,
                        # absent from the axes vocabulary (OD-9);
                        # the checker follows the convention and
                        # the profile records the disagreement.
                        allowed.append("tombstoned")
                    if isinstance(val, str) \
                            and val.strip() not in allowed:
                        report["violations"].append({
                            "page": rel, "class": cls, "element": name,
                            "kind": "value-space",
                            "detail": f"{name} {val!r} is outside its "
                                      f"value space {allowed}"})
                        bucket["violations"] += 1
                continue
            # absent: grade the absence by obligation
            if obligation == "M":
                report["violations"].append({
                    "page": rel, "class": cls, "element": name,
                    "kind": "missing-mandatory",
                    "detail": f"mandatory element {name!r} is absent"})
                bucket["violations"] += 1
            elif obligation == "MA":
                pred_id = spec.get("applicability")
                pred = APPLICABILITY.get(pred_id or "")
                if pred is None:
                    key = (cls, name)
                    if key not in {(c, e) for c, e, _a
                                   in report["undecidable_ma"]}:
                        report["undecidable_ma"].append(
                            (cls, name, pred_id))
                    continue
                gf = spec.get("grandfathered_below_version")
                if gf is not None and _declared_version(fields) < gf:
                    report["grandfathered"].append({
                        "page": rel, "class": cls, "element": name})
                    bucket["grandfathered"] += 1
                elif pred(fields):
                    report["violations"].append({
                        "page": rel, "class": cls, "element": name,
                        "kind": "missing-applicable",
                        "detail": f"element {name!r} is mandatory "
                                  f"if applicable ({pred_id}) and "
                                  f"is absent"})
                    bucket["violations"] += 1
            elif obligation == "R":
                key = f"{cls}/{name}"
                report["recommendation_gaps"][key] = \
                    report["recommendation_gaps"].get(key, 0) + 1
    return report


def render_check(report, profile):
    lines = ["== Application-profile conformance =="]
    lines.append(f"pages checked: {report['pages']} "
                 f"(structural pages exempt)")
    lines.append(f"{'class':<12} {'pages':>5} {'M/MA viol':>9} "
                 f"{'grandf.':>8} {'R gaps':>7}")
    gaps_by_class = {}
    for key, n in report["recommendation_gaps"].items():
        cls = key.split("/", 1)[0]
        gaps_by_class[cls] = gaps_by_class.get(cls, 0) + n
    for cls in sorted(report["by_class"]):
        b = report["by_class"][cls]
        lines.append(f"{cls:<12} {b['pages']:>5} "
                     f"{b['violations']:>9} {b['grandfathered']:>8} "
                     f"{gaps_by_class.get(cls, 0):>7}")
    lines.append(f"TOTAL violations: {len(report['violations'])}; "
                 f"grandfathered absences: "
                 f"{len(report['grandfathered'])}")
    if report["violations"]:
        lines.append("\nViolations (pages named):")
        for v in report["violations"]:
            lines.append(f"  - [{v['kind']}] {v['page']}: {v['detail']}")
    if report["grandfathered"]:
        from collections import Counter
        groups = Counter((g["class"], g["element"])
                         for g in report["grandfathered"])
        lines.append("\nGrandfathered (neither pass nor error — "
                     "the element binds only pages at the newer "
                     "schema version):")
        for (cls, el), n in sorted(groups.items()):
            lines.append(f"  - {cls}/{el}: {n} page(s)")
    if report["recommendation_gaps"]:
        lines.append("\nRecommendation gaps (R elements absent, "
                     "counted, not violations):")
        for key, n in sorted(report["recommendation_gaps"].items()):
            lines.append(f"  - {key}: {n}")
    if report["undecidable_ma"]:
        lines.append("\nMA elements whose applicability is NOT "
                     "mechanically decidable (reported, never "
                     "silently skipped):")
        for cls, name, pred in report["undecidable_ma"]:
            lines.append(f"  - {cls}/{name} (applicability: {pred})")
    return "\n".join(lines)


# ------------------------------------------------------------ sensitivity

def _slug_tokens(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def resolve_source(root, entry, slug_map):
    """Mirror of the validator's source resolution, root-parametric:
    path entries resolve on disk; bare slugs resolve against
    raw/sources/ by exact token-set match on the file stem.
    Returns the repo-relative raw path or None."""
    if entry.startswith(("http://", "https://")):
        return None
    if "/" in entry:
        rel = Path(entry).as_posix()
        return rel if (Path(root) / rel).exists() else None
    matches = slug_map.get(frozenset(_slug_tokens(entry)), [])
    return matches[0] if len(matches) == 1 else None


def class_assignments(sens):
    """[(path, is_prefix, class_id)] from the register."""
    out = []
    for a in sens.get("assignments") or []:
        path = a.get("path") or ""
        out.append((path, path.endswith("/"), a.get("class")))
    return out


def sensitivity_of(assignments, rel):
    """The strictest applicable assignment wins by construction:
    assignments are exact paths or directory prefixes; the
    longest match governs (a file-level seed beats its
    directory's class, per the register's own statement)."""
    best = None
    for path, is_prefix, cls in assignments:
        if (is_prefix and rel.startswith(path)) or rel == path:
            if best is None or len(path) > len(best[0]):
                best = (path, cls)
    return best[1] if best else None


def check_sensitivity(root, sens):
    """Walk every compiled page's sources; flag forbidden
    citations, notice family-sensitive ones, count the rest."""
    root = Path(root)
    assignments = class_assignments(sens)
    slug_map = {}
    raw_sources = root / "raw" / "sources"
    if raw_sources.exists():
        for p in sorted(raw_sources.rglob("*")):
            if p.is_file():
                key = frozenset(_slug_tokens(p.stem))
                slug_map.setdefault(key, []).append(
                    p.relative_to(root).as_posix())
    report = {"cited_total": 0, "by_class": {}, "unclassified": 0,
              "unresolved": 0, "flags": [], "notices": []}
    pages = sorted((root / "wiki").rglob("*.md"))
    for p in pages:
        rel = p.relative_to(root).as_posix()
        if rel in STRUCTURAL:
            continue
        fields, _b = wv.parse_frontmatter(
            p.read_text(encoding="utf-8", errors="ignore"))
        if not fields:
            continue
        cls_of_page = page_class(rel)
        for entry in wv.as_list(fields.get("sources")):
            resolved = resolve_source(root, entry, slug_map)
            if resolved is None:
                report["unresolved"] += 1
                continue
            report["cited_total"] += 1
            scls = sensitivity_of(assignments, resolved)
            if scls is None:
                report["unclassified"] += 1
                continue
            report["by_class"][scls] = \
                report["by_class"].get(scls, 0) + 1
            if scls == "credential-adjacent":
                report["flags"].append({
                    "page": rel, "source": resolved, "class": scls,
                    "detail": "credential-adjacent material is "
                              "never cited by a compiled page"})
            elif scls == "export-only" and cls_of_page != "sources":
                report["flags"].append({
                    "page": rel, "source": resolved, "class": scls,
                    "detail": "export-only material may be cited "
                              "only by its own sources-class page; "
                              "its content is never compiled into "
                              "other pages"})
            elif scls == "family-sensitive":
                report["notices"].append({
                    "page": rel, "source": resolved, "class": scls,
                    "detail": "family-sensitive material compiled "
                              "here — permitted only where the "
                              "owner directed the compilation, "
                              "which is not mechanically decidable"})
    return report


def render_sensitivity(report):
    lines = ["== Sensitivity at the compiled layer =="]
    lines.append(f"raw paths cited by compiled pages: "
                 f"{report['cited_total']} "
                 f"(+{report['unresolved']} unresolvable entries, "
                 f"the validator's concern)")
    for cls, n in sorted(report["by_class"].items()):
        lines.append(f"  classified {cls}: {n} citation(s)")
    lines.append(f"  UNCLASSIFIED: {report['unclassified']} "
                 f"citation(s) — unclassified is a state of "
                 f"ignorance, never a clearance; most of the "
                 f"existing corpus is unclassified because "
                 f"classification began at ingest "
                 f"and the corpus is not backfilled")
    if report["flags"]:
        lines.append("\nFLAGS (citations a class forbids):")
        for f in report["flags"]:
            lines.append(f"  - {f['page']} cites {f['source']} "
                         f"[{f['class']}]: {f['detail']}")
    else:
        lines.append("\nFLAGS: none")
    if report["notices"]:
        lines.append("\nNotices (reported, not violations):")
        for f in report["notices"]:
            lines.append(f"  - {f['page']} cites {f['source']} "
                         f"[{f['class']}]: {f['detail']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ main

def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"wiki_profile: cannot load {path}: {exc}",
              file=sys.stderr)
        return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", default="all",
                    choices=("check", "sensitivity", "all"))
    ap.add_argument("--json", action="store_true",
                    help="emit the report(s) as JSON")
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="repo root (default: this script's repo)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    profile = _load_json(root / "evaluation" / "schema-profile.json")
    sens = _load_json(root / "evaluation" / "sensitivity.json")
    if profile is None or sens is None:
        return 2
    findings = 0
    out = {}
    if args.mode in ("check", "all"):
        rep = check_profile(root, profile)
        out["check"] = rep
        findings += len(rep["violations"])
        if not args.json:
            print(render_check(rep, profile))
    if args.mode in ("sensitivity", "all"):
        srep = check_sensitivity(root, sens)
        out["sensitivity"] = srep
        findings += len(srep["flags"])
        if not args.json:
            if args.mode == "all":
                print()
            print(render_sensitivity(srep))
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
