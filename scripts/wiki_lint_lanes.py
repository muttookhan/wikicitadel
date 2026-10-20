#!/usr/bin/env python3
"""Lint lanes: the wiki's lint restructured as six named lanes.

Modelled on portablellm.wiki's lint swarm (assessed in
docs/research-notes.md): parallel, single-purpose
checks that SURFACE issues for review and never silently rewrite.
Until now this wiki's lint ran as one undifferentiated pass (plus
one-off filings from collaborators); this script gives it the swarm's
shape — six named lanes, one surfacing report:

  Lane 1 — Contradictions: candidate consolidated beliefs from
    the governed observations pass (scripts/wiki_observe.py,
    imported in-process). A statement supported by two or more
    pages is where two tellings of one fact can drift apart, so
    the candidates are surfaced for the owner to rule on — the
    lane reports the candidate count and the top candidate.
    Since WikiCitadel v1 the lane also reports the open
    Contradiction Cases count, read from the Cases register
    (evaluation/contradiction-cases.jsonl,
    scripts/wiki_cases.py) — candidates are not Cases: a Case
    opens only on a same-fact, same-as-of-time conflict.
  Lane 2 — Stale: two signals. The primary signal is semantic:
    pages the wiki's own records mark replaced or retired
    (frontmatter status superseded/deprecated, a superseded_by
    pointer, a claim page retired under wiki_claims.py's rule, a
    resolved talk page recording supersession). The secondary
    signal is the 30-day frontmatter clock (`updated`, else
    `created`) — kept, but labelled secondary: on a young wiki
    it cannot fire, and its zero means nothing on its own.
    Two further eyes ride this lane (WikiCitadel v1):
    owner attestations — the POSITIVE freshness signal:
    a page carrying the owner's `verified_until` date
    (frontmatter, with `verified_by: owner`) counts as attested
    until that date and surfaces here as an "attestation
    expired" finding once it passes; and claim re-verification
    due dates from scripts/wiki_reverify.py (imported
    in-process) — claims whose FSRS-scheduled next check is due
    or overdue surface here as findings.
  Lane 3 — Missing: broken wikilinks and orphan lines extracted
    from scripts/wiki_validate.py's own output (subprocess), so
    the lane reports exactly what the validator sees.
  Lane 4 — Leaks: the export-surface leak lint
    (scripts/wiki_leak_lint.py, imported in-process) over the
    same surfaces it defines — Lens build, filings areas,
    newest take-home zip — with the checked-in baseline
    (scripts/leak-baseline.json) applied: only NEW findings
    surface ("N new (M baselined)"); credential-shaped classes
    are never baselined and always surface.
  Lane 6 — Superseded decisions (added in WikiCitadel v1): the
    superseded-decision gate (scripts/wiki_decision_gate.py,
    imported in-process; pattern: AsDecided / ex-rac-core,
    Apache-2.0) over wiki/** against the decisions register
    (evaluation/decisions-register.jsonl). References to a
    superseded decision FORM are classified HISTORICAL (inside
    the decision record, or framed as past) or LIVE
    (present-tense reliance). Only LIVE hits are listed; the
    lane surfaces, it never blocks — the gate's blocking mode
    is its standalone default.
  Lane 5 — Quotes: direct quotations verified verbatim against
    the ranges they cite (scripts/wiki_cite_lock.py, imported
    in-process; pattern: MetamusicX/zissa-wiki, MIT). A quotation
    counts when it carries a ^[cite:] marker on the same or the
    adjacent line; whitespace and smart quotes are normalised,
    nothing else. Claim-level citation coverage is young, so the
    lane's honest coverage number (quotations checked) is part of
    the report, and divergences are surfaced with the exact point
    of divergence for the owner to rule on.
    The lane also carries the caveat check (added in WikiCitadel v1,
    build): the compilation-fidelity companion — quotes
    verify that wording survived compilation, the caveat check
    verifies that QUALIFICATIONS did. A page is flagged when
    one of its raw sources states conditions, limits or scope
    explicitly (a heading or bold-labelled line naming them,
    or repeated conditional phrasing) and the page carries no
    caveat carriage (no conditions/limits/caveats section, no
    Caveat callout, no bold-labelled caveat line). Detection
    is deliberately conservative; a flag is a candidate for
    the owner to rule on, not a verdict. (Pattern: the
    Effortless Academic's measured caveat-stripping failure,
    via the survey.)
    Two further checks ride this lane (WikiCitadel v1)
    — Lane 5 is the
    statement-level citation-integrity lane, and both are
    about whether the statements on a compiled page can be
    relied on: **treatment signals** (the citator summary from
    scripts/wiki_treatment.py over
    evaluation/treatment-register.jsonl: how later records
    treated cited claims — followed / questioned / caution /
    negative, the strongest signal governing — plus transitive
    weakening, the pages resting on a fallen page over the
    typed `grounds` edges), and **editorial markers** (the
    inline flags {{cite}} / {{clarify}} / {{disputed}} counted
    by kind with their locations: statement-level epistemic
    state, where page frontmatter only tracks page-level
    state; pattern: the Coppermind wiki's editorial notation,
    via the survey).

Coaching (WikiCitadel v1):
every finding class that an agent can act on carries a
"**To clear this:**" line in the filing — what failed, why it
matters, and the concrete change that clears it, written for
collaborating agents (whose filings pass through these
lanes) as much as for the compiling agent. A lane that only
rejects teaches its contributors to route around it
(Halfaker et al., via the survey); the coaching line is
the path back. Lines
appear only for classes with findings this run, and they
change no count, verdict, or surfacing rule.

Alongside the lanes, the report carries one further eye
(WikiCitadel v1): **owner marks** — actionable marks
(correction / question) from the annotation layer over raw
(scripts/wiki_annotate.py) that no compiled page accounts for.
It is an eye on the report, not a seventh lane; the six-lane
structure above is unchanged.

The report is filed at wiki/filings/lint-lanes-<date>.md in the
filings style of wiki/filings/observations.md
(status: draft, confidence: observed, AWAITING OWNER callout).
Nothing is applied, fixed, or promoted by this script; the lanes
only surface. Deterministic ordering everywhere.

Usage:
  python3 scripts/wiki_lint_lanes.py [--lens-dir DIR]

Stdlib only (wiki_observe / wiki_leak_lint imported in-process;
wiki_validate run as a subprocess).
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"
STALE_DAYS = 30

EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observe = _load("wiki_observe")
leak = _load("wiki_leak_lint")
dgate = _load("wiki_decision_gate")
citelock = _load("wiki_cite_lock")
annotate = _load("wiki_annotate")
reverify = _load("wiki_reverify")
treatment = _load("wiki_treatment")
parse_frontmatter = observe.parse_frontmatter


# -- Lane 1: contradictions (observations candidates) --------------------

def _open_cases_count():
    """Open Contradiction Cases on the register
    (evaluation/contradiction-cases.jsonl, scripts/wiki_cases.py):
    a case-kind line whose folded status is open — an opening
    entry with status "open" and no ruling line for its id.
    Read in-process here (the register is a plain JSONL file);
    surfacing only, like every lane."""
    path = ROOT / "evaluation" / "contradiction-cases.jsonl"
    openings, ruled = {}, set()
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
            if entry.get("kind") == "case":
                openings[entry.get("case_id")] = entry.get("status")
            elif entry.get("kind") == "ruling":
                ruled.add(entry.get("case_id"))
    return sum(1 for cid, st in openings.items()
               if st == "open" and cid not in ruled)


def lane_contradictions():
    pages = observe.scan_pages()
    statements = []
    for rel, text in pages:
        fields, _body = parse_frontmatter(text)
        statements.extend(observe.cite_statements(rel, text))
        if fields:
            cs = observe.claim_statement(rel, text, fields)
            if cs:
                statements.append(cs)
    statements.sort(key=lambda s: (s.page, s.line, s.text))
    groups = observe.group_statements(statements)
    observations = observe.build_observations(groups)
    top = None
    if observations:
        first = observations[0]
        top = {"statement": observe.quote_of(first["representative"].text),
               "page": first["representative"].page,
               "pages": len(first["pages"])}
    return {"count": len(observations), "top": top,
            "pages_scanned": len(pages), "statements": len(statements),
            "cases_open": _open_cases_count()}


# -- Lane 2: stale ---------------------------------------------------------

def _page_date(fields):
    if not fields:
        return None
    for key in ("updated", "created"):
        value = fields.get(key)
        if value:
            m = DATE_RE.search(str(value))
            if m:
                return date(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)))
    return None


def _retired_claim_pages():
    """Claim pages retired under wiki_claims.py's own rule,
    derived from evaluation/outcomes.jsonl (that tool's source of
    truth): a page with >= 3 recorded outcomes whose 3 most
    recent all contradict. Returns (retired page set, number of
    outcomes recorded)."""
    by_page = {}
    recorded = 0
    path = ROOT / "evaluation" / "outcomes.jsonl"
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
            recorded += 1
    retired = {page for page, records in by_page.items()
               if page and len(records) >= 3
               and all(r.get("outcome") == "contradicts"
                       for r in records[-3:])}
    return retired, recorded


def attestation_state(fields, today):
    """The owner-attestation state of one page's frontmatter.

    An attestation is `verified_until: YYYY-MM-DD` carried with
    `verified_by: owner` (the Notion pattern; on a claim page
    the same fields attest the claim). Returns (state, until)
    where state is "current" (until >= today), "expired"
    (until < today), "invalid" (the field is present but the
    date cannot be parsed) or None (no attestation carried)."""
    if not fields:
        return None, None
    raw = fields.get("verified_until")
    if raw is None or str(raw).strip() == "":
        return None, None
    m = DATE_RE.search(str(raw))
    if not m:
        return "invalid", None
    until = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return ("expired" if until < today else "current"), until


def reverify_findings(today):
    """Claims whose re-verification is due or overdue, from
    scripts/wiki_reverify.py (imported in-process): the FSRS
    schedule over evaluation/reverify-history.jsonl. Only due
    and overdue claims surface — upcoming ones are on the
    schedule, not findings."""
    rows = []
    for row in reverify.due_claims(today):
        if row["status"] not in ("overdue", "due"):
            continue
        rows.append({"page": row["page"],
                     "due": row["due"].isoformat(),
                     "status": row["status"],
                     "days_overdue": row["days_overdue"],
                     "last_verified": (row["last_verified"].isoformat()
                                       if row["last_verified"] else None),
                     "verifications": row["verifications"]})
    return rows


def lane_stale(today):
    cutoff = today - timedelta(days=STALE_DAYS)
    stale = []
    semantic = []
    undated = 0
    scanned = 0
    claim_pages = 0
    attested_current = 0
    attestation_expired = []
    attestation_invalid = []
    retired_pages, outcomes_recorded = _retired_claim_pages()
    for path in sorted(WIKI.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXCLUDED_FILES or rel.startswith(EXCLUDED_DIRS):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        fields, _body = parse_frontmatter(text)
        # Owner attestation (positive freshness signal): the
        # owner's verified_until date, where a page carries one.
        a_state, a_until = attestation_state(fields, today)
        if a_state == "current":
            attested_current += 1
        elif a_state == "expired":
            attestation_expired.append({
                "page": rel, "verified_until": a_until.isoformat(),
                "verified_by": str(fields.get("verified_by") or "")})
        elif a_state == "invalid":
            attestation_invalid.append({
                "page": rel, "verified_until":
                    str(fields.get("verified_until"))})
        # Semantic signal: the wiki's own records marking this
        # page replaced or retired.
        if fields:
            status = str(fields.get("status")
                         or "").strip().lower()
            if status in ("superseded", "deprecated"):
                semantic.append({
                    "page": rel, "signal": f"status: {status}",
                    "detail": "frontmatter status marks the page "
                              "replaced or retired"})
            superseded_by = fields.get("superseded_by")
            if superseded_by is not None and str(
                    superseded_by).strip().lower() not in (
                    "", "null", "none", "~", "[]"):
                semantic.append({
                    "page": rel, "signal": "superseded_by",
                    "detail": f"frontmatter points at its "
                              f"replacement: {superseded_by}"})
            if fields.get("claim"):
                claim_pages += 1
                outcome_status = str(
                    fields.get("outcome_status")
                    or "").strip().lower()
                if outcome_status == "retired" \
                        or rel in retired_pages:
                    semantic.append({
                        "page": rel, "signal": "claim retired",
                        "detail": "claim page retired under "
                                  "wiki_claims.py's rule (3 most "
                                  "recent outcomes all contradict)"})
        when = _page_date(fields)
        if when is None:
            undated += 1
        elif when < cutoff:
            stale.append((when, rel))
    # Semantic signal, continued: a resolved talk page recording
    # a page's supersession. Talk pages live outside the scan set
    # above (wiki/talk/ is an excluded dir), so scan them here.
    talk_pages = 0
    talk_dir = WIKI / "talk"
    if talk_dir.is_dir():
        for path in sorted(talk_dir.glob("*.md")):
            talk_pages += 1
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            fields, _body = parse_frontmatter(text)
            if not fields:
                continue
            dispute = str(fields.get("dispute_status")
                          or "").strip().lower()
            if dispute == "resolved" \
                    and "supersed" in text.lower():
                semantic.append({
                    "page": str(fields.get("about")
                                or path.relative_to(ROOT).as_posix()),
                    "signal": "resolved talk page",
                    "detail": "talk page "
                              + path.relative_to(ROOT).as_posix()
                              + " is resolved and records a "
                              "supersession"})
    stale.sort(key=lambda item: (item[0], item[1]))
    semantic.sort(key=lambda h: (h["page"], h["signal"]))
    attestation_expired.sort(key=lambda h: h["page"])
    attestation_invalid.sort(key=lambda h: h["page"])
    due_rows = reverify_findings(today)
    return {"count": len(stale),
            "oldest": [{"page": rel, "date": when.isoformat()}
                       for when, rel in stale[:10]],
            "scanned": scanned, "undated": undated,
            "cutoff": cutoff.isoformat(),
            "semantic": semantic,
            "semantic_count": len(semantic),
            "claim_pages": claim_pages,
            "outcomes_recorded": outcomes_recorded,
            "talk_pages": talk_pages,
            "attested_current": attested_current,
            "attestation_expired": attestation_expired,
            "attestation_expired_count": len(attestation_expired),
            "attestation_invalid": attestation_invalid,
            "reverify_due": due_rows,
            "reverify_due_count": len(due_rows)}


# -- Lane 3: missing (validator output) ------------------------------------

def lane_missing():
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "wiki_validate.py")],
        cwd=ROOT, capture_output=True, text=True)
    lines = (proc.stdout + proc.stderr).splitlines()
    broken = sorted({ln.strip() for ln in lines
                     if "broken wikilink" in ln.lower()})
    orphans = sorted({ln.strip() for ln in lines
                      if "orphan" in ln.lower()})
    return {"broken_count": len(broken), "broken": broken,
            "orphan_count": len(orphans), "orphans": orphans,
            "validator_exit": proc.returncode}


# -- Lane 4: leaks -----------------------------------------------------------

def lane_leaks(lens_dir):
    surfaces = leak.collect_surfaces(lens_dir)
    baseline = leak.load_baseline()
    leak.annotate_baseline(surfaces, baseline)
    new_total = sum(s["new_total"] for s in surfaces)
    return {"verdict": "findings" if new_total else "clean",
            "findings_total": new_total,
            "new_total": new_total,
            "baselined_total": sum(s["baselined_total"]
                                   for s in surfaces),
            "baseline_present": baseline is not None,
            "surfaces": surfaces}


# -- Lane 5: quotes ----------------------------------------------------------

def lane_quotes():
    report = citelock.quote_report()
    return {"checked": report["checked"],
            "pages": report["pages"],
            "verified": report["verified"],
            "divergences": report["divergences"],
            "caveats": caveat_findings(),
            "treatment": treatment.treatment_report(),
            "markers": editorial_markers()}


# -- Lane 5 (continued): caveat carriage ---------------------------------
#
# The compilation-fidelity companion to the quotes check above:
# quotes verify that wording survived compilation; this check
# verifies that QUALIFICATIONS did (build; pattern: the
# Effortless Academic's caveat-stripping failure — a compiled
# page dropped the conditions that made its source's claims
# true, and later answers inherited the overstatement).
#
# A source "states conditions explicitly" on conservative
# evidence only: a heading that names them (starts with
# conditions/scope/applicability, or mentions limitations or
# caveats anywhere in the heading), a bold-labelled line
# (**Limitation:**, **Scope:**, ...), or repeated conditional
# phrasing (only if / does not apply / valid only / ... —
# at least CAVEAT_WEAK_MIN hits; a single "only if" in prose
# is not a stated limitation, and a plain unbolded label
# inside quoted material, e.g. "SCOPE:" in an email dump,
# does not count). A page "carries" the caveat when it has a
# conditions/limits/caveats/scope section heading, a Caveat
# callout, a bold-labelled caveat line, or the literal phrase
# "conditions and limits". Pages that do carry their sources'
# caveats are counted, not listed; the rest surface as
# candidates — the owner rules on each, as in every lane.

CAVEAT_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
CAVEAT_BOLD_LABEL_RE = re.compile(
    r"^\s{0,3}(?:\*\*|__)(limitations?|caveats?|conditions|scope|"
    r"applicability)(?:\*\*|__)?\s*:", re.I | re.M)
CAVEAT_WEAK_RES = [re.compile(p, re.I) for p in (
    r"\bonly if\b", r"\bdoes not apply\b", r"\bnot applicable\b",
    r"\bvalid only\b", r"\bapplies only\b",
    r"\bno longer applies\b", r"\bout of scope\b")]
CAVEAT_WEAK_MIN = 3
CAVEAT_SOURCE_SUFFIXES = (".md", ".txt")
CAVEAT_SOURCE_MAX_CHARS = 2_000_000
CAVEAT_PAGE_HEADING_RE = re.compile(
    r"^#{2,}\s+(conditions|limitations|limits|caveats|scope)\b",
    re.I | re.M)
CAVEAT_PAGE_CALLOUT_RE = re.compile(
    r"^>\s*\[!\w+\]\s*Caveat", re.I | re.M)
CAVEAT_PAGE_PHRASE_RE = re.compile(
    r"conditions and limits|conditions & limits", re.I)


def source_caveat_signals(text):
    """Explicit condition/limit/scope signals in a raw source.

    Returns {"strong": int, "weak": int}: strong counts the
    headings and bold-labelled lines that name conditions,
    limits or scope; weak counts conditional-phrasing hits.
    See the block comment above for the conservative rules."""
    strong = 0
    for m in CAVEAT_HEADING_RE.finditer(text):
        h = m.group(1).lower()
        if "limitation" in h or "caveat" in h or re.match(
                r"(conditions|scope|applicability)\b", h):
            strong += 1
    strong += len(CAVEAT_BOLD_LABEL_RE.findall(text))
    weak = sum(len(rx.findall(text)) for rx in CAVEAT_WEAK_RES)
    return {"strong": strong, "weak": weak}


def source_states_caveats(signals):
    """A source states conditions explicitly when it carries
    at least one strong marker, or conditional phrasing at or
    past the conservative weak threshold."""
    return signals["strong"] >= 1 \
        or signals["weak"] >= CAVEAT_WEAK_MIN


def page_carries_caveat(text):
    """True when a compiled page carries caveat carriage for
    its claims: a conditions/limits/caveats/scope section, a
    Caveat callout, a bold-labelled caveat line, or the
    literal phrase "conditions and limits"."""
    return bool(CAVEAT_PAGE_HEADING_RE.search(text)
                or CAVEAT_PAGE_CALLOUT_RE.search(text)
                or CAVEAT_PAGE_PHRASE_RE.search(text)
                or CAVEAT_BOLD_LABEL_RE.search(text))


def caveat_findings(root=None):
    """Lost-caveat candidates over the compiled layer.

    Walks wiki/** under `root` (the repo root; the other
    lanes' exclusions apply), reads each page's frontmatter
    `sources`, and flags a page when at least one cited raw
    source states conditions explicitly and the page carries
    none of them. Returns {"checked", "carried", "findings"}:
    checked = pages compiling at least one caveated source,
    carried = of those, the pages that do carry a caveat;
    findings = the rest, deterministically ordered."""
    root = Path(root) if root is not None else ROOT
    wiki_dir = root / "wiki"
    signals_cache = {}

    def signals_for(src_rel):
        if src_rel not in signals_cache:
            result = None
            path = root / src_rel
            if path.is_file() \
                    and path.suffix in CAVEAT_SOURCE_SUFFIXES:
                text = path.read_text(encoding="utf-8",
                                      errors="ignore")
                result = source_caveat_signals(
                    text[:CAVEAT_SOURCE_MAX_CHARS])
            signals_cache[src_rel] = result
        return signals_cache[src_rel]

    def as_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    checked = 0
    carried = 0
    findings = []
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
            caveated = []
            for src in as_list(fields.get("sources")):
                if not src or not isinstance(src, str):
                    continue
                signals = signals_for(src)
                if signals is not None \
                        and source_states_caveats(signals):
                    caveated.append({"source": src,
                                     "strong": signals["strong"],
                                     "weak": signals["weak"]})
            if not caveated:
                continue
            checked += 1
            if page_carries_caveat(text):
                carried += 1
            else:
                caveated.sort(key=lambda c: c["source"])
                findings.append({"page": rel,
                                 "sources": caveated})
    findings.sort(key=lambda f: f["page"])
    return {"checked": checked, "carried": carried,
            "findings": findings}


# -- Lane 5 (continued): editorial markers --------------------------------
#
# Statement-level editorial markers (WikiCitadel v1;
# pattern: the Coppermind wiki's editorial notation, via
# find 17 of the media lane): inline flags in a page's
# prose — {{cite}} (this statement needs a citation it lacks),
# {{clarify}} (this statement is unclear or ambiguous as
# written), {{disputed}} (this statement is under dispute —
# it pairs with a talk page or a Contradiction callout).
# Frontmatter tracks a page's epistemic state at page level;
# these flags mark it at the statement, where the reader
# trips over it. The check COUNTS markers by kind and lists
# their locations; it never writes one. Counting rules mirror
# the corpus's other readers: fenced code blocks and inline
# code spans never yield a marker (a mention of the convention
# written in backticks is documentation, not a use), the
# frontmatter is not prose and is skipped, and the compiled
# layer's standing exclusions apply (filings and talk pages
# are not counted). A marker mentioned in bare prose — not
# backticked — DOES count: until the schema text lands, the
# count cannot tell a use from a mention, and the locations
# list shows which is which.

EDITORIAL_MARKERS = ("cite", "clarify", "disputed")
EDITORIAL_MARKER_RE = re.compile(r"\{\{(cite|clarify|disputed)\}\}")


def _marker_visible_lines(text):
    """(line number, visible text) per body line: the leading
    frontmatter block, fenced code blocks and inline code
    spans are blanked, so only prose a reader sees is left."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    in_fence = False
    for i in range(start, len(lines)):
        line = lines[i]
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i + 1, re.sub(r"`[^`\n]*`", "", line)


def editorial_markers(root=None):
    """Editorial-marker census over the compiled layer.

    Returns {"counts": {kind: n}, "total": n, "locations":
    [{"page", "line", "kind", "excerpt"}]} — locations in
    deterministic (page, line, kind) order, excerpts from the
    original line, capped."""
    root = Path(root) if root is not None else ROOT
    wiki_dir = root / "wiki"
    counts = {kind: 0 for kind in EDITORIAL_MARKERS}
    locations = []
    if wiki_dir.is_dir():
        for path in sorted(wiki_dir.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in EXCLUDED_FILES \
                    or rel.startswith(EXCLUDED_DIRS):
                continue
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            original = text.splitlines()
            for lineno, visible in _marker_visible_lines(text):
                for m in EDITORIAL_MARKER_RE.finditer(visible):
                    kind = m.group(1)
                    counts[kind] += 1
                    excerpt = original[lineno - 1].strip()
                    if len(excerpt) > 120:
                        excerpt = excerpt[:119].rstrip() + "…"
                    locations.append({"page": rel,
                                      "line": lineno,
                                      "kind": kind,
                                      "excerpt": excerpt})
    locations.sort(key=lambda h: (h["page"], h["line"], h["kind"]))
    return {"counts": counts,
            "total": sum(counts.values()),
            "locations": locations}


# -- Lane 6: superseded decisions ------------------------------------------

def lane_decision_gate():
    result = dgate.scan()
    live = [h for h in result["hits"]
            if h["classification"] == "LIVE"]
    historical = [h for h in result["hits"]
                  if h["classification"] == "HISTORICAL"]
    return {"live": live, "live_count": len(live),
            "historical_count": len(historical),
            "forms": len(result["forms"]),
            "files_scanned": result["files_scanned"]}


# -- Owner marks: unaddressed annotations (eye, not a lane) ---------------

def lane_annotations():
    """Actionable owner marks (correction / question) from the
    annotation layer over raw (scripts/wiki_annotate.py) that no
    compiled page accounts for with a ^[mark: ...] reference.
    A mark the ingest has not dealt with keeps surfacing here
    until a page applies it, answers it, or carries it as an
    open note and cites the mark."""
    rows = annotate.unaddressed_marks()
    return {"count": len(rows), "items": rows,
            "sources": len({r["source"] for r in rows})}


# -- Report ------------------------------------------------------------------

def render(lanes, run_date, lens_note):
    l1, l2, l3, l4, l5, l6 = (lanes["contradictions"], lanes["stale"],
                              lanes["missing"], lanes["leaks"],
                              lanes["quotes"], lanes["decision_gate"])
    la = lanes["annotations"]
    missing_total = l3["broken_count"] + l3["orphan_count"]
    lines = [
        "---",
        f"title: Lint lanes — {run_date} (surfaced issues for the owner)",
        "type: query",
        f"created: {run_date}",
        f"updated: {run_date}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [lint, lanes, proposal, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Lint lanes — {run_date}",
        "",
        "> [!warning] AWAITING OWNER — surfaced issues, nothing applied",
        "> Generated by the lint-lanes pass (`scripts/wiki_lint_lanes.py`),"
        " modelled on portablellm.wiki's lint swarm: six named lanes run"
        " in one pass and surface what they find here for the owner's"
        " review. **Nothing in this file is canonical, no page has been"
        " changed, and nothing here has been fixed or applied.** Each"
        " item moves only when the owner rules on it.",
        "",
        f"Summary: contradictions {l1['count']} · stale"
        f" {l2['semantic_count']} semantic ({l2['count']} by the"
        f" 30-day clock; {l2['attestation_expired_count']}"
        f" attestation(s) expired, {l2['reverify_due_count']}"
        f" claim re-verification(s) due) · missing"
        f" {missing_total} · leaks"
        f" {l4['new_total']} new ({l4['baselined_total']} baselined;"
        f" verdict: {l4['verdict']}) · quotes {l5['checked']}"
        f" checked, {len(l5['divergences'])} divergent,"
        f" caveats {len(l5['caveats']['findings'])} lost-caveat"
        f" candidate(s)"
        f" · treatment {l5['treatment']['subjects']} subject(s)"
        f" ({l5['treatment']['subjects_by_grade']['negative']}"
        f" negative standing),"
        f" {l5['treatment']['weakened_count']} weakened"
        f" · editorial markers {l5['markers']['total']}"
        f" · decision gate {l6['live_count']} live"
        f" ({l6['historical_count']} historical)"
        f" · owner marks {la['count']} unaddressed.",
        "",
        "## Lane 1 — Contradictions",
        "",
        f"Observation candidates from the observations pass"
        f" (`scripts/wiki_observe.py`): **{l1['count']}**"
        f" ({l1['pages_scanned']} pages scanned,"
        f" {l1['statements']} citable statements). A candidate is one"
        f" statement supported by two or more pages — the place two"
        f" tellings of one fact can drift into contradiction.",
        "",
        f"Contradiction Cases on the register"
        f" (`evaluation/contradiction-cases.jsonl`,"
        f" `scripts/wiki_cases.py`): **{l1['cases_open']} open**."
        f" A Case opens only when two claims about the same fact"
        f" cannot both be true at the same as-of time; candidates"
        f" above are not Cases until that test is met.",
        "",
    ]
    if l1["top"]:
        lines += [
            f"Top candidate (supported by {l1['top']['pages']} pages,"
            f" verbatim from `{l1['top']['page']}`):",
            "",
            f"> {l1['top']['statement']}",
            "",
            "The full candidate set with its evidence lives in the"
            " observations filing for the same period"
            " (`wiki/filings/observations-*.md`).",
            "",
        ]
    else:
        lines += ["No multi-page statement groups qualify this run.", ""]
    if l1["top"] or l1["cases_open"]:
        lines += [
            "**To clear this:** rule on the candidate — if two"
            " tellings of one fact disagree, reconcile the page"
            " or filing you own to the governing telling and"
            " note the supersession there; if the two claims"
            " cannot both be true at the same as-of time, open"
            " a Contradiction Case (`python3"
            " scripts/wiki_cases.py`) and adjudicate it on the"
            " register. A candidate the owner rules a false"
            " positive is noted as ruled, so the next run's"
            " context is honest. Unruled candidates keep"
            " surfacing — that is the lane working, not failing.",
            "",
        ]
    lines += [
        "## Lane 2 — Stale",
        "",
        f"**Semantic signal (primary): {l2['semantic_count']}** — a"
        f" page counts here when the wiki's own records say it was"
        f" replaced or retired: frontmatter `status` superseded or"
        f" deprecated; a frontmatter `superseded_by` pointer; a"
        f" claim page retired under `scripts/wiki_claims.py`'s rule"
        f" (frontmatter `outcome_status: retired`, or"
        f" `evaluation/outcomes.jsonl` holding 3+ outcomes for it"
        f" with the 3 most recent all contradicting); or a resolved"
        f" talk page recording its supersession. Checked over"
        f" {l2['scanned']} pages ({l2['claim_pages']} claim pages,"
        f" {l2['outcomes_recorded']} outcomes recorded,"
        f" {l2['talk_pages']} talk pages). Body-text mentions of"
        f" \u201csuperseded\u201d are deliberately not used: in this"
        f" corpus they describe other projects' contents, not this"
        f" wiki's pages.",
        "",
    ]
    if l2["semantic"]:
        lines += [f"- `{h['page']}` — {h['signal']} ({h['detail']})"
                  for h in l2["semantic"]]
        lines.append("")
        lines += [
            "**To clear this:** complete the retirement the"
            " record already started — point the page's"
            " `superseded_by` at its replacement (or record"
            " the retirement on the claim page itself), so"
            " the wiki's own records, not this lane, say the"
            " page is replaced. If the page is in fact"
            " current, remove the stale marker at its source:"
            " a marker left behind keeps superseded knowledge"
            " alive in every answer that cites the page.",
            "",
        ]
    else:
        lines += [
            "No page is marked replaced or retired this run. This"
            " zero is produced by the checks above, not by a"
            " threshold the wiki is too young to cross.",
            "",
        ]
    lines += [
        f"**30-day clock (secondary): {l2['count']}** — pages whose"
        f" frontmatter `updated` (else `created`) predates"
        f" {l2['cutoff']} (more than {STALE_DAYS} days before"
        f" {run_date}), of {l2['scanned']} pages scanned"
        f" ({l2['undated']} pages carry no date and cannot be"
        f" judged by the clock). Kept as a secondary signal: it"
        f" cannot fire on a young wiki, and once the wiki is old"
        f" enough it catches quiet neglect the semantic signal"
        f" misses.",
        "",
    ]
    if l2["oldest"]:
        lines += ["Oldest first (up to 10):", ""]
        lines += [f"- `{item['page']}` — {item['date']}"
                  for item in l2["oldest"]]
        lines.append("")
    else:
        lines += ["No page crosses the clock threshold this run.", ""]
    lines += [
        f"**Owner attestations (positive signal):"
        f" {l2['attested_current']} current,"
        f" {l2['attestation_expired_count']} expired** — a page"
        f" the owner has personally verified carries"
        f" `verified_until` (with `verified_by: owner`) in its"
        f" frontmatter; on a claim page the same fields attest"
        f" the claim. Unlike every other signal in this lane,"
        f" an attestation is positive evidence of freshness"
        f" with a stated horizon: while it runs, the page is"
        f" attested; once the date passes, the attestation —"
        f" not the page — is what expires, and it surfaces"
        f" here for the owner to renew or let lapse. Agents"
        f" never write attestations.",
        "",
    ]
    if l2["attestation_expired"]:
        lines += ["Attestation expired:", ""]
        lines += [f"- `{h['page']}` — verified until"
                  f" {h['verified_until']}"
                  f" (verified_by: {h['verified_by'] or '—'})"
                  for h in l2["attestation_expired"]]
        lines.append("")
    if l2["attestation_invalid"]:
        lines += ["Attestation present but its date cannot be"
                  " parsed:", ""]
        lines += [f"- `{h['page']}` — verified_until:"
                  f" {h['verified_until']}"
                  for h in l2["attestation_invalid"]]
        lines.append("")
    if not l2["attestation_expired"] and not l2["attestation_invalid"]:
        lines += ["No expired or unparseable attestation this"
                  " run.", ""]
    else:
        lines += [
            "**To clear this:** only the owner renews an"
            " attestation — agents never write `verified_until`"
            " or `verified_by`. Surface the page to the owner"
            " for re-verification and leave the date untouched"
            " until they rule; an agent-edited date would"
            " counterfeit the one positive freshness signal"
            " this wiki has.",
            "",
        ]
    lines += [
        f"**Claim re-verification due:"
        f" {l2['reverify_due_count']}** — each claim's next"
        f" check is scheduled from its own verification history"
        f" (`scripts/wiki_reverify.py`, FSRS-inspired: stability"
        f" grows on passes, shrinks on fail/changed; due when"
        f" predicted retrievability decays to 0.90), replacing"
        f" any fixed-interval clock. History:"
        f" `evaluation/reverify-history.jsonl`. Only due and"
        f" overdue claims surface here; the full schedule is"
        f" `python3 scripts/wiki_reverify.py due`.",
        "",
    ]
    if l2["reverify_due"]:
        lines += ["Due or overdue, most overdue first:", ""]
        for h in l2["reverify_due"]:
            last = (f"last verified {h['last_verified']}"
                    if h["last_verified"] else
                    "never verified (as_of anchor)")
            od = (f"{h['days_overdue']}d overdue"
                  if h["status"] == "overdue" else "due today")
            lines.append(f"- `{h['page']}` — due {h['due']}"
                         f" ({od}; {last};"
                         f" {h['verifications']} verification(s)"
                         f" on record)")
        lines.append("")
        lines += [
            "**To clear this:** run the claim's re-verification"
            " (`python3 scripts/wiki_reverify.py`) against its"
            " sources and record the outcome in"
            " `evaluation/reverify-history.jsonl` — a pass"
            " reschedules the claim; a claim that no longer"
            " verifies is corrected or retired on its page,"
            " never silently re-dated.",
            "",
        ]
    else:
        lines += ["No claim's re-verification is due this run.",
                  ""]
    lines += [
        "## Lane 3 — Missing",
        "",
        f"From `scripts/wiki_validate.py` (exit {l3['validator_exit']}):"
        f" broken-wikilink lines **{l3['broken_count']}**, orphan lines"
        f" **{l3['orphan_count']}**.",
        "",
    ]
    if l3["broken"]:
        lines += ["Broken wikilinks:", ""]
        lines += [f"- {ln}" for ln in l3["broken"]]
        lines.append("")
        lines += [
            "**To clear this:** fix the link to name the page"
            " that exists (links resolve by wiki-relative stem)"
            " — or, if the link states an intent, create the"
            " missing page. A link left pointing nowhere breaks"
            " the graph every answer navigates by.",
            "",
        ]
    if l3["orphans"]:
        lines += ["Orphans:", ""]
        lines += [f"- {ln}" for ln in l3["orphans"]]
        lines.append("")
        lines += [
            "**To clear this:** link the orphan from the page"
            " that should lead to it (its parent topic, or"
            " `wiki/index.md`), or record on the page itself"
            " why it stands alone. An unlinked page is"
            " invisible to graph-ranked retrieval.",
            "",
        ]
    if not l3["broken"] and not l3["orphans"]:
        lines += [
            "The validator reports no broken wikilinks this run. It"
            " does not currently emit an orphan section, so the orphan"
            " count is the count of orphan lines in its output: zero.",
            "",
        ]
    baseline_note = (
        "the checked-in baseline (`scripts/leak-baseline.json`)"
        " is applied: a finding is baselined when the exact line"
        " it matched on was fingerprinted by an audited run, and"
        " only NEW findings are listed below. Credential-shaped"
        " classes (bearer-token and kin) are never baselined and"
        " surface on every run until the owner rules on them."
        if l4["baseline_present"] else
        "no baseline is checked in, so every finding counts as"
        " new (regenerate with `scripts/wiki_leak_lint.py"
        " --write-baseline` after an audit).")
    lines += [
        "## Lane 4 — Leaks",
        "",
        f"Export-surface leak lint (`scripts/wiki_leak_lint.py`):"
        f" **{l4['new_total']} new** findings"
        f" ({l4['baselined_total']} baselined) across"
        f" {len(l4['surfaces'])} surfaces; overall verdict:"
        f" **{l4['verdict']}**. {lens_note} In this lane,"
        f" {baseline_note} Findings name file, pattern class, and"
        f" count only — never a matched value.",
        "",
    ]
    any_new = False
    for s in l4["surfaces"]:
        if not s["present"]:
            lines.append(f"- [{s['surface']}] {s['location']} —"
                         f" not present, skipped")
            continue
        lines.append(f"- [{s['surface']}] {s['location']} —"
                     f" {s['files_scanned']} files scanned,"
                     f" {s['new_total']} new"
                     f" ({s['baselined_total']} baselined),"
                     f" verdict: {s['verdict']}")
        for f in s["findings"]:
            if f["new_count"]:
                any_new = True
                note = (f" (+{f['baselined_count']} baselined)"
                        if f["baselined_count"] else "")
                lines.append(f"  - `{f['file']}`: {f['pattern']}"
                             f" x{f['new_count']}{note}")
    if not any_new:
        lines.append("- No new findings on any surface this run.")
    else:
        lines += [
            "",
            "**To clear this:** decide which kind each finding"
            " is. A REAL secret: rotate it at its source and"
            " scrub the surface — never baseline a real secret"
            " to silence the lane. Prose or a benign number"
            " that merely matches a pattern's shape: the owner"
            " rules on it, and only an audited run re-baselines"
            " (`python3 scripts/wiki_leak_lint.py"
            " --write-baseline`); an agent never baselines its"
            " own findings. Credential-shaped classes are"
            " never baselined and keep surfacing until the"
            " owner rules — that persistence is deliberate.",
        ]
    lines += [
        "",
        "Calibration note: the pattern classes are the gateway"
        " scanner's, tuned to BLOCK staged proposals on a single"
        " hit. Over bulk historical text the same classes also match"
        " ordinary long numbers (epoch timestamps, asset IDs) that"
        " pass the Luhn check by chance, and prose that describes a"
        " pattern. A finding here is a prompt to look, not a verdict"
        " that a secret leaked; the owner rules on each.",
        "",
        "## Lane 5 — Quotes",
        "",
        f"Direct quotations verified verbatim against the ranges"
        f" they cite (`scripts/wiki_cite_lock.py`; pattern:"
        f" MetamusicX/zissa-wiki, MIT): **{l5['checked']}**"
        f" checkable quotation(s) on {l5['pages']} page(s) — a"
        f" quotation counts when it carries a `^[cite:]` marker on"
        f" the same or the adjacent line. **{l5['verified']}**"
        f" verified verbatim, **{len(l5['divergences'])}**"
        f" divergent. Only whitespace and smart quotes are"
        f" normalised; capitalisation and wording count. The"
        f" coverage number is the honest one: claim-level"
        f" citation is young in this wiki, so few quotations are"
        f" checkable yet — the lane grows as citation spreads.",
        "",
    ]
    if l5["divergences"]:
        lines += ["Divergences (exact point of divergence shown):",
                  ""]
        for d in l5["divergences"]:
            quote = d["quote"]
            if len(quote) > 120:
                quote = quote[:119].rstrip() + "…"
            lines.append(
                f"- `{d['page']}` line {d['page_line']}:"
                f" \u201c{quote}\u201d — {d['divergence']}")
        lines.append("")
        lines += [
            "**To clear this:** compare the quote against the"
            " cited range at the point of divergence — correct"
            " the PAGE's wording to the source's, or fix the"
            " citation to the range the quote actually comes"
            " from. Never edit the source to match the page:"
            " the lockfile exists to catch exactly that drift.",
            "",
        ]
    else:
        lines += ["No divergent quotations this run.", ""]
    cav = l5["caveats"]
    lines += [
        "### Caveat carriage (Lane 5, continued)",
        "",
        f"Caveat carriage — the compilation-fidelity companion"
        f" to the quotes check above (pattern: the Effortless"
        f" Academic's measured failure: the compiled page"
        f" stripped its source's conditions, and later answers"
        f" inherited the overstatement): **{cav['checked']}**"
        f" page(s) compile a source that states conditions,"
        f" limits or scope explicitly (a heading or"
        f" bold-labelled line naming them, or repeated"
        f" conditional phrasing); **{cav['carried']}** of them"
        f" carry a conditions/limits/caveats section, a Caveat"
        f" callout, or a labelled caveat line;"
        f" **{len(cav['findings'])}** carry none and surface"
        f" below as lost-caveat candidates. Detection is"
        f" deliberately conservative, and a candidate is not a"
        f" verdict: the conditions may be immaterial to the"
        f" page's claims, or carried in prose this check"
        f" cannot see — the owner rules on each.",
        "",
    ]
    if cav["findings"]:
        lines += ["Lost-caveat candidates (page — the source"
                  " whose stated conditions it does not visibly"
                  " carry):", ""]
        for f in cav["findings"]:
            for c in f["sources"]:
                if c["strong"]:
                    signal = (f"{c['strong']} explicit"
                              f" condition/limit marker(s)")
                else:
                    signal = (f"conditional phrasing only"
                              f" ({c['weak']} hits)")
                lines.append(f"- `{f['page']}` —"
                             f" `{c['source']}` ({signal})")
        lines.append("")
        lines += [
            "**To clear this:** carry the source's conditions"
            " on the page — a conditions/limits section, a"
            " Caveat callout, or a bold-labelled caveat line"
            " naming the scope the source states — so answers"
            " compiled from the page inherit the qualification"
            " instead of the overstatement. If the conditions"
            " are immaterial to the page's claims, that is the"
            " owner's ruling to record, not an agent's to"
            " assume.",
            "",
        ]
    else:
        lines += ["No lost-caveat candidates this run.", ""]
    trt = l5["treatment"]
    lines += [
        "### Treatment signals (Lane 5, continued)",
        "",
        f"Citation treatment — the citator half of citation"
        f" integrity (`scripts/wiki_treatment.py` over"
        f" `evaluation/treatment-register.jsonl`; pattern:"
        f" Shepard's / KeyCite treatment signals and KeyCite"
        f" Overruling Risk, via the survey): the"
        f" lockfile proves a cited source has not *changed*;"
        f" treatment records whether the claim it supports"
        f" still *stands*. **{trt['events']}** treatment"
        f" event(s) over **{trt['subjects']}** subject(s)"
        f" (a subject is a page, or one claim on it — flags"
        f" attach to claims the way KeyCite flags attach to"
        f" points of law): standing grades followed"
        f" {trt['subjects_by_grade']['followed']} · questioned"
        f" {trt['subjects_by_grade']['questioned']} · caution"
        f" {trt['subjects_by_grade']['caution']} · negative"
        f" {trt['subjects_by_grade']['negative']} — a"
        f" subject's standing is its STRONGEST signal, per"
        f" citator practice: the most negative treatment"
        f" governs the flag.",
        "",
    ]
    if trt["treated_pages"]:
        lines += ["Treated pages (page — standing grade;"
                  " claim-scoped grades in brackets):", ""]
        for tp in trt["treated_pages"]:
            claims = "; ".join(
                f"[{grade}] {claim}"
                for claim, grade in sorted(tp["claims"].items()))
            if len(claims) > 160:
                claims = claims[:159].rstrip() + "…"
            suffix = f" — {claims}" if claims else ""
            lines.append(f"- `{tp['page']}` — {tp['grade']}"
                         f"{suffix}")
        lines.append("")
    else:
        lines += ["No treatment events on the register yet.",
                  ""]
    lines += [
        f"**Transitive weakening: {trt['weakened_count']}"
        f" page(s) weakened** — a page that rests on a fallen"
        f" page (negative standing, or marked superseded by"
        f" the wiki's own records) is weakened by reliance"
        f" alone, computed over the batch-3.1 typed `grounds`"
        f" edges ({trt['grounds_edges']} edge(s) from"
        f" {trt['resting_pages']} page(s) — the reliance"
        f" graph is young, so a zero here is a coverage"
        f" statement, not an all-clear). Weakening is"
        f" computed, never written back: no page's grade is"
        f" edited by this pass.",
        "",
    ]
    if trt["weakened"]:
        lines += ["Weakened pages (page — distance — fallen"
                  " basis):", ""]
        for w in trt["weakened"]:
            basis = "; ".join(
                f"`{b['page']}` at distance {b['distance']}"
                for b in w["weakened_by"])
            lines.append(f"- `{w['page']}` — {basis}")
        lines.append("")
    else:
        lines += ["No page rests on a fallen page over the"
                  " typed grounds edges this run.", ""]
    mrk = l5["markers"]
    lines += [
        "### Editorial markers (Lane 5, continued)",
        "",
        f"Statement-level editorial markers (pattern: the"
        f" Coppermind wiki's editorial notation, via the"
        f" survey): inline flags in a page's prose —"
        f" `{{{{cite}}}}` (this statement needs a citation it"
        f" lacks), `{{{{clarify}}}}` (unclear or ambiguous as"
        f" written), `{{{{disputed}}}}` (under dispute; pairs"
        f" with a talk page or a Contradiction callout)."
        f" Frontmatter tracks state at page level; these mark"
        f" it at the statement. **{mrk['total']}** marker(s)"
        f" on the compiled layer: cite"
        f" {mrk['counts']['cite']} · clarify"
        f" {mrk['counts']['clarify']} · disputed"
        f" {mrk['counts']['disputed']}. Fenced code and"
        f" inline code never count — a mention of the"
        f" convention in backticks is documentation, not a"
        f" use; a mention in bare prose DOES count, and the"
        f" locations list shows which is which.",
        "",
    ]
    if mrk["locations"]:
        lines += ["Marker locations (page line — kind):", ""]
        for h in mrk["locations"]:
            lines.append(f"- `{h['page']}` line {h['line']} —"
                         f" {{{{{h['kind']}}}}}: {h['excerpt']}")
        lines.append("")
        lines += [
            "**To clear these:** resolve each marker at its"
            " statement — supply the citation the statement"
            " lacks ({{cite}}), rewrite the statement until it"
            " says one thing ({{clarify}}), or settle the"
            " dispute on the page's talk page and align the"
            " statement ({{disputed}}) — and remove the marker"
            " only when the statement itself is fixed. Deleting"
            " a marker without fixing its statement hides the"
            " flag, not the problem.",
            "",
        ]
    else:
        lines += ["No editorial markers on the compiled layer"
                  " this run.", ""]
    lines += [
        "## Lane 6 — Superseded decisions",
        "",
        f"Superseded-decision gate (`scripts/wiki_decision_gate.py`;"
        f" pattern: AsDecided / ex-rac-core, Apache-2.0) over"
        f" wiki/** against the decisions register"
        f" (`evaluation/decisions-register.jsonl`):"
        f" **{l6['live_count']} live** reference(s) to a superseded"
        f" decision form, **{l6['historical_count']} historical**"
        f" (inside the decision record or framed as past — the"
        f" record doing its job; counted, not listed),"
        f" {l6['files_scanned']} files scanned,"
        f" {l6['forms']} superseded form(s) in the register. A live"
        f" hit is a page relying on a superseded form in the"
        f" present tense with no historical framing; the"
        f" classification is a stated heuristic (the gate's"
        f" docstring gives the rules) and the owner rules on each"
        f" hit. This lane surfaces only — the gate's blocking mode"
        f" is its standalone default.",
        "",
    ]
    if l6["live"]:
        lines += ["Live references (file: line — superseded form):",
                  ""]
        for h in l6["live"]:
            excerpt = h["excerpt"]
            if len(excerpt) > 120:
                excerpt = excerpt[:119].rstrip() + "\u2026"
            lines.append(
                f"- `{h['file']}` line {h['line']} —"
                f" {h['form_title']} [{h['form_id']}]: {excerpt}")
        lines.append("")
        lines += [
            "**To clear this:** bring the page onto the"
            " decision's CURRENT form — restate the reliance"
            " in the terms the register now records. If the"
            " reference is genuinely about the past, frame it"
            " as past (a date from before the supersession, a"
            " supersession marker, or a history heading) and"
            " the gate classifies it HISTORICAL. The decision"
            " record itself (the log, the decisions pages) is"
            " exempt by rule H1 — never edit the record to"
            " silence the lane.",
            "",
        ]
    else:
        lines += ["No live references to a superseded decision"
                  " form this run.", ""]
    lines += [
        "## Owner marks — unaddressed annotations",
        "",
        f"Actionable marks from the annotation layer over raw"
        f" (`scripts/wiki_annotate.py`; the owner's highlights,"
        f" notes, questions and corrections live beside each raw"
        f" source, raw itself untouched): **{la['count']}**"
        f" correction/question mark(s) on {la['sources']}"
        f" source(s) that no compiled page accounts for. An"
        f" ingest compiles from the owner's marks first, and"
        f" every correction or question mark must be applied,"
        f" answered, or carried as an open note on a compiled"
        f" page, cited there as `^[mark: raw/<path>#a0001]` —"
        f" until then it surfaces here.",
        "",
    ]
    if la["items"]:
        for row in la["items"]:
            mark = row["mark"]
            loc = mark["locator"]
            pages = (", ".join(f"`{p}`" for p in row["pages"])
                     if row["pages"] else
                     "no compiled page cites this source yet")
            text = mark["text"]
            if len(text) > 120:
                text = text[:119].rstrip() + "\u2026"
            lines.append(
                f"- `{row['source']}` mark {mark['id']}"
                f" ({mark['kind']}, L{loc['start']}-L{loc['end']}):"
                f" {text} — compiled by: {pages}")
        lines.append("")
        lines += [
            "**To clear this:** on a compiled page, apply the"
            " mark (make the correction), answer it (write the"
            " answer the question asks for), or carry it as an"
            " open note — in each case citing the mark there as"
            " `^[mark: raw/<path>#aNNNN]`. A mark clears only"
            " when a compiled page accounts for it; editing the"
            " mark itself is not a route (raw and its marks"
            " are the owner's record).",
            "",
        ]
    else:
        lines += ["No unaddressed actionable marks this run.", ""]
    lines += [
        "## How to rule on these",
        "",
        "Lane by lane or item by item: rule an item in (it gets"
        " fixed or compiled in by hand), rule it out (a false"
        " positive or accepted state, noted so the next run's"
        " context is honest), or ask for a closer look first."
        " Silence leaves everything here surfaced and unapplied —"
        " nothing in this report promotes or repairs itself.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Run the six lint lanes and file one surfacing "
                    "report under wiki/filings/.")
    ap.add_argument("--lens-dir", default=None,
                    help="Lens build output directory for the leaks "
                         "lane (default: /tmp/lens-brief when it "
                         "exists, as in wiki_leak_lint)")
    args = ap.parse_args(argv[1:])

    today = date.today()
    run_date = today.isoformat()
    lens_dir = Path(args.lens_dir) if args.lens_dir else None
    lens_note = (f"Lens surface: {args.lens_dir} (via --lens-dir)."
                 if args.lens_dir else
                 "Lens surface: the leak lint's default"
                 " (/tmp/lens-brief when present).")
    lanes = {
        "contradictions": lane_contradictions(),
        "stale": lane_stale(today),
        "missing": lane_missing(),
        "leaks": lane_leaks(lens_dir),
        "quotes": lane_quotes(),
        "decision_gate": lane_decision_gate(),
        "annotations": lane_annotations(),
    }
    out = WIKI / "filings" / f"lint-lanes-{run_date}.md"
    out.write_text(render(lanes, run_date, lens_note), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT).as_posix()}")
    print(f"contradictions: {lanes['contradictions']['count']}"
          f"   stale: {lanes['stale']['semantic_count']} semantic"
          f" + {lanes['stale']['count']} clock"
          f" + {lanes['stale']['attestation_expired_count']}"
          f" attestation expired"
          f" + {lanes['stale']['reverify_due_count']} reverify due"
          f"   missing: {lanes['missing']['broken_count']}"
          f" broken + {lanes['missing']['orphan_count']} orphan"
          f"   leaks: {lanes['leaks']['new_total']} new"
          f" ({lanes['leaks']['baselined_total']} baselined;"
          f" {lanes['leaks']['verdict']})"
          f"   quotes: {lanes['quotes']['checked']} checked,"
          f" {len(lanes['quotes']['divergences'])} divergent"
          f" + {len(lanes['quotes']['caveats']['findings'])}"
          f" lost-caveat candidate(s)"
          f" + treatment {lanes['quotes']['treatment']['subjects']}"
          f" subject(s),"
          f" {lanes['quotes']['treatment']['weakened_count']}"
          f" weakened"
          f" + editorial markers"
          f" {lanes['quotes']['markers']['total']}"
          f"   decision gate: {lanes['decision_gate']['live_count']}"
          f" live ({lanes['decision_gate']['historical_count']}"
          f" historical)"
          f"   owner marks: {lanes['annotations']['count']}"
          f" unaddressed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
