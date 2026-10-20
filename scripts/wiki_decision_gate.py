#!/usr/bin/env python3
"""Superseded-decision gate for the LLM Wiki.

Pattern: AsDecided / ex-rac-core (Apache-2.0) — a CI-style gate
that rejects references to superseded decisions. Re-implemented
here in this wiki's own style; no code copied.

The gate reads the decisions register
(evaluation/decisions-register.jsonl), which records each
standing decision in its current form and, where the owner has
replaced an earlier form of a decision, that superseded form
with the phrases and aliases it circulates under. The gate
then scans wiki/** (pages and filings) for references to a
superseded form and classifies each hit:

  HISTORICAL — the reference sits inside the record of the
    decision itself: a dated log entry, a decisions page, or
    text that itself frames the form as past (a date from
    before the supersession in the surrounding lines, a
    supersession/reversal marker, or a history-style section
    heading). Allowed; reported for completeness.
  LIVE — the reference carries no historical framing: the
    page relies on the superseded form in the present tense.
    Flagged.

Exit codes: gate mode (default) exits 1 when any LIVE hit
exists, 0 otherwise. --report always exits 0 (surfacing only —
the mode the lint lanes use; the lanes never block).

Matching and classification are HEURISTICS, and their rules
are stated here so a hit can be argued with:

  Matching: text is normalised (lowercased; markdown emphasis,
  backticks and heading marks stripped; curly apostrophes
  folded; whitespace collapsed). Lines within a paragraph
  (blank-line-delimited block) are joined before matching, so
  a phrase wrapped across two physical lines still matches;
  the reported line is the physical line where the match
  starts. A form matches when one of its register phrases
  appears, or when a register alias and the alias's required
  word appear on the SAME physical line (for example: a line
  naming a collaborating agent together with "reserved" —
  this catches table shorthand like "None while reserved" on
  that agent's row, which no seat phrase covers, without
  firing on every mention of the agent in a paragraph that
  happens to discuss the reservation).
  Known limit: phrase matching is confined to a single
  paragraph block — a reference split across a blank line is
  missed.

  Classification, applied in order; the first rule that fires
  decides, and every ambiguous path falls to HISTORICAL (the
  gate must not cry wolf — a lint the owner learns to ignore
  is worse than no lint):
    H1. The file is the wiki's dated log (wiki/log.md), a
        register source page, or its file name contains
        "decisions" — it IS the decision record.
    H2. The matched line is a blockquote line (starts with
        ">"): the page is quoting a source's words, not
        relying on them in its own voice.
    H3. The window (the matched physical line plus the two
        lines above and below it) contains an ISO date from
        BEFORE the form's supersession date — the text
        anchors the form to its own time.
    H4. The window contains a supersession marker:
        "superseded", "supersede", "reversal", "reversed the",
        "formerly", "previously", "originally", "at the time",
        "no longer", "was reserved", "held reserved",
        "seat opened", "opened the seat", "was opened".
    H5. The nearest preceding heading contains an ISO date or
        one of: history, historical, archive, background.
  Otherwise the hit is LIVE.

  Excluded from the scan: the lint lanes' own dated filings
  (wiki/filings/lint-lanes-*.md), which quote the hits they
  surface — scanning them would double-count yesterday's
  report as today's reliance.

  Premortem check: the same report also names the
  staged proposals under staging/proposed/ that lack a
  WRITTEN premortem block. A proposal carries one when it
  has a `## Premortem (YYYY-MM-DD)` section whose body is
  not the generator's placeholder (the placeholder carries
  the marker "NOT YET WRITTEN"). Surfacing only, like
  --report: a missing premortem never changes the exit
  code — promotion is the owner's act; the block informs
  it, it does not gate it mechanically.

  Coaching : the premortem line does not stop at
  naming what is missing — for each proposal it says WHICH
  thing is missing (no block at all, vs only the generator
  placeholder) and the concrete change that clears it (a
  separately-written dated block, format
  templates/proposal.md). A gate that only rejects teaches
  its contributors to route around it (the Halfaker
  warning, via the survey); the coaching is the
  path back. Coaching is text only — verdicts and exit
  codes are exactly what they were before it existed.

Usage:
  python3 scripts/wiki_decision_gate.py [--report] [--json]

Stdlib only. Also importable in-process (the lint lanes call
scan() and render their own lane from the result).
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
REGISTER = ROOT / "evaluation" / "decisions-register.jsonl"

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
HEADING_RE = re.compile(r"^#{1,6}\s")
PROPOSED_DIR = ROOT / "staging" / "proposed"
PREMORTEM_HEADING_RE = re.compile(
    r"^## Premortem \(\d{4}-\d{2}-\d{2}\)\s*$", re.M)
PREMORTEM_PLACEHOLDER = "NOT YET WRITTEN"


def has_written_premortem(text):
    """True when the text carries a premortem block that a
    separate pass actually wrote: a dated `## Premortem`
    heading whose section (to the next `## ` heading or end
    of file) is not the generator placeholder."""
    m = PREMORTEM_HEADING_RE.search(text)
    if not m:
        return False
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    section = rest[:nxt.start()] if nxt else rest
    return PREMORTEM_PLACEHOLDER not in section


def premortem_status(root=ROOT):
    """[(proposal_id, has_written_premortem)] for every
    staged prop-*.md under staging/proposed/, sorted."""
    out = []
    pdir = Path(root) / "staging" / "proposed"
    if not pdir.is_dir():
        return out
    for path in sorted(pdir.glob("prop-*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        out.append((path.stem, has_written_premortem(text)))
    return out


def premortem_gap(text):
    """Which premortem thing a staged proposal is missing:
    'written' (a dated, non-placeholder block), 'placeholder'
    (a block exists but is only the generator's NOT YET
    WRITTEN marker — the undated generator heading counts
    here too), or 'none' (no premortem block at all)."""
    if has_written_premortem(text):
        return "written"
    if PREMORTEM_PLACEHOLDER in text or \
            re.search(r"^## Premortem\b", text, re.M):
        return "placeholder"
    return "none"


def premortem_coaching(root=ROOT):
    """[(proposal_id, gap, coaching)] for every staged
    proposal lacking a written premortem. The coaching names
    what is missing and the concrete change that clears it;
    it changes no verdict — the gate still only surfaces."""
    out = []
    pdir = Path(root) / "staging" / "proposed"
    if not pdir.is_dir():
        return out
    for path in sorted(pdir.glob("prop-*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        gap = premortem_gap(text)
        if gap == "written":
            continue
        if gap == "placeholder":
            missing = ("only the generator placeholder "
                       "(NOT YET WRITTEN) stands where the "
                       "premortem goes — a placeholder is a "
                       "marker, not a premortem")
        else:
            missing = "no premortem block at all"
        coaching = (
            f"{path.stem}: missing a WRITTEN premortem — "
            f"{missing}. To clear: in a pass SEPARATE from "
            f"the drafting pass, replace/append the block in "
            f"staging/proposed/{path.name} as a dated "
            f"`## Premortem (YYYY-MM-DD)` section following "
            f"templates/proposal.md — the premise (\"It is "
            f"<date, ~6 months on> and this failed. The "
            f"reasons were:\") plus 3–7 concrete, past-tense "
            f"failure reasons, each closed by the mitigation "
            f"that designs against it or an explicit "
            f"accepted-risk note. Surfacing only: the gate "
            f"never blocks on this; promotion stays the "
            f"owner's act.")
        out.append((path.stem, gap, coaching))
    return out
PAST_MARKERS = (
    "superseded", "supersede", "reversal", "reversed the",
    "formerly", "previously", "originally", "at the time",
    "no longer", "was reserved", "held reserved", "seat opened",
    "opened the seat", "was opened",
)
HEADING_MARKERS = ("history", "historical", "archive",
                   "background")
EXCLUDED_NAME_PREFIX = "lint-lanes-"


def _norm(text):
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[*_`#>]+", " ", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def load_register(path=REGISTER):
    """Return (header, forms): forms is the flat list of
    superseded-form records, each carrying its decision's id
    and its source page for the H1 rule."""
    header = None
    forms = []
    source_pages = set()
    if not Path(path).is_file():
        return header, forms
    for line in Path(path).read_text(encoding="utf-8").splitlines():
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
        if record.get("kind") != "decision":
            continue
        source = (record.get("source") or {}).get("page")
        if source:
            source_pages.add(source)
        for form in record.get("superseded_forms") or []:
            forms.append({
                "decision_id": record.get("id"),
                "decision_title": record.get("title"),
                "form_id": form.get("form_id"),
                "form_title": form.get("title"),
                "superseded_on": form.get("superseded_on"),
                "superseded_by": form.get("superseded_by"),
                "phrases": [_norm(p)
                            for p in form.get("match_phrases") or []],
                "aliases": [_norm(a)
                            for a in form.get("aliases") or []],
                "alias_requires": _norm(
                    form.get("alias_requires") or ""),
            })
    for form in forms:
        form["source_pages"] = source_pages
    return header, forms


def _blocks(lines):
    """Yield (start_lineno, [(lineno, raw), ...]) per
    blank-line-delimited block."""
    block = []
    start = None
    for lineno, raw in lines:
        if raw.strip():
            if start is None:
                start = lineno
            block.append((lineno, raw))
        else:
            if block:
                yield start, block
            block = []
            start = None
    if block:
        yield start, block


def _match_block(block, form):
    """Find matches of one form inside one block. Returns a
    list of (start_lineno, how) — how is the phrase that
    matched, or 'alias: <alias> + <required word>'."""
    joined_parts = []
    offsets = []  # (joined_offset, lineno)
    pos = 0
    for lineno, raw in block:
        piece = _norm(raw)
        offsets.append((pos, lineno))
        joined_parts.append(piece)
        pos += len(piece) + 1
    joined = " ".join(joined_parts)

    def line_at(offset):
        lineno = offsets[0][1]
        for off, ln in offsets:
            if off <= offset:
                lineno = ln
            else:
                break
        return lineno

    hits = []
    for phrase in form["phrases"]:
        idx = joined.find(phrase)
        while idx != -1:
            hits.append((line_at(idx), f"phrase: {phrase}"))
            idx = joined.find(phrase, idx + 1)
    required = form["alias_requires"]
    if required:
        for lineno, raw in block:
            piece = _norm(raw)
            if required in piece:
                for alias in form["aliases"]:
                    if alias in piece:
                        hits.append(
                            (lineno, f"alias: {alias} + {required}"))
                        break
    # One hit per (line, form) is enough for the report;
    # phrase hits were collected first, so they win the slot.
    seen = {}
    for lineno, how in hits:
        seen.setdefault(lineno, how)
    return sorted(seen.items())


def _classify(rel, lineno, lines_by_no, headings, form):
    """lines_by_no: {lineno: raw line}; headings: [(lineno,
    text)] in file order. Returns (classification, reason)."""
    # H1 — the file is the decision record itself.
    if rel == "wiki/log.md" or "decisions" in Path(rel).name \
            or rel in form["source_pages"]:
        return "HISTORICAL", "H1: the file is the decision record"
    # H2 — a quoted line reproduces a source's words.
    if lines_by_no.get(lineno, "").lstrip().startswith(">"):
        return "HISTORICAL", "H2: blockquote — quoted source text"
    lo = max(1, lineno - 2)
    window = " ".join(_norm(lines_by_no.get(n, ""))
                      for n in range(lo, lineno + 3))
    # H3 — a date from before the supersession anchors the text.
    superseded_on = None
    if form["superseded_on"]:
        m = DATE_RE.search(form["superseded_on"])
        if m:
            superseded_on = date(int(m.group(1)), int(m.group(2)),
                                 int(m.group(3)))
    if superseded_on:
        for m in DATE_RE.finditer(window):
            try:
                when = date(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)))
            except ValueError:
                continue
            if when < superseded_on:
                return "HISTORICAL", (
                    f"H3: window carries {when.isoformat()}, "
                    f"before the {superseded_on.isoformat()} "
                    "supersession")
    # H3 — the window itself records the change.
    for marker in PAST_MARKERS:
        if marker in window:
            return "HISTORICAL", f"H4: window marker '{marker}'"
    # H4 — the enclosing section is a record section.
    heading = None
    for hno, htext in headings:
        if hno < lineno:
            heading = htext
        else:
            break
    if heading:
        hnorm = _norm(heading)
        if DATE_RE.search(hnorm) or any(
                marker in hnorm for marker in HEADING_MARKERS):
            return "HISTORICAL", f"H5: heading '{heading.strip()}'"
    return "LIVE", "no historical framing found"


def scan(root=ROOT):
    """Scan wiki/** against the register's superseded forms.
    Returns {'hits': [...], 'forms': [...], 'files_scanned': n}
    with hits sorted deterministically."""
    header, forms = load_register(root / "evaluation"
                                  / "decisions-register.jsonl")
    wiki = root / "wiki"
    hits = []
    scanned = 0
    if not forms or not wiki.is_dir():
        return {"hits": hits, "forms": forms,
                "files_scanned": scanned}
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.name.startswith(EXCLUDED_NAME_PREFIX) \
                and path.parent.name == "filings":
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        raw_lines = text.splitlines()
        lines = list(enumerate(raw_lines, start=1))
        lines_by_no = dict(lines)
        headings = [(n, raw) for n, raw in lines
                    if HEADING_RE.match(raw)]
        for form in forms:
            for _start, block in _blocks(lines):
                for lineno, how in _match_block(block, form):
                    classification, reason = _classify(
                        rel, lineno, lines_by_no, headings, form)
                    hits.append({
                        "file": rel,
                        "line": lineno,
                        "decision_id": form["decision_id"],
                        "form_id": form["form_id"],
                        "form_title": form["form_title"],
                        "matched": how,
                        "classification": classification,
                        "reason": reason,
                        "excerpt": lines_by_no.get(
                            lineno, "").strip()[:200],
                    })
    hits.sort(key=lambda h: (h["classification"] != "LIVE",
                             h["file"], h["line"]))
    return {"hits": hits, "forms": forms,
            "files_scanned": scanned}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Gate: flag present-tense references to "
                    "superseded decision forms in wiki/**.")
    ap.add_argument("--report", action="store_true",
                    help="surfacing only: always exit 0")
    ap.add_argument("--json", action="store_true",
                    help="emit the result as JSON")
    args = ap.parse_args(argv[1:])

    result = scan()
    live = [h for h in result["hits"]
            if h["classification"] == "LIVE"]
    historical = [h for h in result["hits"]
                  if h["classification"] == "HISTORICAL"]
    premortems = premortem_status()
    missing = [pid for pid, ok in premortems if not ok]
    coaching = premortem_coaching()
    if args.json:
        result["premortem"] = {
            "staged_proposals": len(premortems),
            "with_written_premortem":
                [pid for pid, ok in premortems if ok],
            "missing_written_premortem": missing,
            "coaching": {pid: text for pid, _gap, text in coaching},
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"decisions register: {len(result['forms'])} "
              f"superseded form(s) hunted; "
              f"{result['files_scanned']} files scanned")
        for h in result["hits"]:
            print(f"{h['classification']:10} {h['file']}:"
                  f"{h['line']}  [{h['form_id']}] {h['matched']}"
                  f" — {h['reason']}")
            print(f"           {h['excerpt']}")
        print(f"Overall: {len(live)} live, "
              f"{len(historical)} historical")
        if missing:
            print(f"premortem: {len(premortems)} staged "
                  f"proposal(s); missing a written premortem: "
                  f"{', '.join(missing)}")
            for _pid, _gap, text in coaching:
                print(f"  coaching: {text}")
        else:
            print(f"premortem: {len(premortems)} staged "
                  f"proposal(s); all carry a written premortem")
    if live and not args.report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
