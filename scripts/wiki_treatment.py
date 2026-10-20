#!/usr/bin/env python3
"""Citation treatment signals: the citator half of citation
integrity (WikiCitadel v1).

WikiCitadel v1's citation lockfile (scripts/wiki_cite_lock.py)
proves a cited source has not CHANGED. Law's citators answer
the next question: does the authority still STAND — has
anything later followed, questioned, cautioned or knocked
down the claim it supports, and (KeyCite Overruling Risk) has
anything it relies on fallen? (Pattern: Shepard's Citations /
Westlaw KeyCite treatment signals and Overruling Risk, via
finds 1–3 of the professional-domains survey lane,
docs/research-notes.md — mechanics re-implemented, no
code copied; the citators themselves are proprietary.)

The register is evaluation/treatment-register.jsonl: a header
line (the decisions-register convention), then append-only
treatment events, one JSON object per line:

  {"kind": "treatment", "id": "treat-0001",
   "date": "YYYY-MM-DD",            # when the treatment happened
   "recorded": "YYYY-MM-DD",        # when it entered the register
   "subject": {"page": "wiki/...",  # the cited page
               "claim": null},      # null = the page as a whole;
                                    # a string scopes the event
                                    # to one claim on the page
                                    # (KeyCite flags attach to
                                    # points of law, not documents)
   "grade": "followed" | "questioned" | "caution" | "negative",
   "treated_by": {"source": "<record path>",
                  "detail": "<what treated it>"},
   "reason": "<why this grade>",
   "seed": true}                    # only on the seed entries

Grades, weakest to strongest: followed (later work relies on
it approvingly) < questioned (its validity questioned by a
citing/correcting record) < caution (limited or criticised)
< negative (overruled, reversed, corrected as false,
superseded). A subject's STANDING grade is its strongest
signal — per citator practice, the most negative treatment
governs the flag, however many positives surround it.

TRANSITIVE WEAKENING (Overruling Risk): a page that RESTS ON
a fallen page is itself weakened — the fallen page needs no
negative treatment of its own dependents; reliance is enough.
"Rests on" is computed from the batch-3.1 typed edges
(tools/lens/lenslib.py, imported in-process — the repo's one
edge table): a page rests on the targets of its `grounds`
wikilinks (links under Evidence / Grounds / Basis /
Provenance / Citation / Sources headings). A page is FALLEN
when any of its subjects carries a negative standing grade,
or when the wiki's own records mark it superseded (the Lane-2
semantic signals: frontmatter status superseded/deprecated,
a superseded_by pointer, a claim page retired under
wiki_claims.py's rule, a resolved talk page recording its
supersession). Weakening propagates transitively over the
rests-on graph and is COMPUTED, never written back: no page's
grade is edited by this tool; dependents surface in the
report with their fallen basis and distance, for the owner
to rule on.

Commands:
  record    append a treatment event (validates the grade
            and that the subject page exists)
  standing  standing grades per subject (JSON)
  weakened  the transitive-weakening listing (JSON)
  report    the full summary the lint lanes surface (JSON)

Stdlib only (lenslib + wiki_observe imported in-process).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
REGISTER = ROOT / "evaluation" / "treatment-register.jsonl"

GRADES = ("followed", "questioned", "caution", "negative")
SEVERITY = {grade: i for i, grade in enumerate(GRADES)}

# The compiled layer's exclusions, mirroring
# scripts/wiki_lint_lanes.py (kept local: the lanes import
# this module, never the reverse).
EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observe = _load("wiki_observe", SCRIPTS / "wiki_observe.py")
parse_frontmatter = observe.parse_frontmatter

try:
    lenslib = _load("lenslib_for_treatment",
                    ROOT / "tools" / "lens" / "lenslib.py")
    _typed_links = lenslib.extract_wikilinks_typed
except Exception:  # pragma: no cover - fallback if lenslib moves
    # Mirrored from tools/lens/lenslib.py (WikiCitadel v1), which is
    # canonical: the closed link-type vocabulary and the
    # heading rules that infer it. Used only when lenslib
    # itself cannot be loaded.
    _SECTION_TYPE_RULES = (
        ("contradicts", ("contradict", "conflict", "disagree",
                         "dispute", "contested", "tension")),
        ("supersedes", ("supersede", "replaces", "replaced by",
                        "deprecated", "obsolete", "retired")),
        ("grounds", ("evidence", "ground", "basis", "provenance",
                     "citation", "sources")),
        ("exemplifies", ("example", "exemplif", "illustrat",
                         "case study", "instance")),
        ("extends", ("extend", "extens", "elaborat", "builds on",
                     "built on", "expansion", "follow-up",
                     "followup")),
    )
    _WIKILINK_RE = re.compile(
        r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

    def _infer_link_type(heading):
        if not heading:
            return "mentions"
        h = heading.lower()
        for ltype, keywords in _SECTION_TYPE_RULES:
            if any(re.search(r"\b" + re.escape(k), h)
                   for k in keywords):
                return ltype
        return "mentions"

    def _typed_links(body):
        out = []
        in_code = False
        heading = None
        for line in body.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            hm = _HEADING_RE.match(line)
            if hm:
                heading = re.sub(r"\*\*|`", "",
                                  hm.group(2)).strip()
            stripped = re.sub(r"`[^`\n]*`", "", line)
            for m in _WIKILINK_RE.finditer(stripped):
                target = m.group(1).strip()
                out.append((target, m.group(2),
                            (m.group(3) or m.group(1)).strip(),
                            heading, _infer_link_type(heading)))
        return out


# -- Register ---------------------------------------------------------------

def read_register(path=REGISTER):
    """(header, events) from the treatment register. A missing
    register reads as empty; malformed lines are skipped."""
    header, events = None, []
    path = Path(path)
    if path.is_file():
        for line in path.read_text(encoding="utf-8",
                                   errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("kind") == "header":
                header = entry
            elif entry.get("kind") == "treatment":
                events.append(entry)
    events.sort(key=lambda e: (e.get("date") or "",
                               e.get("id") or ""))
    return header, events


def _next_id(events):
    top = 0
    for e in events:
        m = re.match(r"treat-(\d+)$", str(e.get("id") or ""))
        if m:
            top = max(top, int(m.group(1)))
    return f"treat-{top + 1:04d}"


def record_event(page, claim, grade, when, source, detail,
                 reason, recorded=None, seed=False,
                 register_path=REGISTER, root=ROOT):
    """Append one treatment event; returns the event. Validates
    the grade and that the subject page exists under `root` —
    a treatment event about a page that is not there is a
    recording error, not a finding."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}: {grade!r}")
    if not DATE_RE.fullmatch(when or ""):
        raise ValueError(f"date must be YYYY-MM-DD: {when!r}")
    if not (Path(root) / page).is_file():
        raise ValueError(f"subject page does not exist: {page}")
    _header, events = read_register(register_path)
    event = {"kind": "treatment",
             "id": _next_id(events),
             "date": when,
             "recorded": recorded or date.today().isoformat(),
             "subject": {"page": page, "claim": claim},
             "grade": grade,
             "treated_by": {"source": source, "detail": detail},
             "reason": reason}
    if seed:
        event["seed"] = True
    register_path = Path(register_path)
    register_path.parent.mkdir(parents=True, exist_ok=True)
    with register_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


# -- Standing grades ----------------------------------------------------------

def subject_standings(events):
    """Standing grade per subject (page, claim): the strongest
    signal governs (citator practice). Returns a dict keyed by
    (page, claim) with {"grade", "events": [ids in order]}."""
    out = {}
    for e in events:
        subject = e.get("subject") or {}
        key = (subject.get("page"), subject.get("claim"))
        grade = e.get("grade")
        if grade not in SEVERITY:
            continue
        slot = out.setdefault(key, {"grade": grade, "events": []})
        slot["events"].append(e.get("id"))
        if SEVERITY[grade] > SEVERITY[slot["grade"]]:
            slot["grade"] = grade
    return out


def page_standings(events):
    """Standing per page: the strongest grade across the
    page's subjects (page-level and claim-scoped alike — a
    page is flagged by its worst-treated claim, and the
    per-claim breakdown rides along)."""
    standings = subject_standings(events)
    pages = {}
    for (page, claim), slot in sorted(
            standings.items(),
            key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        entry = pages.setdefault(
            page, {"grade": slot["grade"], "claims": {}})
        if SEVERITY[slot["grade"]] > SEVERITY[entry["grade"]]:
            entry["grade"] = slot["grade"]
        if claim is not None:
            entry["claims"][claim] = slot["grade"]
    return pages


# -- The rests-on graph ---------------------------------------------------------

def _page_index(root):
    """Compiled-layer pages under `root`: {resolution key: rel}.
    Keys are the page stem ("hindsight"), the wiki-relative
    path without extension ("sources/hindsight") and the
    repo-relative path without extension
    ("wiki/sources/hindsight"). An ambiguous stem (two pages
    sharing it) resolves only via a path key."""
    wiki_dir = Path(root) / "wiki"
    pages = []
    if wiki_dir.is_dir():
        for path in sorted(wiki_dir.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in EXCLUDED_FILES \
                    or rel.startswith(EXCLUDED_DIRS):
                continue
            pages.append(rel)
    index = {}
    stems = {}
    for rel in pages:
        noext = rel[:-3] if rel.endswith(".md") else rel
        index[noext] = rel
        index[noext[len("wiki/"):]] = rel
        stems.setdefault(Path(rel).stem, []).append(rel)
    for stem, rels in stems.items():
        if len(rels) == 1:
            index[stem] = rels[0]
    return pages, index


def resting_edges(root=ROOT):
    """{page: {pages it rests on}} over the compiled layer:
    the targets of each page's `grounds` typed wikilinks
    (WikiCitadel v1's edge table), resolved to pages. Self-loops
    and unresolvable targets are dropped."""
    root = Path(root)
    _pages, index = _page_index(root)
    edges = {}
    for rel in _pages:
        text = (root / rel).read_text(encoding="utf-8",
                                      errors="ignore")
        _fields, body = parse_frontmatter(text)
        targets = set()
        for target, _anchor, _label, _heading, ltype \
                in _typed_links(body):
            if ltype != "grounds":
                continue
            resolved = index.get(target.strip())
            if resolved and resolved != rel:
                targets.add(resolved)
        if targets:
            edges[rel] = targets
    return edges


def _retired_claim_pages(root):
    """Claim pages retired under wiki_claims.py's rule,
    derived from evaluation/outcomes.jsonl: >= 3 outcomes
    whose 3 most recent all contradict. (Mirrors the fold in
    scripts/wiki_lint_lanes.py's Lane 2.)"""
    by_page = {}
    path = Path(root) / "evaluation" / "outcomes.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8",
                                   errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            by_page.setdefault(record.get("page"),
                               []).append(record)
    return {page for page, records in by_page.items()
            if page and len(records) >= 3
            and all(r.get("outcome") == "contradicts"
                    for r in records[-3:])}


def superseded_pages(root=ROOT):
    """{page: signal} for pages the wiki's own records mark
    superseded — the Lane-2 semantic signals, computed here so
    the lanes can import this module without a cycle."""
    root = Path(root)
    retired = _retired_claim_pages(root)
    out = {}
    wiki_dir = root / "wiki"
    if wiki_dir.is_dir():
        for path in sorted(wiki_dir.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in EXCLUDED_FILES \
                    or rel.startswith(EXCLUDED_DIRS):
                continue
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            fields, _body = parse_frontmatter(text)
            if not fields:
                continue
            status = str(fields.get("status")
                         or "").strip().lower()
            if status in ("superseded", "deprecated"):
                out[rel] = f"status: {status}"
                continue
            superseded_by = fields.get("superseded_by")
            if superseded_by is not None and str(
                    superseded_by).strip().lower() not in (
                    "", "null", "none", "~", "[]"):
                out[rel] = "superseded_by"
                continue
            if fields.get("claim") \
                    and (str(fields.get("outcome_status")
                             or "").strip().lower() == "retired"
                         or rel in retired):
                out[rel] = "claim retired"
    talk_dir = wiki_dir / "talk"
    if talk_dir.is_dir():
        for path in sorted(talk_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            fields, _body = parse_frontmatter(text)
            if not fields:
                continue
            dispute = str(fields.get("dispute_status")
                          or "").strip().lower()
            about = fields.get("about")
            if dispute == "resolved" and about \
                    and "supersed" in text.lower():
                out.setdefault(str(about),
                               "resolved talk page")
    return out


# -- Transitive weakening -------------------------------------------------------

def weakened_pages(root=ROOT, register_path=REGISTER):
    """Pages weakened by reliance on a fallen page (KeyCite
    Overruling Risk, computed transitively).

    Returns {"fallen": [...], "weakened": [...]}: each fallen
    row names the page and its basis (negative treatment
    event(s) and/or supersession signal); each weakened row
    names the page, its minimum distance from a fallen page,
    and every fallen ancestor with its shortest distance.
    Fallen pages are not also listed as weakened. Nothing is
    written back — weakening is a computed listing, never an
    automatic grade."""
    _header, events = read_register(register_path)
    standings = page_standings(events)
    fallen = {}
    for page, slot in sorted(standings.items()):
        if slot["grade"] == "negative":
            fallen.setdefault(page, []).append(
                {"kind": "treatment", "grade": "negative",
                 "claims": sorted(
                     c for c, g in slot["claims"].items()
                     if g == "negative")})
    for page, signal in sorted(superseded_pages(root).items()):
        fallen.setdefault(page, []).append(
            {"kind": "superseded", "signal": signal})
    edges = resting_edges(root)
    dependents = {}
    for page, targets in edges.items():
        for target in targets:
            dependents.setdefault(target, set()).add(page)
    # BFS outward from the fallen set over reverse edges.
    # Propagation runs THROUGH fallen pages too (a page resting
    # on a fallen page that itself rests on another fallen page
    # carries both bases); fallen pages are filtered out of the
    # weakened listing at the end.
    distance = {}   # page -> {fallen page: shortest distance}
    frontier = {page: {page} for page in fallen}
    depth = 0
    while frontier:
        depth += 1
        nxt = {}
        for src, bases in frontier.items():
            for dep in sorted(dependents.get(src, ())):
                slot = distance.setdefault(dep, {})
                for base in bases:
                    if base not in slot:
                        slot[base] = depth
                if dep not in nxt:
                    nxt[dep] = set(slot)
                else:
                    nxt[dep].update(slot)
        frontier = nxt
    weakened = []
    for page in sorted(distance):
        if page in fallen:
            continue
        by = [{"page": base, "distance": d}
              for base, d in sorted(
                  distance[page].items(),
                  key=lambda kv: (kv[1], kv[0]))]
        weakened.append({"page": page,
                         "distance": min(distance[page].values()),
                         "weakened_by": by})
    fallen_rows = [{"page": page, "basis": fallen[page]}
                   for page in sorted(fallen)]
    return {"fallen": fallen_rows, "weakened": weakened}


# -- Report (the lint lanes' input) --------------------------------------------

def treatment_report(root=ROOT, register_path=REGISTER):
    """The citator summary Lane 5 surfaces: event and subject
    counts by standing grade, the treated pages with their
    grades, the fallen set, and the weakened listing."""
    _header, events = read_register(register_path)
    standings = subject_standings(events)
    pages = page_standings(events)
    events_by_grade = {g: 0 for g in GRADES}
    for e in events:
        if e.get("grade") in events_by_grade:
            events_by_grade[e["grade"]] += 1
    subjects_by_grade = {g: 0 for g in GRADES}
    for slot in standings.values():
        subjects_by_grade[slot["grade"]] += 1
    weak = weakened_pages(root, register_path)
    edges = resting_edges(root)
    return {"events": len(events),
            "events_by_grade": events_by_grade,
            "subjects": len(standings),
            "subjects_by_grade": subjects_by_grade,
            "grounds_edges": sum(len(v) for v in edges.values()),
            "resting_pages": len(edges),
            "treated_pages": [
                {"page": page, "grade": slot["grade"],
                 "claims": slot["claims"]}
                for page, slot in sorted(pages.items())],
            "fallen": weak["fallen"],
            "weakened": weak["weakened"],
            "weakened_count": len(weak["weakened"])}


# -- CLI -------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Citation treatment register "
                    "(evaluation/treatment-register.jsonl): "
                    "record treatment events, compute standing "
                    "grades and transitive weakening.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="append a treatment event")
    p.add_argument("--page", required=True,
                   help="subject page, repo-relative")
    p.add_argument("--claim", default=None,
                   help="claim scope on the page (default: the "
                        "page as a whole)")
    p.add_argument("--grade", required=True, choices=GRADES)
    p.add_argument("--date", required=True,
                   help="treatment date, YYYY-MM-DD")
    p.add_argument("--source", required=True,
                   help="path of the record that treated it")
    p.add_argument("--detail", default="",
                   help="what treated it, in one line")
    p.add_argument("--reason", required=True,
                   help="why this grade")
    p.add_argument("--seed", action="store_true",
                   help="mark as a register seed")

    sub.add_parser("standing", help="standing grades (JSON)")
    sub.add_parser("weakened", help="transitive weakening (JSON)")
    sub.add_parser("report", help="the lane summary (JSON)")
    args = ap.parse_args(argv[1:])

    if args.cmd == "record":
        event = record_event(args.page, args.claim, args.grade,
                             args.date, args.source, args.detail,
                             args.reason, seed=args.seed)
        print(f"recorded {event['id']}: {args.page} "
              f"[{args.grade}]")
        return 0
    if args.cmd == "standing":
        _h, events = read_register()
        print(json.dumps(
            {"subjects": [
                {"page": page, "claim": claim,
                 "grade": slot["grade"],
                 "events": slot["events"]}
                for (page, claim), slot in sorted(
                    subject_standings(events).items(),
                    key=lambda kv: (kv[0][0], kv[0][1] or ""))]},
            indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "weakened":
        print(json.dumps(weakened_pages(), indent=2,
                         ensure_ascii=False))
        return 0
    if args.cmd == "report":
        print(json.dumps(treatment_report(), indent=2,
                         ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
