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
    treatment = _load("wiki_treatment_for_severance",
                      Path(root) / "scripts" / "wiki_treatment.py")
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
    ordered = []
    for entry in entries:
        ordered.append({
            "id": entry["id"],
            "kind": entry["kind"],
            "page": entry["page"],
            "claim": entry["claim"],
            "cues": entry["cues"],
            "source": entry["source"],
        })
    return {
        "kind": "retrieval-severance",
        "version": 1,
        "purpose": "Retrieval-cue severance list "
                   "(WikiCitadel v1): the claims and pages whose "
                   "retrieval cues are cut because the wiki's "
                   "registers record them superseded or negative. "
                   "DERIVED — generated by scripts/wiki_severance.py "
                   "from the decisions register, the treatment "
                   "register and the wiki's supersession signals; "
                   "never hand-edit (regenerate: wiki_severance.py "
                   "build).",
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
                     "superseded_pages())"},
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
                     f"  <- {cite} ({src['record_id']})")
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
