#!/usr/bin/env python3
"""Retrieval-cue severance list: generator + shared matching rules.

WikiCitadel v1, with its strengthening folded in.
The finding (failure literature,
find 18 — Kluge & Gronau 2018 on intentional forgetting,
docs/research-notes.md):
obsolete knowledge is forgotten by removing its RETRIEVAL CUES,
not by deleting it; superseding a claim in a register changes
nothing a reader can find until the cues that surface the old
claim are cut. The frontier research (governing-facts
paper, survey notes find 8) hardens the same rule
for answer time: superseded claims are excluded by REGISTER
LOOKUP, never merely out-ranked — a conflict-blind top-k cannot
be patched into consistency.

This module GENERATES the severance list,
evaluation/retrieval-severance.json — a derived artefact, never
hand-edited. Its sources, each entry citing the exact register
line it derives from:

  1. Superseded decision FORMS (evaluation/decisions-register
     .jsonl): each form the owner has replaced — today the one
     real supersession on record, ch7-d1-reserved.
  2. Treatment subjects at NEGATIVE standing
     (evaluation/treatment-register.jsonl): the strongest grade
     across a subject's events governs (citator practice, as in
     scripts/wiki_treatment.py); questioned/caution do not sever.
  3. Pages the wiki's own records mark superseded — frontmatter
     status superseded/deprecated, a superseded_by pointer, a
     retired claim page, a resolved talk page recording its
     supersession (the Lane-2 semantic signals, computed by
     scripts/wiki_treatment.py's superseded_pages()).

Cues: every entry carries the claim text and its cues — cue
PHRASES (token sequences; for decision forms, the register's own
match_phrases, the patterns the form circulates under) and
DISTINCTIVE TERMS (the claim's content tokens). Matching, one
rule set for every consumer (mirrored in scripts/wiki_search.py,
tools/lens/lenslib.py and tools/ask/severance.py):

  - TEXT match — a document or passage CARRIES the severed
    claim: any cue phrase appears as a contiguous token
    subsequence, or at least 4/5 of the distinctive terms are
    present.
  - QUERY match — a query goes LOOKING for the severed claim:
    any cue phrase as a contiguous token subsequence of the
    query tokens, or at least half (and at least 3) of the
    distinctive terms among the query tokens.
  - PAGE rule — a page-level entry severs its page outright.

How the consumers apply the rules differs by surface, stated
plainly: SEARCH (wiki_search / Lens) excludes a ranked result
when its page is severed, or when the query matches a claim
entry's cues AND the result's text does too — the cue path from
query to dead claim is cut, while the record page stays findable
by queries that are not hunting the dead form (supersede-don't-
delete: hidden from the dead claim's own cues, retained for
lookup). The ASK door applies the TEXT match to candidate
evidence passages unconditionally: a passage carrying a severed
claim never becomes answer evidence, whatever the question was.

LINEAGE DERIVATION (board item 10, 2026-11-03 — severance keyed
to citation lineage, not source wording). The TEXT match above
is keyed to the severed claim's WORDING, and the cross-session
injection slice measured the seam: a retained instruction
paraphrased into compiled prose steers a fresh session (the
match sees 2 of the claim's 12 cue terms), and a deleted source
steers because deletion leaves no register act. The derivation
closes the seam structurally: a compiled passage is severed
when its CITATIONS trace to severed ground, whatever words it
uses. The derived entries are computed here, in the generator,
marked "derived": true, each naming its basis; the consumers
need no new rule — a derived claim entry is an ordinary claim
entry whose cues are the retained passage's own terms, and a
derived page entry is an ordinary page entry. The relations:

  R1 RECEIPT ORIGIN — for each claim entry, the spans its own
  record page cites whose text matches the claim under the
  TEXT rule are the claim's origin receipts; any compiled
  passage citing an origin receipt (overlapping lines) is
  severed with the claim. The claim's statement sentences on
  its record page are severed ground the same way, so a
  passage citing the record page at those lines inherits.
  R2 SUPERSEDED BLOCK — on a page carrying a claim entry, a
  cited passage whose own paragraph block states the form
  superseded (the corpus's convention: a retained form keeps
  its supersession in the same breath) is severed; the basis
  is the page's claim entry the block best matches.
  R3 SEVERED PAGE — a passage citing a page-level severed
  page is severed; derivation runs to a fixpoint, so lineage
  propagates transitively through intermediate pages.
  R4 DANGLING CITATION — a passage whose citation target no
  longer resolves (the file is gone, or the range lies
  outside it) loses standing: deletion is not severance, but
  a claim resting on a vanished receipt does not stand.
  R5 NO LIVE BASIS — a page whose frontmatter sources ALL
  fail to resolve, or name severed pages, is severed whole.

Stated limits, deliberately: origins are read from the claim's
record page receipts (no whole-corpus text search); an
unmarked passage is never attributed to a severed claim by
frontmatter alone (R5 is the only frontmatter rule, and it is
whole-page); a derived claim entry is emitted only when the
passage carries at least 3 distinctive terms — a shorter
passage cannot carry usable cues (the forgetting battery's
paraphrase probe sets the same floor). Entry ids are stable:
the register-derived entries keep the established sorted order
and numbering (the corpus cites sev- ids in batteries and
pages, and a renumbering would silently corrupt those
references); derived entries follow, sorted by (page, claim,
basis), numbered after them.

Regeneration is deterministic: same registers + same wiki tree
=> same bytes (entries sorted, ids assigned in sorted order,
register contents hashed into the header). `check` exits 1 when
the file on disk differs from a fresh generation.

Usage:
  python3 scripts/wiki_severance.py build   # (re)write the list
  python3 scripts/wiki_severance.py check   # exit 1 when stale
  python3 scripts/wiki_severance.py show    # summarise the list

Stdlib only. Also importable in-process (the consumers load the
artefact with load_severance() and apply the matching rules).
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DECISIONS_REGISTER = ROOT / "evaluation" / "decisions-register.jsonl"
TREATMENT_REGISTER = ROOT / "evaluation" / "treatment-register.jsonl"
SEVERANCE_PATH = ROOT / "evaluation" / "retrieval-severance.json"

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Function words carry no cue value; a distinctive term must also
# be at least 3 characters (tokenize() already drops < 2).
STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "to", "in", "on", "is", "was",
    "are", "were", "be", "been", "it", "its", "this", "that",
    "with", "as", "at", "by", "from", "or", "and", "not", "no",
    "has", "have", "had", "its", "their", "they", "them", "then",
    "than", "into", "over", "under", "per",
})


def tokenize(text: str):
    """The wiki_search.py tokenizer (identical rule): lowercase
    [a-z0-9]+ runs of length >= 2."""
    return [t for t in TOKEN_RE.findall(str(text).lower())
            if len(t) >= 2]


def distinctive_terms(text: str):
    """The claim's cue terms: content tokens of length >= 3,
    stopwords removed, sorted, de-duplicated."""
    return sorted({t for t in tokenize(text)
                   if len(t) >= 3 and t not in STOPWORDS})


def phrase_tokens(phrase: str):
    """A cue phrase as a token sequence (the decision gate's
    normalisation reduced to tokens: case folded, punctuation
    gone — the same sequences consumers match against)."""
    return tokenize(phrase)


# -- Matching (the shared rules; mirrored by the consumers) -------------------

def phrase_hit(tokens, phrase):
    """True when `phrase` (a token list) appears in `tokens` as a
    contiguous subsequence."""
    n = len(phrase)
    if n == 0 or n > len(tokens):
        return False
    return any(tokens[i:i + n] == list(phrase)
               for i in range(len(tokens) - n + 1))


def terms_present(tokens, terms):
    have = set(tokens)
    return sum(1 for t in terms if t in have)


def text_matches(tokens, entry):
    """TEXT match: the text carries the entry's severed claim —
    any cue phrase, or >= 4/5 of the distinctive terms."""
    cues = entry.get("cues") or {}
    for phrase in cues.get("phrases") or []:
        if phrase_hit(tokens, phrase):
            return True
    terms = cues.get("terms") or []
    if terms and terms_present(tokens, terms) * 5 >= len(terms) * 4:
        return True
    return False


def query_matches(query_tokens, entry):
    """QUERY match: the query goes looking for the severed claim
    — any cue phrase, or >= half (at least 3) of the terms."""
    cues = entry.get("cues") or {}
    for phrase in cues.get("phrases") or []:
        if phrase_hit(query_tokens, phrase):
            return True
    terms = cues.get("terms") or []
    if terms:
        need = max(3, (len(terms) + 1) // 2)
        if terms_present(query_tokens, terms) >= need:
            return True
    return False


# -- Register reading -----------------------------------------------------------

def _read_jsonl(path):
    """[(lineno, record)] for a JSONL register; malformed lines
    are skipped (the registers' own tools are the validators)."""
    out = []
    path = Path(path)
    if not path.is_file():
        return out
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8",
                           errors="ignore").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append((lineno, json.loads(line)))
        except ValueError:
            continue
    return out


def _sha256(path):
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- Generation -----------------------------------------------------------------

def decision_form_entries(root=ROOT):
    """One entry per superseded decision form, from the
    decisions register (parsed here directly: the gate's loader
    does not retain per-decision source pages or line numbers,
    and the entry must cite both)."""
    entries = []
    register = Path(root) / "evaluation" / "decisions-register.jsonl"
    for lineno, record in _read_jsonl(register):
        if record.get("kind") != "decision":
            continue
        page = (record.get("source") or {}).get("page")
        for form in record.get("superseded_forms") or []:
            title = form.get("title") or form.get("form_id") or ""
            phrases = []
            for raw in form.get("match_phrases") or []:
                toks = phrase_tokens(raw)
                if toks and toks not in phrases:
                    phrases.append(toks)
            title_toks = phrase_tokens(title)
            if title_toks and title_toks not in phrases:
                phrases.append(title_toks)
            entries.append({
                "kind": "decision-form",
                "page": page,
                "claim": title,
                "cues": {"phrases": phrases,
                         "terms": distinctive_terms(title)},
                "source": {
                    "register":
                        "evaluation/decisions-register.jsonl",
                    "line": lineno,
                    "record_id": form.get("form_id"),
                    "signal": "superseded form of decision "
                              + str(record.get("id")),
                },
            })
    return entries


def treatment_entries(root=ROOT):
    """One entry per treatment subject whose STANDING grade is
    negative (the strongest grade across the subject's events —
    citator practice, as scripts/wiki_treatment.py computes).
    The entry cites the register line of the negative event that
    set the standing (the earliest such line, deterministically);
    questioned and caution subjects never sever."""
    entries = []
    register = Path(root) / "evaluation" / "treatment-register.jsonl"
    by_subject = {}
    for lineno, record in _read_jsonl(register):
        if record.get("kind") != "treatment":
            continue
        subject = record.get("subject") or {}
        key = (subject.get("page"), subject.get("claim"))
        by_subject.setdefault(key, []).append((lineno, record))
    severity = {"followed": 0, "questioned": 1, "caution": 2,
                "negative": 3}
    for (page, claim), events in sorted(
            by_subject.items(),
            key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        standing = None
        for _lineno, record in events:
            grade = record.get("grade")
            if grade in severity and (
                    standing is None
                    or severity[grade] > severity[standing]):
                standing = grade
        if standing != "negative":
            continue
        neg = [(ln, r) for ln, r in events
               if r.get("grade") == "negative"]
        lineno, record = sorted(neg, key=lambda lr: lr[0])[0]
        entries.append({
            "kind": "treatment",
            "page": page,
            "claim": claim,
            "cues": {"phrases": [],
                     "terms": distinctive_terms(claim or "")},
            "source": {
                "register": "evaluation/treatment-register.jsonl",
                "line": lineno,
                "record_id": record.get("id"),
                "signal": "negative treatment (standing grade)",
            },
        })
    return entries


def page_entries(root=ROOT):
    """One entry per page the wiki's own records mark superseded
    (scripts/wiki_treatment.py's superseded_pages() — the Lane-2
    semantic signals). Page-level: the page is severed outright,
    so its cues (its title's terms) are informational only."""
    treatment_path = Path(root) / "scripts" / "wiki_treatment.py"
    if not treatment_path.is_file():
        return []
    treatment = _load("wiki_treatment_for_severance",
                      treatment_path)
    observe = treatment.observe
    entries = []
    for page, signal in sorted(treatment.superseded_pages(root).items()):
        title = ""
        path = Path(root) / page
        if path.is_file():
            fields, _body = observe.parse_frontmatter(
                path.read_text(encoding="utf-8", errors="ignore"))
            title = str((fields or {}).get("title") or "")
        entries.append({
            "kind": "page",
            "page": page,
            "claim": None,
            "cues": {"phrases": [],
                     "terms": distinctive_terms(title)},
            "source": {
                "register": "wiki/ frontmatter + outcomes (Lane-2 "
                            "signals via scripts/wiki_treatment.py)",
                "line": None,
                "record_id": page,
                "signal": signal,
            },
        })
    return entries


# -- Lineage derivation (board item 10, 2026-11-03) ---------------------------

CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)#L(\d+)(?:-L?(\d+))?\s*\]")

# Structural pages are catalogues and chronicles, never evidence:
# a marker quoted in their prose derives nothing.
_STRUCTURAL_PAGES = frozenset({"wiki/index.md", "wiki/log.md"})

_SENTENCE_END = re.compile(r"[.!?][\"'\)\]\*]*\s+")

# A derived claim entry must carry at least this many distinctive
# terms: fewer cannot be cut reliably at retrieval time, and the
# forgetting battery's reworded probe sets the same floor.
_MIN_DERIVED_TERMS = 3


def _lite_frontmatter(text):
    """(fields, body_start) — a narrow YAML-subset frontmatter
    parse (scalars and block/flow lists) for the derivation, so
    it runs over any tree in the real formats whether or not the
    tree carries this repo's own tools. Only `sources` and
    `title` are consumed."""
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, 0
    fields = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", lines[i])
        if not km:
            i += 1
            continue
        name, val = km.group(1), km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fields[name] = [v.strip().strip("\"'")
                            for v in val[1:-1].split(",") if v.strip()]
        elif val.startswith("- "):
            fields[name] = [val[2:].strip().strip("\"'")]
        elif val:
            fields[name] = val.strip("\"'")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                items.append(re.sub(r"^\s*-\s+", "", lines[j])
                             .strip().strip("\"'"))
                j += 1
            if items:
                fields[name] = items
                i = j - 1
            else:
                fields[name] = None
        i += 1
    return fields, m.end()


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def _last_sentence(chunk):
    """(sentence, start_offset) — the last sentence of `chunk`:
    the text a cite marker immediately after it attaches to.
    The chunk is right-stripped first: a chunk ending at a
    sentence boundary (the marker directly follows the final
    punctuation) names the sentence that boundary terminates,
    not the empty tail after it."""
    chunk = chunk.rstrip()
    starts = [m.end() for m in _SENTENCE_END.finditer(chunk)]
    start = starts[-1] if starts else 0
    raw = chunk[start:]
    lead = len(raw) - len(raw.lstrip())
    sentence = raw.strip()
    sentence = re.sub(r"^[\s\*\_\>\#\-]+", "", sentence)
    sentence = re.sub(r"[\s\*\_]+$", "", sentence)
    return sentence, start + lead


def _blocks(body):
    """(start, end) char spans of body's blank-line-separated
    blocks."""
    spans = []
    pos = 0
    for m in re.finditer(r"\n\s*\n", body):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(body)))
    return [(s, e) for s, e in spans if body[s:e].strip()]


def _cited_units(text, page_rel):
    """The cited passages of one page: for every cite marker,
    the sentence immediately before it (the corpus's citation
    convention — the marker follows the claim it receipts),
    the sentence's line span, the marker targets that receipt
    it (stacked markers join the same unit), and whether the
    enclosing paragraph block states a supersession."""
    _fields, body_start = _lite_frontmatter(text)
    body = text[body_start:]
    units = []
    for bstart, bend in _blocks(body):
        block = body[bstart:bend]
        markers = list(CITE_RE.finditer(block))
        if not markers:
            continue
        block_superseded = "superseded" in tokenize(block)
        current = None
        prev_end = 0
        for m in markers:
            chunk = block[prev_end:m.start()]
            sentence, soff = _last_sentence(chunk)
            target = (m.group(1), int(m.group(2)),
                      int(m.group(3) or m.group(2)))
            if sentence:
                abs_start = body_start + bstart + prev_end + soff
                abs_end = body_start + bstart + m.start()
                current = {
                    "page": page_rel,
                    "sentence": " ".join(sentence.split()),
                    "span": (_line_of(text, abs_start),
                             _line_of(text, abs_end)),
                    "targets": [target],
                    "block_superseded": block_superseded,
                    "block": block,
                }
                units.append(current)
            elif current is not None:
                current["targets"].append(target)
            prev_end = m.end()
    return units


def _page_sentences(text):
    """(sentence, (start_line, end_line)) for every sentence of
    the page body — the statement spans a claim's record page
    presents."""
    _fields, body_start = _lite_frontmatter(text)
    body = text[body_start:]
    out = []
    for bstart, bend in _blocks(body):
        block = body[bstart:bend]
        pos = 0
        for m in _SENTENCE_END.finditer(block):
            seg = block[pos:m.start() + 1]
            sentence, soff = _last_sentence(seg + " ")
            if sentence:
                a = body_start + bstart + pos + soff
                out.append((sentence,
                            (_line_of(text, a),
                             _line_of(text,
                                      body_start + bstart
                                      + m.start() + 1))))
            pos = m.end()
        tail, toff = _last_sentence(block[pos:])
        if tail:
            a = body_start + bstart + pos + toff
            out.append((tail, (_line_of(text, a),
                               _line_of(text,
                                        body_start + bend))))
    return out


class _Tree:
    """Line/cache view over the tree under derivation."""

    def __init__(self, root):
        self.root = Path(root)
        self._lines = {}

    def lines(self, rel):
        if rel not in self._lines:
            path = self.root / rel
            self._lines[rel] = (
                path.read_text(encoding="utf-8",
                               errors="ignore").splitlines()
                if path.is_file() else None)
        return self._lines[rel]

    def exists(self, rel):
        return (self.root / rel).is_file()

    def resolves(self, rel, start, end):
        """A citation target resolves when the file exists and
        the cited range lies inside it."""
        lines = self.lines(rel)
        return (lines is not None and 1 <= start <= len(lines)
                and 1 <= end <= len(lines))

    def span_tokens(self, rel, start, end):
        lines = self.lines(rel)
        if lines is None:
            return []
        start = max(start, 1)
        end = min(end, len(lines))
        if start > end:
            return []
        return tokenize("\n".join(lines[start - 1:end]))

    def source_resolves(self, ref):
        """A frontmatter source ref resolves as an exact path,
        or by stem anywhere under raw/ or wiki/ (the validator's
        slug convention, read conservatively: any stem hit
        counts as resolving, so the no-live-basis rule fires
        only when nothing on disk answers to the name)."""
        if self.exists(ref) or self.exists(ref + ".md"):
            return True
        stem = Path(str(ref)).name
        if stem.endswith(".md"):
            stem = stem[:-3]
        for base in ("raw", "wiki"):
            folder = self.root / base
            if folder.is_dir():
                for path in folder.rglob("*.md"):
                    if path.stem == stem:
                        return True
        return False


def lineage_entries(root, base_entries, id_offset=0):
    """The citation-lineage closure of the base entries over
    the compiled layer: derived entries (marked "derived")
    severing what cites severed ground, computed by relations
    R1–R5 as stated in the module docstring. `base_entries`
    must already carry their ids; derived ids are assigned
    after `id_offset`, in sorted (page, claim, basis) order,
    and basis references to other derived passages are
    rewritten to their final ids."""
    root = Path(root)
    tree = _Tree(root)
    wiki = root / "wiki"
    pages = {}
    if wiki.is_dir():
        for path in sorted(wiki.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in _STRUCTURAL_PAGES:
                continue
            pages[rel] = path.read_text(encoding="utf-8",
                                        errors="ignore")
    page_fields = {}
    units = []
    for rel in sorted(pages):
        fields, _start = _lite_frontmatter(pages[rel])
        page_fields[rel] = fields
        units.extend(_cited_units(pages[rel], rel))
    units.sort(key=lambda u: (u["page"], u["span"], u["sentence"]))
    units_by_page = {}
    for unit in units:
        units_by_page.setdefault(unit["page"], []).append(unit)

    claim_entries = [e for e in base_entries
                     if e.get("kind") in ("decision-form",
                                          "treatment")]
    claim_pages = {e.get("page") for e in claim_entries}

    # Severed ground: spans (per file) and whole pages, each
    # tagged with a basis key — ("entry", id) for a base entry,
    # ("unit", page, sentence) for a derived passage, ("page",
    # page) for a derived page, ("target", path) for a citation
    # target that no longer resolves.
    severed_pages = {}
    severed_spans = {}

    def add_span(rel, start, end, basis):
        severed_spans.setdefault(rel, []).append((start, end, basis))

    for entry in base_entries:
        if entry.get("kind") == "page" and entry.get("page"):
            severed_pages[entry["page"]] = ("entry", entry["id"])
            add_span(entry["page"], 1, 10 ** 9,
                     ("entry", entry["id"]))

    # R1 seeds: each claim entry's origin receipts (the spans
    # its record page cites that match the claim under the TEXT
    # rule) and its statement sentences on that page.
    for entry in claim_entries:
        page = entry.get("page")
        if not page or page not in pages:
            continue
        for unit in units_by_page.get(page, []):
            for tfile, start, end in unit["targets"]:
                if tree.resolves(tfile, start, end) and \
                        text_matches(tree.span_tokens(tfile, start,
                                                      end), entry):
                    add_span(tfile, start, end, ("entry", entry["id"]))
        for sentence, (start, end) in _page_sentences(pages[page]):
            if text_matches(tokenize(sentence), entry):
                add_span(page, start, end, ("entry", entry["id"]))

    derived = {}
    derived_pages = {}

    def sever_unit(unit, basis, signal):
        key = (unit["page"], unit["sentence"])
        if key in derived:
            return False
        terms = distinctive_terms(unit["sentence"])
        if len(terms) < _MIN_DERIVED_TERMS:
            return False
        derived[key] = {
            "kind": "lineage",
            "page": unit["page"],
            "claim": unit["sentence"],
            "cues": {"phrases": [], "terms": terms},
            "derived": True,
            "_basis": basis,
            "source": {
                "register": "evaluation/retrieval-severance.json"
                            " (lineage derivation)",
                "line": None,
                "record_id": None,
                "signal": signal,
            },
        }
        add_span(unit["page"], unit["span"][0], unit["span"][1],
                 ("unit", unit["page"], unit["sentence"]))
        return True

    def basis_label(basis):
        kind = basis[0]
        if kind == "entry":
            return f"severance entry {basis[1]}"
        if kind == "unit":
            return f"a lineage-severed passage on {basis[1]}"
        if kind == "page":
            return f"derived page severance of {basis[1]}"
        return f"the missing citation target {basis[1]}"

    changed = True
    while changed:
        changed = False
        # R3 / R4 / R1 closure over cited units.
        for unit in units:
            if (unit["page"], unit["sentence"]) in derived:
                continue
            for tfile, start, end in unit["targets"]:
                basis = None
                signal = None
                if not tree.resolves(tfile, start, end):
                    basis = ("target", tfile)
                    signal = ("citation lineage: the passage "
                              f"cites {tfile}#L{start}-L{end}, "
                              "which no longer resolves — a "
                              "claim resting on a vanished "
                              "receipt loses standing (deleted "
                              "source is not severance, but the "
                              "citing claim does not stand)")
                elif tfile in severed_pages:
                    basis = severed_pages[tfile]
                    signal = ("citation lineage: the passage "
                              f"cites {tfile}, severed whole by "
                              f"{basis_label(basis)}")
                else:
                    for s_start, s_end, s_basis in \
                            severed_spans.get(tfile, []):
                        if start <= s_end and s_start <= end:
                            basis = s_basis
                            signal = (
                                "citation lineage: the passage "
                                f"cites {tfile}#L{start}-L{end}, "
                                "which overlaps the severed "
                                f"ground at #L{s_start}-L{s_end} "
                                f"of {basis_label(s_basis)}")
                            break
                if basis is not None and \
                        sever_unit(unit, basis, signal):
                    changed = True
                    break
        # R2: superseded blocks on claim-record pages.
        for unit in units:
            if unit["page"] not in claim_pages or \
                    not unit["block_superseded"]:
                continue
            if (unit["page"], unit["sentence"]) in derived:
                continue
            on_page = [e for e in claim_entries
                       if e.get("page") == unit["page"]]
            if not on_page:
                continue
            block_tokens = set(tokenize(unit["block"]))

            def block_score(entry):
                cues = entry.get("cues") or {}
                terms = cues.get("terms") or []
                return sum(1 for t in terms if t in block_tokens)

            best = sorted(on_page,
                          key=lambda e: (-block_score(e),
                                         e["id"]))[0]
            basis = ("entry", best["id"])
            if sever_unit(unit, basis,
                          "citation lineage: the passage stands "
                          "in a block on the claim's record page "
                          "that states its own form superseded — "
                          "the retained form is severed with "
                          f"{basis_label(basis)}, whatever words "
                          "it now uses"):
                changed = True
        # R5: pages with no live basis.
        for rel in sorted(pages):
            if rel in severed_pages or rel in derived_pages:
                continue
            sources = page_fields[rel].get("sources")
            if isinstance(sources, str):
                sources = [sources]
            if not sources:
                continue
            dead = []
            for ref in sources:
                if ref in severed_pages:
                    dead.append(severed_pages[ref])
                elif not tree.source_resolves(ref):
                    dead.append(("target", str(ref)))
            if len(dead) != len(sources):
                continue
            terms = distinctive_terms(
                str(page_fields[rel].get("title") or ""))
            if len(terms) < _MIN_DERIVED_TERMS:
                extra = []
                for unit in units_by_page.get(rel, []):
                    extra.extend(distinctive_terms(unit["sentence"]))
                for term in extra:
                    if term not in terms:
                        terms.append(term)
                    if len(terms) >= _MIN_DERIVED_TERMS:
                        break
            if len(terms) < _MIN_DERIVED_TERMS:
                continue
            basis = dead[0]
            derived_pages[rel] = {
                "kind": "page",
                "page": rel,
                "claim": None,
                "cues": {"phrases": [], "terms": terms},
                "derived": True,
                "_basis": basis,
                "source": {
                    "register": "evaluation/retrieval-"
                                "severance.json (lineage "
                                "derivation)",
                    "line": None,
                    "record_id": None,
                    "signal": "citation lineage: every source "
                              "this page rests on is severed "
                              "or no longer resolves — the page "
                              "has no live basis and is severed "
                              f"whole ({basis_label(basis)})",
                },
            }
            severed_pages[rel] = ("page", rel)
            add_span(rel, 1, 10 ** 9, ("page", rel))
            changed = True

    drafts = list(derived.values()) + list(derived_pages.values())
    drafts.sort(key=lambda d: (d["page"] or "", d["claim"] or "",
                               repr(d["_basis"])))
    for i, draft in enumerate(drafts, start=1):
        draft["id"] = f"sev-{id_offset + i:04d}"
    by_unit = {(d["page"], d["claim"]): d["id"]
               for d in derived.values()}
    by_page = {rel: d["id"] for rel, d in derived_pages.items()}
    for draft in drafts:
        basis = draft.pop("_basis")
        if basis[0] == "entry":
            draft["source"]["record_id"] = basis[1]
        elif basis[0] == "unit":
            draft["source"]["record_id"] = by_unit[(basis[1],
                                                    basis[2])]
        elif basis[0] == "page":
            draft["source"]["record_id"] = by_page[basis[1]]
        else:
            draft["source"]["record_id"] = basis[1]
    return drafts


def build_artefact(root=ROOT):
    """The severance list, generated from the registers and the
    wiki tree. Deterministic: entries sorted by (kind, page,
    record id), ids assigned in that order, register hashes in
    the header — same inputs, same bytes."""
    root = Path(root)
    entries = (decision_form_entries(root)
               + treatment_entries(root)
               + page_entries(root))
    entries.sort(key=lambda e: (e["kind"], e["page"] or "",
                                (e["source"] or {}).get("record_id")
                                or ""))
    for i, entry in enumerate(entries, start=1):
        entry["id"] = f"sev-{i:04d}"
    entries = entries + lineage_entries(root, entries,
                                        id_offset=len(entries))
    ordered = []
    for entry in entries:
        item = {
            "id": entry["id"],
            "kind": entry["kind"],
            "page": entry["page"],
            "claim": entry["claim"],
            "cues": entry["cues"],
            "source": entry["source"],
        }
        if entry.get("derived"):
            item["derived"] = True
        ordered.append(item)
    return {
        "kind": "retrieval-severance",
        "version": 1,
        "purpose": "Retrieval-cue severance list "
                   "(WikiCitadel v1): the claims and pages whose "
                   "retrieval cues are cut because the wiki's "
                   "registers record them superseded or negative. "
                   "DERIVED — generated by scripts/wiki_severance.py "
                   "from the decisions register, the treatment "
                   "register and the wiki's supersession signals, "
                   "plus the citation-lineage derivation "
                   "(severance follows ^[cite:] lineage, not "
                   "wording); never hand-edit (regenerate: "
                   "wiki_severance.py build).",
        "generated_from": [
            {"path": "evaluation/decisions-register.jsonl",
             "sha256": _sha256(root / "evaluation"
                               / "decisions-register.jsonl")},
            {"path": "evaluation/treatment-register.jsonl",
             "sha256": _sha256(root / "evaluation"
                               / "treatment-register.jsonl")},
            {"path": "wiki/",
             "sha256": None,
             "note": "frontmatter supersession scan "
                     "(scripts/wiki_treatment.py "
                     "superseded_pages()) + citation-lineage "
                     "derivation over the compiled layer"},
        ],
        "entries": ordered,
    }


def render_artefact(artefact):
    return json.dumps(artefact, indent=2, ensure_ascii=False) + "\n"


def load_severance(path=None):
    """The parsed severance list at `path` (default: the repo's
    evaluation/retrieval-severance.json), or None when absent or
    unreadable — an absent list means severance is simply off,
    and every consumer's behaviour is unchanged."""
    path = Path(path) if path is not None else SEVERANCE_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("kind") \
            != "retrieval-severance":
        return None
    return data


# -- CLI ------------------------------------------------------------------------

def _summarise(artefact):
    lines = [f"severance list: {len(artefact['entries'])} "
             f"entr{'y' if len(artefact['entries']) == 1 else 'ies'}"]
    for e in artefact["entries"]:
        src = e["source"]
        cite = f"{src['register']}" + (
            f":{src['line']}" if src.get("line") else "")
        lines.append(f"  {e['id']} [{e['kind']}] {e['page']}"
                     f" — {e['claim'] or '(whole page)'}"
                     f"  <- {cite} ({src['record_id']})"
                     + (" [derived]" if e.get("derived") else ""))
    return lines


def main(argv):
    ap = argparse.ArgumentParser(
        description="Generate / check / show the retrieval-cue "
                    "severance list (evaluation/"
                    "retrieval-severance.json).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="(re)write the list from the "
                                 "registers")
    sub.add_parser("check", help="exit 1 when the list on disk "
                                 "differs from a fresh generation")
    sub.add_parser("show", help="summarise the list on disk")
    args = ap.parse_args(argv[1:])

    if args.cmd == "build":
        artefact = build_artefact()
        SEVERANCE_PATH.write_text(render_artefact(artefact),
                                  encoding="utf-8")
        for line in _summarise(artefact):
            print(line)
        print(f"wrote {SEVERANCE_PATH.relative_to(ROOT)}")
        return 0
    if args.cmd == "check":
        if not SEVERANCE_PATH.is_file():
            print("no severance list on disk — run build")
            return 2
        fresh = render_artefact(build_artefact())
        current = SEVERANCE_PATH.read_text(encoding="utf-8")
        if fresh == current:
            print("severance list is up to date")
            return 0
        print("severance list is STALE — regenerate with "
              "wiki_severance.py build")
        return 1
    if args.cmd == "show":
        artefact = load_severance()
        if artefact is None:
            print("no severance list on disk")
            return 2
        for line in _summarise(artefact):
            print(line)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
