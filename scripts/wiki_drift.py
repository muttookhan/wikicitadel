#!/usr/bin/env python3
"""Drift check for the LLM Wiki — log-vs-prose drift and the
dead-term hunt.

WikiCitadel v1, from the practitioner lane of the
feature survey: six months of production elsewhere found the
#1 silent failure of a Karpathy-pattern wiki is **log-vs-prose
drift** — the dated log entry records the change, but the
present-tense reference prose elsewhere in the wiki keeps
stating the old state (MPT / The Cloud Codex, in
docs/research-notes.md) — with the
companion **dead-term hunt** for retired names and phrasings
still circulating in live pages.

Two checks, both surfacing-only (nothing is edited):

  (a) Log-vs-prose. For every supersession recorded in the
      decisions register (evaluation/decisions-register.jsonl),
      find the log entry in wiki/log.md that ANNOUNCED it
      (dated on/after the supersession, naming the decision,
      carrying a change marker) — a supersession with no
      announcing log entry is itself a finding, the inverse
      drift: the register moved and the log never said so.
      Then hunt the superseded FORM in live pages: this is
      exactly the superseded-decision gate's scan, run
      in-process (scripts/wiki_decision_gate.py — composed
      with, never duplicated: its matching, and its
      HISTORICAL-vs-LIVE classifier with the
      ambiguity-falls-to-HISTORICAL rule, are used as-is).
      Each LIVE hit is drift; a hit on a page the announcing
      log entry itself named is flagged as the priority case
      — the change's own record pointed at the page and the
      page still carries the pre-change form.

  (b) Dead-term hunt. evaluation/dead-terms.jsonl is the
      maintained register of retired names and phrasings,
      seeded from the register's superseded forms (those are
      hunted by check (a) through the gate and marked
      via: decision-gate) and from the corrections ledger's
      retired phrasings (via: dead-term-hunt — this check).
      Matching and the historical classifier are the gate's
      own machinery, driven with the term's phrases and its
      retirement date. One drift-local refinement, stated
      plainly: the corrections that retire these phrases are
      themselves written by NEGATING the phrase ("There is no
      standing always-allow") or by recounting it inside
      correction framing ("an earlier version wrongly
      claimed ... a promotion re-scan"). A hit whose text
      negates the term, or whose window carries correction
      framing, is the correction doing its job and is
      reported as CORRECTED-MENTION, never as drift. The
      gate's forms do not need this rule (decision forms are
      framed by supersession language, which its H4 markers
      already cover); dead terms do, because the ledger's
      corrections live in prose exactly like this.

Why a standalone script and not a seventh lint lane: the
lanes file one surfacing report per nightly pass and never
block; the drift check has its own exit-code contract (gate
mode exits non-zero on findings, like the decision gate it
composes) and its own register (dead-terms.jsonl), and its
log-side join has no lane analogue. render_section() emits a
lanes-compatible markdown section so the sweep can embed the
result in a filing verbatim, and --write-filing files it in
the lanes' style (status: draft, confidence: observed,
AWAITING OWNER callout).

Excluded from both hunts: the lint lanes' own dated filings
and this check's own dated filings (wiki/filings/drift-*.md)
— they quote the hits they surface, and scanning them would
double-count yesterday's report as today's reliance (the
gate's own exclusion, extended to this check's filings).

Wiring (documented for the integrator; this script edits no
cron): in the nightly sweep, after the lint-lanes step, run
  python3 scripts/wiki_drift.py --report --write-filing
The sweep surfaces the counts like the lanes' counts; a
standalone run without --report is the blocking gate form.

Usage:
  python3 scripts/wiki_drift.py [--report] [--json]
                                [--write-filing] [--date D]

Exit codes: 1 when any drift finding exists (gate mode),
0 otherwise; --report always exits 0 (surfacing only).

Stdlib only. Also importable: scan() returns the result dict;
render_section(result, run_date) renders the filing section.
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"
REGISTER = ROOT / "evaluation" / "decisions-register.jsonl"
DEAD_TERMS = ROOT / "evaluation" / "dead-terms.jsonl"
LOG = WIKI / "log.md"

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.*)$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
PATH_RE = re.compile(r"wiki/[\w.\-/]+\.md")
CHANGE_MARKERS = ("revers", "supersed", "replac", "opened",
                  "opens the", "rescinded", "withdrawn",
                  "no longer stands")
STOPWORDS = {"the", "a", "an", "of", "on", "in", "to", "and",
             "or", "for", "with", "seat", "decision"}
CORRECTION_MARKERS = ("corrected", "correction", "wrongly",
                      "in error", "mistaken", "overstated",
                      "retracted", "erroneous")
NEGATION_RE = re.compile(
    r"\b(no|not|never|none|isn't|aren't|wasn't|weren't|"
    r"doesn't|don't|is not|are not|was not)\b")
DRIFT_FILING_PREFIX = "drift-"
LANES_FILING_PREFIX = "lint-lanes-"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dgate = _load("wiki_decision_gate")
_norm = dgate._norm


# -- log parsing -----------------------------------------------------------

def parse_log(path=LOG):
    """Parse wiki/log.md into entries: [{date, kind, title,
    body, line}] in file order (the log is append-only,
    newest at the bottom)."""
    entries = []
    if not Path(path).is_file():
        return entries
    current = None
    for lineno, raw in enumerate(
            Path(path).read_text(encoding="utf-8",
                                 errors="ignore").splitlines(),
            start=1):
        m = LOG_ENTRY_RE.match(raw)
        if m:
            if current:
                entries.append(current)
            current = {"date": m.group(1), "kind": m.group(2),
                       "title": m.group(3).strip(),
                       "body_lines": [], "line": lineno}
        elif current is not None:
            current["body_lines"].append(raw)
    if current:
        entries.append(current)
    for entry in entries:
        entry["body"] = "\n".join(entry.pop("body_lines"))
    return entries


def _entry_named_pages(entry, stem_index):
    """Pages an entry names: explicit wiki/...md paths plus
    [[wikilinks]] resolved through the stem index."""
    named = set()
    for m in PATH_RE.finditer(entry["body"]):
        named.add(m.group(0))
    title_paths = PATH_RE.findall(entry["title"])
    named.update(title_paths)
    for text in (entry["body"], entry["title"]):
        for m in WIKILINK_RE.finditer(text):
            target = m.group(1).strip()
            if "/" in target:
                cand = target if target.startswith("wiki/") \
                    else f"wiki/{target}"
                if not cand.endswith(".md"):
                    cand += ".md"
                named.add(cand)
            elif target in stem_index:
                named.add(stem_index[target])
    return sorted(named)


def _stem_index(root=ROOT):
    index = {}
    wiki = root / "wiki"
    if wiki.is_dir():
        for path in sorted(wiki.rglob("*.md")):
            index.setdefault(
                path.stem,
                path.relative_to(root).as_posix())
    return index


def find_announcements(entries, form, decision):
    """Log entries announcing one register supersession:
    dated on/after the supersession, naming the decision
    (an alias, or a distinctive title word), and carrying a
    change marker. Returns the matching entries, file order."""
    superseded_on = form.get("superseded_on") or ""
    keywords = set()
    for alias in form.get("aliases") or []:
        if alias:
            keywords.add(alias)
    for token in re.findall(r"[a-z0-9']+",
                            _norm(decision.get("title") or "")):
        if len(token) >= 4 and token not in STOPWORDS:
            keywords.add(token)
    found = []
    for entry in entries:
        if superseded_on and entry["date"] < superseded_on:
            continue
        text = _norm(entry["title"] + " " + entry["body"])
        if not any(k in text for k in keywords):
            continue
        if not any(marker in text for marker in CHANGE_MARKERS):
            continue
        found.append(entry)
    return found


# -- check (a): log-vs-prose ----------------------------------------------

def check_log_vs_prose(root=ROOT):
    """Returns {live: [...], historical_count: n,
    unannounced: [...], announcements: {form_id: [...]},
    forms: [...], files_scanned: n}. LIVE hits are the gate's,
    post-filtered only to drop this check's own filings (the
    gate already drops the lanes' filings)."""
    result = dgate.scan(root)
    stem_index = _stem_index(root)
    entries = parse_log(root / "wiki" / "log.md")
    # The gate's load_register flattens forms and drops the
    # parent decision; re-read the register here for the
    # decision titles the announcement join needs.
    decisions = {}
    register = root / "evaluation" / "decisions-register.jsonl"
    if register.is_file():
        for line in register.read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("kind") == "decision":
                decisions[record.get("id")] = record
    announcements = {}
    unannounced = []
    for form in result["forms"]:
        decision = decisions.get(form["decision_id"]) or {}
        found = find_announcements(entries, form, decision)
        # The named-pages priority signal comes from the
        # EARLIEST announcing entry — the announcement proper.
        # Later entries discuss the change (and name many
        # pages); folding them in would mark nearly every hit
        # "named" and empty the signal of meaning.
        named = set()
        if found:
            named.update(_entry_named_pages(found[0], stem_index))
        announcements[form["form_id"]] = {
            "entries": [{"date": e["date"], "kind": e["kind"],
                         "title": e["title"]}
                        for e in found],
            "announcement_date": found[0]["date"] if found
            else None,
            "named_pages": sorted(named),
        }
        if not found:
            unannounced.append({
                "form_id": form["form_id"],
                "form_title": form["form_title"],
                "decision_id": form["decision_id"],
                "superseded_on": form["superseded_on"],
            })
    live = []
    historical_count = 0
    for hit in result["hits"]:
        if hit["file"].startswith("wiki/filings/" + DRIFT_FILING_PREFIX):
            continue
        if hit["classification"] == "LIVE":
            ann = announcements.get(hit["form_id"]) or {}
            hit = dict(hit)
            hit["named_in_announcement"] = \
                hit["file"] in (ann.get("named_pages") or [])
            live.append(hit)
        else:
            historical_count += 1
    return {"live": live, "historical_count": historical_count,
            "unannounced": unannounced,
            "announcements": announcements,
            "forms": result["forms"],
            "files_scanned": result["files_scanned"]}


# -- check (b): the dead-term hunt -----------------------------------------

def load_dead_terms(path=DEAD_TERMS):
    """Return (header, terms): term records in file order,
    each with normalised phrases and a gate-shaped form."""
    header = None
    terms = []
    if not Path(path).is_file():
        return header, terms
    for line in Path(path).read_text(
            encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("kind") == "header":
            header = record
            continue
        if record.get("kind") != "term":
            continue
        record = dict(record)
        record["phrases_norm"] = [_norm(p)
                                  for p in record.get("phrases")
                                  or []]
        terms.append(record)
    return header, terms


def _correction_context(joined_block, window):
    """The drift-local refinement for dead terms: the text
    either negates the term or frames it as the corrected
    error. Returns a reason string, or None."""
    for marker in CORRECTION_MARKERS:
        if marker in window:
            return f"correction framing ('{marker}')"
    return None


def _negates(joined_block, phrase):
    """True when a negation word stands within 60 normalised
    characters before the phrase in the joined block text —
    the sentence is denying the retired claim, not making it
    ('there is no standing always-allow')."""
    idx = joined_block.find(phrase)
    while idx != -1:
        start = max(0, idx - 60)
        if NEGATION_RE.search(joined_block[start:idx]):
            return True
        idx = joined_block.find(phrase, idx + 1)
    return False


def check_dead_terms(root=ROOT):
    """Hunt the register's via: dead-term-hunt terms over
    wiki/** with the gate's matcher and classifier, plus the
    negation / correction-framing refinement. Returns
    {findings: [...], corrected_mentions: [...],
     terms_hunted: n, terms_total: n, files_scanned: n}."""
    _header, terms = load_dead_terms(
        root / "evaluation" / "dead-terms.jsonl")
    hunted = [t for t in terms
              if (t.get("via") or "dead-term-hunt")
              == "dead-term-hunt"]
    wiki = root / "wiki"
    findings = []
    corrected = []
    scanned = 0
    if not hunted or not wiki.is_dir():
        return {"findings": findings, "corrected": corrected,
                "terms_hunted": len(hunted),
                "terms_total": len(terms), "files_scanned": 0}
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.parent.name == "filings" and (
                path.name.startswith(LANES_FILING_PREFIX)
                or path.name.startswith(DRIFT_FILING_PREFIX)):
            continue
        try:
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
        except OSError:
            # A page vanished between listing and reading
            # (a parallel build's scratch file); it is not
            # part of the corpus this run.
            continue
        scanned += 1
        raw_lines = text.splitlines()
        lines = list(enumerate(raw_lines, start=1))
        lines_by_no = dict(lines)
        headings = [(n, raw) for n, raw in lines
                    if dgate.HEADING_RE.match(raw)]
        blocks = list(dgate._blocks(lines))
        for term in hunted:
            form = {
                "decision_id": None,
                "form_id": term["term"],
                "form_title": term["term"],
                "superseded_on": term.get("retired_on"),
                "phrases": term["phrases_norm"],
                "aliases": [],
                "alias_requires": "",
                "source_pages": {
                    "wiki/rules/corrections-ledger.md",
                    "wiki/log.md",
                },
            }
            for _start, block in blocks:
                joined = " ".join(_norm(raw)
                                  for _ln, raw in block)
                for lineno, how in dgate._match_block(block, form):
                    classification, reason = dgate._classify(
                        rel, lineno, lines_by_no, headings, form)
                    hit = {
                        "file": rel, "line": lineno,
                        "term": term["term"],
                        "matched": how,
                        "retired_on": term.get("retired_on"),
                        "origin": term.get("origin"),
                        "replaced_by": term.get("replaced_by"),
                        "excerpt": lines_by_no.get(
                            lineno, "").strip()[:200],
                    }
                    if classification == "LIVE":
                        lo = max(1, lineno - 2)
                        window = " ".join(
                            _norm(lines_by_no.get(n, ""))
                            for n in range(lo, lineno + 3))
                        phrase = how.removeprefix("phrase: ")
                        if _negates(joined, phrase):
                            hit["reason"] = (
                                "the sentence negates the term")
                            corrected.append(hit)
                            continue
                        ctx = _correction_context(joined, window)
                        if ctx:
                            hit["reason"] = ctx
                            corrected.append(hit)
                            continue
                        hit["reason"] = reason
                        findings.append(hit)
                    else:
                        hit["reason"] = reason
                        corrected.append(hit)
    findings.sort(key=lambda h: (h["file"], h["line"]))
    corrected.sort(key=lambda h: (h["file"], h["line"]))
    return {"findings": findings, "corrected": corrected,
            "terms_hunted": len(hunted),
            "terms_total": len(terms), "files_scanned": scanned}


# -- combined scan + rendering ---------------------------------------------

def scan(root=ROOT):
    prose = check_log_vs_prose(root)
    terms = check_dead_terms(root)
    return {"prose": prose, "terms": terms,
            "findings": len(prose["live"])
            + len(prose["unannounced"])
            + len(terms["findings"])}


def render_section(result, run_date):
    prose, terms = result["prose"], result["terms"]
    lines = [
        "## Drift — log-vs-prose and dead terms",
        "",
        f"Drift check (`scripts/wiki_drift.py`; build,"
        f" pattern: MPT / The Cloud Codex on log-vs-prose drift"
        f" as the #1 silent failure of a wiki run this way):"
        f" **{len(prose['live'])} live** page(s) still carrying"
        f" a superseded decision form in the present tense"
        f" ({prose['historical_count']} historical — the record"
        f" doing its job), **{len(prose['unannounced'])}**"
        f" register supersession(s) with no announcing log"
        f" entry, **{len(terms['findings'])} live** dead-term"
        f" hit(s) ({terms['corrected']} corrected mention(s) —"
        f" negations and correction recounts, counted, not"
        f" listed). {prose['files_scanned']} files scanned;"
        f" {terms['terms_hunted']} of {terms['terms_total']}"
        f" dead terms hunted here (the rest ride the decision"
        f" gate). A live hit is a page relying on the old form"
        f" or the retired phrase in the present tense with no"
        f" historical framing; classification is the decision"
        f" gate's stated heuristic, reused as-is, and the owner"
        f" rules on each hit.",
        "",
    ]
    if prose["live"]:
        lines += ["Live prose carrying a superseded form"
                  " (file: line — superseded form):", ""]
        for h in prose["live"]:
            excerpt = h["excerpt"]
            if len(excerpt) > 120:
                excerpt = excerpt[:119].rstrip() + "…"
            named = (" — **named in the announcing log entry**"
                     if h.get("named_in_announcement") else "")
            lines.append(
                f"- `{h['file']}` line {h['line']} —"
                f" {h['form_title']} [{h['form_id']}]:"
                f" {excerpt}{named}")
        lines.append("")
    else:
        lines += ["No live prose carries a superseded decision"
                  " form this run.", ""]
    if prose["unannounced"]:
        lines += ["Register supersessions the log never"
                  " announced (the inverse drift):", ""]
        for u in prose["unannounced"]:
            lines.append(
                f"- [{u['form_id']}] {u['form_title']} —"
                f" superseded {u['superseded_on']}, no log entry"
                f" on/after that date announces it")
        lines.append("")
    if terms["findings"]:
        lines += ["Dead terms in live prose (file: line —"
                  " retired term):", ""]
        for h in terms["findings"]:
            excerpt = h["excerpt"]
            if len(excerpt) > 120:
                excerpt = excerpt[:119].rstrip() + "…"
            lines.append(
                f"- `{h['file']}` line {h['line']} —"
                f" {h['term']} (retired {h['retired_on']}):"
                f" {excerpt}")
        lines.append("")
    else:
        lines += ["No dead term circulates in live prose this"
                  " run.", ""]
    return "\n".join(lines)


def render_filing(result, run_date):
    lines = [
        "---",
        f"title: Drift check — {run_date} (surfaced issues for the owner)",
        "type: query",
        f"created: {run_date}",
        f"updated: {run_date}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [lint, drift, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Drift check — {run_date}",
        "",
        "> [!warning] AWAITING OWNER — surfaced issues, nothing applied",
        "> Generated by the drift check (`scripts/wiki_drift.py`)."
        " **Nothing in this file is canonical, no page has been"
        " changed, and nothing here has been fixed or applied.**"
        " Each item moves only when the owner rules on it.",
        "",
        f"Summary: {result['findings']} drift finding(s) —"
        f" {len(result['prose']['live'])} live superseded-form"
        f" reference(s), {len(result['prose']['unannounced'])}"
        f" unannounced supersession(s),"
        f" {len(result['terms']['findings'])} dead-term hit(s).",
        "",
        render_section(result, run_date),
        "",
        "## How to rule on these",
        "",
        "Rule an item in (the page gets corrected by hand to"
        " the current form), rule it out (a false positive or"
        " an accepted as-written record, noted so the next"
        " run's context is honest), or ask for a closer look"
        " first. Silence leaves everything here surfaced and"
        " unapplied.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Drift check: log-vs-prose drift and the "
                    "dead-term hunt over wiki/**.")
    ap.add_argument("--report", action="store_true",
                    help="surfacing only: always exit 0")
    ap.add_argument("--json", action="store_true",
                    help="emit the result as JSON")
    ap.add_argument("--write-filing", action="store_true",
                    help="file the report at "
                         "wiki/filings/drift-<date>.md")
    ap.add_argument("--date", default=None,
                    help="filing date (default: today)")
    args = ap.parse_args(argv[1:])

    run_date = args.date or date.today().isoformat()
    result = scan()
    if args.write_filing:
        out = WIKI / "filings" / f"drift-{run_date}.md"
        out.write_text(render_filing(result, run_date),
                       encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT).as_posix()}")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        prose, terms = result["prose"], result["terms"]
        for h in prose["live"]:
            named = " [named in announcing log entry]" \
                if h.get("named_in_announcement") else ""
            print(f"DRIFT {h['file']}:{h['line']}  "
                  f"[{h['form_id']}] {h['matched']}{named}")
            print(f"      {h['excerpt']}")
        for u in prose["unannounced"]:
            print(f"UNANNOUNCED [{u['form_id']}] "
                  f"{u['form_title']} — superseded "
                  f"{u['superseded_on']}, no announcing log entry")
        for h in terms["findings"]:
            print(f"DEAD-TERM {h['file']}:{h['line']}  "
                  f"{h['term']} ({h['matched']})")
            print(f"      {h['excerpt']}")
        print(f"Overall: {len(prose['live'])} live prose, "
              f"{len(prose['unannounced'])} unannounced, "
              f"{len(terms['findings'])} dead terms "
              f"({len(terms['corrected'])} corrected mentions, "
              f"{prose['historical_count']} historical gate hits)")
    if result["findings"] and not args.report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
